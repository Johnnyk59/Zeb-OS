import { describe, expect, it } from "vitest";

import {
  deriveBrainEnergy,
  estimateTaskIntensity,
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
  });

  it("separates medium activity from an intense hard-task storm", () => {
    const medium = getBrainMotionProfile(0.5);
    const hard = getBrainMotionProfile(1);

    expect(medium.firingRate).toBeGreaterThan(5);
    expect(hard.firingRate).toBeGreaterThan(medium.firingRate * 4);
    expect(hard.fanoutChance).toBeGreaterThan(medium.fanoutChance);
    expect(hard.cascadeChance).toBeGreaterThan(0.7);
  });
});
