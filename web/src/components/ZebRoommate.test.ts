import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ROOMMATE_ACTIVITY_CYCLE,
  ROOMMATE_SCENES,
  ZebRoommate,
  roommateTransition,
  selectNextRoommateScene,
  type RoommateScene,
  type RoommateSceneId,
} from "./ZebRoommate";

const EXPECTED_SCENE_IDS = [
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
] as const satisfies readonly RoommateSceneId[];

const VALID_SHEETS = new Set([
  "/zeb/zeb-roommate-core-sprites-v2.png",
  "/zeb/zeb-roommate-daily-sprites-v2.png",
  "/zeb/zeb-roommate-flow-sprites-v2.png",
  "/zeb/zeb-roommate-extra-sprites-v2.png",
  "/zeb/zeb-roommate-smoke-sprites-v2.png",
]);

const OPEN_EYE_SCENE_IDS = [
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
] as const satisfies readonly RoommateSceneId[];

const PROP_LOCKED_SCENE_IDS = [
  "couch",
  "tv",
  "couch-crossed",
  "gaming",
  "sleep",
  "laptop",
  "plant",
  "trading",
  "ramen",
  "meditate",
  "maker",
  "couch-vape",
  "crate-vape",
  "big-exhale",
] as const satisfies readonly RoommateSceneId[];

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderRoommate(sceneId?: RoommateSceneId): string {
  if (sceneId) {
    vi.stubGlobal("window", {
      location: { search: `?roommateScene=${sceneId}` },
    });
  }
  return renderToStaticMarkup(createElement(ZebRoommate));
}

function expectValidEyeGeometry(scene: RoommateScene): void {
  expect(scene.eyes, `${scene.id} should define eye geometry`).toBeDefined();
  if (!scene.eyes) return;
  const { eyes } = scene;

  for (const [field, value] of [
    ["x", eyes.x],
    ["y", eyes.y],
    ["width", eyes.width],
  ] as const) {
    expect(Number.isFinite(value), `${scene.id}.eyes.${field} should be finite`).toBe(true);
    expect(value, `${scene.id}.eyes.${field} should fit within its sprite cell`).toBeGreaterThanOrEqual(0);
    expect(value, `${scene.id}.eyes.${field} should fit within its sprite cell`).toBeLessThanOrEqual(100);
  }

  expect(eyes.width, `${scene.id}.eyes.width should be visible`).toBeGreaterThan(0);

  for (const [field, value] of [
    ["height", eyes.height],
    ["gap", eyes.gap],
  ] as const) {
    if (value === undefined) continue;
    expect(Number.isFinite(value), `${scene.id}.eyes.${field} should be finite`).toBe(true);
    expect(value, `${scene.id}.eyes.${field} should be visible`).toBeGreaterThan(0);
    expect(value, `${scene.id}.eyes.${field} should fit within its sprite cell`).toBeLessThanOrEqual(100);
  }

  if (eyes.rotate !== undefined) {
    expect(Number.isFinite(eyes.rotate), `${scene.id}.eyes.rotate should be finite`).toBe(true);
  }
}

describe("ROOMMATE_SCENES", () => {
  it("contains the complete upgraded scene registry with keys aligned to scene ids", () => {
    expect(Object.keys(ROOMMATE_SCENES).sort()).toEqual([...EXPECTED_SCENE_IDS].sort());

    for (const [id, scene] of Object.entries(ROOMMATE_SCENES)) {
      expect(scene.id).toBe(id);
    }
  });

  it("uses known sprite sheets and unique cells from the 3-by-2 grid", () => {
    const addresses = new Set<string>();

    for (const scene of Object.values(ROOMMATE_SCENES)) {
      expect(VALID_SHEETS.has(scene.sheet), `${scene.id} should use a known sheet`).toBe(true);
      expect(Number.isInteger(scene.cell), `${scene.id}.cell should be an integer`).toBe(true);
      expect(scene.cell, `${scene.id}.cell should be on the sprite grid`).toBeGreaterThanOrEqual(0);
      expect(scene.cell, `${scene.id}.cell should be on the sprite grid`).toBeLessThan(6);

      const address = `${scene.sheet}:${scene.cell}`;
      expect(addresses.has(address), `${address} should identify only one scene`).toBe(false);
      addresses.add(address);
    }

    expect(new Set(Object.values(ROOMMATE_SCENES).map((scene) => scene.sheet))).toEqual(
      VALID_SHEETS,
    );
  });

  it("defines valid eye geometry for every open-eye scene", () => {
    const scenes = Object.values(ROOMMATE_SCENES).filter((scene) => scene.eyes !== undefined);
    expect(scenes.map((scene) => scene.id).sort()).toEqual([...OPEN_EYE_SCENE_IDS].sort());
    for (const scene of scenes) expectValidEyeGeometry(scene);
  });

  it("omits eye overlays only for the closed-eye sleep pose", () => {
    const scenesWithoutEyes = Object.values(ROOMMATE_SCENES)
      .filter((scene) => scene.eyes === undefined)
      .map((scene) => scene.id);

    expect(scenesWithoutEyes).toEqual(["sleep"]);
  });

  it("keeps prop locks constrained to seated/floor composites that should not drift", () => {
    const lockedSceneIds = Object.values(ROOMMATE_SCENES)
      .filter((scene) => scene.propLocked)
      .map((scene) => scene.id);

    expect(lockedSceneIds.sort()).toEqual([...PROP_LOCKED_SCENE_IDS].sort());
  });
});

describe("ROOMMATE_ACTIVITY_CYCLE", () => {
  it("covers the 24-scene rotation with exactly 25% smoking time", () => {
    expect(ROOMMATE_ACTIVITY_CYCLE).toHaveLength(24);
    expect(new Set(ROOMMATE_ACTIVITY_CYCLE)).toEqual(new Set(EXPECTED_SCENE_IDS));

    for (const id of ROOMMATE_ACTIVITY_CYCLE) {
      expect(ROOMMATE_SCENES[id], `${id} should be registered`).toBeDefined();
    }

    const smokeSlots = ROOMMATE_ACTIVITY_CYCLE.filter(
      (id) => ROOMMATE_SCENES[id].effect === "smoke",
    );
    expect(smokeSlots).toHaveLength(6);
    expect(smokeSlots.length / ROOMMATE_ACTIVITY_CYCLE.length).toBe(0.25);
  });
});

describe("selectNextRoommateScene", () => {
  it("selects the first queued scene that differs from the current scene", () => {
    const selection = selectNextRoommateScene("vape", ["vape", "vape", "phone", "tv"]);

    expect(selection).toEqual({ sceneId: "phone", remaining: ["vape", "vape", "tv"] });
  });

  it("replenishes once when only duplicate current scenes are queued", () => {
    const replenish = vi.fn(() => ["idle", "couch", "gaming"] as RoommateSceneId[]);
    const selection = selectNextRoommateScene("idle", ["idle"], replenish);

    expect(selection).toEqual({ sceneId: "couch", remaining: ["idle", "idle", "gaming"] });
    expect(replenish).toHaveBeenCalledOnce();
  });

  it("falls back to a different registered scene when replenishment is invalid", () => {
    const replenish = vi.fn(() => ["idle", "idle"] as RoommateSceneId[]);
    const selection = selectNextRoommateScene("idle", [], replenish);

    expect(selection.sceneId).not.toBe("idle");
    expect(ROOMMATE_SCENES[selection.sceneId]).toBeDefined();
    expect(replenish).toHaveBeenCalledOnce();
  });
});

describe("ZebRoommate structure", () => {
  it("keeps the pose, eyelids, and effects inside the stage without a separate card shell", () => {
    const markup = renderRoommate("phone-vape");

    expect(markup).toContain('<div class="zeb-roommate__stage">');
    expect(markup).toContain(
      '<div class="zeb-roommate__ambient"><div class="zeb-roommate__pose"',
    );
    expect(markup.indexOf("zeb-roommate__pose")).toBeLessThan(
      markup.indexOf("zeb-roommate__eyelids"),
    );
    expect(markup.indexOf("zeb-roommate__eyelids")).toBeLessThan(
      markup.indexOf("zeb-roommate__fx"),
    );
    expect(markup.indexOf("zeb-roommate__floor")).toBeLessThan(
      markup.indexOf("zeb-roommate__meta"),
    );
  });

  it("propagates fixed-composite locking to the scene and ambient wrapper", () => {
    const markup = renderRoommate("couch-vape");

    expect(markup).toMatch(/zeb-roommate__scene[^"]*is-prop-locked/);
    expect(markup).toContain(
      'class="zeb-roommate__ambient is-ambient-locked"',
    );
  });
});

describe("roommateTransition", () => {
  const sceneByRole = {
    standing: ROOMMATE_SCENES.idle,
    seated: ROOMMATE_SCENES.couch,
    mobile: ROOMMATE_SCENES["carry-tv"],
    floor: ROOMMATE_SCENES.ramen,
    desk: ROOMMATE_SCENES.laptop,
  } satisfies Record<"standing" | "seated" | "mobile" | "floor" | "desk", RoommateScene>;

  it.each([
    ["standing", "standing", "crossfade"],
    ["standing", "seated", "lounge"],
    ["standing", "mobile", "walk"],
    ["standing", "floor", "floor"],
    ["standing", "desk", "desk"],
    ["seated", "standing", "rise"],
    ["seated", "desk", "desk"],
    ["seated", "floor", "floor"],
    ["mobile", "desk", "walk"],
    ["floor", "standing", "floor"],
    ["desk", "desk", "desk"],
  ] as const)("classifies %s to %s as %s", (from, to, expected) => {
    expect(roommateTransition(sceneByRole[from], sceneByRole[to])).toBe(expected);
  });
});
