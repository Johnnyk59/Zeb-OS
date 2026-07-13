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
 * Visual language (upgraded pass):
 *   • ~64 neurons on a denser synapse graph — a real, alive-feeling network.
 *   • No flat blue wash — every glow is additive light on transparency, so
 *     the brain reads as luminous energy over the chat, not a colored box.
 *   • Two-layer neuron bloom (wide soft halo + tight bright core) plus a
 *     hot white pinpoint on firing for crisp "spark" lighting.
 *   • Faster rotation, drift and signal travel; smoother energy easing.
 */
import { useEffect, useRef } from "react";

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
}

interface Signal {
  from: number;
  to: number;
  t: number;
}

const TILT = 0.34;
const CT = Math.cos(TILT);
const ST = Math.sin(TILT);

function rnd(a: number, b: number): number {
  return a + Math.random() * (b - a);
}

export function BrainCanvas({
  energy = 0.05,
  className,
}: {
  /** Target activity level 0..1 — eased internally, safe to change often. */
  energy?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const energyRef = useRef(energy);
  energyRef.current = energy;

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
    let cur = 0.05;
    let raf = 0;
    let running = true;
    let visible = true;

    // --- topology -----------------------------------------------------
    // A dense cortex: ~96 neurons make the brain read as a living network
    // rather than a lattice, still holding 60fps (per-frame cost is gradients,
    // capped by the depth sort + signal ceiling). This is a deliberate, large
    // step up from the original sparse 24-node version.
    const N = 96;
    const nodes: Node[] = [];
    const GA = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = GA * i;
      let x = Math.cos(th) * r;
      let z = Math.sin(th) * r;
      let yy = y;
      const k = rnd(0.82, 1.0);
      x *= 1.18 * k;
      yy *= 0.86 * k;
      z *= 0.92 * k;
      x += rnd(-0.045, 0.045);
      yy += rnd(-0.045, 0.045);
      z += rnd(-0.045, 0.045);
      nodes.push({ bx: x, by: yy, bz: z, x, y: yy, z, seed: Math.random(), drift: rnd(0, 6.28), fire: 0 });
    }
    const edges: Array<[number, number]> = [];
    const has = (i: number, j: number) =>
      edges.some((e) => (e[0] === i && e[1] === j) || (e[0] === j && e[1] === i));
    const D3 = (a: Node, b: Node) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    // Tighter threshold than before because neurons sit closer together at
    // this density — this keeps each neuron wired to a handful of neighbours
    // instead of the whole hemisphere.
    for (let i = 0; i < N; i++)
      for (let j = i + 1; j < N; j++) {
        if (D3(nodes[i], nodes[j]) < 0.44) edges.push([i, j]);
      }
    // Guarantee no orphan neurons: wire each to its two nearest peers.
    for (let i = 0; i < N; i++) {
      const dist = nodes
        .map((n, j) => ({ j, d: j === i ? 9 : D3(nodes[i], n) }))
        .sort((a, b) => a.d - b.d);
      for (const { j } of dist.slice(0, 2)) {
        if (!has(i, j)) edges.push([Math.min(i, j), Math.max(i, j)]);
      }
    }
    const signals: Signal[] = [];
    const SIGNAL_CAP = 340;

    const emitFrom = (idx: number) => {
      nodes[idx].fire = 1;
      for (const e of edges) {
        let to = -1;
        if (e[0] === idx) to = e[1];
        else if (e[1] === idx) to = e[0];
        else continue;
        if (signals.length < SIGNAL_CAP && Math.random() < 0.6) signals.push({ from: idx, to, t: 0 });
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
      // Snappy energy easing so thinking bursts feel instant.
      cur += (energyRef.current - cur) * Math.min(1, dt * 3.2);
      // Faster spin: idle drifts, working whirls hard.
      rot += dt * (0.09 + cur * 0.58);
      tGlobal += dt;
      for (const n of nodes) {
        const w = tGlobal * 0.85 + n.drift;
        // Livelier micro-motion so the whole mesh visibly breathes.
        n.x = n.bx + Math.sin(w) * 0.042;
        n.y = n.by + Math.cos(w * 0.9) * 0.042;
        n.z = n.bz + Math.sin(w * 1.1) * 0.042;
        n.fire = Math.max(0, n.fire - dt * 1.9);
      }
      // High spontaneous firing rate — the net is always alive, and storms
      // under load.
      fireAcc += dt * (1.1 + cur * 11.0);
      while (fireAcc >= 1) {
        fireAcc -= 1;
        emitFrom((Math.random() * nodes.length) | 0);
      }
      // Signals travel fast and chain readily → a cascading, electric net.
      const speed = 0.95 + cur * 3.1;
      for (let i = signals.length - 1; i >= 0; i--) {
        const s = signals[i];
        s.t += dt * speed;
        if (s.t >= 1) {
          nodes[s.to].fire = Math.min(1, nodes[s.to].fire + 0.8);
          if (Math.random() < 0.34 + cur * 0.45) emitFrom(s.to);
          signals.splice(i, 1);
        }
      }
    };

    // Neuron teal + signal violet. No blue core wash — light only.
    const NC: [number, number, number] = [64, 240, 220];
    const SC: [number, number, number] = [168, 132, 255];

    const draw = () => {
      // Pull existing pixels toward alpha 0 → comet trails without a
      // dark box over the content behind the overlay. A gentler fade at
      // high energy leaves longer, silkier light streaks.
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = `rgba(0,0,0,${0.22 + 0.16 * (1 - cur)})`;
      ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";

      const P = nodes.map((n, i) => {
        const p = project(n) as ReturnType<typeof project> & {
          i: number;
          fire: number;
          seed: number;
        };
        p.i = i;
        p.fire = n.fire;
        p.seed = n.seed;
        return p;
      });
      const order = P.slice().sort((a, b) => a.depth - b.depth);

      // Synapses — brighter and slightly warmer as the net lights up. Front
      // edges read stronger than the ones curving behind the sphere.
      for (const e of edges) {
        const a = P[e[0]];
        const b = P[e[1]];
        const dep = (a.depth + b.depth) / 2;
        const heat = Math.max(a.fire, b.fire);
        const al = (0.05 + cur * 0.2 + heat * 0.28) * (0.42 + 0.58 * ((dep + 1) / 2));
        ctx.strokeStyle = `rgba(${NC[0]},${NC[1]},${NC[2]},${al})`;
        ctx.lineWidth = Math.max(0.4, scale * (0.006 + heat * 0.006) * a.persp);
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.stroke();
      }

      // Travelling signals — a soft violet comet with a hot core.
      for (const s of signals) {
        const a = P[s.from];
        const b = P[s.to];
        const te = s.t * s.t * (3 - 2 * s.t);
        const x = a.sx + (b.sx - a.sx) * te;
        const y = a.sy + (b.sy - a.sy) * te;
        const persp = (a.persp + b.persp) / 2;
        const r = (scale * 0.013 + cur * scale * 0.014) * persp;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3.6);
        g.addColorStop(0, `rgba(255,255,255,0.9)`);
        g.addColorStop(0.25, `rgba(${SC[0]},${SC[1]},${SC[2]},0.85)`);
        g.addColorStop(0.6, `rgba(${SC[0]},${SC[1]},${SC[2]},0.32)`);
        g.addColorStop(1, `rgba(${SC[0]},${SC[1]},${SC[2]},0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, r * 3.6, 0, 7);
        ctx.fill();
      }

      // Neurons — two-layer bloom (wide halo + tight core) plus a hot white
      // pinpoint while firing, drawn back-to-front for depth.
      for (const p of order) {
        const pulse = 0.5 + 0.5 * Math.sin(tGlobal * (0.8 + cur * 1.4) + p.seed * 6.28);
        const depthN = (p.depth + 1) / 2;
        const base = scale * (0.008 + 0.013 * depthN) * p.persp;
        const rr = base * (1 + pulse * 0.2 + p.fire * 0.95 + cur * 0.28);
        const bright = Math.min(1, 0.36 + p.fire * 0.55 + cur * 0.2 + depthN * 0.15);

        // Wide soft halo — a touch larger for a brighter bloom.
        const halo = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, rr * 4.6);
        halo.addColorStop(0, `rgba(${NC[0]},${NC[1]},${NC[2]},${bright * 0.5})`);
        halo.addColorStop(0.5, `rgba(${NC[0]},${NC[1]},${NC[2]},${bright * 0.16})`);
        halo.addColorStop(1, `rgba(${NC[0]},${NC[1]},${NC[2]},0)`);
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, rr * 4.2, 0, 7);
        ctx.fill();

        // Tight bright core.
        const core = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, rr * 1.6);
        core.addColorStop(0, `rgba(${NC[0]},${NC[1]},${NC[2]},${bright})`);
        core.addColorStop(1, `rgba(${NC[0]},${NC[1]},${NC[2]},0)`);
        ctx.fillStyle = core;
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, rr * 1.6, 0, 7);
        ctx.fill();

        // Hot white spark at the centre — sharpest while firing.
        ctx.fillStyle = `rgba(255,255,255,${Math.min(1, 0.35 + p.fire * 0.55)})`;
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, Math.max(0.5, rr * (0.4 + p.fire * 0.35)), 0, 7);
        ctx.fill();
      }
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
      const dt = Math.min((ts - last) / 1000, 0.05);
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

    raf = requestAnimationFrame((ts) => {
      last = ts;
      frame(ts);
    });

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden />;
}
