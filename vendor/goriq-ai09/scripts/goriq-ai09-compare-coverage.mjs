// GitHub API diff hunks can only certify full review when their line counts
// match the authoritative per-file statistics. Reject missing/partial patches.
export function assertCompleteComparison(compare) {
  if (!compare || !Array.isArray(compare.files) || compare.files.length === 0) {
    throw new Error("missing_comparison_files");
  }
  for (const file of compare.files) {
    if (!Number.isSafeInteger(file?.additions) || file.additions < 0 ||
        !Number.isSafeInteger(file?.deletions) || file.deletions < 0 ||
        typeof file.patch !== "string" || !file.patch.startsWith("@@")) {
      throw new Error("unverifiable_patch_statistics");
    }
    let additions = 0;
    let deletions = 0;
    // GitHub compare's file.patch is a hunks-only patch (no +++ / --- headers).
    // Count every hunk line beginning in + or -, including literal +++ code.
    for (const line of file.patch.split("\n")) {
      if (line.startsWith("+")) additions++;
      else if (line.startsWith("-")) deletions++;
    }
    if (additions !== file.additions || deletions !== file.deletions) {
      throw new Error("incomplete_github_patch");
    }
  }
}
