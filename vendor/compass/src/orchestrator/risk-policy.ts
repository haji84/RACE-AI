export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface RiskSignals {
  productionDeploy?: boolean;
  secretsOrCredentialsChange?: boolean;
  permissionChange?: boolean;
  billingOrContractChange?: boolean;
  destructiveSchemaChange?: boolean;
  destructiveOrHardToRecoverDelete?: boolean;
  securityWeakening?: boolean;
  majorExternalPublicationChange?: boolean;
  highRiskMainMerge?: boolean;
  dependencyUpdate?: boolean;
  crossComponentChange?: boolean;
  mainMerge?: boolean;
  humanGatePolicyRelaxation?: boolean;
  protectionOrAuditDisable?: boolean;
  unrecoverableProductionDestruction?: boolean;
}

export interface MediumRiskChecks {
  ciPassed?: boolean;
  qaPassed?: boolean;
  reviewerPassed?: boolean;
  unresolvedReviewThreads?: number;
  destructiveChangeAbsent?: boolean;
  privilegedChangeAbsent?: boolean;
}

export interface RiskDecision {
  level: RiskLevel;
  autoExecutionAllowed: boolean;
  humanApprovalRequired: boolean;
  executionBlocked: boolean;
  reasons: string[];
}

function truthyEntries(signals: RiskSignals, keys: (keyof RiskSignals)[]): string[] {
  return keys.filter((key) => signals[key] === true).map(String);
}

function mediumChecksPass(checks: MediumRiskChecks | undefined): boolean {
  if (!checks) return false;
  return checks.ciPassed === true
    && checks.qaPassed === true
    && checks.reviewerPassed === true
    && (checks.unresolvedReviewThreads ?? 0) === 0
    && checks.destructiveChangeAbsent === true
    && checks.privilegedChangeAbsent === true;
}

export function evaluateRiskPolicy(
  signals: RiskSignals = {},
  mediumChecks?: MediumRiskChecks,
): RiskDecision {
  const criticalReasons = truthyEntries(signals, [
    "humanGatePolicyRelaxation",
    "protectionOrAuditDisable",
    "unrecoverableProductionDestruction",
  ]);
  if (criticalReasons.length > 0) {
    return {
      level: "CRITICAL",
      autoExecutionAllowed: false,
      humanApprovalRequired: false,
      executionBlocked: true,
      reasons: criticalReasons,
    };
  }

  const highReasons = truthyEntries(signals, [
    "productionDeploy",
    "secretsOrCredentialsChange",
    "permissionChange",
    "billingOrContractChange",
    "destructiveSchemaChange",
    "destructiveOrHardToRecoverDelete",
    "securityWeakening",
    "majorExternalPublicationChange",
    "highRiskMainMerge",
  ]);
  if (highReasons.length > 0) {
    return {
      level: "HIGH",
      autoExecutionAllowed: false,
      humanApprovalRequired: true,
      executionBlocked: false,
      reasons: highReasons,
    };
  }

  const mediumReasons = truthyEntries(signals, [
    "dependencyUpdate",
    "crossComponentChange",
    "mainMerge",
  ]);
  if (mediumReasons.length > 0) {
    const verified = mediumChecksPass(mediumChecks);
    return {
      level: "MEDIUM",
      autoExecutionAllowed: verified,
      humanApprovalRequired: false,
      executionBlocked: false,
      reasons: verified ? mediumReasons : [...mediumReasons, "medium_verification_required"],
    };
  }

  return {
    level: "LOW",
    autoExecutionAllowed: true,
    humanApprovalRequired: false,
    executionBlocked: false,
    reasons: [],
  };
}
