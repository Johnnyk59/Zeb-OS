import { describe, expect, it } from "vitest";

import {
  deriveBrainEnergy,
  estimateTaskIntensity,
  getBrainActivityTier,
  getBrainFrameEnergy,
  getBrainMotionProfile,
} from "./brain-activity";

describe("estimateTaskIntensity", () => {
  it("keeps short simple requests below structured hard tasks", () => {
    const simple = estimateTaskIntensity("Summarize this paragraph.");
    const hard = estimateTaskIntensity(`
      Analyze and debug the current architecture.
      1. Trace the data flow and compare alternatives.
      2. Design and implement the migration.
      3. Test, benchmark, and review the result.
      Include risks, rollback strategy, and an optimization plan.
    `);

    expect(simple).toBeGreaterThan(0);
    expect(simple).toBeLessThan(0.35);
    expect(hard).toBeGreaterThan(0.75);
    expect(hard).toBeGreaterThan(simple);
  });

  it("returns zero for empty input and clamps very large prompts", () => {
    expect(estimateTaskIntensity("   ")).toBe(0);
    expect(estimateTaskIntensity("analyze, design, implement, test\n".repeat(500))).toBe(1);
  });
});

describe("deriveBrainEnergy", () => {
  it("keeps idle, background, simple, and hard work in distinct tiers", () => {
    const simpleIntensity = estimateTaskIntensity("Summarize this paragraph.");
    const hardIntensity = estimateTaskIntensity(
      "Analyze, architect, debug, implement, benchmark, test, and review this migration plan:\n".repeat(8),
    );
    const idle = deriveBrainEnergy({});
    const background = deriveBrainEnergy({ bgStatus: "learning" });
    const simple = deriveBrainEnergy({ busy: true, taskIntensity: simpleIntensity });
    const hard = deriveBrainEnergy({ thinking: true, taskIntensity: hardIntensity });

    expect(idle).toBe(0);
    expect(background).toBeGreaterThan(idle);
    expect(simple).toBeGreaterThan(background);
    expect(simple).toBeLessThan(0.7);
    expect(hard).toBeGreaterThan(0.9);
  });

  it("uses observed tool work to escalate understated prompts", () => {
    const promptIntensity = estimateTaskIntensity("Fix it.");
    const initial = deriveBrainEnergy({ busy: true, taskIntensity: promptIntensity });
    const multiTool = deriveBrainEnergy({
      busy: true,
      taskIntensity: promptIntensity,
      toolStarts: 5,
    });

    expect(multiTool).toBeGreaterThan(initial);
    expect(multiTool).toBeGreaterThan(0.85);
  });

  it("accepts either background status key and clamps invalid intensity", () => {
    expect(deriveBrainEnergy({ backgroundStatus: "processing" })).toBe(0.3);
    expect(deriveBrainEnergy({ thinking: true, taskIntensity: Number.POSITIVE_INFINITY })).toBe(
      0.48,
    );
    expect(deriveBrainEnergy({ thinking: true, taskIntensity: 20 })).toBe(1);
  });
});

describe("getBrainMotionProfile", () => {
  it("keeps idle alive but sparse", () => {
    const idle = getBrainMotionProfile(0);

    expect(idle.rotationSpeed).toBeGreaterThan(0);
    expect(idle.firingRate * 10).toBeCloseTo(5, 5);
    expect(idle.fanoutChance).toBeLessThan(0.02);
    expect(idle.cameraZoom).toBe(1);
    expect(idle.cameraFocus).toBe(0);
  });

  it("moves from calm framing through a modest zoom to a deep high-work focus", () => {
    const idle = getBrainMotionProfile(0);
    const ordinary = getBrainMotionProfile(0.5);
    const intense = getBrainMotionProfile(1);

    expect(idle.cameraZoom).toBe(1);
    expect(ordinary.cameraZoom).toBeGreaterThan(1.1);
    expect(ordinary.cameraZoom).toBeLessThan(1.25);
    expect(intense.cameraZoom).toBeGreaterThan(1.5);
    expect(intense.cameraFocus).toBeGreaterThan(ordinary.cameraFocus * 3);
    expect(intense.cameraDepth).toBeGreaterThan(0.65);
  });

  it("separates medium activity from an intense hard-task storm", () => {
    const medium = getBrainMotionProfile(0.5);
    const hard = getBrainMotionProfile(1);

    expect(medium.firingRate).toBeGreaterThan(5);
    expect(hard.firingRate).toBeGreaterThan(medium.firingRate * 4);
    expect(hard.fanoutChance).toBeGreaterThan(medium.fanoutChance);
    expect(hard.cascadeChance).toBeGreaterThan(0.6);
    expect(hard.cascadeChance).toBeLessThanOrEqual(0.65);
  });

  it("keeps every energy profile inside explicit rendering budgets", () => {
    const profiles = Array.from({ length: 101 }, (_, index) =>
      getBrainMotionProfile(index / 100),
    );

    for (const profile of profiles) {
      expect(profile.frameRate).toBeGreaterThanOrEqual(18);
      expect(profile.frameRate).toBeLessThanOrEqual(42);
      expect(profile.signalBudget).toBeGreaterThanOrEqual(14);
      expect(profile.signalBudget).toBeLessThanOrEqual(186);
      expect(profile.fanoutChance).toBeLessThanOrEqual(0.65);
      expect(profile.cascadeChance).toBeLessThanOrEqual(0.65);
      expect(profile.cameraZoom).toBeGreaterThanOrEqual(1);
      expect(profile.cameraZoom).toBeLessThanOrEqual(1.58);
      expect(profile.cameraFocus).toBeGreaterThanOrEqual(0);
      expect(profile.cameraFocus).toBeLessThanOrEqual(0.465);
      expect(profile.cameraDepth).toBeGreaterThanOrEqual(0.46);
      expect(profile.cameraDepth).toBeLessThanOrEqual(0.71);
    }
  });

  it("scales frame, signal, field, and motion energy monotonically", () => {
    const energies = [0, 0.25, 0.55, 0.82, 1];
    const profiles = energies.map(getBrainMotionProfile);
    const keys = [
      "rotationSpeed",
      "driftSpeed",
      "driftAmplitude",
      "firingRate",
      "signalSpeed",
      "frameRate",
      "signalBudget",
      "edgeOpacity",
      "fieldStrength",
      "cameraZoom",
      "cameraFocus",
      "cameraDepth",
    ] as const;

    for (const key of keys) {
      for (let index = 1; index < profiles.length; index += 1) {
        expect(profiles[index][key]).toBeGreaterThanOrEqual(profiles[index - 1][key]);
      }
    }
  });
});

describe("getBrainFrameEnergy", () => {
  it("keeps frame cadence elevated while energy and camera easing settle", () => {
    expect(getBrainFrameEnergy(1, 0, 1)).toBe(1);
    expect(getBrainFrameEnergy(0, 0.78, 1.4)).toBe(0.78);
    expect(getBrainFrameEnergy(0, 0.02, 1.18)).toBe(0.4);
    expect(getBrainFrameEnergy(0, 0, 1.004)).toBe(0);
  });

  it("clamps invalid activity without letting an invalid zoom hold cadence open", () => {
    expect(getBrainFrameEnergy(Number.NaN, -2, Number.NaN)).toBe(0);
    expect(getBrainFrameEnergy(9, Number.POSITIVE_INFINITY, 1)).toBe(1);
  });
});

describe("getBrainActivityTier", () => {
  it("maps normalized energy to idle, small, medium, and high tiers", () => {
    expect(getBrainActivityTier(0)).toBe("idle");
    expect(getBrainActivityTier(0.3)).toBe("small");
    expect(getBrainActivityTier(0.6)).toBe("medium");
    expect(getBrainActivityTier(0.9)).toBe("high");
  });

  it("clamps invalid and out-of-range energy", () => {
    expect(getBrainActivityTier(Number.NaN)).toBe("idle");
    expect(getBrainActivityTier(-2)).toBe("idle");
    expect(getBrainActivityTier(4)).toBe("high");
  });
});
