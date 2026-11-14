# Training without final-test feedback

`fit_training_only` fits the existing four-sport ranking kernel using only admitted training snapshots and separate training labels. It rejects records outside the declared training boundary instead of silently dropping them. The artifact contains training provenance, weights and the actual local creation clock, but no validation/test labels or diagnostic scores.

`evaluate_training_candidate` evaluates a frozen artifact on a separate validation period and returns a separate report. It does not modify the artifact. Final-test exposure and tuning decisions belong to the experiment registry; this function alone cannot prove that a caller never previously saw a result.

The new `0.2-train-only` version verifies `trained_data_until <= trained_until <= created_at <= prediction.as_of`. A model fitted today cannot claim a historical creation time. The clock callback is trusted caller input, not an independent time authority. Source permissions and model hashes remain separately required. Existing `fit_chronological` behavior is retained as a research API; its combined validation/test diagnostics are not the new isolated evaluation route.

Validation before integration: 15 new fictional tests and 11 existing learning tests pass locally. Root independently reviewed the change and ran 20 additional checks across boat, keirin, autorace and horse models, including no input mutation, no later-label influence on the training artifact, and rejection of a retrospectively unavailable artifact. These are software checks, not real-race accuracy or 98% Hit@8 evidence.

The workflow adds bounded Windows/Linux checks for the new API. It enables no source-fetch schedule, paid API, deployment, wagering or main integration. Real historical feature sufficiency and official outcome evaluation remain separate gates.
