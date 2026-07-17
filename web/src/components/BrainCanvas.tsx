/**
 * BrainCanvas — Zeb's thinking brain as a 2.5D neuron network.
 *
 * A Fibonacci-sphere of neurons squashed into a brain-ish ellipsoid,
 * depth-sorted and perspective-projected onto a 2D canvas. Signals travel
 * along synapses and fire the neurons they reach; a transparent trail-fade
 * leaves comet smears without painting over whatever sits behind the
 * canvas (it's an overlay — the chat flows underneath).
 *
 * `energy` (0..1) drives firing rate, rotation, glow and motion so the
 * brain visibly "thinks harder" while the agent is working. The animation
 * pauses when the tab is hidden or the canvas leaves the viewport.
 *
 * Visual language: a still, readable cortex at rest that turns into a layered
 * signal storm under load. Motion, firing, trails and bloom all scale from the
 * same energy value so harder tasks visibly demand more of the brain.
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

interface Signal {
  from: number;
  to: number;
  t: number;
}

interface Edge {
  from: number;
  to: number;
  color: RGB;
}

const TILT = 0.34;
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
  const size = 96;
  sprite.width = size;
  sprite.height = size;
  const spriteContext = sprite.getContext("2d");
  if (!spriteContext) return sprite;

  const center = size / 2;
  const gradient = spriteContext.createRadialGradient(center, center, 0, center, center, center);
  if (whiteCore) {
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.12, `rgba(${color[0]},${color[1]},${color[2]},0.98)`);
  } else {
    gradient.addColorStop(0, `rgba(${color[0]},${color[1]},${color[2]},1)`);
  }
  gradient.addColorStop(0.38, `rgba(${color[0]},${color[1]},${color[2]},0.42)`);
  gradient.addColorStop(0.72, `rgba(${color[0]},${color[1]},${color[2]},0.1)`);
  gradient.addColorStop(1, `rgba(${color[0]},${color[1]},${color[2]},0)`);
  spriteContext.fillStyle = gradient;
  spriteContext.fillRect(0, 0, size, size);
  return sprite;
}

export function BrainCanvas({
  energy = 0,
  className,
}: {
  /** Target activity level 0..1 — eased internally, safe to change often. */
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
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let W = 0;
    let H = 0;
    let CX = 0;
    let CY = 0;
    let scale = 1;
    let rot = 0;
    let tGlobal = 0;
    let last = 0;
    let fireAcc = 0;
    let cur = 0;
    let raf = 0;
    let running = true;
    let visible = true;
    const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reducedMotion = reducedMotionQuery.matches;

    const palette: readonly RGB[] = [
      [45, 230, 255], // cyan
      [65, 126, 255], // electric blue
      [157, 102, 255], // violet
      [255, 103, 132], // coral
    ];
    const nodeSprites = palette.map((color) => createGlowSprite(color));
    const signalSprite = createGlowSprite(palette[3], true);
    const fieldSprites = [createGlowSprite(palette[0]), createGlowSprite(palette[2])];
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

    // --- topology -----------------------------------------------------
    // A dense two-hemisphere cortex. The centre cleft and lobe modulation make
    // the silhouette read as a brain rather than a generic glowing sphere.
    const N = 132;
    const nodes: Node[] = [];
    const GA = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = GA * i;
      let x = Math.cos(th) * r;
      let z = Math.sin(th) * r;
      let yy = y;
      const lobe = 0.92 + 0.08 * Math.cos(yy * Math.PI * 1.6);
      const k = rnd(0.84, 1.0) * lobe;
      x *= 1.22 * k;
      yy *= 0.88 * k;
      z *= 0.94 * k;
      x += x >= 0 ? 0.055 : -0.055;
      x += rnd(-0.045, 0.045);
      yy += rnd(-0.045, 0.045);
      z += rnd(-0.045, 0.045);
      const seed = Math.random();
      const paletteIndex =
        seed < 0.075 ? 3 : x < 0 ? (z > 0 ? 0 : 1) : z > 0 ? 2 : 1;
      nodes.push({
        bx: x,
        by: yy,
        bz: z,
        x,
        y: yy,
        z,
        seed,
        drift: rnd(0, 6.28),
        fire: 0,
        palette: paletteIndex,
      });
    }
    const edgePairs: Array<[number, number]> = [];
    const has = (i: number, j: number) =>
      edgePairs.some((e) => (e[0] === i && e[1] === j) || (e[0] === j && e[1] === i));
    const D3 = (a: Node, b: Node) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    // Tighter threshold than before because neurons sit closer together at
    // this density — this keeps each neuron wired to a handful of neighbours
    // instead of the whole hemisphere.
    for (let i = 0; i < N; i++)
      for (let j = i + 1; j < N; j++) {
        if (D3(nodes[i], nodes[j]) < 0.39) edgePairs.push([i, j]);
      }
    // Guarantee no orphan neurons: wire each to its two nearest peers.
    for (let i = 0; i < N; i++) {
      const dist = nodes
        .map((n, j) => ({ j, d: j === i ? 9 : D3(nodes[i], n) }))
        .sort((a, b) => a.d - b.d);
      for (const { j } of dist.slice(0, 2)) {
        if (!has(i, j)) edgePairs.push([Math.min(i, j), Math.max(i, j)]);
      }
    }
    const edges: Edge[] = edgePairs.map(([from, to]) => ({
      from,
      to,
      color: mixColor(palette[nodes[from].palette], palette[nodes[to].palette]),
    }));
    const signals: Signal[] = [];
    const SIGNAL_CAP = 480;

    const emitFrom = (idx: number, fanoutChance: number) => {
      nodes[idx].fire = 1;
      for (const e of edges) {
        let to = -1;
        if (e.from === idx) to = e.to;
        else if (e.to === idx) to = e.from;
        else continue;
        if (signals.length < SIGNAL_CAP && Math.random() < fanoutChance)
          signals.push({ from: idx, to, t: 0 });
      }
    };

    // --- projection ----------------------------------------------------
    const project = (n: Node) => {
      const cr = Math.cos(rot);
      const sr = Math.sin(rot);
      const x = n.x * cr - n.z * sr;
      const z = n.x * sr + n.z * cr;
      const y2 = n.y * CT - z * ST;
      const z2 = n.y * ST + z * CT;
      const persp = 1 / (2.0 - z2 * 0.6);
      return { sx: CX + x * scale * persp, sy: CY + y2 * scale * persp, depth: z2, persp };
    };

    const step = (dt: number) => {
      const target = Math.max(0, Math.min(1, energyRef.current));
      cur += (target - cur) * Math.min(1, dt * (target > cur ? 4.8 : 2.4));
      const profile = getBrainMotionProfile(cur);

      if (reducedMotion) {
        signals.length = 0;
        fireAcc = 0;
        for (const n of nodes) {
          n.x = n.bx;
          n.y = n.by;
          n.z = n.bz;
          n.fire = 0;
        }
        return;
      }

      rot += dt * profile.rotationSpeed;
      tGlobal += dt * profile.driftSpeed;
      for (const n of nodes) {
        const w = tGlobal + n.drift;
        n.x = n.bx + Math.sin(w) * profile.driftAmplitude;
        n.y = n.by + Math.cos(w * 0.9) * profile.driftAmplitude;
        n.z = n.bz + Math.sin(w * 1.1) * profile.driftAmplitude;
        n.fire = Math.max(0, n.fire - dt * profile.fireDecay);
      }

      fireAcc += dt * profile.firingRate;
      while (fireAcc >= 1) {
        fireAcc -= 1;
        emitFrom((Math.random() * nodes.length) | 0, profile.fanoutChance);
      }

      for (let i = signals.length - 1; i >= 0; i--) {
        const s = signals[i];
        s.t += dt * profile.signalSpeed;
        if (s.t >= 1) {
          nodes[s.to].fire = Math.min(1, nodes[s.to].fire + 0.8);
          if (Math.random() < profile.cascadeChance) {
            emitFrom(s.to, profile.fanoutChance);
          }
          signals.splice(i, 1);
        }
      }
    };

    const draw = () => {
      if (reducedMotion) {
        ctx.globalCompositeOperation = "source-over";
        ctx.clearRect(0, 0, W, H);
      } else {
        // Fade old pixels without painting a dark rectangle over the chat.
        ctx.globalCompositeOperation = "destination-out";
        ctx.fillStyle = `rgba(0,0,0,${0.22 + 0.16 * (1 - cur)})`;
        ctx.fillRect(0, 0, W, H);
      }
      ctx.globalCompositeOperation = "lighter";

      // These fields and every neuron/signal bloom reuse mount-time sprites;
      // the animation loop allocates no CanvasGradient objects.
      if (cur > 0.03) {
        drawSprite(fieldSprites[0], CX - scale * 0.2, CY, scale * 1.18, cur * 0.075);
        drawSprite(fieldSprites[1], CX + scale * 0.2, CY, scale * 1.18, cur * 0.065);
      }

      const P = nodes.map((n, i) => {
        const p = project(n) as ReturnType<typeof project> & {
          i: number;
          fire: number;
          seed: number;
          palette: number;
        };
        p.i = i;
        p.fire = n.fire;
        p.seed = n.seed;
        p.palette = n.palette;
        return p;
      });
      const order = P.slice().sort((a, b) => a.depth - b.depth);

      ctx.globalAlpha = 1;
      for (const e of edges) {
        const a = P[e.from];
        const b = P[e.to];
        const dep = (a.depth + b.depth) / 2;
        const heat = Math.max(a.fire, b.fire);
        const al =
          (0.045 + cur * 0.29 + heat * 0.32) *
          (0.42 + 0.58 * ((dep + 1) / 2));
        ctx.strokeStyle = `rgba(${e.color[0]},${e.color[1]},${e.color[2]},${al})`;
        ctx.lineWidth = Math.max(0.4, scale * (0.006 + heat * 0.006) * a.persp);
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.stroke();
      }

      for (const s of signals) {
        const a = P[s.from];
        const b = P[s.to];
        const te = s.t * s.t * (3 - 2 * s.t);
        const x = a.sx + (b.sx - a.sx) * te;
        const y = a.sy + (b.sy - a.sy) * te;
        const persp = (a.persp + b.persp) / 2;
        const r = (scale * 0.013 + cur * scale * 0.014) * persp;
        drawSprite(signalSprite, x, y, r * 3.8, 0.78 + cur * 0.22);
      }

      for (const p of order) {
        const pulse = cur * (0.5 + 0.5 * Math.sin(tGlobal * (0.8 + cur * 1.8) + p.seed * 6.28));
        const depthN = (p.depth + 1) / 2;
        const base = scale * (0.008 + 0.013 * depthN) * p.persp;
        const visibleFire = p.fire * (0.35 + cur * 0.65);
        const rr = base * (1 + pulse * 0.2 + visibleFire * 0.95 + cur * 0.3);
        const bright = Math.min(
          1,
          0.28 + visibleFire * 0.58 + cur * 0.36 + depthN * 0.13,
        );
        const sprite = nodeSprites[p.palette];

        drawSprite(sprite, p.sx, p.sy, rr * 4.6, bright * (0.42 + cur * 0.12));
        drawSprite(sprite, p.sx, p.sy, rr * 1.7, bright * 0.9);

        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgba(255,255,255,${Math.min(1, 0.24 + visibleFire * 0.7 + cur * 0.12)})`;
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, Math.max(0.45, rr * (0.34 + visibleFire * 0.34)), 0, 7);
        ctx.fill();
      }

      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.clientWidth || 180;
      H = canvas.clientHeight || 180;
      canvas.width = Math.max(1, Math.round(W * dpr));
      canvas.height = Math.max(1, Math.round(H * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      CX = W / 2;
      CY = H / 2;
      scale = Math.min(W, H) * 0.42;
      ctx.clearRect(0, 0, W, H);
    };

    const frame = (ts: number) => {
      if (!running) return;
      if (!visible || document.hidden) {
        // Skip work while off-screen; keep the loop alive cheaply.
        last = ts;
        raf = requestAnimationFrame(frame);
        return;
      }
      // A reduced-motion canvas only needs enough frames to ease brightness
      // when energy changes; rotation, drift and signals remain disabled.
      if (reducedMotion && ts - last < 100) {
        raf = requestAnimationFrame(frame);
        return;
      }
      const dt = Math.min((ts - last) / 1000, reducedMotion ? 0.1 : 0.05);
      last = ts;
      step(dt);
      draw();
      raf = requestAnimationFrame(frame);
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const io = new IntersectionObserver((entries) => {
      visible = entries[0]?.isIntersecting ?? true;
    });
    io.observe(canvas);
    const onReducedMotionChange = (event: MediaQueryListEvent) => {
      reducedMotion = event.matches;
      if (reducedMotion) {
        signals.length = 0;
        fireAcc = 0;
      }
    };
    reducedMotionQuery.addEventListener("change", onReducedMotionChange);

    raf = requestAnimationFrame((ts) => {
      last = ts;
      frame(ts);
    });

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      reducedMotionQuery.removeEventListener("change", onReducedMotionChange);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden />;
}
