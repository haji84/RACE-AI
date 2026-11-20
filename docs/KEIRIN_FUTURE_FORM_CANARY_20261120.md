# Future-race acceptance: official identities, form and falls

## Owner instruction and scope

The owner instructed on 2026-11-20:

> 次の本番合格条件は、未来の実レース1件で、登録番号の確認→落車・近況履歴の自動取得→A/Bと補正A/Bの締切前保存→公式結果との同一条件比較を完走すること。それができたら全国レースへ拡張をそのままして

This authorizes the scoped live canary and, after its genuine acceptance,
continuation to nationwide future races. It is not permission to change
repository access, secrets, branch protection, paid services, hosting vendors,
the unchanged baseline model, or the prohibition on public plaintext originals.
Existing global production variables are not silently enabled. A main-only,
date-limited canary uses the existing GitHub Actions permissions, existing
encrypted Git history and pinned owner RSA key. Pull-request jobs use invented
test data and receive no owner decryption secret.

## Selected real race

- Race ID: `202611208105`, Kokura race 5, 2026-11-20 JST.
- The official KEIRIN.JP public card displays six L1 starters.
- Official card sales cutoff: `2026-11-20T17:07:00+09:00`.
- Start: `2026-11-20T17:10:00+09:00`.
- The observed SJ0314 source explicitly displays `ライン無し`. The input has
  six individual groups; no men's cooperative line is invented.
- All four originals and the independent GitHub readback must be completed
  before the existing 65-second cutoff margin. A failed or delayed run cannot
  be repaired by backdating or regenerating a prediction after the cutoff.

The official event timetable is at
<https://keirinsai.jp/timeschedule.html>. Runtime acceptance uses the separately
captured official KEIRIN.JP card bytes and its exact cutoff, not this document.

## Source acquisition and identity binding

The collector follows the published official calendar, race-list and race-card
forms. The prediction information tab is a public display operation. Its
linked controller and view scripts define the request, its opaque race token,
and the display rule that an absent/null mark renders as an empty cell. Those
scripts and the resulting tab document are saved and checked. Unknown request
types or endpoints are not guessed. A denial, challenge or redirect stops the
collector. No WINTICKET refusal is bypassed and no new race-data provider is
substituted.

`keirin_official_canary_join` reconstructs the following from original bytes:

1. Official race date, venue, race number, cutoff and complete starter roster.
2. Published marks and comments with the same car numbers and registration IDs.
3. Each registration-specific official profile, its H/B counts, competition
   points and displayed four-month win percentage.
4. Actual historical result pages reached through the profile's published
   controls. Full dates, race numbers, actual starter counts, ranks and fall
   statuses are read from the result pages, not inferred from meeting labels.

Manifests locate source documents. Their claimed normalized statistics and
results are not trusted. Raw bytes, SHA-256 receipts, publication-page updates
and capture times are checked again at the join. Independent acquisition time
still requires the main workflow and GitHub server evidence; local consistency
tests do not establish it.

## Actual source feasibility observed before deployment

The local source feasibility collection completed on 2026-11-20, before the
selected race. It is a source check, not a successful production prediction.

| Check | Observed |
| --- | ---: |
| Card/profile registration matches | 6 / 6 |
| Rider-specific historical results | 44 |
| Distinct historical result documents | 39 |
| Official profile documents | 6 |
| History requests with HTTP 200 | 45 / 45 |
| Card, navigation scripts and prediction-tab requests with HTTP 200 | 12 / 12 |
| Published comments joined by registration | 6 |
| Documented fall results in the selected history | 2 |
| Absence observations without verified start/end dates | 6 |

History capture: 13:40:56–13:45:15 JST. The completed card/tab collection was
observed by 13:49:26 JST. Private source capture manifest SHA-256:
`4e64fc06d41ccdd191a9172e17e8a833540188511c840efdc74d17488198ac8c`.
Private completed-card manifest SHA-256:
`dcc973fcf834740a273b6780eee8327529ea53c7ce4d899fe55c62ff80bfbfef`.

No raw source documents, rider comments or forecast tickets are included here.
The live main job recollects and seals its own actual source evidence. These
local counts must not be presented as successful GitHub production operation.

## Four independent originals and fair comparison

- Original A: the existing marks/observed-strength generator.
- Original B: the existing six-phase tactical generator.
- Adjusted A: the same A scoring with the documented form adjustment.
- Adjusted B: the same B branches with documented form factors.

The baseline source SHA-256 remains
`9aa0143192707733a9666f8d0dad70e589451f67943130796d3ed4af0387f413`.
No result is consulted to generate or choose a pre-race ticket. The two
baseline arms and their two adjusted counterparts share the same target race,
starter roster, cutoff and generation instant. The adjusted envelope binds
the exact baseline prediction hash. They are retained independently; missing
adjusted evidence must not suppress a valid saved baseline.

The scorer admits a race only when all four arms, official final result and
their origin evidence are valid. It uses the same eligible race IDs and a
virtual 100 yen per unique ticket, at most 12 tickets per arm. It records point
counts, first-ticket hit, any-ticket hit, virtual stake and payout. Aggregates
are committed atomically only after all four arms pass validation. A partial
arm cannot leave phantom stake or profit in the totals. No bets are placed.

The official result's complete registration roster, cutoff, final flag,
refund state, finish order and trifecta payout order must agree with the saved
pre-race identity. Payout denomination uses an actual saved official venue
guide when the result page does not state it. The existing approved guide
<https://www.hofukeirin.jp/ticket/> explicitly states that published payouts
are per 100 yen. Its captured raw SHA on this date is
`4ec68447b3883bee75065fb085e20825d4eacf377ae59f0b8bda8c9feb26ff64`.
Without verified denomination, finish-order matching can still be reported,
but no unverified monetary comparison is promoted to full acceptance.

## Interpretation limits that remain visible

- A fall alone is never an automatic ability penalty. Normal finishes before
  and after it are required for the existing post-fall adjustment.
- A fall-affected finish is retained as a fall event and excluded from the
  normal-performance trend. It is not evidence of recovery or of causation.
- A rider with only two verified post-fall finishes does not receive an
  invented third observation. The adjustment remains unavailable when the
  existing three-before/three-after rule cannot be met.
- A fall outside the existing 180-day evaluation window is preserved in the
  evidence but does not enter that window's form adjustment.
- Unknown absence endpoints stay unknown. Source comments are attributed to
  their publishing source; no medical assessment is inferred from them.
- Displayed page-update times are not claimed to be first-publication times.
- The selected history is not a lifetime-complete crash register. Zero falls
  in a selected sample does not prove the rider has never fallen.
- One completed race establishes operational acceptance of this path. It does
  not establish that the adjustment improves predictive accuracy.

## Acceptance and nationwide continuation

Acceptance requires the genuine sequence, in order: verified official IDs,
automatic history acquisition, all four pre-cutoff originals durably saved,
independent readback/origin verification, then one official result scored under
the same conditions. Offline fixtures, a green CI run, local source capture,
or a self-reported status flag alone cannot satisfy it.

Only the actual accepted receipt permits the next rollout step. Nationwide
continuation must discover current official venues/races and verify coverage,
including men's published lines and each class's observed facts. Expired or
missing races stay explicitly unpredicted; they are not regenerated or counted
as losses. The canary's girls-specific source parser must not be relabelled
as nationwide coverage. Existing originals, encryption and optional C
independence remain intact during the extension.
