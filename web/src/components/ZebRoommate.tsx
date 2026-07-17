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
  | "couch-forward"
  | "couch-crossed"
  | "couch-vape"
  | "gaming"
  | "sleep"
  | "laptop"
  | "plant"
  | "music"
  | "groceries";

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
  | "music";

type RoommateEffect =
  | "none"
  | "smoke"
  | "tv"
  | "phone"
  | "crumbs"
  | "weights"
  | "controller"
  | "dream"
  | "laptop"
  | "water"
  | "music"
  | "footsteps";

export type RoommateTransition = "crossfade" | "walk" | "sit" | "stand";

type MicroAction =
  | "none"
  | "look"
  | "settle"
  | "draw"
  | "exhale"
  | "rep"
  | "tap"
  | "bite"
  | "play"
  | "dream"
  | "type"
  | "water"
  | "bop"
  | "step";

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
  pose: "standing" | "seated" | "mobile";
  motion: RoommateMotion;
  effect: RoommateEffect;
  eyes?: EyeGeometry;
  scale?: number;
  x?: number;
  y?: number;
  propLocked?: boolean;
}

const SHEET_MAIN = "/zeb/zeb-roommate-sprites.png";
const SHEET_LIFE = "/zeb/zeb-roommate-life-sprites.png";
const SHEET_HOBBIES = "/zeb/zeb-roommate-hobbies-sprites.png";

const DEFAULT_EYES: EyeGeometry = { x: 50, y: 25, width: 28, height: 8, gap: 5 };

export const ROOMMATE_SCENES: Record<RoommateSceneId, RoommateScene> = {
  idle: {
    id: "idle",
    sheet: SHEET_MAIN,
    cell: 0,
    label: "chilling",
    pose: "standing",
    motion: "rest",
    effect: "none",
    eyes: { ...DEFAULT_EYES, x: 56.3, y: 25.5, width: 21.3 },
    scale: 0.9,
    y: 2,
  },
  vape: {
    id: "vape",
    sheet: SHEET_MAIN,
    cell: 1,
    label: "smoke break",
    pose: "standing",
    motion: "smoke",
    effect: "smoke",
    eyes: { ...DEFAULT_EYES, x: 50.1, y: 26.2, width: 21.3 },
    scale: 0.9,
    y: 2,
  },
  weights: {
    id: "weights",
    sheet: SHEET_MAIN,
    cell: 2,
    label: "getting a pump",
    pose: "standing",
    motion: "lift",
    effect: "weights",
    eyes: { ...DEFAULT_EYES, x: 43.1, y: 25.7, width: 20.9 },
    scale: 0.88,
    y: 2,
  },
  couch: {
    id: "couch",
    sheet: SHEET_MAIN,
    cell: 3,
    label: "posted up",
    pose: "seated",
    motion: "lounge",
    effect: "none",
    eyes: { ...DEFAULT_EYES, x: 45.6, y: 26.5, width: 18.2 },
    scale: 0.79,
    y: 5,
    propLocked: true,
  },
  tv: {
    id: "tv",
    sheet: SHEET_MAIN,
    cell: 4,
    label: "watching something",
    pose: "seated",
    motion: "watch",
    effect: "tv",
    eyes: { ...DEFAULT_EYES, x: 39.6, y: 26.1, width: 18.6 },
    scale: 0.76,
    x: -1,
    y: 5,
    propLocked: true,
  },
  "carry-tv": {
    id: "carry-tv",
    sheet: SHEET_MAIN,
    cell: 5,
    label: "moving the TV",
    pose: "mobile",
    motion: "walk",
    effect: "footsteps",
    eyes: { ...DEFAULT_EYES, x: 46, y: 20.4, width: 18.6 },
    scale: 0.84,
    x: 1,
    y: 4,
  },
  phone: {
    id: "phone",
    sheet: SHEET_LIFE,
    cell: 1,
    label: "checking the group chat",
    pose: "standing",
    motion: "phone",
    effect: "phone",
    eyes: { ...DEFAULT_EYES, x: 52.3, y: 28.7, width: 25.4 },
    scale: 0.89,
    y: 2,
  },
  snack: {
    id: "snack",
    sheet: SHEET_LIFE,
    cell: 2,
    label: "snack run",
    pose: "standing",
    motion: "snack",
    effect: "crumbs",
    eyes: { ...DEFAULT_EYES, x: 49.6, y: 28.9, width: 25.8 },
    scale: 0.88,
    y: 2,
  },
  "couch-forward": {
    id: "couch-forward",
    sheet: SHEET_LIFE,
    cell: 3,
    label: "locked in",
    pose: "seated",
    motion: "lounge",
    effect: "none",
    eyes: { ...DEFAULT_EYES, x: 58.7, y: 29.5, width: 24.1 },
    scale: 0.79,
    y: 5,
    propLocked: true,
  },
  "couch-crossed": {
    id: "couch-crossed",
    sheet: SHEET_LIFE,
    cell: 4,
    label: "getting comfortable",
    pose: "seated",
    motion: "lounge",
    effect: "none",
    eyes: { ...DEFAULT_EYES, x: 38, y: 25.9, width: 23.3 },
    scale: 0.79,
    y: 5,
    propLocked: true,
  },
  "couch-vape": {
    id: "couch-vape",
    sheet: SHEET_LIFE,
    cell: 5,
    label: "smoke break",
    pose: "seated",
    motion: "smoke",
    effect: "smoke",
    eyes: { ...DEFAULT_EYES, x: 41.5, y: 25.2, width: 23.7 },
    scale: 0.77,
    y: 5,
    propLocked: true,
  },
  gaming: {
    id: "gaming",
    sheet: SHEET_HOBBIES,
    cell: 0,
    label: "one more game",
    pose: "seated",
    motion: "game",
    effect: "controller",
    eyes: { ...DEFAULT_EYES, x: 62.1, y: 32.5, width: 23.5 },
    scale: 0.8,
    y: 5,
    propLocked: true,
  },
  sleep: {
    id: "sleep",
    sheet: SHEET_HOBBIES,
    cell: 1,
    label: "power nap",
    pose: "seated",
    motion: "sleep",
    effect: "dream",
    scale: 0.8,
    y: 5,
    propLocked: true,
  },
  laptop: {
    id: "laptop",
    sheet: SHEET_HOBBIES,
    cell: 2,
    label: "building something",
    pose: "seated",
    motion: "type",
    effect: "laptop",
    eyes: { ...DEFAULT_EYES, x: 45.4, y: 32.4, width: 23.7, rotate: -2 },
    scale: 0.77,
    y: 5,
    propLocked: true,
  },
  plant: {
    id: "plant",
    sheet: SHEET_HOBBIES,
    cell: 3,
    label: "plant duty",
    pose: "standing",
    motion: "water",
    effect: "water",
    eyes: { ...DEFAULT_EYES, x: 49.3, y: 21.2, width: 22.1, rotate: -1 },
    scale: 0.82,
    x: -1,
    y: 4,
    propLocked: true,
  },
  music: {
    id: "music",
    sheet: SHEET_HOBBIES,
    cell: 4,
    label: "in his zone",
    pose: "standing",
    motion: "music",
    effect: "music",
    scale: 0.88,
    y: 2,
  },
  groceries: {
    id: "groceries",
    sheet: SHEET_HOBBIES,
    cell: 5,
    label: "back from the store",
    pose: "mobile",
    motion: "walk",
    effect: "footsteps",
    eyes: { ...DEFAULT_EYES, x: 44.3, y: 19, width: 21.9 },
    scale: 0.82,
    y: 4,
  },
};

// Five of twenty equal-duration slots are smoking scenes, keeping long-run
// visible smoking time at one quarter without an obviously repeating pattern.
export const ROOMMATE_ACTIVITY_CYCLE: RoommateSceneId[] = [
  "vape",
  "couch-vape",
  "vape",
  "couch-vape",
  "vape",
  "idle",
  "weights",
  "couch",
  "tv",
  "carry-tv",
  "phone",
  "snack",
  "couch-forward",
  "couch-crossed",
  "gaming",
  "sleep",
  "laptop",
  "plant",
  "music",
  "groceries",
];

const MICRO_ACTIONS: Record<RoommateSceneId, MicroAction[]> = {
  idle: ["look", "settle", "look"],
  vape: ["draw", "exhale", "settle"],
  weights: ["rep", "rep", "settle"],
  couch: ["settle", "look"],
  tv: ["look", "settle"],
  "carry-tv": ["step", "settle"],
  phone: ["tap", "look", "tap"],
  snack: ["bite", "settle"],
  "couch-forward": ["settle", "look"],
  "couch-crossed": ["settle", "look"],
  "couch-vape": ["draw", "exhale", "settle"],
  gaming: ["play", "play", "look"],
  sleep: ["dream", "dream"],
  laptop: ["type", "type", "look"],
  plant: ["water", "look"],
  music: ["bop", "bop", "settle"],
  groceries: ["step", "settle"],
};

function shuffledCycle(): RoommateSceneId[] {
  const next = [...ROOMMATE_ACTIVITY_CYCLE];
  for (let i = next.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [next[i], next[j]] = [next[j], next[i]];
  }
  return next;
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
  if (from.pose === "seated" && to.pose !== "seated") return "stand";
  if (from.pose !== "seated" && to.pose === "seated") return "sit";
  if (from.pose === "mobile" || to.pose === "mobile") return "walk";
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
    const schedule = (delay = randomBetween(44_000, 78_000)) => {
      sceneTimerRef.current = window.setTimeout(() => {
        if (cancelled) return;
        if (document.hidden) {
          schedule(10_000);
          return;
        }

        if (queueRef.current.length === 0) queueRef.current = shuffledCycle();
        let next = queueRef.current.shift() ?? "idle";
        if (next === sceneRef.current) next = queueRef.current.shift() ?? "idle";

        const fromId = sceneRef.current;
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
        }, 1_850);
        schedule();
      }, delay);
    };

    schedule(22_000);
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
          const doubleBlink = Math.random() < 0.18;
          setBlinkPattern(doubleBlink ? "double" : "single");
          setBlinking(true);
          blinkEnd = window.setTimeout(
            () => setBlinking(false),
            doubleBlink ? 520 : 210,
          );
        }
        if (!cancelled) scheduleBlink();
      }, randomBetween(11_500, 16_500));
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
    const scheduleAction = () => {
      timer = window.setTimeout(() => {
        if (!document.hidden && !cancelled) {
          const options = MICRO_ACTIONS[sceneId];
          const nextAction = options[Math.floor(Math.random() * options.length)] ?? "none";
          setMicroAction(nextAction);
          actionEnd = window.setTimeout(
            () => setMicroAction("none"),
            randomBetween(1_200, 2_600),
          );
        }
        if (!cancelled) scheduleAction();
      }, randomBetween(5_500, 12_500));
    };
    scheduleAction();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(actionEnd);
      setMicroAction("none");
    };
  }, [previousSceneId, reducedMotion, sceneId]);

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
      </div>

      <div className="zeb-roommate__meta" aria-live="polite">
        <span>ZEB / OFF CLOCK</span>
        <span className="zeb-roommate__activity">{scene.label}</span>
      </div>
    </section>
  );
}
