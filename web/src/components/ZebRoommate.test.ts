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
  "couch-forward",
  "couch-crossed",
  "couch-vape",
  "gaming",
  "sleep",
  "laptop",
  "plant",
  "music",
  "groceries",
] as const satisfies readonly RoommateSceneId[];

const VALID_SHEETS = new Set([
  "/zeb/zeb-roommate-sprites.png",
  "/zeb/zeb-roommate-life-sprites.png",
  "/zeb/zeb-roommate-hobbies-sprites.png",
]);

const EYE_SCENES_BY_POSE = {
  standing: ["idle", "vape", "weights", "phone", "snack", "plant"],
  seated: [
    "couch",
    "tv",
    "couch-forward",
    "couch-crossed",
    "couch-vape",
    "gaming",
    "laptop",
  ],
  mobile: ["carry-tv", "groceries"],
} as const satisfies Record<RoommateScene["pose"], readonly RoommateSceneId[]>;

const FURNITURE_SCENE_IDS = [
  "couch",
  "tv",
  "couch-forward",
  "couch-crossed",
  "couch-vape",
  "gaming",
  "sleep",
  "laptop",
] as const satisfies readonly RoommateSceneId[];

const PROP_LOCKED_SCENE_IDS = [
  ...FURNITURE_SCENE_IDS,
  "plant",
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
  it("contains the complete scene registry with keys aligned to scene ids", () => {
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

  for (const [pose, expectedIds] of Object.entries(EYE_SCENES_BY_POSE)) {
    it(`defines valid eye geometry for applicable ${pose} scenes`, () => {
      const scenes = Object.values(ROOMMATE_SCENES).filter(
        (scene) => scene.pose === pose && scene.eyes !== undefined,
      );

      expect(scenes.map((scene) => scene.id).sort()).toEqual([...expectedIds].sort());
      for (const scene of scenes) expectValidEyeGeometry(scene);
    });
  }

  it("omits eye overlays only for closed or obscured eye poses", () => {
    const scenesWithoutEyes = Object.values(ROOMMATE_SCENES)
      .filter((scene) => scene.eyes === undefined)
      .map((scene) => scene.id);

    expect(scenesWithoutEyes.sort()).toEqual(["music", "sleep"]);
  });

  it("prop-locks every seated furniture scene", () => {
    const seatedSceneIds = Object.values(ROOMMATE_SCENES)
      .filter((scene) => scene.pose === "seated")
      .map((scene) => scene.id);

    expect(seatedSceneIds.sort()).toEqual([...FURNITURE_SCENE_IDS].sort());
    for (const id of FURNITURE_SCENE_IDS) {
      expect(ROOMMATE_SCENES[id].propLocked, `${id} should remain fixed with its furniture`).toBe(
        true,
      );
    }
  });

  it("limits prop locks to fixed furniture and plant composites", () => {
    const lockedSceneIds = Object.values(ROOMMATE_SCENES)
      .filter((scene) => scene.propLocked)
      .map((scene) => scene.id);

    expect(lockedSceneIds.sort()).toEqual([...PROP_LOCKED_SCENE_IDS].sort());
  });
});

describe("ROOMMATE_ACTIVITY_CYCLE", () => {
  it("covers the registry with 20 valid slots and exactly 25% smoking", () => {
    expect(ROOMMATE_ACTIVITY_CYCLE).toHaveLength(20);
    expect(new Set(ROOMMATE_ACTIVITY_CYCLE)).toEqual(new Set(EXPECTED_SCENE_IDS));

    for (const id of ROOMMATE_ACTIVITY_CYCLE) {
      expect(ROOMMATE_SCENES[id], `${id} should be registered`).toBeDefined();
    }

    const smokeSlots = ROOMMATE_ACTIVITY_CYCLE.filter(
      (id) => ROOMMATE_SCENES[id].effect === "smoke",
    );
    expect(smokeSlots).toHaveLength(5);
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
  it("keeps the pose, aligned eyelids, and effects inside a stable ambient wrapper", () => {
    const markup = renderRoommate("vape");

    expect(markup).toContain(
      '<div class="zeb-roommate__ambient"><div class="zeb-roommate__pose"',
    );
    expect(markup.indexOf("zeb-roommate__pose")).toBeLessThan(
      markup.indexOf("zeb-roommate__eyelids"),
    );
    expect(markup.indexOf("zeb-roommate__eyelids")).toBeLessThan(
      markup.indexOf("zeb-roommate__fx"),
    );
  });

  it("propagates fixed-composite locking to the scene and ambient wrapper", () => {
    const markup = renderRoommate("couch");

    expect(markup).toMatch(/zeb-roommate__scene[^"]*is-prop-locked/);
    expect(markup).toContain(
      'class="zeb-roommate__ambient is-ambient-locked"',
    );
  });
});

describe("roommateTransition", () => {
  const sceneByPose = {
    standing: ROOMMATE_SCENES.idle,
    seated: ROOMMATE_SCENES.couch,
    mobile: ROOMMATE_SCENES["carry-tv"],
  } satisfies Record<RoommateScene["pose"], RoommateScene>;

  it.each([
    ["standing", "standing", "crossfade"],
    ["standing", "seated", "sit"],
    ["standing", "mobile", "walk"],
    ["seated", "standing", "stand"],
    ["seated", "seated", "crossfade"],
    ["seated", "mobile", "stand"],
    ["mobile", "standing", "walk"],
    ["mobile", "seated", "sit"],
    ["mobile", "mobile", "walk"],
  ] as const)("classifies %s to %s as %s", (from, to, expected) => {
    expect(roommateTransition(sceneByPose[from], sceneByPose[to])).toBe(expected);
  });
});
