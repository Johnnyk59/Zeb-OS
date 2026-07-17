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
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
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
  return {
    // At idle this is one revolution in roughly nine minutes.
    rotationSpeed: 0.012 + 0.78 * Math.pow(value, 1.5),
    driftSpeed: 0.12 + 1.5 * Math.pow(value, 1.2),
    driftAmplitude: 0.0025 + 0.055 * Math.pow(value, 1.3),
    // Five small root flashes per ten seconds at idle; propagation is negligible.
    firingRate: 0.5 + 30 * Math.pow(value, 2.4),
    fanoutChance: 0.008 + 0.68 * Math.pow(value, 1.2),
    cascadeChance: 0.01 + 0.72 * Math.pow(value, 1.35),
    signalSpeed: 0.55 + value * 4.55,
    fireDecay: 2.8 - value * 1.2,
  };
}
