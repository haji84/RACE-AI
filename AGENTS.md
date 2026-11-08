# RACE-AI: owner constraints

## KEIRIN: mandatory every-race, every-rider pre-race inspection (2026-11-08)

The owner explicitly requested: 「予想する時は今の情報を必ず全て確認すること」.

- Before ANY KEIRIN 3連単 forecast or model A/B comparison, follow docs/KEIRIN_PRE_RACE_ALL_FACTORS_POLICY_20261108.md and the authoritative identifiers in race_ai/keirin_preflight.py.
- Inspect ALL race-level items and ALL rider-level items for EACH starter. For 7 riders that means 347 audit statuses; for 9 riders, 437. Count changes if the registry is amended.
- Every item must have a verifiable status: verified, unavailable, stale, rights_blocked, or not_applicable. Record why any item is not verified. Do NOT invent, impute as zero, quietly skip, or call unavailable information "checked and known".
- In real-data PR71 research inference, the audit must be present in the hashed private pre-race snapshot. Missing entries, a cutoff/time/provenance failure, or an unverified CORE factor must fail closed BEFORE the forecast model runs. Optional unknowns must be disclosed.
- Check date/venue/race/stage and advancement rules, deadline, official entrants and revisions, ALL lines/solo riders/roles, leader contests and alternative scenarios; per rider compare scoring, recent 3/10 races, S/H/B, escape/makuri/sashi/mark tactics, teammates, head-to-head, bank fit, direct comments, injuries/absence/return status, rest/fatigue, gear; track geometry and actual weather. See the full registry for every item.
- No odds, popularity, tips, market-derived numbers, or post-result payouts may enter prediction features, learning, or model selection. Payouts may be used separately to compute POST-result research settlement only.
- Confirm rights through independent authorization; a source URL or rights_ref string does not itself grant rights. The documentation/audit does not make a currently missing legal feeder or live execution operational.
- Keep <=8 ordered trifecta picks, original pre-cutoff prediction immutable, results and revisions separate, reference virtual losses distinct from any verified real wagers, and A/B comparisons prospective on the same future races.
- Changes to docs and tests are NOT evidence that every item is collected or used by the existing predictor. Do not claim full operation until a real permitted feeder, evidence/forecast readback, independent timestamp and forward-test quality are demonstrated.
- Rakuten/KDreams MUST NOT be used as a future KEIRIN source. Enforce `race_ai/keirin_non_rakuten_sources.py`: block *.kdreams.jp, *.rakuten.co.jp, *.rakuten.com and related origins from manual and licensed intake and prevent the old scheduled one-GET KDreams discovery. Use official KEIRIN.JP as the first reference candidate, WINTICKET, オッズパーク, チャリロト, netkeirin and JMA as supplementary candidates. None is automatically an authorized machine feed.
- Personal research: owner-captured, privately supplied observations MAY be processed offline through `race_ai/keirin_owner_manual.py` without a commercial API or provider licence manifest; this grants NO automatic remote collection, publication, or commercial rights. Every source must retain true source URL and as-of provenance, and missing values remain explicit.
- 347 checked items != 347 separately published or automatically retrievable facts. In `race_ai/keirin_field_acquisition.py`, scenario hypotheses and calculated indicators are classified separately from direct source facts. Never call unobserved future scenarios "collected".
- Owner requires all KEIRIN score inputs to have NO finite score ceiling, including >100 and >200. Never reject/cap a finite, nonnegative athlete score based on a max. Current transform is `keirin-audit-score_open_v2-v1` with model_value=raw_score/(100+raw_score), untrained and not a probability. Preserve source raw values and provenance, version any future change; never rewrite historic picks.


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
