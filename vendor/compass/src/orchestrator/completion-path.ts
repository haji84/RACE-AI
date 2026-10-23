import { createHash } from "node:crypto";
import type { DevelopmentEvidence, DevelopmentWorkItem } from "./development-job.ts";
import { evaluateGoalFromWorkState } from "./goal-evaluator.ts";
import { evaluateRecovery, type FailureClass, type RecoveryDecision } from "./recovery-policy.ts";
import { evaluateRiskPolicy, type RiskSignals, type MediumRiskChecks } from "./risk-policy.ts";
import type { WorkState } from "./work-state.ts";

// Advisory data has no approval/dispatch capability. Only trusted adapters should
// supply evidence requirements, issuer identities, receipts and observations.
export interface CompletionRequirement {
  criterionId: string;
  weight: number;
  evidence: { kind: string; environment: string; sourceRevision: string; artifactDigest: string; trustedIssuers: string[] }[];
}
export interface HumanAction {
  kind: "account" | "authentication" | "os_permission" | "physical_operation" | "publication" | "billing" | "contract" | "credentials" | "approval";
  operation: string;
  reason: string;
  target: string;
  deadline: string | null;
  impact: string;
}
export interface CompletionCandidate {
  workItem: DevelopmentWorkItem;
  criterionIds: string[];
  strategyId: string;
  rationale: string;
  evidenceRefs: string[];
  feasibility: "available" | "unavailable" | "unknown";
  estimatedMinutes: number | null;
  riskSignals: RiskSignals;
  mediumChecks?: MediumRiskChecks;
  humanActions: HumanAction[];
  existingIssue?: string;
  existingPr?: string;
}
export interface NotificationDelivery { notificationId: string; at: string; receiptRef: string }
export interface HumanResponse extends NotificationDelivery { status: "approved" | "denied" | "deferred" }
export interface CompletionInput {
  goalId: string;
  cycleId: string;
  at: string;
  requirements: CompletionRequirement[];
  evidence: DevelopmentEvidence[];
  candidates: CompletionCandidate[];
  capabilities: Record<string, boolean | undefined>;
  /** IDs confirmed completed by the existing state controller, not executor claims. */
  completedWorkItems: string[];
  deliveries: NotificationDelivery[];
  responses: HumanResponse[];
  attempt?: { taskId: string; strategyId: string; failureSignature: string; failureClass: FailureClass };
}
export interface CompletionNotification extends HumanAction {
  id: string;
  taskId: string;
  preparedAt: string;
  status: "PREPARED" | "DELIVERED" | "ANSWERED";
  deliveredAt?: string;
  delivery?: NotificationDelivery;
  response?: HumanResponse;
  responses?: HumanResponse[];
}
export type CandidateStatus = "READY" | "INVESTIGATE" | "HUMAN_REQUIRED" | "WAITING_DEPENDENCY" | "UNAVAILABLE" | "SECURITY_BLOCK" | "REPLAN" | "DUPLICATE" | "NO_CONTRIBUTION" | "DONE";
export interface CandidateAssessment {
  taskId: string;
  status: CandidateStatus;
  score: number;
  contributesTo: string[];
  reasons: string[];
  risk: ReturnType<typeof evaluateRiskPolicy>;
  reuse: { issue?: string; pr?: string };
}
export interface CompletionCycle {
  version: 1;
  cycleId: string;
  inputDigest: string;
  contractDigest: string;
  stateDigest: string;
  at: string;
  executionAuthority: false;
  readyForCompletionReview: boolean;
  verifiedCriteria: string[];
  remainingCriteria: string[];
  gaps: string[];
  blockers: string[];
  addedCriteria: string[];
  lostCriteria: string[];
  resolvedBlockers: string[];
  candidates: CandidateAssessment[];
  recommendation: { taskId: string; mode: "ASSESS_FOR_EXECUTION" | "INVESTIGATE"; reasons: string[]; reuse: { issue?: string; pr?: string } } | null;
  notifications: CompletionNotification[];
  newNotificationIds: string[];
  attempt?: CompletionInput["attempt"];
  recovery?: RecoveryDecision;
  replanRequired: boolean;
  metrics: { verifiedDelta: number; unproductiveAttempts: number; consecutiveNoProgress: number; stagnationSince: string | null; stagnationMs: number; deliveredNotifications: number; lateNotifications: number };
}

export const MAX_COMPLETION_CYCLES = 256;
export function completionDigest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}
function text(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !value.trim() || value.length > 2_000) throw Error(`invalid ${label}`);
}
function time(value: string): number {
  const ms = Date.parse(value);
  if (!Number.isFinite(ms) || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) throw Error("invalid timestamp");
  return ms;
}
function unique(values: string[]): string[] { return [...new Set(values)]; }
const RISK_KEYS = new Set<keyof RiskSignals>([
  "productionDeploy", "secretsOrCredentialsChange", "permissionChange", "billingOrContractChange", "destructiveSchemaChange",
  "destructiveOrHardToRecoverDelete", "securityWeakening", "majorExternalPublicationChange", "highRiskMainMerge",
  "dependencyUpdate", "crossComponentChange", "mainMerge", "humanGatePolicyRelaxation", "protectionOrAuditDisable", "unrecoverableProductionDestruction",
]);

function validate(state: WorkState, input: CompletionInput, history: CompletionCycle[]): void {
  text(input.cycleId, "cycle id");
  if (state.goalId !== input.goalId) throw Error("goal identity mismatch");
  time(input.at);
  for (const list of [input.requirements, input.candidates, input.completedWorkItems, input.responses, input.deliveries, state.definitionOfDone]) {
    if (!Array.isArray(list) || list.length > 256) throw Error("advisory input capacity exceeded");
  }
  if (!input.evidence || input.evidence.length > 1024) throw Error("evidence capacity exceeded");
  if (history.length >= MAX_COMPLETION_CYCLES) throw Error("advisory journal capacity requires archival review");
  const criteria = new Set(state.definitionOfDone.map(c => c.id));
  if (criteria.size !== state.definitionOfDone.length || !criteria.size) throw Error("invalid locked criteria");
  const contracts = new Set<string>();
  for (const r of input.requirements) {
    if (!criteria.has(r.criterionId) || contracts.has(r.criterionId)) throw Error("invalid criterion contract");
    contracts.add(r.criterionId);
    if (!Number.isFinite(r.weight) || r.weight <= 0 || r.weight > 100 || !r.evidence.length || r.evidence.length > 32) throw Error("invalid criterion evidence contract");
    for (const e of r.evidence) {
      text(e.kind, "evidence kind"); text(e.environment, "evidence environment");
      if (!/^[a-f0-9]{40,64}$/.test(e.sourceRevision) || !/^[a-f0-9]{64}$/.test(e.artifactDigest) || !e.trustedIssuers.length || e.trustedIssuers.length > 32) throw Error("invalid evidence provenance contract");
      e.trustedIssuers.forEach(v => text(v, "trusted issuer"));
    }
  }
  const ids = new Set<string>();
  for (const c of input.candidates) {
    text(c.workItem.id, "task id"); text(c.workItem.objective, "objective"); text(c.strategyId, "strategy");
    if (ids.has(c.workItem.id)) throw Error("duplicate task identity"); ids.add(c.workItem.id);
    if (c.criterionIds.some(id => !criteria.has(id))) throw Error("unknown contribution criterion");
    if (!["available", "unavailable", "unknown"].includes(c.feasibility)) throw Error("invalid feasibility");
    if (c.estimatedMinutes !== null && (!Number.isFinite(c.estimatedMinutes) || c.estimatedMinutes <= 0)) throw Error("invalid resource estimate");
    if (!c.riskSignals || typeof c.riskSignals !== "object") throw Error("risk assessment required");
    if (Object.keys(c.riskSignals).some(key => !RISK_KEYS.has(key as keyof RiskSignals))) throw Error("unknown risk signal; investigate required gate");
    for (const value of Object.values(c.riskSignals)) if (typeof value !== "boolean") throw Error("invalid risk signal");
    if (c.humanActions.length > 32 || c.workItem.dependsOn.length > 256 || c.workItem.requiredCapabilities.length > 128) throw Error("task input capacity exceeded");
    for (const h of c.humanActions) {
      if (!["account", "authentication", "os_permission", "physical_operation", "publication", "billing", "contract", "credentials", "approval"].includes(h.kind)) throw Error("invalid human action kind");
      [h.operation, h.reason, h.target, h.impact].forEach(v => text(v, "human action"));
      if (h.deadline !== null) time(h.deadline);
    }
  }
  for (const c of input.candidates) for (const id of c.workItem.dependsOn) if (!ids.has(id) && !input.completedWorkItems.includes(id)) throw Error(`unknown dependency:${id}`);
  const visiting = new Set<string>(), visited = new Set<string>();
  const visit = (id: string) => {
    if (visiting.has(id)) throw Error("cyclic dependency");
    if (visited.has(id)) return;
    visiting.add(id);
    input.candidates.find(c => c.workItem.id === id)?.workItem.dependsOn.forEach(visit);
    visiting.delete(id); visited.add(id);
  };
  ids.forEach(visit);
  if (input.attempt) {
    text(input.attempt.taskId, "attempt task"); text(input.attempt.strategyId, "attempt strategy"); text(input.attempt.failureSignature, "failure signature");
    if (!["transient", "implementation", "environment", "unknown"].includes(input.attempt.failureClass)) throw Error("invalid failure class");
  }
}

function accepted(requirement: CompletionRequirement, evidence: DevelopmentEvidence[], at: string): boolean {
  return requirement.evidence.every(rule => {
    // A later failure or revision mismatch must invalidate an older success.
    const observations = evidence.filter(e => e.criterionId === requirement.criterionId && e.kind === rule.kind
      && e.environment === rule.environment && rule.trustedIssuers.includes(e.issuer));
    if (!observations.length || observations.some(e => !e.recordedAt || !Number.isFinite(Date.parse(e.recordedAt)) || Date.parse(e.recordedAt) > time(at))) return false;
    const newest = Math.max(...observations.map(e => Date.parse(e.recordedAt!)));
    return observations.filter(e => Date.parse(e.recordedAt!) === newest).every(e => e.verified === true
      && e.sourceRevision === rule.sourceRevision && e.artifactDigest === rule.artifactDigest);
  });
}

export function assessCompletionPath(state: WorkState, input: CompletionInput, history: CompletionCycle[] = []): CompletionCycle {
  if (state.goalId !== input.goalId) throw Error("goal identity mismatch");
  const stateDigest = completionDigest(state);
  const contractDigest = completionDigest({ goalId: state.goalId, objective: state.objective, criteria: state.definitionOfDone, constraints: state.constraints });
  const seenCycles = new Set<string>();
  let lastAt = -Infinity;
  for (const cycle of history) {
    if (cycle.version !== 1 || cycle.contractDigest !== contractDigest || seenCycles.has(cycle.cycleId) || time(cycle.at) < lastAt) throw Error("incompatible advisory history");
    seenCycles.add(cycle.cycleId); lastAt = time(cycle.at);
  }
  const replay = history.find(c => c.cycleId === input.cycleId);
  if (replay) {
    if (replay.inputDigest !== completionDigest(input)) throw Error("cycle identity conflict");
    if (replay.contractDigest !== contractDigest || replay.stateDigest !== stateDigest) throw Error("stale assessment; use a new cycle for the current WorkState");
    return structuredClone(replay);
  }
  validate(state, input, history);
  const previous = history.at(-1);
  if (previous && time(input.at) < time(previous.at)) throw Error("non-monotonic cycle timestamp");
  const verified = input.requirements.filter(r => accepted(r, input.evidence, input.at)).map(r => r.criterionId);
  const normalized = { ...state, definitionOfDone: state.definitionOfDone.map(c => ({ ...c, required: c.required !== false })),
    verificationResults: verified.map(id => ({ itemId: id, passed: true })) };
  const goal = evaluateGoalFromWorkState(normalized);
  const missingContracts = state.definitionOfDone.filter(c => !input.requirements.some(r => r.criterionId === c.id)).map(c => `missing_evidence_contract:${c.id}`);
  const addedCriteria = previous ? verified.filter(id => !previous.verifiedCriteria.includes(id)) : [];
  const lostCriteria = previous ? previous.verifiedCriteria.filter(id => !verified.includes(id)) : [];
  const resolvedBlockers = previous ? previous.blockers.filter(b => !state.blockers.includes(b)) : [];
  const verifiedDelta = addedCriteria.length - lostCriteria.length;
  const advanced = verifiedDelta > 0 || (lostCriteria.length === 0 && resolvedBlockers.length > 0);
  const unproductive = !!input.attempt && !advanced;
  const consecutiveNoProgress = advanced ? 0 : (previous?.metrics.consecutiveNoProgress ?? 0) + (unproductive ? 1 : 0);
  const stagnationSince = advanced ? null : previous?.metrics.stagnationSince ?? (unproductive ? input.at : null);
  const attempts = [...history.flatMap(c => c.attempt ? [c.attempt] : []), ...(input.attempt ? [input.attempt] : [])];
  const lastAttempt = attempts.at(-1);
  const taskAttempts = attempts.filter(a => a.taskId === lastAttempt?.taskId);
  const recovery = lastAttempt && consecutiveNoProgress >= 3 ? evaluateRecovery({
    failureSignature: lastAttempt.failureSignature, failureClass: lastAttempt.failureClass,
    attemptsForSignature: taskAttempts.filter(a => a.failureSignature === lastAttempt.failureSignature && a.strategyId === lastAttempt.strategyId).length,
    strategyPivots: Math.max(0, unique(taskAttempts.map(a => a.strategyId)).length - 1), totalAttempts: taskAttempts.length,
  }) : undefined;
  const replanRequired = consecutiveNoProgress >= 3 || lostCriteria.length > 0;
  const notifications = structuredClone(previous?.notifications ?? []);
  const newNotificationIds: string[] = [];
  for (const c of input.candidates) {
    const risk = evaluateRiskPolicy(c.riskSignals, c.mediumChecks);
    const needs = [...c.humanActions];
    if (risk.humanApprovalRequired) needs.push({ kind: "approval", operation: `Review ${c.workItem.objective}`, reason: risk.reasons.join(", "), target: c.workItem.id, deadline: null, impact: "Existing Human Gate must authorize this exact task before execution" });
    for (const need of needs) {
      const id = completionDigest({ goalId: state.goalId, taskId: c.workItem.id, need });
      if (!notifications.some(n => n.id === id)) {
        notifications.push({ ...need, id, taskId: c.workItem.id, preparedAt: input.at, status: "PREPARED" }); newNotificationIds.push(id);
      }
    }
  }
  if (notifications.length > 256) throw Error("notification capacity requires archival review");
  for (const [kind, receipts] of [["delivery", input.deliveries], ["response", input.responses]] as const) for (const receipt of receipts) {
    const n = notifications.find(n => n.id === receipt.notificationId);
    if (!n || time(receipt.at) < time(n.preparedAt) || time(receipt.at) > time(input.at)) throw Error("invalid notification receipt");
    text(receipt.receiptRef, "receipt reference");
    if (kind === "delivery") {
      if (n.delivery && JSON.stringify(n.delivery) !== JSON.stringify(receipt)) throw Error("notification receipt conflict");
      n.delivery = receipt; n.deliveredAt = receipt.at; if (!n.response) n.status = "DELIVERED";
    }
    else {
      const response = receipt as HumanResponse;
      if (!["approved", "denied", "deferred"].includes(response.status)) throw Error("invalid human response");
      const responses = n.responses ?? [];
      const prior = responses.find(r => r.receiptRef === response.receiptRef);
      if (prior && JSON.stringify(prior) !== JSON.stringify(response)) throw Error("notification receipt conflict");
      if (!prior) {
        if (n.response && time(response.at) <= time(n.response.at)) throw Error("non-monotonic response timestamp");
        if (responses.length >= 32) throw Error("response capacity requires archival review");
        n.responses = [...responses, response];
      } else continue;
      n.response = response; n.status = "ANSWERED";
    }
  }
  const remaining = state.definitionOfDone.filter(c => !verified.includes(c.id)).map(c => c.id);
  const descendants = (id: string, seen = new Set<string>()): string[] => {
    if (seen.has(id)) return []; seen.add(id);
    const own = input.candidates.find(c => c.workItem.id === id)?.criterionIds ?? [];
    return unique([...own, ...input.candidates.filter(c => c.workItem.dependsOn.includes(id)).flatMap(c => descendants(c.workItem.id, seen))]).filter(id => remaining.includes(id));
  };
  const identities = new Set<string>();
  const candidates = input.candidates.map(c => {
    const risk = evaluateRiskPolicy(c.riskSignals, c.mediumChecks);
    const contributesTo = descendants(c.workItem.id);
    const weight = contributesTo.reduce((sum, id) => sum + (input.requirements.find(r => r.criterionId === id)?.weight ?? 0), 0);
    const score = weight / Math.max(1, c.estimatedMinutes ?? 60) / (risk.level === "LOW" ? 1 : 2);
    const reasons: string[] = [`contributes:${contributesTo.join(",") || "none"}`, `estimated_minutes:${c.estimatedMinutes ?? "unknown"}`, ...risk.reasons];
    const identity = completionDigest({ objective: c.workItem.objective.trim(), criteria: [...c.criterionIds].sort(), strategy: c.strategyId,
      dependencies: [...c.workItem.dependsOn].sort(), capabilities: [...c.workItem.requiredCapabilities].sort(), feasibility: c.feasibility,
      riskSignals: c.riskSignals, mediumChecks: c.mediumChecks, humanActions: c.humanActions,
      rationale: c.rationale, evidenceRefs: [...c.evidenceRefs].sort(), estimatedMinutes: c.estimatedMinutes, issue: c.existingIssue, pr: c.existingPr });
    const duplicate = identities.has(identity); identities.add(identity);
    let status: CandidateStatus;
    if (input.completedWorkItems.includes(c.workItem.id)) status = "DONE";
    else if (duplicate) status = "DUPLICATE";
    else if (risk.executionBlocked) status = "SECURITY_BLOCK";
    else if (c.humanActions.length || risk.humanApprovalRequired) status = "HUMAN_REQUIRED";
    else if (!contributesTo.length) status = "NO_CONTRIBUTION";
    else if (c.workItem.dependsOn.some(id => !input.completedWorkItems.includes(id))) status = "WAITING_DEPENDENCY";
    else if (c.feasibility === "unavailable" || c.workItem.requiredCapabilities.some(id => input.capabilities[id] === false)) status = "UNAVAILABLE";
    else if ((recovery?.action === "strategy_pivot" || recovery?.blocked) && c.workItem.id === lastAttempt?.taskId && c.strategyId === lastAttempt?.strategyId) status = "REPLAN";
    else if (c.feasibility === "unknown" || c.estimatedMinutes === null || !c.rationale.trim() || !c.evidenceRefs.length || c.workItem.requiredCapabilities.some(id => input.capabilities[id] !== true) || !risk.autoExecutionAllowed || contributesTo.some(id => !input.requirements.some(r => r.criterionId === id))) status = "INVESTIGATE";
    else status = "READY";
    reasons.push(`status:${status}`, `rationale:${c.rationale}`, ...c.evidenceRefs.map(ref => `evidence:${ref}`));
    return { taskId: c.workItem.id, status, score, contributesTo, reasons, risk, reuse: { ...(c.existingIssue ? { issue: c.existingIssue } : {}), ...(c.existingPr ? { pr: c.existingPr } : {}) } };
  });
  const best = candidates.filter(c => c.status === "READY" || c.status === "INVESTIGATE")
    .sort((a, b) => b.score - a.score || Number(b.status === "READY") - Number(a.status === "READY") || a.taskId.localeCompare(b.taskId))[0];
  return {
    version: 1, cycleId: input.cycleId, inputDigest: completionDigest(input), contractDigest, stateDigest, at: input.at, executionAuthority: false,
    readyForCompletionReview: goal.achieved && missingContracts.length === 0,
    verifiedCriteria: verified, remainingCriteria: remaining, gaps: [...goal.remainingGaps, ...missingContracts], blockers: [...state.blockers],
    addedCriteria, lostCriteria, resolvedBlockers, candidates,
    recommendation: best ? { taskId: best.taskId, mode: best.status === "INVESTIGATE" ? "INVESTIGATE" : "ASSESS_FOR_EXECUTION", reasons: best.reasons, reuse: best.reuse } : null,
    notifications, newNotificationIds, ...(input.attempt ? { attempt: input.attempt } : {}), ...(recovery ? { recovery } : {}), replanRequired,
    metrics: { verifiedDelta, unproductiveAttempts: (previous?.metrics.unproductiveAttempts ?? 0) + (unproductive ? 1 : 0), consecutiveNoProgress, stagnationSince,
      stagnationMs: stagnationSince ? time(input.at) - time(stagnationSince) : 0,
      deliveredNotifications: notifications.filter(n => n.deliveredAt).length,
      lateNotifications: notifications.filter(n => n.deadline && (n.deliveredAt ? time(n.deliveredAt) > time(n.deadline) : time(input.at) > time(n.deadline))).length },
  };
}
