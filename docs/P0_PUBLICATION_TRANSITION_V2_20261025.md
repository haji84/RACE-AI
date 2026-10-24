# Offline publication transition V2 — 2026-10-25

Scope: PR #72, `race_ai/four_sport_publication_transition.py`. This contract
repairs synthetic publication-evidence and replay handling. It does not start
collection, authorize source use, execute a model or establish a real source
publication time.

## API and evidence

`compare_first_party_snapshots(previous, current, *, now, already_issued=())`
continues to consume two exact `inspect_presentation_observation` records.
The result schema is `RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V2`.

The records must identify the same sport, race and presentation kind, retain
the same recorded cutoff, and have strictly increasing capture times. Both
observations must have explicitly verified race and participant identities;
an unverified PENDING record cannot establish the earlier publication state.
PENDING to AVAILABLE/PARTIAL requires different source SHA-256 values.
Changing a status label on identical bytes, or presenting simultaneous
captures as a publication sequence, raises `PresentationEvidenceError`.
AVAILABLE to AVAILABLE remains a non-event. Existing cutoff and current-time
checks still prevent an event after the cutoff.

The V2 stable identity contains:

- V2 schema, sport, race ID and presentation kind;
- published source SHA-256;
- scheduled cutoff normalized to its UTC instant.

It excludes both capture times. The output retains `previous_captured_at`,
`captured_at` and the original `scheduled_cutoff_at` as observation evidence.
`transition_sha256` is the digest of this V2 identity. Re-observing the same
published bytes later therefore retains the same identity, including when a
restart compares them with an older PENDING observation.

Persist and replay the explicitly versioned `issued_event_key`, whose form is
`RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V2:<transition_sha256>`.
`already_issued` accepts a list, tuple or set of these exact keys. A matching
key suppresses `would_enqueue_input_check`; it does not erase the observed
publication candidate or its timestamps. Distinct races, presentation kinds,
source revisions and cutoff instants retain distinct identities.

## V1 recovery is held

V1 `transition_sha256` included capture time. A bare 64-character digest
cannot identify its version or reconstruct a stable publication identity.
V2 rejects bare digests, V1-prefixed strings, V1 event objects and malformed
issued records. It does not ignore them, reinterpret them as V2, clear them,
or authorize replay with an empty ledger.

An operator recovering an existing V1 store must hold enqueueing until a
separately reviewed offline migration can establish complete original event
identity, original observations and issuance evidence. Merely adding the V2
prefix to a V1 hash cannot perform this migration. No migration helper,
persisted V1 migration or real V1 ledger change is included or authorized by
this slice. An empty `already_issued` is appropriate only for a store whose
absence of prior issuance has been established by the caller.

## Remaining gates and proof limits

This pure function neither stores issued keys nor atomically reserves work.
The caller must supply an authoritative issuance history and use atomic
check-and-append/claim storage before starting downstream work. Two concurrent
calls with the same empty history can both return a candidate; this code is
not proof of production exactly-once execution or crash recovery.

Race/participant matching and source-status assertions still depend on
independently reviewed provider parsing and provenance. Changed bytes alone
are not authenticated proof that the required presentation was published.
Source-purpose rights, official cutoff verification and original provider
publication time require separate evidence. All returned rights, full-model
admission, monitor-start, original-publication-verification and official
prediction flags remain false. No time or missing model input is invented.

The regression evidence is synthetic: equal captures, identical bytes,
recapture replay, legacy recovery rejection, partial publication, all five
presentation kinds, cutoff/time failures and existing presentation tests.
It is separate from lawful real pre/post source observations, future model
freeze, official results, iPhone acceptance and main integration.
