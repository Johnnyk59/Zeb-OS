export interface BrainEnergyInput {
  busy?: boolean;
  thinking?: boolean;
  taskIntensity?: number;
  bgStatus?: string | null;
  backgroundStatus?: string | null;
  toolStarts?: number;
}

export interface BrainMotionProfile {
  rotationSpeed: number;
  driftSpeed: number;
  driftAmplitude: number;
  firingRate: number;
  fanoutChance: number;
  cascadeChance: number;
  signalSpeed: number;
  fireDecay: number;
  frameRate: number;
  signalBudget: number;
  edgeOpacity: number;
  fieldStrength: number;
  cameraZoom: number;
  cameraFocus: number;
  cameraDepth: number;
}

export type BrainActivityTier = "idle" | "small" | "medium" | "high";

export function getBrainFrameEnergy(
  targetEnergy: number,
  currentEnergy: number,
  cameraZoom: number,
): number {
  const normalize = (value: number) =>
    Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
  const settlingFloor = Math.abs((Number.isFinite(cameraZoom) ? cameraZoom : 1) - 1) > 0.006
    ? 0.4
    : 0;
  return Math.max(normalize(targetEnergy), normalize(currentEnergy), settlingFloor);
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function smoothstep(start: number, end: number, value: number): number {
  const normalized = clamp01((value - start) / (end - start));
  return normalized * normalized * (3 - 2 * normalized);
}

/** Stable labels for UI copy, diagnostics, and renderer quality decisions. */
export function getBrainActivityTier(energy: number): BrainActivityTier {
  const value = clamp01(energy);
  if (value < 0.16) return "idle";
  if (value < 0.46) return "small";
  if (value < 0.78) return "medium";
  return "high";
}

/** Estimate prompt complexity without assigning every short prompt a hard-work floor. */
export function estimateTaskIntensity(text: string): number {
  const normalized = String(text || "").trim().toLowerCase();
  if (!normalized) return 0;

  const complexitySignals =
    normalized.match(
      /\b(?:analy[sz]e|architect|benchmark|build|compare|debug|design|implement|investigate|migrate|optimize|plan|refactor|research|review|strategy|test|trace)\b/g,
    )?.length ?? 0;
  const structureSignals =
    normalized.match(/(?:\n\s*(?:[-*]|\d+[.)])\s+)|[\n,:;?]/g)?.length ?? 0;

  const base = 0.08;
  const lengthWeight = Math.min(0.4, normalized.length / 1600);
  const structureWeight = Math.min(0.24, structureSignals * 0.022);
  const complexityWeight = Math.min(0.34, complexitySignals * 0.065);

  return clamp01(base + lengthWeight + structureWeight + complexityWeight);
}

/** Merge prompt complexity and live React state into BrainCanvas' normalized energy. */
export function deriveBrainEnergy({
  busy = false,
  thinking = false,
  taskIntensity = 0,
  bgStatus,
  backgroundStatus,
  toolStarts = 0,
}: BrainEnergyInput): number {
  const promptIntensity = clamp01(taskIntensity);
  const observedIntensity = clamp01(Math.max(promptIntensity, toolStarts * 0.18));

  if (thinking) return clamp01(0.48 + observedIntensity * 0.52);
  if (busy) return clamp01(0.42 + observedIntensity * 0.52);

  const background = String(bgStatus ?? backgroundStatus ?? "idle").toLowerCase();
  if (background === "learning") return 0.38;
  if (background === "processing" || background === "thinking") return 0.3;
  return 0;
}

/** Convert energy into animation rates. Kept pure so activity tiers stay testable. */
export function getBrainMotionProfile(energy: number): BrainMotionProfile {
  const value = clamp01(energy);
  const small = smoothstep(0.06, 0.36, value);
  const medium = smoothstep(0.34, 0.72, value);
  const high = smoothstep(0.68, 1, value);

  return {
    // Idle is a near-still observatory; each tier adds a distinct motion layer.
    rotationSpeed: 0.007 + small * 0.025 + medium * 0.09 + high * 0.22,
    driftSpeed: 0.09 + small * 0.28 + medium * 0.7 + high * 0.85,
    driftAmplitude: 0.0018 + small * 0.006 + medium * 0.018 + high * 0.025,
    // Five root flashes per ten seconds at idle, with bounded propagation.
    firingRate: 0.5 + small * 1.8 + medium * 9 + high * 18,
    fanoutChance: 0.006 + small * 0.07 + medium * 0.25 + high * 0.32,
    cascadeChance: 0.004 + small * 0.035 + medium * 0.23 + high * 0.38,
    signalSpeed: 0.42 + small * 0.45 + medium * 0.9 + high * 2.2,
    fireDecay: 3 - small * 0.18 - medium * 0.3 - high * 0.5,
    // These are renderer ceilings, not targets that can grow without bound.
    frameRate: 18 + small * 6 + medium * 8 + high * 10,
    signalBudget: Math.round(14 + small * 22 + medium * 58 + high * 92),
    edgeOpacity: 0.05 + small * 0.035 + medium * 0.11 + high * 0.13,
    fieldStrength: 0.012 + small * 0.018 + medium * 0.055 + high * 0.07,
    // The renderer eases toward these targets and reserves the final portion
    // of the dive for sustained high activity rather than snapping on prompt.
    cameraZoom: 1 + small * 0.075 + medium * 0.19 + high * 0.315,
    cameraFocus: small * 0.035 + medium * 0.16 + high * 0.27,
    cameraDepth: 0.46 + small * 0.03 + medium * 0.09 + high * 0.13,
  };
}
