export type FailureClass = "transient" | "implementation" | "environment" | "unknown";

export type RecoveryAction = "retry_same" | "repair" | "strategy_pivot" | "blocked";

export interface RecoveryState {
  failureSignature: string;
  failureClass: FailureClass;
  attemptsForSignature: number;
  strategyPivots: number;
  totalAttempts: number;
  explicitBlocker?: string | null;
}

export interface RecoveryLimits {
  maxAttemptsPerSignature?: number;
  maxStrategyPivots?: number;
  maxTotalAttempts?: number;
}

export interface RecoveryDecision {
  action: RecoveryAction;
  reason: string;
  nextStrategyPivot: number;
  blocked: boolean;
  humanInterventionHint?: string;
}

const DEFAULT_LIMITS = {
  maxAttemptsPerSignature: 3,
  maxStrategyPivots: 2,
  maxTotalAttempts: 9,
} as const;

function normalizePositiveInteger(value: number | undefined, fallback: number, label: string): number {
  const normalized = value ?? fallback;
  if (!Number.isInteger(normalized) || normalized < 1) {
    throw new Error(`${label} must be a positive integer`);
  }
  return normalized;
}

function normalizeState(state: RecoveryState): RecoveryState {
  if (!state.failureSignature.trim()) throw new Error("failureSignature is required");
  if (!Number.isInteger(state.attemptsForSignature) || state.attemptsForSignature < 0) {
    throw new Error("attemptsForSignature must be a non-negative integer");
  }
  if (!Number.isInteger(state.strategyPivots) || state.strategyPivots < 0) {
    throw new Error("strategyPivots must be a non-negative integer");
  }
  if (!Number.isInteger(state.totalAttempts) || state.totalAttempts < 0) {
    throw new Error("totalAttempts must be a non-negative integer");
  }
  return {
    ...state,
    failureSignature: state.failureSignature.trim(),
    explicitBlocker: state.explicitBlocker?.trim() || null,
  };
}

export function evaluateRecovery(
  rawState: RecoveryState,
  rawLimits: RecoveryLimits = {},
): RecoveryDecision {
  const state = normalizeState(rawState);
  const maxAttemptsPerSignature = normalizePositiveInteger(
    rawLimits.maxAttemptsPerSignature,
    DEFAULT_LIMITS.maxAttemptsPerSignature,
    "maxAttemptsPerSignature",
  );
  const maxStrategyPivots = normalizePositiveInteger(
    rawLimits.maxStrategyPivots,
    DEFAULT_LIMITS.maxStrategyPivots,
    "maxStrategyPivots",
  );
  const maxTotalAttempts = normalizePositiveInteger(
    rawLimits.maxTotalAttempts,
    DEFAULT_LIMITS.maxTotalAttempts,
    "maxTotalAttempts",
  );

  if (state.explicitBlocker) {
    return {
      action: "blocked",
      reason: `Explicit blocker: ${state.explicitBlocker}`,
      nextStrategyPivot: state.strategyPivots,
      blocked: true,
      humanInterventionHint: state.explicitBlocker,
    };
  }

  if (state.totalAttempts >= maxTotalAttempts) {
    return {
      action: "blocked",
      reason: `Total recovery budget exhausted after ${state.totalAttempts} attempts`,
      nextStrategyPivot: state.strategyPivots,
      blocked: true,
      humanInterventionHint: "Review the failure history and provide the smallest missing decision, permission, runtime access, or requirement clarification.",
    };
  }

  if (state.attemptsForSignature < maxAttemptsPerSignature) {
    if (state.failureClass === "transient") {
      return {
        action: "retry_same",
        reason: `Transient failure can retry the same operation (${state.attemptsForSignature}/${maxAttemptsPerSignature})`,
        nextStrategyPivot: state.strategyPivots,
        blocked: false,
      };
    }

    return {
      action: "repair",
      reason: `Failure can be repaired within the current strategy (${state.attemptsForSignature}/${maxAttemptsPerSignature})`,
      nextStrategyPivot: state.strategyPivots,
      blocked: false,
    };
  }

  if (state.strategyPivots < maxStrategyPivots) {
    return {
      action: "strategy_pivot",
      reason: `Failure signature ${state.failureSignature} reached ${maxAttemptsPerSignature} attempts; stop repeating the same repair and re-plan with a different strategy`,
      nextStrategyPivot: state.strategyPivots + 1,
      blocked: false,
    };
  }

  return {
    action: "blocked",
    reason: `Failure signature persisted after ${state.strategyPivots} strategy pivots`,
    nextStrategyPivot: state.strategyPivots,
    blocked: true,
    humanInterventionHint: "Inspect the saved failure evidence and provide only the missing external capability, approval, runtime access, or requirement decision needed to resume.",
  };
}
