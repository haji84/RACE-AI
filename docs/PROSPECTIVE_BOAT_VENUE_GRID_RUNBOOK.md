# Explicit prospective BOAT venue input

This optional research path uses the separately retained Nov6 grid for **new**
BOAT native inputs. No caller enables it by default. Canonical dataset pointers,
historical training/cohorts, owner decisions, model formulas and weights remain
unchanged. Existing source budgets, frozen-race filtering and issued maps remain;
an already issued race or incomplete native case can HOLD.

Prepare a separate manifest at an explicitly chosen repository path. Its exact
fields are `schema: RACE_AI_PROSPECTIVE_BOAT_VENUE_GRID_INPUT_V1`,
`dataset_pointer`, `observed_only: true`,
`course_feature_policy: EXPLICIT_REPLACE_SUPPORTED_COURSE_FIELDS_RETAIN_PRIOR_V1`,
and `readback`. `dataset_pointer` is the unchanged full pointer from
`audit/state/boat-venue-dataset-nov6-research-input.json`. `readback` contains only
`run_id: 42370578793`, `run_attempt: 1`, `job_id: 128397771646`,
`head_sha: b569f3c0248c51092a24db1995d5418c2f1e18e4`,
`metadata_sha256: a7c6ed0a973309804938eeefdb207b69d3b402c24247a7488fe8b09f676f15bf`,
`log_sha256: 34b242bba6a1724e1107452da2f2e283ea71abd35a2ef60328334ba3c3dd7208`.
There is no latest-pointer inference or arbitrary witness selection.

The existing Actions caller supplies the existing secret. Explicit preparation:

```bash
python -m scripts.boat_all_model_cycle prepare --round 1 \
  --prospective-grid-input audit/state/boat-venue-future-grid-input.json
```

Actual GitHub attempt/job metadata and decoded logs must match the reviewed
witness, including repo, owner, immutable HEAD, checkout and required successful
SQLite/history/grid steps. The actual grid readback must be READY with verified
hashes/MAC and 63,432 cells. Job success or documentation alone is insufficient.
The job completed at `2026-11-07T12:04:44Z`; new original source as-of must be
strictly later than `12:04:45Z`, the grid's authenticated build availability
`2026-11-07T10:55:41.637327Z`, and this preparation's actual verification time.
The job is a readback-by-time witness, not a claim of the ciphertext's first save.

The existing composite action accepts optional `prospective-grid-input`. It
prepares before any round source and passes the same path to the existing fresh
forecast command. Missing, changed, late or failed admission stops that selected
path. The empty input preserves the existing flow. No workflow or schedule is
added or activated. Do not run the ordinary source command before preparation
and then retrofit a grid to its saved input.

Pure native conversion copies the original master at its original as-of. It
applies only the existing observed course-mean finish/ST fields and established
shared/full mappings. The explicit policy retains old replaced terms, source
period, actual-course/current-frame condition, sample counts, coverage, unknown
membership and missingness privately. Other recent/tactical/PDCA/AB/CLite signals
remain their genuine original inputs. The aggregate grid is not raw history.
Unrecoverable contemporary facts remain unavailable; sparse entrants are not
filled with invented boats or measurements.

New native capsules are sealed and independently read back through the existing
opaque storage. The prospective carrier requires all14 original BOAT cells with
the same roster/cutoff/scope and grid evidence and ten minutes remaining. It
bypasses the old canonical re-enrichment path while preserving that path's
training-dataset equality checks. Every paired model receives the same exact
native input. No previous capsule or forecast is overwritten or retimed.

Only after this real carrier is independently saved, add its actual source pin
to the existing `native-p1-compare:` V4 nineteen / V3 thirty manifest. The current
candidate and other sports retain their own actual pins and contracts. A case
already forecast with that same candidate remains HOLD in the future runner;
do not count it twice. Real training, a complete future comparison and settled
PDCA are separate gates. This implementation alone establishes none of them.
