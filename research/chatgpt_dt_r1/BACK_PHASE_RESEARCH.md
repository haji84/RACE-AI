# Archived actual B leader, conditional finish research

The official definition of B is the leader crossing the final back-stretch line with half a lap remaining: https://keirin.jp/pc/static/beginner/basics/racecard.html. The archive has a result-side sb_mark field. A unique explicit B and complete result roster are required. No B is NOT evidence of a particular rider losing; missing/ambiguous records are counted. Archive records are not independently certified pre-cutoff or official results.

The experimental internal candidate learns P(B leader | pre-race features) and P(ordered finish | pre-race features, B leader). Conditional fit uses the archived B label ONLY as a training condition. Forecast marginalizes over all hypothetical leaders and never reads the target's result. A direct ranker on the same labeled training set provides a fair baseline. Evaluate on all eligible finish results, including missing B. B accuracy uses only explicit eligible labels. Record coverage, same-period Hit@1/2/4/9/12, exacta Hit@1/2 and log loss. Candidate is not automatically selected or mixed into the existing frozen five-ability model. No new authority or schedule. No actual kinematic or full-phase label claim.

This is a research path toward abilities 2, 3, 4 that does not require pretending incomplete video observations are full trajectories. Motion/identity and six-stage validation still require independently reviewed real data. No historical result feeds the target prediction.

The completed one-shot pilot downloaded the same two pinned public archives, checked SHA, and froze privately before measuring later periods. Only aggregate output was logged; source rows and forecasts were not published. Its temporary weights were discarded. The saved artifact hash and aggregate cannot reconstruct those weights. Do not call a newly fitted candidate a recovery of that exact artifact, and do not repeat its final-period scoring merely to reproduce known results.

## Candidate retention and private forecast interface

`back_candidate.py` implements a separate v2 research-candidate envelope. It binds the leader, conditional and direct weights, exact feature schemas, shared labeled training count, chronological split, actual freeze time, dataset SHA and source-code hashes. Loading requires a separately retained SHA-256 of the candidate file's exact bytes, then checks the envelope hash and both ranker hashes. The source checkout must match the saved hashes, including `requirements.txt`. This is an unselected fit-period candidate: its schema rejects transferred temperature/selection metadata and requires temperature 1. A later calibrated or selected variant needs its own declared contract and receipt.

`study(paths, new_private_directory)` now freezes this envelope and scores **tune only by default**. `test_evaluated` is false and `test` is null. Explicit `evaluate_reused_test=True` / `--include-reused-test` permits a separately requested reference score; it never makes the already-viewed period independent. No B-specific calibration or confidence claim is supplied. Feature HOLDs stay in the valid-result and valid-B target denominators; the report separately gives predicted counts and the proper-score sample size.

The command refuses training without an output path and the existing pinned owner public key. Its ciphertext directory must be outside the temporary private directory, so the normal private cleanup cannot delete the retained output. The exact public output inventory is:

- `manifest.json`: strict file inventory, byte hashes, candidate/dataset identities and owner pin.
- `candidate.sealed.json`: the existing owner codec's authenticated ciphertext. It contains the exact private `back_candidate.json` and `aggregate.json` bytes; no plaintext copy of either is exported.

This distinct format does not relax `bundle.py`'s main-study allowlists. Ciphertext verification does not prove owner decryption, source authenticity, long-term retention or future accuracy. Durable Git retention and an independent readback remain required after export. A successful local directory write alone is not that acceptance.

For a separately justified new study, the existing job can pass these retention arguments. This command is not a request to rerun the completed pilot:

```bash
python -m research.chatgpt_dt_r1.back_phase_study "$private" \
  --bundle-dir "$RUNNER_TEMP/dt-r1-back-evidence" \
  --owner-public-key "$GITHUB_WORKSPACE/docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem"
```

It logs `DT_R1_B_AGGREGATE` and `DT_R1_B_BUNDLE` receipts. The latter supplies both the candidate byte SHA and manifest byte SHA. Retain those pins independently. The existing workflow needs to retain **only** the two ciphertext-directory files; this module does not dispatch or modify a workflow. Existing locally verified archives can instead be passed directly to `study()` and `export_candidate()` without downloading them again. A new study directory is mandatory.

Verify or restore an already retained candidate without retraining:

```bash
python -m research.chatgpt_dt_r1.back_candidate verify \
  --bundle-dir /private/ciphertext --manifest-sha256 "$MANIFEST_SHA256"
python -m research.chatgpt_dt_r1.back_candidate restore \
  --bundle-dir /private/ciphertext --manifest-sha256 "$MANIFEST_SHA256" \
  --output-dir /private/new-restored-study
```

Restore reads the already configured `RACE_AI_KEIRIN_PRIVATE_RSA_PEM` only in the existing approved owner-key environment. It creates the destination only after all file, owner, ciphertext, payload, model, dataset and current-code checks pass. Private files are create-only mode 0600 outside Git. No new key is generated or permission requested by these commands.

The private prediction command requires the exact candidate byte pin:

```bash
python -m research.chatgpt_dt_r1.back_candidate forecast \
  --candidate /private/new-restored-study/back_candidate.json \
  --candidate-sha256 "$CANDIDATE_BYTES_SHA256" \
  --record /private/normalized-target.json --history /private/normalized-history.json \
  --at "$ACTUAL_PREDICTION_TIME" --output /private/new-b-shadow.json
```

For prospective inputs it enforces the shared 15-minute cutoff, source-availability and model-age checks, plus the earlier-day history and source/result availability clocks. Independent admission and readback must still authenticate the sources and seal the original; the command reports `independent_source_attestation=false` and prospective shadow status. Historical archive rows lacking availability evidence cannot be relabeled as prospective. Retrospective calls omit `--at` and keep their research scope.

All possible B leaders are marginalized. Full rank, exacta and trifecta probabilities come from that same mixture; target B and finish labels are unused. Prediction confidence stays HOLD until a new candidate-specific calibrated policy has independent audit evidence. The interface does not change the existing model pin or register this candidate as a contest entrant.

History JSON has a separate 256 MiB bound, aligned with the existing archive-reader cap; a candidate or aggregate file is bounded at 2 MiB. The tests include a history input exceeding 2 MiB, a smaller enforced-cap rejection, target-result invariance, nonuniform mixture consistency, HOLD denominators, mismatched pins/arrays/code/clocks, and a real-cryptography synthetic roundtrip with a fixture owner key. Those tests do not attest real source data or owner-key restoration.

## Next accuracy work

The preserved pilot comparison uses the same B-labeled training cohort for both arms (20,041 races), while the frozen main DT-R1 uses a different feature/candidate/calibration path. Their headline counts cannot isolate the causal contribution of B conditioning. Retain the paired direct baseline when testing a new B recipe. Use fit/tune only for any new ridge, feature, blend or temperature choice, freeze that choice before later evaluation, and reserve a genuinely new period for the final improvement decision. Do not select changes from the known October–November test, widen ticket counts to claim a one-point gain, transfer the main model's confidence calibration, or label B supervision as measured motion or physical energy.
