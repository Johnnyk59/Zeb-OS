/**
 * A freeform, depth-sorted neural field whose camera and signal density track
 * live activity. Every expensive dimension has an explicit or adaptive bound.
 */
import { useEffect, useRef } from "react";
import { getBrainFrameEnergy, getBrainMotionProfile } from "@/lib/brain-activity";

type RGB = readonly [number, number, number];
type Point3 = readonly [number, number, number];

interface Node {
  bx: number;
  by: number;
  bz: number;
  x: number;
  y: number;
  z: number;
  seed: number;
  drift: number;
  fire: number;
  palette: number;
  cluster: number;
  radius: number;
}

interface ProjectedNode {
  i: number;
  sx: number;
  sy: number;
  depth: number;
  persp: number;
  fire: number;
  seed: number;
  palette: number;
  radius: number;
}

interface Signal {
  edge: number;
  from: number;
  to: number;
  t: number;
  palette: number;
  phase: number;
  speed: number;
}

interface Edge {
  from: number;
  to: number;
  color: RGB;
  bend: number;
  reach: number;
}

interface Connection {
  edge: number;
  peer: number;
}

interface ClusterSpec {
  center: Point3;
  spread: Point3;
  count: number;
  palette: number;
}

const TAU = Math.PI * 2;
const TILT = 0.3;
const CT = Math.cos(TILT);
const ST = Math.sin(TILT);
const BASE_CAMERA_DEPTH = 0.46;
const MAX_EDGES = 620;

function createRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function rnd(random: () => number, a: number, b: number): number {
  return a + random() * (b - a);
}

function mixColor(a: RGB, b: RGB): RGB {
  return [
    Math.round((a[0] + b[0]) / 2),
    Math.round((a[1] + b[1]) / 2),
    Math.round((a[2] + b[2]) / 2),
  ];
}

function createGlowSprite(color: RGB, whiteCore = false): HTMLCanvasElement {
  const sprite = document.createElement("canvas");
  const size = 88;
  sprite.width = size;
  sprite.height = size;
  const spriteContext = sprite.getContext("2d");
  if (!spriteContext) return sprite;

  const center = size / 2;
  const gradient = spriteContext.createRadialGradient(center, center, 0, center, center, center);
  if (whiteCore) {
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.1, `rgba(${color[0]},${color[1]},${color[2]},1)`);
  } else {
    gradient.addColorStop(0, `rgba(${color[0]},${color[1]},${color[2]},1)`);
  }
  gradient.addColorStop(0.34, `rgba(${color[0]},${color[1]},${color[2]},0.46)`);
  gradient.addColorStop(0.7, `rgba(${color[0]},${color[1]},${color[2]},0.11)`);
  gradient.addColorStop(1, `rgba(${color[0]},${color[1]},${color[2]},0)`);
  spriteContext.fillStyle = gradient;
  spriteContext.fillRect(0, 0, size, size);
  return sprite;
}

export function BrainCanvas({
  energy = 0,
  className,
}: {
  /** Target activity level 0..1, eased internally and safe to update often. */
  energy?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const energyRef = useRef(energy);

  useEffect(() => {
    energyRef.current = energy;
  }, [energy]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let centerX = 0;
    let centerY = 0;
    let scale = 1;
    let rotation = 0;
    let globalTime = 0;
    let lastFrame = 0;
    let fireAccumulator = 0;
    let currentEnergy = 0;
    let sustainedDive = 0;
    let cameraZoom = 1;
    let cameraDepth = BASE_CAMERA_DEPTH;
    let cameraX = 0;
    let cameraY = 0;
    let cameraZ = 0;
    let focusTimer = 0;
    let focusIndex = 0;
    let raf = 0;
    let disposed = false;
    let inViewport = true;
    let adaptiveQuality = 1;
    let averageFrameCost = 0;
    const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reducedMotion = reducedMotionQuery.matches;
    const random = createRandom(0x5eb05);

    const palette: readonly RGB[] = [
      [66, 226, 246],
      [74, 137, 255],
      [91, 239, 184],
      [255, 185, 79],
      [255, 101, 132],
    ];
    const nodeSprites = palette.map((color) => createGlowSprite(color));
    const signalSprites = palette.map((color) => createGlowSprite(color, true));
    const fieldSprites = [
      createGlowSprite(palette[0]),
      createGlowSprite(palette[1]),
      createGlowSprite(palette[2]),
    ];

    const drawSprite = (
      sprite: HTMLCanvasElement,
      x: number,
      y: number,
      radius: number,
      alpha: number,
    ) => {
      if (alpha <= 0 || radius <= 0) return;
      ctx.globalAlpha = Math.min(1, alpha);
      ctx.drawImage(sprite, x - radius, y - radius, radius * 2, radius * 2);
    };

    // Uneven, overlapping constellations keep the network spatially legible
    // without collecting the points into a recognizable perimeter.
    const clusterSpecs: readonly ClusterSpec[] = [
      { center: [-0.72, -0.14, -0.14], spread: [0.5, 0.4, 0.42], count: 32, palette: 0 },
      { center: [-0.4, 0.54, 0.28], spread: [0.39, 0.34, 0.34], count: 29, palette: 2 },
      { center: [0.02, 0.04, -0.5], spread: [0.38, 0.48, 0.31], count: 28, palette: 1 },
      { center: [0.34, -0.5, 0.22], spread: [0.43, 0.33, 0.4], count: 30, palette: 4 },
      { center: [0.78, 0.12, -0.12], spread: [0.47, 0.4, 0.37], count: 32, palette: 1 },
      { center: [0.32, 0.62, 0.4], spread: [0.38, 0.3, 0.32], count: 26, palette: 3 },
    ];
    const nodes: Node[] = [];
    const clusterAnchors: number[] = [];

    const addNode = (
      x: number,
      y: number,
      z: number,
      cluster: number,
      paletteIndex: number,
      radius = rnd(random, 0.72, 1.42),
    ) => {
      const seed = random();
      nodes.push({
        bx: x,
        by: y,
        bz: z,
        x,
        y,
        z,
        seed,
        drift: rnd(random, 0, TAU),
        fire: 0,
        palette: paletteIndex,
        cluster,
        radius,
      });
    };

    for (let cluster = 0; cluster < clusterSpecs.length; cluster += 1) {
      const spec = clusterSpecs[cluster];
      clusterAnchors.push(nodes.length);
      addNode(spec.center[0], spec.center[1], spec.center[2], cluster, spec.palette, 1.5);

      for (let index = 1; index < spec.count; index += 1) {
        const azimuth = random() * TAU;
        const vertical = rnd(random, -1, 1);
        const planar = Math.sqrt(Math.max(0, 1 - vertical * vertical));
        const radial = Math.pow(random(), 0.58);
        const curl = (1 - radial) * 0.24 + cluster * 0.17;
        const x =
          spec.center[0] +
          Math.cos(azimuth + curl) * planar * spec.spread[0] * radial +
          rnd(random, -0.018, 0.018);
        const y =
          spec.center[1] +
          vertical * spec.spread[1] * radial +
          Math.sin(azimuth * 1.7) * spec.spread[1] * 0.08;
        const z =
          spec.center[2] +
          Math.sin(azimuth + curl) * planar * spec.spread[2] * radial +
          rnd(random, -0.018, 0.018);
        const accent = random();
        const paletteIndex =
          accent < 0.08 ? 4 : accent < 0.16 ? 3 : accent < 0.26 ? (spec.palette + 1) % 3 : spec.palette;
        addNode(x, y, z, cluster, paletteIndex);
      }
    }

    // These loose chains create branching depth and several readable long
    // routes through the field while remaining independent of any boundary.
    const clusterLinks: ReadonlyArray<readonly [number, number]> = [
      [0, 1],
      [0, 2],
      [0, 3],
      [1, 5],
      [2, 3],
      [2, 4],
      [3, 4],
      [4, 5],
    ];
    const filamentChains: number[][] = [];
    for (let link = 0; link < clusterLinks.length; link += 1) {
      const [fromCluster, toCluster] = clusterLinks[link];
      const from = clusterSpecs[fromCluster].center;
      const to = clusterSpecs[toCluster].center;
      const dx = to[0] - from[0];
      const dy = to[1] - from[1];
      const planarLength = Math.max(0.001, Math.hypot(dx, dy));
      const direction = link % 2 === 0 ? 1 : -1;
      const arc = rnd(random, 0.12, 0.26) * direction;
      const chain = [clusterAnchors[fromCluster]];

      for (let step = 1; step <= 3; step += 1) {
        const progress = step / 4;
        const bow = Math.sin(Math.PI * progress);
        const x =
          from[0] +
          dx * progress +
          (-dy / planarLength) * arc * bow +
          rnd(random, -0.025, 0.025);
        const y =
          from[1] +
          dy * progress +
          (dx / planarLength) * arc * bow +
          rnd(random, -0.025, 0.025);
        const z =
          from[2] +
          (to[2] - from[2]) * progress +
          bow * rnd(random, -0.18, 0.18);
        const nodeIndex = nodes.length;
        addNode(x, y, z, -1, link % 3, rnd(random, 0.7, 1.08));
        chain.push(nodeIndex);
      }
      chain.push(clusterAnchors[toCluster]);
      filamentChains.push(chain);
    }

    const distance3 = (a: Node, b: Node) =>
      Math.hypot(a.bx - b.bx, a.by - b.by, a.bz - b.bz);
    const edgeKeys = new Map<string, number>();
    const edgePairs: Array<{ from: number; to: number; longRange: boolean }> = [];
    const addEdge = (a: number, b: number, longRange = false) => {
      if (a === b) return;
      const from = Math.min(a, b);
      const to = Math.max(a, b);
      const key = `${from}:${to}`;
      const existing = edgeKeys.get(key);
      if (existing !== undefined) {
        if (longRange) edgePairs[existing].longRange = true;
        return;
      }
      if (edgePairs.length >= MAX_EDGES) return;
      edgeKeys.set(key, edgePairs.length);
      edgePairs.push({ from, to, longRange });
    };

    for (let index = 0; index < nodes.length; index += 1) {
      const nearest = nodes
        .map((node, peer) => ({
          peer,
          distance: peer === index ? Infinity : distance3(nodes[index], node),
        }))
        .sort((a, b) => a.distance - b.distance);
      const neighborCount = nodes[index].seed < 0.22 ? 4 : 3;
      for (let neighbor = 0; neighbor < neighborCount; neighbor += 1) {
        addEdge(index, nearest[neighbor].peer);
      }
    }

    for (const chain of filamentChains) {
      for (let index = 1; index < chain.length; index += 1) {
        addEdge(chain[index - 1], chain[index], true);
      }
    }

    let longAxons = 0;
    for (let attempt = 0; attempt < 180 && longAxons < 24; attempt += 1) {
      const from = Math.floor(random() * nodes.length);
      const to = Math.floor(random() * nodes.length);
      const distance = distance3(nodes[from], nodes[to]);
      if (nodes[from].cluster === nodes[to].cluster || distance < 0.58 || distance > 1.48) continue;
      const before = edgePairs.length;
      addEdge(from, to, true);
      if (edgePairs.length > before) longAxons += 1;
    }

    const edges: Edge[] = edgePairs.map(({ from, to, longRange }) => {
      const distance = distance3(nodes[from], nodes[to]);
      return {
        from,
        to,
        color: mixColor(palette[nodes[from].palette], palette[nodes[to].palette]),
        bend: rnd(random, -1, 1) * (longRange ? 1 : 0.52),
        reach: longRange ? Math.max(0.7, Math.min(1, distance / 1.35)) : Math.min(0.68, distance / 1.1),
      };
    });
    const adjacency: Connection[][] = Array.from({ length: nodes.length }, () => []);
    for (let edgeIndex = 0; edgeIndex < edges.length; edgeIndex += 1) {
      const edge = edges[edgeIndex];
      adjacency[edge.from].push({ edge: edgeIndex, peer: edge.to });
      adjacency[edge.to].push({ edge: edgeIndex, peer: edge.from });
    }

    const projected: ProjectedNode[] = nodes.map((node, index) => ({
      i: index,
      sx: 0,
      sy: 0,
      depth: 0,
      persp: 1,
      fire: 0,
      seed: node.seed,
      palette: node.palette,
      radius: node.radius,
    }));
    const depthOrder = projected.slice();
    const signals: Signal[] = [];
    focusIndex = clusterAnchors[2];

    const projectNodes = () => {
      const cosine = Math.cos(rotation);
      const sine = Math.sin(rotation);
      const focusRotatedX = cameraX * cosine - cameraZ * sine;
      const focusRotatedZ = cameraX * sine + cameraZ * cosine;
      const focusTiltedY = cameraY * CT - focusRotatedZ * ST;
      const focusDepth = cameraY * ST + focusRotatedZ * CT;

      for (let index = 0; index < nodes.length; index += 1) {
        const node = nodes[index];
        const point = projected[index];
        const x = node.x * cosine - node.z * sine;
        const z = node.x * sine + node.z * cosine;
        const tiltedY = node.y * CT - z * ST;
        const depth = node.y * ST + z * CT;
        const relativeDepth = depth - focusDepth;
        const perspective = 1 / Math.max(0.82, 2.08 - relativeDepth * cameraDepth);
        point.sx = centerX + (x - focusRotatedX) * scale * cameraZoom * perspective;
        point.sy = centerY + (tiltedY - focusTiltedY) * scale * cameraZoom * perspective;
        point.depth = relativeDepth;
        point.persp = perspective;
        point.fire = node.fire;
      }
      depthOrder.sort((a, b) => a.depth - b.depth);
    };

    const emitFrom = (index: number, fanoutChance: number, signalLimit: number) => {
      nodes[index].fire = 1;
      const connections = adjacency[index];
      for (let peerIndex = 0; peerIndex < connections.length; peerIndex += 1) {
        if (signals.length >= signalLimit) break;
        const connection = connections[peerIndex];
        const reach = edges[connection.edge].reach;
        const propagationChance = fanoutChance * (reach > 0.68 ? 0.58 + currentEnergy * 0.38 : 1);
        if (random() < propagationChance) {
          signals.push({
            edge: connection.edge,
            from: index,
            to: connection.peer,
            t: 0,
            palette: nodes[index].palette,
            phase: rnd(random, 0, TAU),
            speed: rnd(random, 0.82, 1.18),
          });
        }
      }
    };

    const step = (delta: number) => {
      const rawTarget = energyRef.current;
      const target = Number.isFinite(rawTarget) ? Math.max(0, Math.min(1, rawTarget)) : 0;
      currentEnergy +=
        (target - currentEnergy) * Math.min(1, delta * (target > currentEnergy ? 4.6 : 2.2));
      const profile = getBrainMotionProfile(currentEnergy);

      if (reducedMotion) {
        signals.length = 0;
        fireAccumulator = 0;
        sustainedDive = 0;
        cameraZoom = 1;
        cameraDepth = BASE_CAMERA_DEPTH;
        cameraX = 0;
        cameraY = 0;
        cameraZ = 0;
        rotation = 0;
        for (const node of nodes) {
          node.x = node.bx;
          node.y = node.by;
          node.z = node.bz;
          node.fire = 0;
        }
        return profile;
      }

      rotation += delta * profile.rotationSpeed;
      globalTime += delta * profile.driftSpeed;
      for (const node of nodes) {
        const phase = globalTime + node.drift;
        const amplitude = profile.driftAmplitude * (0.7 + node.radius * 0.3);
        node.x = node.bx + Math.sin(phase) * amplitude;
        node.y = node.by + Math.cos(phase * 0.91) * amplitude;
        node.z = node.bz + Math.sin(phase * 1.09) * amplitude;
        node.fire = Math.max(0, node.fire - delta * profile.fireDecay);
      }

      const intenseTarget = Math.max(0, Math.min(1, (currentEnergy - 0.68) / 0.32));
      const diveResponse = intenseTarget > sustainedDive ? 0.22 : 0.52;
      sustainedDive += (intenseTarget - sustainedDive) * Math.min(1, delta * diveResponse);
      const diveBlend = 0.72 + sustainedDive * 0.28;
      const cameraEase = 1 - Math.exp(-delta * (1.25 + currentEnergy * 0.9));
      const zoomTarget = 1 + (profile.cameraZoom - 1) * diveBlend;
      const depthTarget = BASE_CAMERA_DEPTH + (profile.cameraDepth - BASE_CAMERA_DEPTH) * diveBlend;
      cameraZoom += (zoomTarget - cameraZoom) * cameraEase;
      cameraDepth += (depthTarget - cameraDepth) * cameraEase;

      focusTimer -= delta;
      if (currentEnergy > 0.12 && focusTimer <= 0) {
        if (signals.length > 0 && currentEnergy > 0.46) {
          focusIndex = signals[Math.floor(random() * signals.length)].to;
        } else {
          focusIndex = clusterAnchors[Math.floor(random() * clusterAnchors.length)];
        }
        focusTimer = 6.8 - currentEnergy * 4.3;
      }
      const focusNode = nodes[focusIndex];
      const focusBlend = profile.cameraFocus * (0.58 + sustainedDive * 0.42);
      const focusEase = 1 - Math.exp(-delta * (0.72 + currentEnergy * 0.58));
      cameraX += (focusNode.x * focusBlend - cameraX) * focusEase;
      cameraY += (focusNode.y * focusBlend - cameraY) * focusEase;
      cameraZ += (focusNode.z * focusBlend - cameraZ) * focusEase;

      const signalLimit = Math.max(8, Math.round(profile.signalBudget * adaptiveQuality));
      if (signals.length > signalLimit) signals.length = signalLimit;
      fireAccumulator = Math.min(4, fireAccumulator + delta * profile.firingRate);
      const rootBursts = Math.min(3, Math.floor(fireAccumulator));
      fireAccumulator -= rootBursts;
      for (let burst = 0; burst < rootBursts; burst += 1) {
        emitFrom(Math.floor(random() * nodes.length), profile.fanoutChance, signalLimit);
      }

      let cascadeBudget = 3 + Math.floor(currentEnergy * 5);
      for (let index = signals.length - 1; index >= 0; index -= 1) {
        const signal = signals[index];
        const reach = edges[signal.edge].reach;
        signal.t += (delta * profile.signalSpeed * signal.speed) / (1 + reach * 0.3);
        if (signal.t < 1) continue;
        const destination = signal.to;
        nodes[destination].fire = Math.min(1, nodes[destination].fire + 0.82);
        signals[index] = signals[signals.length - 1];
        signals.pop();
        if (cascadeBudget > 0 && random() < profile.cascadeChance) {
          cascadeBudget -= 1;
          emitFrom(destination, profile.fanoutChance, signalLimit);
        }
      }
      return profile;
    };

    const draw = (profile: ReturnType<typeof getBrainMotionProfile>) => {
      if (reducedMotion) {
        ctx.globalCompositeOperation = "source-over";
        ctx.clearRect(0, 0, width, height);
      } else {
        ctx.globalCompositeOperation = "destination-out";
        ctx.fillStyle = `rgba(0,0,0,${0.27 + 0.15 * (1 - currentEnergy)})`;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.globalCompositeOperation = "lighter";
      projectNodes();

      const fieldAlpha = profile.fieldStrength * (0.6 + currentEnergy * 0.4);
      const fieldStride = adaptiveQuality < 0.68 ? 2 : 1;
      for (let index = 0; index < clusterAnchors.length; index += fieldStride) {
        const point = projected[clusterAnchors[index]];
        const sprite = fieldSprites[index % fieldSprites.length];
        const radius = scale * cameraZoom * (0.34 + currentEnergy * 0.09) * point.persp;
        drawSprite(sprite, point.sx, point.sy, radius, fieldAlpha * (0.68 + (index % 3) * 0.1));
      }

      const edgeStride = adaptiveQuality < 0.64 ? 2 : 1;
      for (let index = 0; index < edges.length; index += edgeStride) {
        const edge = edges[index];
        const from = projected[edge.from];
        const to = projected[edge.to];
        const dx = to.sx - from.sx;
        const dy = to.sy - from.sy;
        const length = Math.max(1, Math.hypot(dx, dy));
        const bend = scale * cameraZoom * (0.012 + edge.reach * 0.05) * edge.bend;
        const controlX = (from.sx + to.sx) * 0.5 - (dy / length) * bend;
        const controlY = (from.sy + to.sy) * 0.5 + (dx / length) * bend;
        const depth = (from.depth + to.depth) * 0.5;
        const heat = Math.max(from.fire, to.fire);
        const depthAlpha = 0.24 + 0.76 * Math.max(0, Math.min(1, (depth + 1.55) / 3.1));
        const alpha = (profile.edgeOpacity + heat * 0.31) * depthAlpha * (1 - edge.reach * 0.16);

        if (edge.reach > 0.68 && adaptiveQuality > 0.76) {
          ctx.globalAlpha = 1;
          ctx.strokeStyle = `rgba(${edge.color[0]},${edge.color[1]},${edge.color[2]},${alpha * 0.17})`;
          ctx.lineWidth = Math.max(1.1, scale * cameraZoom * 0.011 * from.persp);
          ctx.beginPath();
          ctx.moveTo(from.sx, from.sy);
          ctx.quadraticCurveTo(controlX, controlY, to.sx, to.sy);
          ctx.stroke();
        }

        ctx.globalAlpha = 1;
        ctx.strokeStyle = `rgba(${edge.color[0]},${edge.color[1]},${edge.color[2]},${alpha})`;
        ctx.lineWidth = Math.max(0.36, scale * cameraZoom * (0.0036 + heat * 0.0048) * from.persp);
        ctx.beginPath();
        ctx.moveTo(from.sx, from.sy);
        ctx.quadraticCurveTo(controlX, controlY, to.sx, to.sy);
        ctx.stroke();
      }

      for (const signal of signals) {
        const edge = edges[signal.edge];
        const from = projected[edge.from];
        const to = projected[edge.to];
        const eased = signal.t * signal.t * (3 - 2 * signal.t);
        const trailProgress = Math.max(0, eased - 0.07 - edge.reach * 0.025);
        const tailProgress = Math.max(0, eased - 0.145 - edge.reach * 0.04);
        const forward = signal.from === edge.from;
        const headT = forward ? eased : 1 - eased;
        const trailT = forward ? trailProgress : 1 - trailProgress;
        const tailT = forward ? tailProgress : 1 - tailProgress;
        const dx = to.sx - from.sx;
        const dy = to.sy - from.sy;
        const length = Math.max(1, Math.hypot(dx, dy));
        const bendScale = scale * cameraZoom * (0.012 + edge.reach * 0.05) * edge.bend;
        const normalX = -dy / length;
        const normalY = dx / length;
        const headBend = 2 * headT * (1 - headT) * bendScale;
        const trailBend = 2 * trailT * (1 - trailT) * bendScale;
        const tailBend = 2 * tailT * (1 - tailT) * bendScale;
        const x = from.sx + dx * headT + normalX * headBend;
        const y = from.sy + dy * headT + normalY * headBend;
        const trailX = from.sx + dx * trailT + normalX * trailBend;
        const trailY = from.sy + dy * trailT + normalY * trailBend;
        const tailX = from.sx + dx * tailT + normalX * tailBend;
        const tailY = from.sy + dy * tailT + normalY * tailBend;
        const perspective = (from.persp + to.persp) * 0.5;
        const radius = scale * cameraZoom * (0.0085 + currentEnergy * 0.0085) * perspective;
        const sprite = signalSprites[signal.palette];
        const shimmer = 0.9 + Math.sin(globalTime * 4.2 + signal.phase) * 0.1;

        ctx.globalAlpha = 1;
        ctx.strokeStyle = `rgba(${palette[signal.palette][0]},${palette[signal.palette][1]},${palette[signal.palette][2]},${0.2 + currentEnergy * 0.28})`;
        ctx.lineWidth = Math.max(0.55, radius * 0.35);
        ctx.beginPath();
        ctx.moveTo(trailX, trailY);
        ctx.lineTo(x, y);
        ctx.stroke();
        if (adaptiveQuality > 0.68 && currentEnergy > 0.42) {
          drawSprite(sprite, tailX, tailY, radius * 2.2, (0.12 + currentEnergy * 0.13) * shimmer);
        }
        drawSprite(sprite, trailX, trailY, radius * 2.8, (0.22 + currentEnergy * 0.22) * shimmer);
        drawSprite(sprite, x, y, radius * 4.1, (0.72 + currentEnergy * 0.22) * shimmer);
      }

      const renderWideGlow = adaptiveQuality >= 0.62;
      for (const point of depthOrder) {
        const pulse = reducedMotion
          ? 0
          : currentEnergy *
            (0.5 + 0.5 * Math.sin(globalTime * (0.72 + currentEnergy * 1.65) + point.seed * TAU));
        const normalizedDepth = Math.max(0, Math.min(1, (point.depth + 1.55) / 3.1));
        const baseRadius =
          scale * cameraZoom * (0.0052 + 0.0092 * normalizedDepth) * point.persp * point.radius;
        const visibleFire = point.fire * (0.32 + currentEnergy * 0.68);
        const radius = baseRadius * (1 + pulse * 0.2 + visibleFire * 0.92 + currentEnergy * 0.16);
        const brightness = Math.min(
          1,
          0.22 + visibleFire * 0.62 + currentEnergy * 0.3 + normalizedDepth * 0.16,
        );
        const sprite = nodeSprites[point.palette];

        if (renderWideGlow && (normalizedDepth > 0.2 || visibleFire > 0.2)) {
          drawSprite(sprite, point.sx, point.sy, radius * 4.35, brightness * 0.4);
        }
        drawSprite(sprite, point.sx, point.sy, radius * 1.7, brightness * 0.9);
        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgba(255,255,255,${Math.min(1, 0.19 + visibleFire * 0.74 + currentEnergy * 0.11)})`;
        ctx.beginPath();
        ctx.arc(point.sx, point.sy, Math.max(0.4, radius * (0.3 + visibleFire * 0.33)), 0, TAU);
        ctx.fill();
      }

      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    const resize = () => {
      width = canvas.clientWidth || 180;
      height = canvas.clientHeight || 180;
      const pixelBudget = 900_000;
      const desiredDpr = Math.min(window.devicePixelRatio || 1, 1.75);
      const budgetDpr = Math.sqrt(pixelBudget / Math.max(1, width * height));
      const dpr = Math.max(1, Math.min(desiredDpr, budgetDpr));
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      centerX = width * 0.5;
      centerY = height * 0.5;
      scale = Math.min(width, height) * 0.46;
      ctx.clearRect(0, 0, width, height);
    };

    const shouldRun = () => !disposed && inViewport && !document.hidden;
    const requestFrame = () => {
      if (raf === 0 && shouldRun()) raf = requestAnimationFrame(frame);
    };
    const syncAnimation = () => {
      if (shouldRun()) {
        lastFrame = performance.now();
        requestFrame();
      } else if (raf !== 0) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };

    function frame(timestamp: number) {
      raf = 0;
      if (!shouldRun()) return;
      const frameEnergy = getBrainFrameEnergy(energyRef.current, currentEnergy, cameraZoom);
      const targetProfile = getBrainMotionProfile(frameEnergy);
      const targetFrameRate = reducedMotion ? 8 : targetProfile.frameRate * (0.78 + adaptiveQuality * 0.22);
      const interval = 1000 / targetFrameRate;
      const elapsed = timestamp - lastFrame;
      if (elapsed < interval) {
        requestFrame();
        return;
      }

      const frameStart = performance.now();
      const delta = Math.min(elapsed / 1000, reducedMotion ? 0.125 : 0.065);
      lastFrame = timestamp;
      const profile = step(delta);
      draw(profile);
      const frameCost = performance.now() - frameStart;
      averageFrameCost = averageFrameCost === 0 ? frameCost : averageFrameCost * 0.92 + frameCost * 0.08;
      if (averageFrameCost > 8) adaptiveQuality = Math.max(0.52, adaptiveQuality - 0.035);
      else if (averageFrameCost < 4.5) adaptiveQuality = Math.min(1, adaptiveQuality + 0.004);
      requestFrame();
    }

    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    const intersectionObserver = new IntersectionObserver((entries) => {
      inViewport = entries[0]?.isIntersecting ?? true;
      syncAnimation();
    });
    intersectionObserver.observe(canvas);
    const onVisibilityChange = () => syncAnimation();
    document.addEventListener("visibilitychange", onVisibilityChange);
    const onReducedMotionChange = (event: MediaQueryListEvent) => {
      reducedMotion = event.matches;
      signals.length = 0;
      fireAccumulator = 0;
      syncAnimation();
    };
    reducedMotionQuery.addEventListener("change", onReducedMotionChange);
    requestFrame();

    return () => {
      disposed = true;
      if (raf !== 0) cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener("visibilitychange", onVisibilityChange);
      reducedMotionQuery.removeEventListener("change", onReducedMotionChange);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden />;
}
