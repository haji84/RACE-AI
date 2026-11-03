# BOAT 2026-11-04 JST: D+1 historical original result recheck

## Scope / preservation boundary

Selected historical, read-only verification of the existing 2026-11-03 original batch: GitHub run 41577960865 / artifact 13204251708 (server-created 2026-11-03T04:24:58Z, JST 13:24:58). Three original races: Miyajima8R, Tokuyama11R, Heiwajima7R. Same 26-entry canonical original index, no new freezes, no changes to model coefficients or original ZIP/JSON. The later Heiwajima7R artifact 13204793279 is retained as a distinct observation but never used for grading when an earlier receipt exists.

Previous historical audit run [41675366137](https://github.com/haji84/RACE-AI/actions/runs/41675366137) (03:33 JST 2026-11-04) stopped safely with SourceError for all three, 3 official GET, 0 verified scores. The previous result artifact was not rewritten or deleted.

After the previous code update allowing pre-close roster proof from the frozen C-lite shadow, recheck [run 41695227877](https://github.com/haji84/RACE-AI/actions/runs/41695227877) completed the same three-race original under the existing result workflow. It used **3 official GET** (historical individual racerresult, no new racelist reconstruction). Output artifact **13261970136** created 2026-11-03T18:36:34Z, actual downloaded ZIP SHA256 **3d3fce1140d8f19ff591de6c650d8681032a253bb8f33051bc8914d1cdc1bcf0**, matched GitHub metadata digest. The workflow authenticated the original artifact and JSON against the index before checking official 6-boat identity, official settlement, refund and abnormal outcomes. No source 4xx was seen in this run.

## Independently checked outcomes (NOT newly generated predictions)

| Original race | Official 3T | 100-yen payout | A winning rank / Hit@8 | B winning rank / Hit@8 | C-lite winning rank / Hit@8 | Normal denominator |
| --- | --- | ---: | --- | --- | --- | --- |
| 20261103-17-08 Miyajima8R | 1-2-3 | 830 JPY | 28 / 0 | 7 / 1 | 3 / 1 | Eligible ordinary settled |
| 20261103-18-11 Tokuyama11R | 2-1-4 | 2,640 JPY | 25 / 0 | 9 / 0 | 5 / 1 | Eligible ordinary settled |
| 20261103-04-07 Heiwajima7R | 1-4-6 | 14,710 JPY | Not scored | Not scored | Not scored | Excluded from ordinary: lane 5 finish status 落 |

These are **2 independently verified ordinary race results and 1 separate abnormal-finish classification on a D+1 rerun**, not 3 new forecast records or 3 newly discovered outcomes. Do not increment any earlier cumulative totals for matching source result revisions. The C-lite comparison is additive from pre-cutoff frozen predictions, not backfit. On the selected two normal races only: A Hit@8=0/2, B=1/2, C-lite=2/2, insufficient for superiority, calibration, model promotion, or national inference. Heiwajima7R qualifies as an observed >=10,000 JPY trifecta but remains separately flagged because of abnormal finish; do not mix its payout into normal ROI or the two normal-race denominator.

The first saved receipt is the only source used to score Heiwajima7R; the later observation, any older result revisions, and the original SHA remain preserved. Date rollover does not create a new pre-close prediction.

## Current-day discovery and backup limits

Previously authenticated official discovery artifact 13244030784 / run 41663948277 for 2026-11-04: 12 active venues, 144 distinct race slots (12 per venue), GitHub ZIP SHA256 c16533f19fa6063403bbf0f04df0d37a7f26026aa6dcf605611ddf189f006bf8, as observed at 2026-11-04 00:26:57 JST. Earliest official scheduled close is Ashiya1R 08:35 JST. This is a **00:26 snapshot**, not a fresh 03:36 nationwide GET and not 144 validated predictions. No 2026-11-04 new preclose predictions or actual purchases occurred in this run.

The owner's existing private backup folder had owner-only, shared=false metadata and the same original archived package previously reported for 14 races. A missing later original 13227136203 was independently checked against original archive and index SHA and intended for new-file backup only. Drive upload was blocked with `BLOCKED_FILE_REFERENCE` (connector egress); no Drive write, re-upload, permission change, name replacement or backup completion is claimed. Folder ID and URLs are intentionally omitted from this public report.

Nationwide Hit@8_all remains uncomputed because the full official 144/156 all-target sold/result/exception denominator is not yet audited. This result recheck resolves the D+1 source matching gap for this **one** registered original batch, not automatic nationwide D+1 completion. No main integration, Vercel, Cloudflare deployment, new PR, paid service, wager, old nonce resubmission or model auto-promotion.
