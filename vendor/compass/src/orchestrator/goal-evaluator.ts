import type { WorkState } from "./work-state.ts";

export interface GoalEvaluation {
  achieved: boolean;
  verifiedRequired: string[];
  failedRequired: string[];
  unverifiedRequired: string[];
  blockers: string[];
  remainingGaps: string[];
}

export function evaluateGoalFromWorkState(state: WorkState): GoalEvaluation {
  const verifiedRequired: string[] = [];
  const failedRequired: string[] = [];
  const unverifiedRequired: string[] = [];

  for (const criterion of state.definitionOfDone.filter((item) => item.required)) {
    const results = state.verificationResults.filter((result) => result.itemId === criterion.id);
    const accepted = results.some((result) => result.passed || result.waived);
    const failed = results.some((result) => !result.passed && !result.waived);
    if (accepted) verifiedRequired.push(criterion.id);
    else if (failed) failedRequired.push(criterion.id);
    else unverifiedRequired.push(criterion.id);
  }

  const remainingGaps = [
    ...failedRequired.map((id) => `failed:${id}`),
    ...unverifiedRequired.map((id) => `unverified:${id}`),
    ...state.blockers.map((item) => `blocker:${item}`),
  ];

  return {
    achieved: failedRequired.length === 0 && unverifiedRequired.length === 0 && state.blockers.length === 0,
    verifiedRequired,
    failedRequired,
    unverifiedRequired,
    blockers: [...state.blockers],
    remainingGaps,
  };
}
