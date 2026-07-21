/**
 * Zeb's cognitive observatory: a depth-sorted, activity-aware cortical network.
 * Rendering is bounded by explicit frame and signal budgets so high activity
 * increases information density without monopolizing the browser main thread.
 */
import { useEffect, useRef } from "react";
import { getBrainMotionProfile } from "@/lib/brain-activity";

type RGB = readonly [number, number, number];

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
}

interface Signal {
  from: number;
  to: number;
  t: number;
  bend: number;
  palette: number;
}

interface Edge {
  from: number;
  to: number;
  color: RGB;
}

const TAU = Math.PI * 2;
const TILT = 0.32;
const CT = Math.cos(TILT);
const ST = Math.sin(TILT);

function rnd(a: number, b: number): number {
  return a + Math.random() * (b - a);
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

function createBrainHull(): Path2D {
  const path = new Path2D();
  path.moveTo(0, -0.98);
  path.bezierCurveTo(-0.12, -1.08, -0.28, -1.04, -0.39, -0.98);
  path.bezierCurveTo(-0.76, -1.01, -1.04, -0.76, -1.08, -0.43);
  path.bezierCurveTo(-1.2, -0.18, -1.13, 0.15, -0.94, 0.34);
  path.bezierCurveTo(-0.91, 0.66, -0.62, 0.91, -0.23, 0.87);
  path.bezierCurveTo(-0.08, 0.84, -0.04, 0.68, 0, 0.53);
  path.bezierCurveTo(0.04, 0.68, 0.08, 0.84, 0.23, 0.87);
  path.bezierCurveTo(0.62, 0.91, 0.91, 0.66, 0.94, 0.34);
  path.bezierCurveTo(1.13, 0.15, 1.2, -0.18, 1.08, -0.43);
  path.bezierCurveTo(1.04, -0.76, 0.76, -1.01, 0.39, -0.98);
  path.bezierCurveTo(0.28, -1.04, 0.12, -1.08, 0, -0.98);
  path.closePath();
  return path;
}

function createCorticalContours(): readonly Path2D[] {
  const paths: Path2D[] = [];
  const add = (draw: (path: Path2D) => void) => {
    const path = new Path2D();
    draw(path);
    paths.push(path);
  };

  add((path) => {
    path.moveTo(-0.95, -0.35);
    path.bezierCurveTo(-0.7, -0.55, -0.46, -0.46, -0.23, -0.64);
  });
  add((path) => {
    path.moveTo(0.95, -0.35);
    path.bezierCurveTo(0.7, -0.55, 0.46, -0.46, 0.23, -0.64);
  });
  add((path) => {
    path.moveTo(-1.02, 0.06);
    path.bezierCurveTo(-0.78, -0.06, -0.58, 0.08, -0.35, -0.11);
    path.bezierCurveTo(-0.23, -0.2, -0.15, -0.15, -0.1, -0.28);
  });
  add((path) => {
    path.moveTo(1.02, 0.06);
    path.bezierCurveTo(0.78, -0.06, 0.58, 0.08, 0.35, -0.11);
    path.bezierCurveTo(0.23, -0.2, 0.15, -0.15, 0.1, -0.28);
  });
  add((path) => {
    path.moveTo(-0.85, 0.42);
    path.bezierCurveTo(-0.63, 0.28, -0.45, 0.46, -0.2, 0.31);
  });
  add((path) => {
    path.moveTo(0.85, 0.42);
    path.bezierCurveTo(0.63, 0.28, 0.45, 0.46, 0.2, 0.31);
  });
  return paths;
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
    let raf = 0;
    let disposed = false;
    let inViewport = true;
    let adaptiveQuality = 1;
    let averageFrameCost = 0;
    let shellGradient: CanvasGradient | string = "rgba(28,72,118,0.08)";
    const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reducedMotion = reducedMotionQuery.matches;

    // Cyan and blue carry the structure; violet, amber, and coral are accents.
    const palette: readonly RGB[] = [
      [70, 224, 246],
      [77, 132, 255],
      [156, 112, 255],
      [255, 184, 80],
      [255, 99, 128],
    ];
    const nodeSprites = palette.map((color) => createGlowSprite(color));
    const signalSprites = palette.map((color) => createGlowSprite(color, true));
    const fieldSprites = [
      createGlowSprite(palette[0]),
      createGlowSprite(palette[2]),
      createGlowSprite(palette[3]),
    ];
    const brainHull = createBrainHull();
    const corticalContours = createCorticalContours();

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

    // A lobed two-hemisphere surface with a readable longitudinal fissure.
    const nodeCount = 148;
    const nodes: Node[] = [];
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    for (let index = 0; index < nodeCount; index += 1) {
      const normalizedY = 1 - (index / (nodeCount - 1)) * 2;
      const radial = Math.sqrt(Math.max(0, 1 - normalizedY * normalizedY));
      const angle = goldenAngle * index;
      let x = Math.cos(angle) * radial;
      let z = Math.sin(angle) * radial;
      let y = normalizedY;
      const lobe = 0.91 + Math.cos(y * Math.PI * 1.55) * 0.09;
      const variation = rnd(0.88, 1) * lobe;
      x *= 1.24 * variation;
      y *= 0.9 * variation;
      z *= 0.98 * variation;
      x += x >= 0 ? 0.064 : -0.064;
      z += (1 - y * y) * 0.035;
      x += rnd(-0.035, 0.035);
      y += rnd(-0.035, 0.035);
      z += rnd(-0.035, 0.035);
      const seed = Math.random();
      const paletteIndex =
        seed < 0.04 ? 4 : seed < 0.1 ? 3 : seed < 0.22 ? 2 : x < 0 ? 0 : 1;
      nodes.push({
        bx: x,
        by: y,
        bz: z,
        x,
        y,
        z,
        seed,
        drift: rnd(0, TAU),
        fire: 0,
        palette: paletteIndex,
      });
    }

    const distance3 = (a: Node, b: Node) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    const edgeKeys = new Set<string>();
    const edgePairs: Array<[number, number]> = [];
    const addEdge = (a: number, b: number) => {
      const from = Math.min(a, b);
      const to = Math.max(a, b);
      const key = `${from}:${to}`;
      if (edgeKeys.has(key)) return;
      edgeKeys.add(key);
      edgePairs.push([from, to]);
    };

    for (let from = 0; from < nodeCount; from += 1) {
      for (let to = from + 1; to < nodeCount; to += 1) {
        if (distance3(nodes[from], nodes[to]) < 0.365) addEdge(from, to);
      }
    }
    for (let index = 0; index < nodeCount; index += 1) {
      const nearest = nodes
        .map((node, peer) => ({ peer, distance: peer === index ? Infinity : distance3(nodes[index], node) }))
        .sort((a, b) => a.distance - b.distance);
      addEdge(index, nearest[0].peer);
      addEdge(index, nearest[1].peer);
    }

    const edges: Edge[] = edgePairs.map(([from, to]) => ({
      from,
      to,
      color: mixColor(palette[nodes[from].palette], palette[nodes[to].palette]),
    }));
    const adjacency: number[][] = Array.from({ length: nodeCount }, () => []);
    for (const edge of edges) {
      adjacency[edge.from].push(edge.to);
      adjacency[edge.to].push(edge.from);
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
    }));
    const depthOrder = projected.slice();
    const signals: Signal[] = [];

    const projectNodes = () => {
      const cosine = Math.cos(rotation);
      const sine = Math.sin(rotation);
      for (let index = 0; index < nodes.length; index += 1) {
        const node = nodes[index];
        const point = projected[index];
        const x = node.x * cosine - node.z * sine;
        const z = node.x * sine + node.z * cosine;
        const tiltedY = node.y * CT - z * ST;
        const depth = node.y * ST + z * CT;
        const perspective = 1 / (2 - depth * 0.58);
        point.sx = centerX + x * scale * perspective;
        point.sy = centerY + tiltedY * scale * perspective;
        point.depth = depth;
        point.persp = perspective;
        point.fire = node.fire;
      }
      depthOrder.sort((a, b) => a.depth - b.depth);
    };

    const emitFrom = (index: number, fanoutChance: number, signalLimit: number) => {
      nodes[index].fire = 1;
      const peers = adjacency[index];
      for (let peerIndex = 0; peerIndex < peers.length; peerIndex += 1) {
        if (signals.length >= signalLimit) break;
        if (Math.random() < fanoutChance) {
          signals.push({
            from: index,
            to: peers[peerIndex],
            t: 0,
            bend: rnd(-1, 1),
            palette: nodes[index].palette,
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
        node.x = node.bx + Math.sin(phase) * profile.driftAmplitude;
        node.y = node.by + Math.cos(phase * 0.91) * profile.driftAmplitude;
        node.z = node.bz + Math.sin(phase * 1.09) * profile.driftAmplitude;
        node.fire = Math.max(0, node.fire - delta * profile.fireDecay);
      }

      const signalLimit = Math.max(8, Math.round(profile.signalBudget * adaptiveQuality));
      if (signals.length > signalLimit) signals.length = signalLimit;
      fireAccumulator = Math.min(4, fireAccumulator + delta * profile.firingRate);
      const rootBursts = Math.min(3, Math.floor(fireAccumulator));
      fireAccumulator -= rootBursts;
      for (let burst = 0; burst < rootBursts; burst += 1) {
        emitFrom((Math.random() * nodes.length) | 0, profile.fanoutChance, signalLimit);
      }

      let cascadeBudget = 3 + Math.floor(currentEnergy * 5);
      for (let index = signals.length - 1; index >= 0; index -= 1) {
        const signal = signals[index];
        signal.t += delta * profile.signalSpeed;
        if (signal.t < 1) continue;
        const destination = signal.to;
        nodes[destination].fire = Math.min(1, nodes[destination].fire + 0.82);
        signals[index] = signals[signals.length - 1];
        signals.pop();
        if (cascadeBudget > 0 && Math.random() < profile.cascadeChance) {
          cascadeBudget -= 1;
          emitFrom(destination, profile.fanoutChance, signalLimit);
        }
      }
      return profile;
    };

    const drawShell = (fieldStrength: number) => {
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.scale(scale * 0.59, scale * 0.49);
      ctx.rotate(Math.sin(rotation * 0.45) * 0.018);
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = 0.58 + currentEnergy * 0.2;
      ctx.fillStyle = shellGradient;
      ctx.fill(brainHull);
      ctx.globalAlpha = 0.25 + currentEnergy * 0.28;
      ctx.strokeStyle = "rgba(111,210,255,0.42)";
      ctx.lineWidth = 2.2 / Math.max(1, scale);
      ctx.stroke(brainHull);

      ctx.globalAlpha = 0.14 + fieldStrength * 1.8;
      ctx.strokeStyle = "rgba(121,153,255,0.55)";
      ctx.lineWidth = 1.25 / Math.max(1, scale);
      for (const contour of corticalContours) ctx.stroke(contour);

      ctx.globalAlpha = 0.22 + currentEnergy * 0.3;
      ctx.strokeStyle = "rgba(208,223,255,0.58)";
      ctx.lineWidth = 1.8 / Math.max(1, scale);
      ctx.beginPath();
      ctx.moveTo(0, -0.94);
      ctx.bezierCurveTo(-0.055, -0.68, 0.045, -0.42, -0.025, -0.13);
      ctx.bezierCurveTo(-0.06, 0.08, 0.015, 0.28, 0, 0.52);
      ctx.stroke();
      ctx.restore();
    };

    const draw = (profile: ReturnType<typeof getBrainMotionProfile>) => {
      if (reducedMotion) {
        ctx.globalCompositeOperation = "source-over";
        ctx.clearRect(0, 0, width, height);
      } else {
        ctx.globalCompositeOperation = "destination-out";
        ctx.fillStyle = `rgba(0,0,0,${0.25 + 0.13 * (1 - currentEnergy)})`;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.globalCompositeOperation = "lighter";

      drawShell(profile.fieldStrength);
      const fieldAlpha = profile.fieldStrength * (0.7 + currentEnergy * 0.3);
      drawSprite(fieldSprites[0], centerX - scale * 0.23, centerY - scale * 0.05, scale, fieldAlpha);
      drawSprite(fieldSprites[1], centerX + scale * 0.23, centerY - scale * 0.06, scale, fieldAlpha * 0.82);
      if (currentEnergy > 0.36) {
        drawSprite(fieldSprites[2], centerX, centerY + scale * 0.18, scale * 0.72, fieldAlpha * 0.42);
      }

      projectNodes();
      const edgeStride = adaptiveQuality < 0.68 ? 2 : 1;
      for (let index = 0; index < edges.length; index += edgeStride) {
        const edge = edges[index];
        const from = projected[edge.from];
        const to = projected[edge.to];
        const depth = (from.depth + to.depth) * 0.5;
        const heat = Math.max(from.fire, to.fire);
        const depthAlpha = 0.3 + 0.7 * Math.max(0, Math.min(1, (depth + 1.15) / 2.3));
        const alpha = (profile.edgeOpacity + heat * 0.31) * depthAlpha;
        ctx.globalAlpha = 1;
        ctx.strokeStyle = `rgba(${edge.color[0]},${edge.color[1]},${edge.color[2]},${alpha})`;
        ctx.lineWidth = Math.max(0.38, scale * (0.0048 + heat * 0.006) * from.persp);
        ctx.beginPath();
        ctx.moveTo(from.sx, from.sy);
        ctx.lineTo(to.sx, to.sy);
        ctx.stroke();
      }

      for (const signal of signals) {
        const from = projected[signal.from];
        const to = projected[signal.to];
        const eased = signal.t * signal.t * (3 - 2 * signal.t);
        const dx = to.sx - from.sx;
        const dy = to.sy - from.sy;
        const length = Math.max(1, Math.hypot(dx, dy));
        const bend = Math.sin(Math.PI * eased) * scale * 0.018 * signal.bend;
        const x = from.sx + dx * eased - (dy / length) * bend;
        const y = from.sy + dy * eased + (dx / length) * bend;
        const trailT = Math.max(0, eased - 0.075);
        const trailBend = Math.sin(Math.PI * trailT) * scale * 0.018 * signal.bend;
        const trailX = from.sx + dx * trailT - (dy / length) * trailBend;
        const trailY = from.sy + dy * trailT + (dx / length) * trailBend;
        const perspective = (from.persp + to.persp) * 0.5;
        const radius = scale * (0.011 + currentEnergy * 0.01) * perspective;
        const sprite = signalSprites[signal.palette];
        drawSprite(sprite, trailX, trailY, radius * 2.8, 0.23 + currentEnergy * 0.22);
        drawSprite(sprite, x, y, radius * 4, 0.72 + currentEnergy * 0.2);
      }

      const renderWideGlow = adaptiveQuality >= 0.62;
      for (const point of depthOrder) {
        const pulse = reducedMotion
          ? 0
          : currentEnergy *
            (0.5 + 0.5 * Math.sin(globalTime * (0.72 + currentEnergy * 1.65) + point.seed * TAU));
        const normalizedDepth = Math.max(0, Math.min(1, (point.depth + 1.15) / 2.3));
        const baseRadius = scale * (0.007 + 0.012 * normalizedDepth) * point.persp;
        const visibleFire = point.fire * (0.32 + currentEnergy * 0.68);
        const radius = baseRadius * (1 + pulse * 0.18 + visibleFire * 0.9 + currentEnergy * 0.2);
        const brightness = Math.min(
          1,
          0.24 + visibleFire * 0.61 + currentEnergy * 0.3 + normalizedDepth * 0.14,
        );
        const sprite = nodeSprites[point.palette];

        if (renderWideGlow && (normalizedDepth > 0.22 || visibleFire > 0.2)) {
          drawSprite(sprite, point.sx, point.sy, radius * 4.4, brightness * 0.42);
        }
        drawSprite(sprite, point.sx, point.sy, radius * 1.65, brightness * 0.9);
        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgba(255,255,255,${Math.min(1, 0.2 + visibleFire * 0.72 + currentEnergy * 0.11)})`;
        ctx.beginPath();
        ctx.arc(point.sx, point.sy, Math.max(0.42, radius * (0.31 + visibleFire * 0.32)), 0, TAU);
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
      scale = Math.min(width, height) * 0.48;
      shellGradient = ctx.createRadialGradient(
        centerX - scale * 0.12,
        centerY - scale * 0.2,
        scale * 0.08,
        centerX,
        centerY,
        scale * 0.74,
      );
      shellGradient.addColorStop(0, "rgba(65,154,232,0.17)");
      shellGradient.addColorStop(0.54, "rgba(40,84,158,0.09)");
      shellGradient.addColorStop(0.83, "rgba(118,92,220,0.055)");
      shellGradient.addColorStop(1, "rgba(10,28,54,0.015)");
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
      const targetEnergy = Number.isFinite(energyRef.current) ? energyRef.current : 0;
      const targetProfile = getBrainMotionProfile(targetEnergy);
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
