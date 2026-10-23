export type WorkStatus =
  | "NOT_STARTED"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED";

export type WorkRiskClass = "R0" | "R1" | "R2" | "R3" | "R4";

export interface DefinitionOfDoneItem {
  id: string;
  description: string;
  required?: boolean;
}

export interface DefinitionOfDoneResult {
  itemId: string;
  passed: boolean;
  evidence?: unknown;
  waived?: boolean;
  note?: string;
}

export interface DecisionRecord {
  id: string;
  summary: string;
  rationale?: string;
  at: string;
}

export interface ArtifactRef {
  id: string;
  uri: string;
  kind?: string;
  summary?: string;
}

export interface ChildWorkItem {
  id: string;
  objective: string;
  definitionOfDone: DefinitionOfDoneItem[];
  affectedScope: string[];
  executionApproach: string;
  verificationMethod: string;
  status: WorkStatus;
}

export interface WorkEvent {
  id: string;
  at: string;
  type: string;
  summary: string;
  evidence?: unknown;
}

export interface WorkState {
  goalId: string;
  objective: string;
  definitionOfDone: DefinitionOfDoneItem[];
  currentState: string;
  status: WorkStatus;
  riskClass: WorkRiskClass;
  constraints: string[];
  decisions: DecisionRecord[];
  artifacts: ArtifactRef[];
  verificationResults: DefinitionOfDoneResult[];
  childWorkItems: ChildWorkItem[];
  blockers: string[];
  nextAction?: string | null;
  updatedAt: string;
}

export interface HandoffSnapshot {
  goalId: string;
  objective: string;
  status: WorkStatus;
  currentState: string;
  remainingDefinitionOfDone: DefinitionOfDoneItem[];
  decisions: DecisionRecord[];
  artifacts: ArtifactRef[];
  blockers: string[];
  nextAction?: string | null;
  updatedAt: string;
}

export interface WorkStateStore {
  get(goalId: string): Promise<WorkState | null>;
  put(state: WorkState): Promise<void>;
  appendEvent(goalId: string, event: WorkEvent): Promise<void>;
}

export interface MutationBinding {
  materialMutation?: boolean;
  workItemId?: string | null;
}

export interface MutationBindingValidation {
  ok: boolean;
  reason?: string;
}

export function validateMutationBinding(
  binding: MutationBinding,
  state?: WorkState | null,
): MutationBindingValidation {
  if (!binding.materialMutation) return { ok: true };

  const workItemId = binding.workItemId?.trim();
  if (!workItemId) {
    return {
      ok: false,
      reason: "material_mutation_requires_bound_work_item",
    };
  }

  if (!state) return { ok: true };

  const workItem = state.childWorkItems.find((item) => item.id === workItemId);
  if (!workItem) {
    return {
      ok: false,
      reason: "bound_work_item_not_found",
    };
  }

  if (workItem.status === "COMPLETED" || workItem.status === "FAILED") {
    return {
      ok: false,
      reason: "bound_work_item_not_active",
    };
  }

  return { ok: true };
}

function resultFor(
  item: DefinitionOfDoneItem,
  results: DefinitionOfDoneResult[],
): DefinitionOfDoneResult | undefined {
  return results.find((result) => result.itemId === item.id);
}

export function remainingDefinitionOfDone(state: WorkState): DefinitionOfDoneItem[] {
  return state.definitionOfDone.filter((item) => {
    const result = resultFor(item, state.verificationResults);
    return !(result?.passed === true || result?.waived === true);
  });
}

export function canCompleteWorkState(state: WorkState): boolean {
  if (state.blockers.length > 0) return false;

  return state.definitionOfDone
    .filter((item) => item.required !== false)
    .every((item) => {
      const result = resultFor(item, state.verificationResults);
      return result?.passed === true || result?.waived === true;
    });
}

export function deriveWorkStatus(state: WorkState): WorkStatus {
  if (state.blockers.length > 0) return "BLOCKED";
  if (canCompleteWorkState(state)) return "COMPLETED";
  if (state.verificationResults.length > 0) return "VERIFYING";
  if (state.currentState.trim().length > 0) return "IN_PROGRESS";
  return "NOT_STARTED";
}

export function createHandoffSnapshot(state: WorkState): HandoffSnapshot {
  return {
    goalId: state.goalId,
    objective: state.objective,
    status: deriveWorkStatus(state),
    currentState: state.currentState,
    remainingDefinitionOfDone: remainingDefinitionOfDone(state),
    decisions: [...state.decisions],
    artifacts: [...state.artifacts],
    blockers: [...state.blockers],
    nextAction: state.nextAction ?? null,
    updatedAt: state.updatedAt,
  };
}

export function mergeDefinitionOfDoneResults(
  state: WorkState,
  incoming: DefinitionOfDoneResult[],
  updatedAt: string,
): WorkState {
  const next = new Map(state.verificationResults.map((result) => [result.itemId, result]));
  for (const result of incoming) next.set(result.itemId, result);

  const merged: WorkState = {
    ...state,
    verificationResults: [...next.values()],
    updatedAt,
  };

  return {
    ...merged,
    status: deriveWorkStatus(merged),
  };
}
