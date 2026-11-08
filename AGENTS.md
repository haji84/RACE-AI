# RACE-AI: owner constraints

## KEIRIN: mandatory every-race, every-rider pre-race inspection (2026-11-08)

The owner explicitly requested: 「予想する時は今の情報を必ず全て確認すること」.

- Before ANY KEIRIN 3連単 forecast or model A/B comparison, follow docs/KEIRIN_PRE_RACE_ALL_FACTORS_POLICY_20261108.md and the authoritative identifiers in race_ai/keirin_preflight.py.
- Inspect ALL race-level items and ALL rider-level items for EACH starter. For 7 riders that means 347 audit statuses; for 9 riders, 437. Count changes if the registry is amended.
- Every item must have a verifiable status: verified, unavailable, stale, rights_blocked, or not_applicable. Record why any item is not verified. Do NOT invent, impute as zero, quietly skip, or call unavailable information "checked and known".
- In real-data PR71 research inference, the audit must be present in the hashed private pre-race snapshot. Missing entries, a cutoff/time/provenance failure, or an unverified CORE factor must fail closed BEFORE the forecast model runs. Optional unknowns must be disclosed.
- Check date/venue/race/stage and advancement rules, deadline, official entrants and revisions, ALL lines/solo riders/roles, leader contests and alternative scenarios; per rider compare scoring, recent 3/10 races, S/H/B, escape/makuri/sashi/mark tactics, teammates, head-to-head, bank fit, direct comments, injuries/absence/return status, rest/fatigue, gear; track geometry and actual weather. See the full registry for every item.
- No odds, popularity, tips, market-derived numbers, or post-result payouts may enter **ability estimates, race simulation, scenario weights, model training or calibration input features**. After an independent pre-cutoff research score is sealed, separately captured pre-cutoff odds MAY be used ONLY in an explicit isolated variable-ticket selection step. Post-result payouts are allowed only for subsequent settlement/research comparison. Never treat market-implied probability as a model probability.
- Confirm rights through independent authorization; a source URL or rights_ref string does not itself grant rights. The documentation/audit does not make a currently missing legal feeder or live execution operational.
- Preserve the baseline's immutable ordered top8 as-is. The owner's newer 2026-11-08 decision permits a SEPARATE 0..8 variable research pick selection, or 0..12 if a disclosed untrained dispersion heuristic indicates a wide scenario; 0 means skip. Do not rewrite the old top8 contract or backdate variable tickets. Preserve result revisions and actual vs simulated stakes, and compare only prospective versions on the same future race. Incomplete market odds or unknown data fail closed.
- Changes to docs and tests are NOT evidence that every item is collected or used by the existing predictor. Do not claim full operation until a real permitted feeder, evidence/forecast readback, independent timestamp and forward-test quality are demonstrated.

- For genuine pre-race rider source data missing PR71-required inferred ability metrics, do not invent them. An explicitly *separate* observed-only untrained research shadow `race_ai/keirin_real_rider_shadow.py` may compute at most 8 trifecta research rankings using independently traceable pre-cutoff rider scores, B counts, escape/makuri statistics and anticipated lines; all 347/437 factor statuses are still inspected. `race_ai/keirin_real_shadow_intake.py` stores private `shadow_pre` independently from the full PR71 store. Never call this the existing full PR71 run, a calibrated probability, a formal A/B proof or a verified Hit@8 result. See docs/KEIRIN_REAL_RIDER_SHADOW_FORECAST_20261108.md.

- Rakuten/KDreams MUST NOT be used as a future KEIRIN source. Enforce `race_ai/keirin_non_rakuten_sources.py`: block *.kdreams.jp, *.rakuten.co.jp, *.rakuten.com and related origins from manual and licensed intake and prevent the old scheduled one-GET KDreams discovery. Use official KEIRIN.JP as the first reference candidate, WINTICKET, オッズパーク, チャリロト, netkeirin and JMA as supplementary candidates. None is automatically an authorized machine feed.
- Owner-saved non-Rakuten racecards (CSV, and KEIRIN HEX-style markdown) are parsed only from already locally saved files by `race_ai/keirin_owner_saved_csv.py` and `race_ai/keirin_owner_saved_hex.py`. The private agent automatically normalizes them into partial 347/437-field audits without external HTTP. These converters MUST NOT be represented as a live scrape, independent provider publication proof, or a successful forecast when critical observations remain missing. Reject conflicting race count and placing data; source expected lineups are explicitly not official actual formations. Do not ingest upstream model marks, probabilities, odds or result labels.
- Personal research: owner-captured, privately supplied observations MAY be processed offline through `race_ai/keirin_owner_manual.py` without a commercial API or provider licence manifest; this grants NO automatic remote collection, publication, or commercial rights. Every source must retain true source URL and as-of provenance, and missing values remain explicit.
- 347 checked items != 347 separately published or automatically retrievable facts. In `race_ai/keirin_field_acquisition.py`, scenario hypotheses and calculated indicators are classified separately from direct source facts. Never call unobserved future scenarios "collected".
- Owner requires all KEIRIN score inputs to have NO finite score ceiling, including >100 and >200. Never reject/cap a finite, nonnegative athlete score based on a max. Current transform is `keirin-audit-score_open_v2-v1` with model_value=raw_score/(100+raw_score), untrained and not a probability. Preserve source raw values and provenance, version any future change; never rewrite historic picks.


## Prospective PR101 → PR103 shadow research gate (2026-11-08)

- PR101's source-grounded sparse shadow (8 candidate picks) is **not** the full-input PR71 model. Sparse relative scores are untrained heuristics, not calibrated winning probabilities.
- For the new same-race study, preserve the FULL ordered trifecta shadow score table and its original input SHA, using the exact admitted observation packet before cutoff. Keep odds in a separate, timestamped, source-bound input that is never passed into the shadow feature builder.
- PR103 may compute an **uncalibrated score × pre-cutoff odds proxy** to compare 0..12 hypothetical tickets. This is NOT a demonstrated positive expected value, calibrated P(win), real betting recommendation, model promotion or independent pre-cutoff proof. The result must remain research-only and purchase disabled.
- Save both the original 8 and variable selection to the owner-private existing SQLite transaction before the cutoff with a conservative margin; verify SHA readback. An unavailable/invalid odds set means the original shadow survives, but no fabricated sidecar.
- Post-cutoff replays may only audit already-frozen original and variable tickets against separately logged result revisions. Never replay historical results to fabricate a pre-race alternative prediction.
- Do not publish private athlete source materials, odds snapshots, original predictions, SQLite data, or encryption keys in public repo commits/CI artifacts/logs. No unapproved automated site access, licensing assertions, new paid services, Cloudflare/Vercel or live bets.

## Cloudflare is prohibited

The owner explicitly instructed on 2026-11-03: 「Cloudflare使わない！」.

- Do not adopt, deploy, provision, reactivate, call, or depend on Cloudflare for RACE-AI. This includes Workers, D1, KV, R2, Cron and the OIDC bridge.
- This instruction supersedes older documents, previous Cloudflare integrations, and suggestions in issues/PRs. A request to complete automation does not authorize changing this constraint.
- Do not re-enable `.github/workflows/keirin-d1-oidc-bridge.yml`, its live smoke test, key refresh, or D1 synchronization. Its jobs are disabled and automatic triggers removed.
- Existing Cloudflare source files are retained as inactive historical implementation, not an approved deployment path. Offline fixture tests do not authorize live calls.
- Administrative access is permitted only to stop the mistakenly introduced RACE-AI integrations or preserve/export existing data. Do not destroy D1 data or unrelated account resources without explicit permission.
- The dedicated `race-ai-keirin-private-state` workers.dev and preview endpoints were disabled and read back as disabled. The dedicated D1 remains untouched for data preservation; this is not migration completion.

## Preserve other owner constraints

- Vercel is also not an approved RACE-AI deployment target.
- Do not silently substitute another external service, enable new charges, expose prediction originals, change security permissions, or place bets.
- Reuse validated model, result-comparison, and local SQLite code where appropriate. Do not invent an approved replacement platform beyond the owner's explicit choice below.
- Preserve all pre-cutoff prediction originals and result revision history. Do not call an incomplete real-data automation pipeline complete.
- Prefer existing work/PRs. Main protection and required CI must remain intact. Do not merge unrelated draft work.

## Owner selected GitHub-only continuation

The owner explicitly instructed after the Cloudflare shutdown: 「GitHubで出来るならそれで進めて」.

- Run on GitHub Actions and keep state within GitHub. Do not reintroduce Cloudflare, Vercel, or another hosting/storage provider.
- Keep RACE-AI public. Never upload plaintext private forecast SQLite files, keys, raw prediction originals or result-source documents to public branches, logs, artifacts or caches.
- The current implementation choice is authenticated AES-256-GCM encrypted SQLite snapshots. Production requires the owner's separately configured `RACE_AI_STATE_KEY` GitHub Actions secret, 32 random bytes encoded as base64. Do not invent a key from repo identifiers, GITHUB_TOKEN, a commit, OIDC or a public test value.
- Synthetic GitHub handoff tests may use the explicitly public fixture-only key with invented riders. They are not proof of private real-data operation, live accuracy, scheduled all-race coverage, or indefinite retention.
- A runner filesystem is temporary. Restore verified previous state before executing the existing model, and preserve the original prediction and revision history. Missing/expired state is a stop condition, not permission to reset the DB.
- GitHub artifacts expire. The three-day synthetic proof is not a permanent production backup. Indefinite encrypted retention and real-data feeder integration remain separate acceptance gates.
- No new private repository, unrelated project vault, changed repository visibility, paid runner or storage plan is authorized by the test implementation.
