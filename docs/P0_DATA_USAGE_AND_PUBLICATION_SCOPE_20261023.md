# RACE-AI: data use and public-results scope (owner clarification, 2026-10-23 JST)

Refs: Issue #67; existing P0 data-intake Draft PR #72. This is a *requirement clarification*, not a license, site publishing approval, provider admission, implementation of automatic collection, or modification of any model in PR #71.

## Owner's actual product purpose

1. Publicly viewable **factual race data** (boats, keirin, autorace, JRA and NAR racing) is used as input to RACE-AI's **original** private analytics, training, prediction and prospective PDCA.
2. RACE-AI is **not** intended to host a replica of official race cards, racing databases, articles, images, videos, or third-party forecast content.
3. A future user-facing website **will** publish **RACE-AI's own independent forecasts** and **limited official results needed to compare predictions with reality**, including hit/miss and measured performance. Accordingly, "no external publication" is not a correct blanket product requirement.
4. The owner's goal remains odds-independent pre-cutoff trifecta Top 8, independent freeze evidence, complete denominator including misses and unfrozen races, results/refunds/payback comparison, and future-only model version improvements. No automatic betting, subscription purchase or paywalled access.

## Distinct processing and publication categories

| Category | Examples | Public website | Separate checks |
|---|---|---|---|
| Internal public-fact extraction | Race ID, runners, finish order, time, conditions, payout figures | Not the full feed | Source retrieval method, site terms, access controls, rate, legal basis, privacy |
| Private analysis and model training | Performance features, derived factors, outcome labels, backtesting | No raw feature feed / raw database | Japanese copyright law Article 30-4 and its exceptions, site terms, data/contract rights, provenance and contamination |
| Prospective original forecast | RACE-AI model/version, ranked Top8, explanation | **Yes** after safe release gates | No odds in predictive inputs; forecast frozen before cutoff; own authorship |
| Minimal verified result facts | Date/venue/race, official winning triple(s), payable yen/100, refund/void/status/revision | **Intended, limited** | Confirm result facts, site terms and necessary attribution/link; avoid republishing databases, layouts, wording, media |
| Original evaluation | Hit@1, Hit@8_all, payout-based paper ROI, coverage, missing/race exclusions, model comparison | **Yes**, honestly labeled | Precutoff receipt, independent result verification, denominator rules and no post-result rewriting |
| Official bulk content or protected media | Full race-card copies, large exported tables, article texts, video, screenshots, logos | **No by default** | Additional express licensing/legal review before any change |

No blanket inference: *visible to everyone* does not by itself authorize automated access, bulk reproduction, training or redistribution. Conversely, *AI information analysis* does **not always** need express copyright permission: Article 30-4 of the Japanese Copyright Act provides exceptions subject to conditions and its proviso. Assess the legal basis separately for each activity and material, including rightsholder market impact, site terms, database rights, technical access restrictions, privacy and potential commercial use. A rights/reference field is not the same as a legally binding grant; an internal reviewer must document why each use is permissible. Do not turn on automated collection merely by setting `allow=true`.

Authoritative references accessed on 2026-10-23:
- Agency for Cultural Affairs: https://www.bunka.go.jp/seisaku/chosakuken/aiandcopyright.html and https://www.bunka.go.jp/seisaku/chosakuken/hokaisei/h30_hokaisei/
- BOAT RACE site policy: https://www.boatrace.jp/owsp/sp/extra/policy.html
- KEIRIN.JP site policy: https://keirin.jp/sp/dfw/portal/guest/policy/index.html
- NAR terms: https://www.keiba.go.jp/terms.html
- JRA policy: https://www.jra.go.jp/use/index.html

## Site output boundary (planned, not yet deployed)

An example projected row contains ONLY:
`sport / venue / event_date_jst / race_no / model_id / model_version / frozen_at / externally_verifiable_evidence_url / ordered_top8 / official_3ren_tan_result / official_100yen_payout / refund_status / result_revision / source_url / result_verified_at / hit_at_1 / hit_at_8`.

Label the 100-yen payout simulation as hypothetical unless backed by actual user purchase records. Keep model prediction probabilities uncalibrated/unknown until validation is completed. The site must never expose raw provider payloads, complete racing databases, model-training datasets, reviewer keys/HMAC, private log material, personal secrets, exact private output paths, or copyrighted footage/graphics. Link to original providers as appropriate, but a link alone is not proof of reuse permission.

Show clear states: `UNFROZEN`, `UNKNOWN_SOURCE`, `PENDING_RESULT`, `REFUND_OR_VOID`, `PROOF_MISSING`, `VERIFIED_HIT`, `VERIFIED_MISS`. Distinguish site-rendered independent forecast from official race organizer forecasts. Public product data projections are separate from private internal research ledger.

## PDCA integrity

- Prediction and model version are fixed at cutoff; after results, do **not** rewrite them.
- Revisions to official results are append-only and versioned, not edits to predicted picks.
- Candidate models may be changed *after* learning from prior results only for **new future races**, with time-split evaluations and preregistered prospective A/B tests.
- Count misses/unsent/unfrozen predictions in full eligible denominator; distinguish refund/void/non-offering races and insufficient evidence from misses.
- Publish Hit@1 and Hit@8_all, objective denominator, missingness/coverage, simulated refund-adjusted return, and independent result links once verified. Do not present synthetic performance as measured results.

## Required implementation follow-up

1. Split today's existing `SOURCE_PERMISSION` verdict into **source-access** and **purpose-specific private analysis/training** versus **minimal fact-based public comparison**. Record independent reviewer/legal-basis decisions (written license / statutory exception with rationale / separately verified fact-based use / not admitted). Never treat a generic permission string as a blanket grant.
2. Keep official HTML/JSON/CSV/ZIPS as alternative format-specific routes; choose compliant, bounded provider access and normalize to one evidence schema, not mirrored site data.
3. Use existing PR #69 synthetic lifecycle, PR #71 source-to-model seam and independent receipt checks, and PR #72 offline intake as components. Do not replace/mutate PR #71 model modules or existing prediction hashes.
4. Wire a genuine future pre-cutoff forecast to independent external receipt and read-back; authenticate official result/refund/paybacks and render only vetted public projections after site release review.
5. Continue four-sport full coverage, unattended scheduling, all-race missingness and A/B reporting.

**Status as of 2026-10-23:** this document records intended lawful private-analysis and limited-publication scope. No provider now has an automatically authorized production fetch by virtue of this clarification. No new real-race freeze, automated collection, public site deploy, official settlement, main merge, payment or ticket purchase is claimed.
