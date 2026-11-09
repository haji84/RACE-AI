# Existing PR71 real prior-result input connection

Goal: Build source-linked historical inputs, not another model or synthetic accuracy claim.
Spec: docs/KEIRIN_PR71_HISTORICAL_SIGNAL_INPUT_CONTRACT_20261109.md and owner Public/PC-free/unchanged-four-model requirements.
Architecture: Ordinary already-approved WINTICKET racecard -> source-provided historical cup/race/rider identities -> exact past result page -> existing _field and fixed prior equations. Retrospective lineup publication, actual end time and unobserved acceleration splits stay None. All outputs to public CI are counts/hashes only. Raw data and model inputs are never public artifacts.

- [x] Reproduce absence of prior source adapter in isolated local unit test.
- [x] Test roster joins, duplicate source versions, current/future exclusion, malformed results, missing time and accident handling.
- [x] Extract source-linked result pages with full measured 7/9-rider fields; no hidden API or alternative host.
- [x] Use unchanged existing finishing-power and bank-fit equations, minimum samples and prior-only time window. Preserve unknown tactical and acceleration fields.
- [x] Verify source-only first live probe: 28 pages/196 rider results/193 half-lap seconds, three finishing-power candidates; zero full forecasts or admitted complete input.
- [ ] Prioritize observed matching race category and balance home/away results; verify larger bounded live sample within existing workflow.
- [ ] Record exact evidence and remaining required input gaps. Never claim the original 79 gaps have vanished merely from counts or synthetic CI.

No changes to main protection, original model coefficients, production keys, past predictions, KEIRIN-AI, wagers, spending, hosting, or timers. No claim that owner-approved personal observation proves independent provider licence or official pre-cutoff timestamp. Source collection and derived candidate readiness remain distinct from complete PR71 model admission.
