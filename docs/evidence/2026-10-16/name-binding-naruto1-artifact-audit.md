# Naruto 1R name-binding artifact audit

Verdict: **PASS; zero actionable discrepancies in the local artifact scope.**

Audited at 2026-10-15T20:03:37.191552+00:00 (2026-10-16 JST), using independent Python standard-library checks. Scope: race 20261016-14-01 only, run 38798278470 / job 116640353110 / artifact 12003490999. No product modules, helpers, tests, network, source requests, credential access, Git commands, or subordinate agents were used. Only this UTF-8 LF report was written.

## Archive and full-object integrity

Independently read every byte of the five-file ZIP and cold restore: 38,631 expanded bytes; ZIP 8,061 bytes; SHA-256 f676c735cd7c807dd5bfeeef06ace2431f0772f48fac6205cbc818c19d5427d0. Verified the complete unique member set, regular-file metadata, no encryption, sizes, CRCs, full byte equality, and all manifest member hashes. All five files are exact canonical UTF-8 JSON; strict parsing rejected duplicate keys and nonfinite numbers.

| Member | Bytes | SHA-256 |
|---|---:|---|
| baseline.json | 29751 | 0d12977efba6f93a5aa6ffb70b98e86b9836423dc62ff09a93925eb99a02c84c |
| manifest.json | 789 | a041fc49c190c754c156b924bd9f79c327f5d02c56851de2e2cbe09a2d9fcf69 |
| name-proof.json | 2242 | 512f4b4e3a610a3178ed172764d9958112f012f62d5a7ea8df3247a4dc1fc526 |
| receipt.json | 3380 | a7bafb20240b3e4d14c360edc8522f07464c0d53a4bb912bfd37d8eec965bf5d |
| request.json | 2469 | 549c825c68ad8ddb2c6b38d12b23d2ac1ecfff62743dfa2d844415fa7f2af3f7 |

Latest, fixed-request, and publisher API witnesses match the entire archived receipt/finalization envelope after independent canonicalization. All three witnesses are also byte-identical: 3,381 bytes, SHA-256 28cae2ea08d4fa0f1f142ad5e27f8d4388082c05bbd573cac172cbf29c832094. Their terminal newline is outside the canonical 3,380-byte envelope, whose SHA-256 is a7bafb20240b3e4d14c360edc8522f07464c0d53a4bb912bfd37d8eec965bf5d.

Independently recomputed the name-proof snapshot self-hash and the complete receipt hash used by finalization. Snapshot ID: f8b09b2bcb4a77b603c65db262def6a3f7d32af795a394dcfd4c40f7f7c7a861. Finalization receipt SHA-256: 8d010f2c42fe7017041610ad3cab724b0bdb99b9d28468ed079953dd8dfb9e7f. Request, proof, receipt, and finalization consistently bind nonce 38798278470-1 and the same own-race identity.

## Parent preservation and six-name identity

The parent remains request 38764082826-1 / snapshot c2f996a96bd0d46529615c500ef0aa96858b19305b0ac2649c4105fcd12c8402. Preflight latest, preflight fixed, historical cohort API, and baseline-after witnesses are whole-byte identical (32,037 bytes; SHA-256 ec42010501d472fc129d026cb67efe4fa871d202f0f0e959e6556dce5d8965a0). Their entire canonical object equals archived baseline.json (29,751 bytes; SHA-256 0d12977efba6f93a5aa6ffb70b98e86b9836423dc62ff09a93925eb99a02c84c). Original models, as_of, generation, cloud-save, and cutoff fields are consequently unchanged; no model recalculation was performed.

All six lanes, registration IDs, program names, and ratings agree with the retained day preflight and baseline. Independently formed the program identity from race_id, UTC-microsecond closed_at, and all six lane/registration/NFKC-whitespace-normalized names. SHA-256 c0b58dbb1424ab7850f1f21a5cf0f591755fe0834e65d095558197cbf8396d3c matches proof, receipt, and finalization. The immutable B-program hash remains 87dce616b2207807b5671ff875d9aedda2c46bd9709a7dfdcb3117a42bb2b66f.

| Lane | Registration | Independently normalized name | Relation |
|---|---|---|---|
| 1 | 5137 | 川原涼 | EXACT_CANONICAL_NAME |
| 2 | 5237 | 永松良教 | EXACT_CANONICAL_NAME |
| 3 | 5353 | 草川壮良 | EXACT_CANONICAL_NAME |
| 4 | 5179 | 藤本元輝 | EXACT_CANONICAL_NAME |
| 5 | 5258 | 仲本舜 | EXACT_CANONICAL_NAME |
| 6 | 5427 | 港理樹 | EXACT_CANONICAL_NAME |

The retained observed name and verified_full_name agree for every lane, and normalize to the corresponding program name. All six relations are exact canonical equality. No abbreviation, inferred alias, or broader name-resolution coverage is claimed.

The retained source URL is exactly https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd=14&hd=20261016: own date, venue 14, race 1. Source metadata records official-racelist/v1, body_identity_verified=true, upstream_published_at=null, and SHA-256 4c80cc4d0b7329846bcc72d3a2926c233f1624e1b26a92c6e4bfed246f6b1273. Source available_at equals captured_at. The HTML was not retained; this audit checks the retained parsed identities and hash bindings, and cannot recompute that original HTML hash or newly establish source authenticity.

## Clock and counter reconciliation

| Event | UTC |
|---|---|
| Source captured / available | 2026-10-15T19:59:38.294629+00:00 |
| Proof generated | 2026-10-15T19:59:38.310879+00:00 |
| Runner saved | 2026-10-15T19:59:38.311846+00:00 |
| Cloud saved | 2026-10-15T19:59:42.482349+00:00 |
| Receipt confirmed | 2026-10-15T19:59:43.547448+00:00 |
| Race cutoff | 2026-10-15T23:35:00.000000+00:00 |

All clocks are timezone-aware and strictly ordered; all fall on JST 2026-10-16. The frozen baseline precedes the new capture. Confirmation at 04:59:43.547448 JST precedes the unchanged 08:35 cutoff by an independently calculated 12,916.452552 seconds. Audit time follows confirmation. Capture/cloud pre-race flags are consistent with these retained times. This establishes retained clock consistency and cutoff eligibility, not physical pre-exhibition timing.

The completed manifest independently reconciles four business API GETs, one POST attempt, and one official-source request, under a 180-second configured bound. The shared scratch probe is outside these business/source counters. The manifest producer commit is 325ddce19ae999d626782a9929e6511c17d60ba1. These are artifact counter/identity checks, not fresh network observations or independent verification of the supplied workflow and worker pins.

## Limits

The manifest and unchanged baseline remain UNVALIDATED with purchase_decision=skip and empty purchase recommendations. This proof adds zero independently verified physical pre-exhibition pairs. It supplies name-binding evidence only; no numeric or video forecast, predictive precision, prospective accuracy, calibration, adoption, or purchase claim follows. The summary correctly retains raw_source_retained=false, raw_source_hash_recomputed_after_disposal=false, and alias_prediction_integration_complete=false.

No other race, all-156 cohort audit, historical project, source collection, job, restoration, authorization, workflow, code, or deployment was repeated or modified.
