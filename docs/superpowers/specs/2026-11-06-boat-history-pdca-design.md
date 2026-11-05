# BOAT historical facts and prospective PDCA

Owner instruction: complete the previously proposed steps 1–3 and collect historical racer, tactics and motor facts. The owner identified BOATERS, then confirmed no operator permission. BOATERS terms §8(5) explicitly prohibit scraping/crawling; no BOATERS collection or training is enabled. The existing official B/K daily download path is the available alternative, disclosed in this conversation.

## Deliverables

1. Resolve scoring disagreement caused by pre-cutoff schedule revisions, without altering any forecast original. All phases use the same result observation; only a same-roster, independently read pre-cutoff P1 original can substantiate a revised cutoff. A forecast late under the revised cutoff is not scored. Preserve original cutoff, effective cutoff and revision evidence. Keep missing predictions and exceptional results visible.
2. Download and retain dated official B/K originals privately, resumably, with source URL, actual capture time and SHA. Initial collection is the 90 calendar days ending 2026-11-04; unavailable/malformed days remain explicit gaps. Reuse the pinned LZH, program, result and winning-method parsers. Build racer profiles with counts, positions, recent 10/30 starts, actual course, ST dispositions, entry patterns and winning methods. Keep motor number plus venue and dated observed results; never claim a verified lifetime/season aggregate without a motor replacement epoch.
3. Prepare reproducible baseline/history pairs using the existing observed models, equal information time, same current facts and eight tickets. Historical data must have been actually captured before the new forecast; data collected now never repairs an old prediction. Only the recent-history inputs change initially; unknown current actual course stays unknown. Keep full lineage, preserve frozen pairs, and score both against identical later observations. A local timestamp is not an independent external receipt. Build the comparison mechanism and demonstrate actual input readiness; future superiority remains unmeasured until future results arrive.

## Approach

Reuse PR71 and its pinned PR64 parsers, Python stdlib and private SQLite. Extend the existing evaluation boundary for explicit cutoff revisions; add a private historical-fact store/collector and a separate prospective comparison CLI. Preserve the operating worker and all baseline originals. No new predictor family, service, paid resource, workflow, bet or production model promotion.

Alternative: BOATERS scraping is unavailable under its published conditions; manual/provider-authorized exports can be considered later. Scraping race HTML one race at a time is unnecessary for the historical facts provided by the daily archives.

## Acceptance and limits

- Test same-roster revised deadlines, earlier revisions, foreign roster, conflicting revisions and forecast immutability.
- Test real decompression/parser fixtures, wrong day/source/hash, interrupted/resumed intake, exceptional finishes, duplicate revisions, cutoff/capture filtering and motor-number reuse boundaries.
- Test equal current inputs, frozen eight-ticket pairs, no future leakage, unknown-course preservation, tamper/replay rejection and paired outcome counts.
- Real-data report distinguishes collected files, accepted/excluded races, profiles, historical window, source gaps and usable feature coverage. Never publish source originals or forecasts to this public repository.
- GitHub-only encrypted production retention needs the separately configured owner key; local collection does not prove indefinite retention. No fabricated key or plaintext Actions artifact.
- Run meaningful targeted RED/GREEN checks, then full Python/Node checks and a separate code review. Future performance and continuous integration into the live worker are separate acceptance evidence, not inferred from tests.
