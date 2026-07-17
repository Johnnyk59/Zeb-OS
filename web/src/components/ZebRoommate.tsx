/* eslint-disable react-refresh/only-export-components -- registry exports keep tests aligned with the renderer. */
import {
  startTransition,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

export type RoommateSceneId =
  | "idle"
  | "vape"
  | "weights"
  | "couch"
  | "tv"
  | "carry-tv"
  | "phone"
  | "snack"
  | "window-vape"
  | "couch-crossed"
  | "groceries"
  | "gaming"
  | "sleep"
  | "laptop"
  | "plant"
  | "music"
  | "trading"
  | "ramen"
  | "meditate"
  | "maker"
  | "couch-vape"
  | "crate-vape"
  | "phone-vape"
  | "big-exhale";

type RoommatePose = "standing" | "seated" | "mobile" | "floor";
type RoommateZone = "free" | "lounge" | "desk" | "mobile" | "floor";

type RoommateMotion =
  | "rest"
  | "smoke"
  | "lift"
  | "lounge"
  | "watch"
  | "walk"
  | "phone"
  | "snack"
  | "game"
  | "sleep"
  | "type"
  | "water"
  | "music"
  | "trade"
  | "noodle"
  | "meditate"
  | "maker";

type RoommateEffect =
  | "none"
  | "smoke"
  | "weights"
  | "tv"
  | "phone"
  | "crumbs"
  | "footsteps"
  | "controller"
  | "dream"
  | "laptop"
  | "water"
  | "music"
  | "hologram"
  | "steam"
  | "aura"
  | "maker";

export type RoommateTransition =
  | "crossfade"
  | "walk"
  | "lounge"
  | "rise"
  | "desk"
  | "floor";

type MicroAction =
  | "none"
  | "look"
  | "settle"
  | "draw"
  | "exhale"
  | "rep"
  | "tap"
  | "scroll"
  | "bite"
  | "play"
  | "dream"
  | "type"
  | "water"
  | "bop"
  | "step"
  | "focus"
  | "steam"
  | "float"
  | "repair";

interface EyeGeometry {
  x: number;
  y: number;
  width: number;
  height?: number;
  gap?: number;
  rotate?: number;
}

export interface RoommateScene {
  id: RoommateSceneId;
  sheet: string;
  cell: number;
  label: string;
  pose: RoommatePose;
  zone: RoommateZone;
  motion: RoommateMotion;
  effect: RoommateEffect;
  holdMs: readonly [number, number];
  eyes?: EyeGeometry;
  scale?: number;
  x?: number;
  y?: number;
  propLocked?: boolean;
}

const SHEET_CORE = "/zeb/zeb-roommate-core-sprites-v2.png";
const SHEET_DAILY = "/zeb/zeb-roommate-daily-sprites-v2.png";
const SHEET_FLOW = "/zeb/zeb-roommate-flow-sprites-v2.png";
const SHEET_EXTRA = "/zeb/zeb-roommate-extra-sprites-v2.png";
const SHEET_SMOKE = "/zeb/zeb-roommate-smoke-sprites-v2.png";

const STANDING_EYES: EyeGeometry = { x: 50, y: 22, width: 21.5, height: 7.5, gap: 5.1 };
const SEATED_EYES: EyeGeometry = { x: 33, y: 24, width: 18.6, height: 7.2, gap: 4.6 };
const FLOOR_EYES: EyeGeometry = { x: 28, y: 21.5, width: 18.8, height: 7.1, gap: 4.3 };

export const ROOMMATE_SCENES: Record<RoommateSceneId, RoommateScene> = {
  idle: {
    id: "idle",
    sheet: SHEET_CORE,
    cell: 0,
    label: "just standing there faded",
    pose: "standing",
    zone: "free",
    motion: "rest",
    effect: "none",
    holdMs: [34_000, 58_000],
    eyes: { ...STANDING_EYES, x: 51.8, y: 21.8, width: 21.2 },
    scale: 1.08,
    y: 1,
  },
  vape: {
    id: "vape",
    sheet: SHEET_CORE,
    cell: 1,
    label: "taking a smoke break",
    pose: "standing",
    zone: "free",
    motion: "smoke",
    effect: "smoke",
    holdMs: [32_000, 54_000],
    eyes: { ...STANDING_EYES, x: 50.4, y: 22.2, width: 21.4 },
    scale: 1.09,
    y: 1,
  },
  weights: {
    id: "weights",
    sheet: SHEET_CORE,
    cell: 2,
    label: "getting a little pump in",
    pose: "standing",
    zone: "free",
    motion: "lift",
    effect: "weights",
    holdMs: [26_000, 42_000],
    eyes: { ...STANDING_EYES, x: 50.1, y: 21.5, width: 20.7 },
    scale: 1.07,
    y: 1,
  },
  couch: {
    id: "couch",
    sheet: SHEET_CORE,
    cell: 3,
    label: "posted up on the couch",
    pose: "seated",
    zone: "lounge",
    motion: "lounge",
    effect: "none",
    holdMs: [38_000, 64_000],
    eyes: { ...SEATED_EYES, x: 26.5, y: 24.1, width: 18.1, rotate: 1 },
    scale: 1.04,
    y: 3,
    propLocked: true,
  },
  tv: {
    id: "tv",
    sheet: SHEET_CORE,
    cell: 4,
    label: "locked into a retro screen",
    pose: "seated",
    zone: "lounge",
    motion: "watch",
    effect: "tv",
    holdMs: [36_000, 60_000],
    eyes: { ...SEATED_EYES, x: 31.8, y: 24.6, width: 18.3, rotate: 1 },
    scale: 1.02,
    x: -1,
    y: 4,
    propLocked: true,
  },
  "carry-tv": {
    id: "carry-tv",
    sheet: SHEET_CORE,
    cell: 5,
    label: "moving the whole setup",
    pose: "mobile",
    zone: "mobile",
    motion: "walk",
    effect: "footsteps",
    holdMs: [20_000, 36_000],
    eyes: { ...STANDING_EYES, x: 52.2, y: 20.3, width: 18.8 },
    scale: 1.05,
    y: 3,
  },
  phone: {
    id: "phone",
    sheet: SHEET_DAILY,
    cell: 0,
    label: "checking his phone",
    pose: "standing",
    zone: "free",
    motion: "phone",
    effect: "phone",
    holdMs: [26_000, 46_000],
    eyes: { ...STANDING_EYES, x: 52.6, y: 21.6, width: 21.4 },
    scale: 1.08,
    y: 1,
  },
  snack: {
    id: "snack",
    sheet: SHEET_DAILY,
    cell: 1,
    label: "killing a bag of chips",
    pose: "standing",
    zone: "free",
    motion: "snack",
    effect: "crumbs",
    holdMs: [24_000, 40_000],
    eyes: { ...STANDING_EYES, x: 50.8, y: 22.1, width: 21.4 },
    scale: 1.05,
    y: 1,
  },
  "window-vape": {
    id: "window-vape",
    sheet: SHEET_DAILY,
    cell: 2,
    label: "leaning back with the vape",
    pose: "standing",
    zone: "free",
    motion: "smoke",
    effect: "smoke",
    holdMs: [32_000, 52_000],
    eyes: { ...STANDING_EYES, x: 51.3, y: 21.5, width: 20.9 },
    scale: 1.06,
    y: 1,
  },
  "couch-crossed": {
    id: "couch-crossed",
    sheet: SHEET_DAILY,
    cell: 4,
    label: "sitting all comfortable",
    pose: "seated",
    zone: "lounge",
    motion: "lounge",
    effect: "none",
    holdMs: [38_000, 64_000],
    eyes: { ...SEATED_EYES, x: 34.7, y: 24.2, width: 18.6 },
    scale: 1.03,
    y: 4,
    propLocked: true,
  },
  groceries: {
    id: "groceries",
    sheet: SHEET_DAILY,
    cell: 5,
    label: "back from the store",
    pose: "mobile",
    zone: "mobile",
    motion: "walk",
    effect: "footsteps",
    holdMs: [22_000, 38_000],
    eyes: { ...STANDING_EYES, x: 50.4, y: 20.2, width: 18.9 },
    scale: 1.03,
    y: 3,
  },
  gaming: {
    id: "gaming",
    sheet: SHEET_FLOW,
    cell: 0,
    label: "running one more game",
    pose: "seated",
    zone: "lounge",
    motion: "game",
    effect: "controller",
    holdMs: [30_000, 50_000],
    eyes: { ...SEATED_EYES, x: 28.7, y: 21.8, width: 18.5 },
    scale: 1.04,
    y: 4,
    propLocked: true,
  },
  sleep: {
    id: "sleep",
    sheet: SHEET_FLOW,
    cell: 1,
    label: "out cold for a minute",
    pose: "seated",
    zone: "lounge",
    motion: "sleep",
    effect: "dream",
    holdMs: [52_000, 90_000],
    scale: 1.03,
    y: 4,
    propLocked: true,
  },
  laptop: {
    id: "laptop",
    sheet: SHEET_FLOW,
    cell: 2,
    label: "building something",
    pose: "seated",
    zone: "desk",
    motion: "type",
    effect: "laptop",
    holdMs: [34_000, 62_000],
    eyes: { ...SEATED_EYES, x: 32.2, y: 22.2, width: 18.2, rotate: -1 },
    scale: 1.01,
    y: 4,
    propLocked: true,
  },
  plant: {
    id: "plant",
    sheet: SHEET_FLOW,
    cell: 3,
    label: "watering the plant",
    pose: "standing",
    zone: "free",
    motion: "water",
    effect: "water",
    holdMs: [28_000, 46_000],
    eyes: { ...STANDING_EYES, x: 28.2, y: 21.8, width: 20.8, rotate: -2 },
    scale: 1.03,
    x: -4,
    y: 2,
    propLocked: true,
  },
  music: {
    id: "music",
    sheet: SHEET_FLOW,
    cell: 4,
    label: "floating in the music",
    pose: "standing",
    zone: "free",
    motion: "music",
    effect: "music",
    holdMs: [30_000, 50_000],
    eyes: { ...STANDING_EYES, x: 50.1, y: 21.9, width: 21.2 },
    scale: 1.06,
    y: 1,
  },
  trading: {
    id: "trading",
    sheet: SHEET_FLOW,
    cell: 5,
    label: "watching the charts",
    pose: "seated",
    zone: "desk",
    motion: "trade",
    effect: "hologram",
    holdMs: [34_000, 60_000],
    eyes: { ...SEATED_EYES, x: 33.1, y: 22.6, width: 18.3 },
    scale: 1.03,
    y: 4,
    propLocked: true,
  },
  ramen: {
    id: "ramen",
    sheet: SHEET_EXTRA,
    cell: 0,
    label: "eating ramen on the floor",
    pose: "floor",
    zone: "floor",
    motion: "noodle",
    effect: "steam",
    holdMs: [26_000, 46_000],
    eyes: { ...FLOOR_EYES, x: 23.2, y: 20.4, width: 19.3 },
    scale: 0.99,
    y: 6,
    propLocked: true,
  },
  meditate: {
    id: "meditate",
    sheet: SHEET_EXTRA,
    cell: 3,
    label: "sitting still for once",
    pose: "floor",
    zone: "floor",
    motion: "meditate",
    effect: "aura",
    holdMs: [42_000, 74_000],
    eyes: { ...FLOOR_EYES, x: 22.4, y: 22.6, width: 18.3 },
    scale: 0.98,
    y: 6,
    propLocked: true,
  },
  maker: {
    id: "maker",
    sheet: SHEET_EXTRA,
    cell: 5,
    label: "messing with a little gadget",
    pose: "seated",
    zone: "desk",
    motion: "maker",
    effect: "maker",
    holdMs: [32_000, 56_000],
    eyes: { ...SEATED_EYES, x: 27.9, y: 21.1, width: 18.2 },
    scale: 1,
    y: 5,
    propLocked: true,
  },
  "couch-vape": {
    id: "couch-vape",
    sheet: SHEET_SMOKE,
    cell: 0,
    label: "smoking on the couch",
    pose: "seated",
    zone: "lounge",
    motion: "smoke",
    effect: "smoke",
    holdMs: [34_000, 56_000],
    eyes: { ...SEATED_EYES, x: 27.4, y: 23.6, width: 18.2 },
    scale: 1.03,
    y: 4,
    propLocked: true,
  },
  "crate-vape": {
    id: "crate-vape",
    sheet: SHEET_SMOKE,
    cell: 1,
    label: "smoking on a milk crate",
    pose: "seated",
    zone: "lounge",
    motion: "smoke",
    effect: "smoke",
    holdMs: [32_000, 52_000],
    eyes: { ...SEATED_EYES, x: 49.7, y: 21.8, width: 19.1 },
    scale: 1.02,
    y: 4,
    propLocked: true,
  },
  "phone-vape": {
    id: "phone-vape",
    sheet: SHEET_SMOKE,
    cell: 2,
    label: "scrolling and smoking",
    pose: "standing",
    zone: "free",
    motion: "smoke",
    effect: "smoke",
    holdMs: [30_000, 50_000],
    eyes: { ...STANDING_EYES, x: 50.4, y: 22.1, width: 21.2 },
    scale: 1.06,
    y: 1,
  },
  "big-exhale": {
    id: "big-exhale",
    sheet: SHEET_SMOKE,
    cell: 4,
    label: "blowing a giant cloud",
    pose: "seated",
    zone: "lounge",
    motion: "smoke",
    effect: "smoke",
    holdMs: [30_000, 50_000],
    eyes: { ...SEATED_EYES, x: 33.6, y: 24, width: 18.4 },
    scale: 1.03,
    y: 4,
    propLocked: true,
  },
};

export const ROOMMATE_ACTIVITY_CYCLE: RoommateSceneId[] = [
  "idle",
  "vape",
  "weights",
  "couch",
  "tv",
  "carry-tv",
  "phone",
  "snack",
  "window-vape",
  "couch-crossed",
  "groceries",
  "gaming",
  "sleep",
  "laptop",
  "plant",
  "music",
  "trading",
  "ramen",
  "meditate",
  "maker",
  "couch-vape",
  "crate-vape",
  "phone-vape",
  "big-exhale",
];

const MICRO_ACTIONS: Record<RoommateSceneId, readonly MicroAction[]> = {
  idle: ["look", "settle", "look"],
  vape: ["draw", "exhale", "settle"],
  weights: ["rep", "rep", "settle"],
  couch: ["settle", "look"],
  tv: ["focus", "focus", "settle"],
  "carry-tv": ["step", "step", "settle"],
  phone: ["tap", "scroll", "look"],
  snack: ["bite", "settle", "bite"],
  "window-vape": ["draw", "exhale", "look"],
  "couch-crossed": ["settle", "look"],
  groceries: ["step", "settle"],
  gaming: ["play", "play", "focus"],
  sleep: ["dream", "dream"],
  laptop: ["type", "type", "focus"],
  plant: ["water", "look"],
  music: ["bop", "bop", "settle"],
  trading: ["type", "focus", "focus"],
  ramen: ["bite", "steam", "settle"],
  meditate: ["float", "float", "settle"],
  maker: ["repair", "repair", "focus"],
  "couch-vape": ["draw", "exhale", "settle"],
  "crate-vape": ["draw", "exhale", "look"],
  "phone-vape": ["tap", "draw", "exhale"],
  "big-exhale": ["draw", "exhale", "exhale"],
};

const MICRO_ACTION_DELAYS: Record<RoommateMotion, readonly [number, number]> = {
  rest: [8_500, 15_000],
  smoke: [4_800, 8_800],
  lift: [4_000, 7_200],
  lounge: [8_500, 16_000],
  watch: [6_800, 12_500],
  walk: [4_400, 7_800],
  phone: [4_000, 7_800],
  snack: [4_800, 8_400],
  game: [4_000, 7_200],
  sleep: [10_500, 16_500],
  type: [4_200, 7_800],
  water: [5_400, 9_200],
  music: [4_500, 8_000],
  trade: [4_500, 7_600],
  noodle: [5_500, 9_400],
  meditate: [6_500, 11_500],
  maker: [4_600, 8_200],
};

function shuffledCycle(): RoommateSceneId[] {
  const next = [...ROOMMATE_ACTIVITY_CYCLE];
  for (let i = next.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [next[i], next[j]] = [next[j], next[i]];
  }
  return next;
}

export function selectNextRoommateScene(
  current: RoommateSceneId,
  queued: readonly RoommateSceneId[],
  replenish: () => RoommateSceneId[] = shuffledCycle,
): { sceneId: RoommateSceneId; remaining: RoommateSceneId[] } {
  const remaining = [...queued];
  let replenished = false;

  while (true) {
    const candidateIndex = remaining.findIndex((candidate) => candidate !== current);
    if (candidateIndex >= 0) {
      const [sceneId] = remaining.splice(candidateIndex, 1);
      if (sceneId) return { sceneId, remaining };
    }

    if (replenished) break;
    remaining.push(...replenish());
    replenished = true;
  }

  const fallback = ROOMMATE_ACTIVITY_CYCLE.find((candidate) => candidate !== current);
  return { sceneId: fallback ?? current, remaining: [] };
}

function randomBetween(min: number, max: number): number {
  return min + Math.floor(Math.random() * (max - min + 1));
}

function classes(...values: Array<string | false | undefined>): string {
  return values.filter(Boolean).join(" ");
}

function readPreviewScene(): RoommateSceneId | null {
  if (!import.meta.env.DEV || typeof window === "undefined") return null;
  const candidate = new URLSearchParams(window.location.search).get("roommateScene");
  return candidate && Object.hasOwn(ROOMMATE_SCENES, candidate)
    ? (candidate as RoommateSceneId)
    : null;
}

export function roommateTransition(
  from: RoommateScene,
  to: RoommateScene,
): RoommateTransition {
  if (from.pose === "mobile" || to.pose === "mobile") return "walk";
  if (from.pose === "floor" || to.pose === "floor") return "floor";
  if (from.zone === "desk" || to.zone === "desk") return "desk";
  if (from.pose === "seated" && to.pose !== "seated") return "rise";
  if (from.pose !== "seated" && to.pose === "seated") return "lounge";
  return "crossfade";
}

function sceneVariables(scene: RoommateScene): CSSProperties {
  return {
    "--pose-scale": scene.scale ?? 1,
    "--pose-x": `${scene.x ?? 0}%`,
    "--pose-y": `${scene.y ?? 0}%`,
  } as CSSProperties;
}

function spritePosition(scene: RoommateScene): CSSProperties {
  const column = scene.cell % 3;
  const row = Math.floor(scene.cell / 3);
  return {
    transform: `translate3d(${-column * (100 / 3)}%, ${-row * 50}%, 0)`,
  };
}

function eyeVariables(eyes: EyeGeometry): CSSProperties {
  return {
    "--eye-x": `${eyes.x}%`,
    "--eye-y": `${eyes.y}%`,
    "--eye-width": `${eyes.width}%`,
    "--eye-height": `${eyes.height ?? 8}%`,
    "--eye-gap": `${eyes.gap ?? 5}%`,
    "--eye-rotate": `${eyes.rotate ?? 0}deg`,
  } as CSSProperties;
}

function sceneDelay(scene: RoommateScene): number {
  return randomBetween(scene.holdMs[0], scene.holdMs[1]);
}

function RoommateEffects({
  scene,
  action,
}: {
  scene: RoommateScene;
  action: MicroAction;
}) {
  if (scene.effect === "none") return null;

  return (
    <span
      aria-hidden
      className={classes(
        "zeb-roommate__fx",
        `effect-${scene.effect}`,
        `action-${action}`,
      )}
    >
      <i />
      <i />
      <i />
    </span>
  );
}

function RoommateSceneLayer({
  scene,
  role,
  transition,
  action,
  blinking,
  blinkPattern,
  onSettled,
}: {
  scene: RoommateScene;
  role: "steady" | "incoming" | "outgoing";
  transition: RoommateTransition;
  action: MicroAction;
  blinking: boolean;
  blinkPattern: "single" | "double";
  onSettled?: () => void;
}) {
  return (
    <div
      aria-hidden
      className={classes(
        "zeb-roommate__scene",
        `scene-${scene.id}`,
        `pose-${scene.pose}`,
        `zone-${scene.zone}`,
        `motion-${scene.motion}`,
        `is-${role}`,
        role !== "steady" && `transition-${transition}`,
        role !== "outgoing" && `action-${action}`,
        scene.propLocked && "is-prop-locked",
      )}
      onAnimationEnd={(event) => {
        if (role === "incoming" && event.target === event.currentTarget) onSettled?.();
      }}
    >
      <div
        className={classes(
          "zeb-roommate__ambient",
          scene.propLocked && "is-ambient-locked",
        )}
      >
        <div className="zeb-roommate__pose" style={sceneVariables(scene)}>
          <img
            src={scene.sheet}
            alt=""
            draggable={false}
            className="zeb-roommate__sheet"
            style={spritePosition(scene)}
          />
          {scene.eyes && role !== "outgoing" ? (
            <span
              className={classes(
                "zeb-roommate__eyelids",
                blinking && "is-blinking",
                blinking && blinkPattern === "double" && "is-double-blink",
              )}
              style={eyeVariables(scene.eyes)}
            >
              <i />
              <i />
            </span>
          ) : null}
          {role !== "outgoing" ? <RoommateEffects scene={scene} action={action} /> : null}
        </div>
      </div>
    </div>
  );
}

export function ZebRoommate() {
  const [previewScene] = useState(readPreviewScene);
  const [sceneId, setSceneId] = useState<RoommateSceneId>(previewScene ?? "idle");
  const [previousSceneId, setPreviousSceneId] = useState<RoommateSceneId | null>(null);
  const [transition, setTransition] = useState<RoommateTransition>("crossfade");
  const [transitionNonce, setTransitionNonce] = useState(0);
  const [blinking, setBlinking] = useState(false);
  const [blinkPattern, setBlinkPattern] = useState<"single" | "double">("single");
  const [microAction, setMicroAction] = useState<MicroAction>("none");
  const [reducedMotion, setReducedMotion] = useState(false);
  const sceneRef = useRef<RoommateSceneId>(sceneId);
  const queueRef = useRef<RoommateSceneId[]>([]);
  const sceneTimerRef = useRef<number | null>(null);
  const transitionTimerRef = useRef<number | null>(null);
  const lastMicroActionRef = useRef<MicroAction>("none");

  const scene = ROOMMATE_SCENES[sceneId];
  const previousScene = previousSceneId ? ROOMMATE_SCENES[previousSceneId] : null;

  const settleTransition = () => {
    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
      transitionTimerRef.current = null;
    }
    setPreviousSceneId(null);
  };

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      setReducedMotion(media.matches);
      if (media.matches) {
        setPreviousSceneId(null);
        setMicroAction("none");
        setBlinking(false);
      }
    };
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    for (const src of new Set(Object.values(ROOMMATE_SCENES).map((item) => item.sheet))) {
      const image = new Image();
      image.decoding = "async";
      image.src = src;
      void image.decode().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (reducedMotion || previewScene) return;

    let cancelled = false;
    const schedule = (delay = sceneDelay(ROOMMATE_SCENES[sceneRef.current])) => {
      sceneTimerRef.current = window.setTimeout(() => {
        if (cancelled) return;
        if (document.hidden) {
          schedule(10_000);
          return;
        }

        const fromId = sceneRef.current;
        const selection = selectNextRoommateScene(fromId, queueRef.current);
        const next = selection.sceneId;
        queueRef.current = selection.remaining;

        if (next === fromId) {
          schedule();
          return;
        }

        const nextTransition = roommateTransition(
          ROOMMATE_SCENES[fromId],
          ROOMMATE_SCENES[next],
        );
        sceneRef.current = next;

        if (transitionTimerRef.current !== null) {
          window.clearTimeout(transitionTimerRef.current);
        }

        startTransition(() => {
          setMicroAction("none");
          setPreviousSceneId(fromId);
          setTransition(nextTransition);
          setTransitionNonce((value) => value + 1);
          setSceneId(next);
        });

        transitionTimerRef.current = window.setTimeout(() => {
          if (!cancelled) setPreviousSceneId(null);
        }, 1_980);
        schedule(sceneDelay(ROOMMATE_SCENES[next]));
      }, delay);
    };

    schedule(18_000);
    return () => {
      cancelled = true;
      if (sceneTimerRef.current !== null) window.clearTimeout(sceneTimerRef.current);
      if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current);
    };
  }, [previewScene, reducedMotion]);

  useEffect(() => {
    if (reducedMotion || !scene.eyes || previousSceneId) return;

    let blinkEnd = 0;
    let timer = 0;
    let cancelled = false;
    const scheduleBlink = () => {
      timer = window.setTimeout(() => {
        if (!document.hidden && !cancelled) {
          const doubleBlink = Math.random() < 0.22;
          setBlinkPattern(doubleBlink ? "double" : "single");
          setBlinking(true);
          blinkEnd = window.setTimeout(
            () => setBlinking(false),
            doubleBlink ? 540 : 190,
          );
        }
        if (!cancelled) scheduleBlink();
      }, randomBetween(12_500, 18_500));
    };
    scheduleBlink();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(blinkEnd);
    };
  }, [previousSceneId, reducedMotion, scene.eyes, sceneId]);

  useEffect(() => {
    if (reducedMotion || previousSceneId) return;

    let actionEnd = 0;
    let timer = 0;
    let cancelled = false;
    lastMicroActionRef.current = "none";
    const scheduleAction = () => {
      const [minDelay, maxDelay] = MICRO_ACTION_DELAYS[scene.motion];
      timer = window.setTimeout(() => {
        if (!document.hidden && !cancelled) {
          const options = MICRO_ACTIONS[sceneId];
          const variedOptions = options.filter(
            (action) => action !== lastMicroActionRef.current,
          );
          const candidates = variedOptions.length > 0 ? variedOptions : options;
          const nextAction =
            candidates[Math.floor(Math.random() * candidates.length)] ?? "none";
          lastMicroActionRef.current = nextAction;
          setMicroAction(nextAction);
          actionEnd = window.setTimeout(
            () => setMicroAction("none"),
            randomBetween(1_200, 2_700),
          );
        }
        if (!cancelled) scheduleAction();
      }, randomBetween(minDelay, maxDelay));
    };
    scheduleAction();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(actionEnd);
      setMicroAction("none");
    };
  }, [previousSceneId, reducedMotion, scene.motion, sceneId]);

  return (
    <section className="zeb-roommate" aria-label={`Zeb is ${scene.label}`}>
      <div className="zeb-roommate__stage">
        <div className="zeb-roommate__sprite-window">
          {previousScene ? (
            <RoommateSceneLayer
              key={`out-${previousScene.id}-${transitionNonce}`}
              scene={previousScene}
              role="outgoing"
              transition={transition}
              action="none"
              blinking={false}
              blinkPattern="single"
            />
          ) : null}
          <RoommateSceneLayer
            key={`in-${scene.id}-${transitionNonce}`}
            scene={scene}
            role={previousScene ? "incoming" : "steady"}
            transition={transition}
            action={microAction}
            blinking={blinking}
            blinkPattern={blinkPattern}
            onSettled={settleTransition}
          />
        </div>
        <span aria-hidden className="zeb-roommate__floor" />
        <div className="zeb-roommate__meta" aria-live="polite">
          <span>ZEB / OFF CLOCK</span>
          <span className="zeb-roommate__activity">{scene.label}</span>
        </div>
      </div>
    </section>
  );
}
