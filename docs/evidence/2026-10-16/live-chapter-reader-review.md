# LIVE chapter metadata reader independent review

Verdict: **PASS0 — no actionable findings.** Scope: `race_ai/live_video_chapters.py` and `tests/test_live_video_chapters.py`, against base `a21f289475e0dcd8e47440f1327a5aaf8aeca126`. No implementation/product changes were made by this reviewer.

## Contract and safeguards

The reader makes one exact current-venue/mix chapter-setting GET with a 65536-byte accepted-body bound and 10-second transport/capture budget. It reuses the existing no-redirect transport and requests no playback API, manifests, segments, keys, or player seek.

Before the GET, it copies the parent into privately owned JSON values, validates the exact `normal-live-schedule/v1` fields and snapshot hash, pinned venue/stadium/player/source/channel identities, current JST date, source clock/window relations, fresh age at most90 seconds, and all unverified/prediction gates. It revalidates the same frozen parent after the GET, so expiry during transport fails and a callback cannot switch the parent's venue/hash or loosen its gates.

The child schema requires exactly12 rows, exactly5 positions per row, current-day nonfuture update time, and only exact empty strings or positive integers at most86400. The reader accepts only one globally increasing nonmissing prefix across all60 positions. Duplicates, reversal, within-row holes, later rows after a gap, unknown schemas, and other unsupported patterns fail without returning partial usable output.

The five labels and two/three publisher phase groups describe the observed publisher chapter controls. Indexed slot numbers and seek values do not verify the pictures or actual race/phase. The result constructs no interval, schedule-start-plus-offset wall clock, or absolute event time. Player origin, actual frame/race/phase verification, and physical exhibition timing remain UNVERIFIED; prediction eligibility is false, boat features are empty, and model validation remains UNVALIDATED. Unused source text is not retained and error messages remain fixed/sanitized.

## Verification executed

Fresh focused command:

```text
.venv/Scripts/python.exe -X utf8 -m unittest tests.test_live_video_chapters tests.test_live_video_source tests.test_exhibition_video_source -q
Ran 43 tests in 0.098s
OK
```

This comprises14 new chapter tests plus the focused existing LIVE/VOD source regressions. No broad suite or completed operational job was rerun.

**19 independent synthetic probes passed**: exact64KiB and over-limit bodies; exact10-second and over-budget capture; parent age89→90 acceptance and expiry during fetch; inclusive86400 seek and over-limit rejection; all60 increasing points; a global hole and cross-race duplicate; nested duplicate JSON and huge integer rejection; unused metadata non-retention; strict rehashed parent gates/digest; and an independent valid-Toda-parent callback mutation that leaves the Omura result bound to its original frozen parent.

The final synthetic probe exercised the actual default fetcher through a fake urllib opener. It verified exactly one GET to `/setting/chapter/24omura/mix/chapter.json`, the no-redirect handler, timeout10, and readcap65537. No real network/source call occurred.

**Five retained derived-output consistency groups passed** for `artifacts/local/live-chapter-observation-20261016/{schedule,chapters,manifest}.json`: canonical derived snapshot IDs/parent linkage; current-day ordered/fresh clocks; 25 increasing points occupying the first five complete rows with the remaining seven rows blank; exact request identities and manifest-reported two metadata attempts/zero media-or-key GETs/zero POSTs; and all unverified/research/no-raw-retention gates. These are retained-record consistency checks, not a repeated observation or independent measurement of the network traffic. No disposed raw source body or raw-source SHA256 was recomputed.

`git diff --check` passed. Existing schedule reader, VOD resolver, media config, and workflows remain unchanged from the stated base.

## Exact reviewed files and limits

| File | SHA256 |
| --- | --- |
| `race_ai/live_video_chapters.py` | `5f2ff162e1867ff5a72959b78e01dc879836238df0b8c3a0460eccc9ef7f2717` |
| `tests/test_live_video_chapters.py` | `ebe394ddc91309d45fcf119cc7ceb649495ed8f37363e6157adadd280a0c96d5` |

The supplied primary-JS route/ordinal/currentTime observations were review context; this reviewer did not reacquire them. Supported ordering deliberately follows only the observed prefix pattern. Other publisher layouts, time origins, actual sought frames, interval boundaries, race identity, physical clocks, cross-venue availability, CV/boat identity/world calibration, and predictive use remain unverified. The earlier22-point observation and later25-point observation indicate changed publisher metadata, not independently verified event or frame timing.

No real source/network/media/cloud action, credentials, raw-hash reacquisition, player seek, product mutation, or old completed operational replay occurred. Only this review report was written by the reviewer.
