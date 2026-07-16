import { useEffect, useMemo, useRef, useState } from "react";

type SceneId =
  | "idle"
  | "vape"
  | "weights"
  | "couch"
  | "tv"
  | "carry-tv"
  | "blink"
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

interface Scene {
  id: SceneId;
  sheet: string;
  cell: number;
  label: string;
  seated?: boolean;
  fetchesProp?: boolean;
  alreadyBlinking?: boolean;
  eyeX?: number;
  eyeY?: number;
  eyeWidth?: number;
}

const SHEET_MAIN = "/zeb/zeb-roommate-sprites.png";
const SHEET_LIFE = "/zeb/zeb-roommate-life-sprites.png";
const SHEET_HOBBIES = "/zeb/zeb-roommate-hobbies-sprites.png";

const SCENES: Record<SceneId, Scene> = {
  idle: { id: "idle", sheet: SHEET_MAIN, cell: 0, label: "chilling" },
  vape: { id: "vape", sheet: SHEET_MAIN, cell: 1, label: "smoke break" },
  weights: { id: "weights", sheet: SHEET_MAIN, cell: 2, label: "getting a pump" },
  couch: { id: "couch", sheet: SHEET_MAIN, cell: 3, label: "posted up", seated: true, eyeY: 25 },
  tv: { id: "tv", sheet: SHEET_MAIN, cell: 4, label: "watching something", seated: true, eyeX: 42, eyeY: 24 },
  "carry-tv": { id: "carry-tv", sheet: SHEET_MAIN, cell: 5, label: "moving the TV", fetchesProp: true },
  blink: { id: "blink", sheet: SHEET_LIFE, cell: 0, label: "chilling", alreadyBlinking: true },
  phone: { id: "phone", sheet: SHEET_LIFE, cell: 1, label: "checking the group chat" },
  snack: { id: "snack", sheet: SHEET_LIFE, cell: 2, label: "snack run" },
  "couch-forward": { id: "couch-forward", sheet: SHEET_LIFE, cell: 3, label: "locked in", seated: true, eyeY: 27 },
  "couch-crossed": { id: "couch-crossed", sheet: SHEET_LIFE, cell: 4, label: "getting comfortable", seated: true, eyeY: 24 },
  "couch-vape": { id: "couch-vape", sheet: SHEET_LIFE, cell: 5, label: "smoke break", seated: true, eyeY: 24 },
  gaming: { id: "gaming", sheet: SHEET_HOBBIES, cell: 0, label: "one more game", seated: true, eyeY: 25 },
  sleep: { id: "sleep", sheet: SHEET_HOBBIES, cell: 1, label: "power nap", seated: true, alreadyBlinking: true, eyeX: 42, eyeY: 30 },
  laptop: { id: "laptop", sheet: SHEET_HOBBIES, cell: 2, label: "building something", seated: true, eyeX: 52, eyeY: 23 },
  plant: { id: "plant", sheet: SHEET_HOBBIES, cell: 3, label: "plant duty", eyeX: 33, eyeY: 24 },
  music: { id: "music", sheet: SHEET_HOBBIES, cell: 4, label: "in his zone", alreadyBlinking: true },
  groceries: { id: "groceries", sheet: SHEET_HOBBIES, cell: 5, label: "back from the store", fetchesProp: true },
};

// Five smoke-break entries per twenty equal-duration scenes keeps long-run
// visible smoking time close to 25%. Every other illustrated life state gets
// one slot, then the cycle is shuffled so the pattern never feels fixed.
const ACTIVITY_CYCLE: SceneId[] = [
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

function shuffledCycle(): SceneId[] {
  const next = [...ACTIVITY_CYCLE];
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

export function ZebRoommate() {
  const [sceneId, setSceneId] = useState<SceneId>("idle");
  const [blinking, setBlinking] = useState(false);
  const [fidget, setFidget] = useState<"none" | "look" | "shift">("none");
  const [offscreen, setOffscreen] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const queueRef = useRef<SceneId[]>([]);
  const sceneTimerRef = useRef<number | null>(null);
  const transitionTimerRef = useRef<number | null>(null);

  const scene = SCENES[sceneId];
  const position = useMemo(() => {
    const column = scene.cell % 3;
    const row = Math.floor(scene.cell / 3);
    return {
      transform: `translate(${-column * (100 / 3)}%, ${-row * 50}%)`,
    };
  }, [scene.cell]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (reducedMotion) return;

    let cancelled = false;
    const clearSceneTimers = () => {
      if (sceneTimerRef.current !== null) window.clearTimeout(sceneTimerRef.current);
      if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current);
    };

    const schedule = (delay = randomBetween(55_000, 105_000)) => {
      sceneTimerRef.current = window.setTimeout(() => {
        if (cancelled || document.hidden) {
          schedule(15_000);
          return;
        }
        if (queueRef.current.length === 0) queueRef.current = shuffledCycle();
        const next = queueRef.current.shift() ?? "idle";
        const nextScene = SCENES[next];

        if (nextScene.fetchesProp) {
          setOffscreen(true);
          transitionTimerRef.current = window.setTimeout(() => {
            if (cancelled) return;
            setSceneId(next);
            setOffscreen(false);
          }, 1_900);
        } else {
          setSceneId(next);
        }
        schedule();
      }, delay);
    };

    schedule(18_000);
    return () => {
      cancelled = true;
      clearSceneTimers();
    };
  }, [reducedMotion]);

  useEffect(() => {
    if (reducedMotion || scene.alreadyBlinking) return;
    let blinkEnd = 0;
    let timer = 0;
    let cancelled = false;
    const scheduleBlink = () => {
      timer = window.setTimeout(() => {
        if (!document.hidden && !cancelled) {
          setBlinking(true);
          blinkEnd = window.setTimeout(() => setBlinking(false), 190);
        }
        if (!cancelled) scheduleBlink();
      }, randomBetween(12_000, 18_000));
    };
    scheduleBlink();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(blinkEnd);
      setBlinking(false);
    };
  }, [reducedMotion, scene.alreadyBlinking, sceneId]);

  useEffect(() => {
    if (reducedMotion) return;
    let resetTimer = 0;
    let timer = 0;
    let cancelled = false;
    const scheduleFidget = () => {
      timer = window.setTimeout(() => {
        if (!document.hidden && !cancelled) {
          setFidget(Math.random() > 0.46 ? "shift" : "look");
          resetTimer = window.setTimeout(() => setFidget("none"), randomBetween(900, 1_800));
        }
        if (!cancelled) scheduleFidget();
      }, randomBetween(8_000, 24_000));
    };
    scheduleFidget();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(resetTimer);
    };
  }, [reducedMotion]);

  return (
    <section className="zeb-roommate" aria-label={`Zeb is ${scene.label}`}>
      <div className="zeb-roommate__meta" aria-live="polite">
        <span>ZEB / OFF CLOCK</span>
        <span className="zeb-roommate__activity">{scene.label}</span>
      </div>
      <div
        className={classes(
          "zeb-roommate__stage",
          scene.seated && "is-seated",
          offscreen && "is-offscreen",
          fidget === "look" && "is-looking",
          fidget === "shift" && "is-shifting",
        )}
      >
        <div className="zeb-roommate__sprite-window">
          <img
            key={scene.sheet}
            src={scene.sheet}
            alt=""
            draggable={false}
            className="zeb-roommate__sheet"
            style={position}
          />
          {!scene.alreadyBlinking ? (
            <span
              aria-hidden
              className={classes("zeb-roommate__eyelids", blinking && "is-blinking")}
              style={{
                left: `${scene.eyeX ?? 50}%`,
                top: `${scene.eyeY ?? 25}%`,
                width: `${scene.eyeWidth ?? 29}%`,
              }}
            >
              <i />
              <i />
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}
