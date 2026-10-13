# RACE AI v0.8 implementation status

## Implemented in this branch
- **Offline extracted-text K/B import** from user-provided CP932 `.TXT` after LZH decompression. Checks `STARTK`/`STARTB`, BGN, venue, race and six boats. F/L, missing ST and actual course are handled without treating F/L as 0 seconds. SQLite stores SHA-256 and source timestamps.
- **Per racer, by boat lane** latest 10 historical starts and **per actual entry course** latest 5/10/20 starts. Shows raw start series, ST mean/median/population SD, top-1/top-3 and samples, plus overall latest 10. Uses results available **strictly before decision time**, avoiding post-event leakage.
- **Exhibition manual/authorized feed import**, immutable SHA-256 snapshots, recorded publication/capture times, unknown measurements as null; prevents after-decision leakage.
- **Entry interaction evidence register**, requires rights-confirmed footage annotation, reviewer and clip pointer. Ordered player pair results are evidence-gated; Beta(1,1) displayed as an uncalibrated small-sample illustrative prior only. Does not infer attempts from entry-shift alone.
- Standard-library Python CLI for B/K, histories, exhibition and entry evidence; optional OpenCV for rights-gated **local video frame indexing**. Tests in `tests/`.

## Not completed and must not be claimed
- No live downloads or automated network scraping. Official permission/usage terms must be confirmed separately; manually downloaded official archives can be imported after trusted, safe extraction.
- Real latest 2026 B/K archives **not tested**. The parser handles a verified published structural *example*, but actual current archival layouts, abnormal-race rows, full event coverage and real-day official-result reconciliation remain unproven. Any unparseable file is SAFE_STOP, not fabricated.
- Official original exhibition feed automatic capture **not built**. Manual provenance-supported snapshot saving works; publication timestamp may be unknown, in which case record is excluded from historical prediction.
- Local video frame **decoding and fingerprint indexing** is implemented only for rights-confirmed operator-provided media (optional opencv-python), without copying frames. Boat tracking, acceleration/turn performance scoring, and independent verification of media rights **not built**. Frame indexing is **not** calibrated boat performance analysis.
- Entry depth measurement and pair-specific conditional model / automated 120-outcome probabilities not built. No bets or payments.
- No time-split holdout backtest, CI proof or real-data end-to-end proof in this branch yet.
- The `verified_official` field remains 0 for unvalidated user-supplied text, even if its headers resemble official K/B structure. Real-source authentication is not proven.
- Offline frame index command (operator declares rights): `python -m race_ai.cli video-index local_video.mp4 --rights-confirmed --sample-seconds 2`.

## Safe import examples
```
python -m race_ai.cli --db race.sqlite import-k K261012.TXT --date 2026-10-12 --published-at 2026-10-13T00:00:00+09:00 --captured-at 2026-10-13T01:00:00+09:00
python -m race_ai.cli --db race.sqlite stats --racer 4171 --lane 1 --course 1 --asof 2026-10-14T20:00:00+09:00
python -m unittest discover -s tests -v
```
Publication date must be documented from the actual source; the timestamps above are syntax examples, **not verified publication times**. Do not retroactively assign earlier times.

## Data boundary
Official files are available from https://www.boatrace.jp/owpc/pc/extra/data/download.html . These archives are LZH and require a separate safe extractor; the program accepts extracted text and *does not automatically download or execute archives*. No proprietary video is copied into the repository.
