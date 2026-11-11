# Existing PR71 real prior-result input connection

Goal: Build source-linked historical inputs, not another model or synthetic accuracy claim.
Spec: docs/KEIRIN_PR71_HISTORICAL_SIGNAL_INPUT_CONTRACT_20261109.md and owner Public/PC-free/unchanged-four-model requirements.
Architecture: Ordinary already-approved WINTICKET racecard -> source-provided historical cup/race/rider identities -> exact past result page -> existing _field and fixed prior equations. Retrospective lineup publication, actual end time and unobserved acceleration splits stay None. All outputs to public CI are counts/hashes only. Raw data and model inputs are never public artifacts.

- [x] Reproduce absence of prior source adapter in isolated local unit test.
- [x] Test roster joins, duplicate source versions, current/future exclusion, malformed results, missing time and accident handling.
- [x] Extract source-linked result pages with full measured 7/9-rider fields; no hidden API or alternative host.
- [x] Use unchanged existing finishing-power and bank-fit equations, minimum samples and prior-only time window. Preserve unknown tactical and acceleration fields.
- [x] Verify source-only first live probe: 28 pages/196 rider results/193 half-lap seconds, three finishing-power candidates; zero full forecasts or admitted complete input.
- [x] Prioritize observed matching race category and balance home/away results; verified 34 eligible prior result pages, 238 rider result rows, 233 half-lap times in CI run #42683485491; only 3/7 riders have finishing-power candidates.
- [x] Record source-only evidence and missing 79 required input slots in issue #67. None of the 3/7 research candidates are licensed/admitted model inputs.

No changes to main protection, original model coefficients, production keys, past predictions, KEIRIN-AI, wagers, spending, hosting, or timers. No claim that owner-approved personal observation proves independent provider licence or official pre-cutoff timestamp. Source collection and derived candidate readiness remain distinct from complete PR71 model admission.

## Latest continuation: private normalized evidence replay (2026-11-10)

- [x] Optional owner-private historical research packet, with all accepted prior result rows and calculated candidates, joined source references, racecard/index SHA-256, source observation times and the original fixed formula ID. Uses `race_ai/keirin_prior_private_stage.py` and existing `scripts/keirin_prior_real_input_probe.py --private-evidence-dir /absolute/private/path`.
- [x] Immutable create-once SHA filename, independent canonical readback, exact re-run of the existing prior equations, source race/URL reconciliation, target cutoff exclusion, public workspace/symlink rejection and tamper/replay tests.
- [x] No new model, coefficient, source grant, official result, forecast, public artifact, or ChatGPT cron. Public CLI prints only research candidate counts and packet SHA, never rider-specific values or source raw bytes.
- [ ] This owner-private packet is **not** automatically an encrypted Git history generation. A GitHub-hosted runner's temporary directory is NOT persistent storage. Retention into the existing AES state ref requires owner-authorized machine data acquisition, trusted main and source authorization, a separate accepted production design and independently verified readback.
- [ ] Observe and authorize every model-required source feature before four-model production freeze. Three isolated finishing-power candidate values cannot close 79 missing model slots or justify interpreting half-lap speed as measured acceleration.
- [ ] Real future race: complete admitted inputs -> 4 model immutable pre-cutoff SHA -> existing AES Git save -> independent new runner restore -> independently verified official results and unchanged historical revisions. None of this live sequence is proven by the research-spool tests.

This private packet does not include the original HTML bodies; each source's original content SHA is retained, and the normalized research rows are replayable. Do not call it a full immutable vendor-source original until the original bytes are separately preserved under approved rights and encryption.
