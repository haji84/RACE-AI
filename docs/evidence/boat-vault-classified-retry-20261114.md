# BOAT exact-read retry, 2026-11-14 JST

User request: recover from failures and continue prediction generation. This change repairs the confirmed GitHub vault-read stop path, not video inference or every possible forecast failure.

## Evidence and design
The 2026-11-13 owner run 43348227701, source 0796b52c2804177976e4c2e5ab9b65f32589720b, uploaded result artifact 14004326635 but its vault capture failed with an unclassified gh exit. The endpoint and HTTP status were discarded. No precise historical network cause is claimed. Source bundle artifact 14004311685 was independently SHA256 checked as c14270792f0b9b789e8a1791df65276e614e2fde729affdc4d771dc29a718f28. Its vault CLI was brought to the exact PR272 blob 67b32c1266a454a0888474d1521792075e6c7204 before modification.

Retry only the exact failed GitHub metadata/run/ZIP GET, at most three attempts with 2/4 second delays. Explicit 5xx, local timeout and recognized connection faults are transient. HTTP 401/403/404/429, unknown exits, corrupt hashes, bounds and identity errors are not silently retried or approved. Classified diagnostics contain endpoint kind, attempt and fixed reason, not raw stderr/body/credentials. Both stdout and stderr are drained with byte/time bounds.

The existing capture, AES, exact SHA/clock verification, independent readback and next-round completion barrier remain unchanged. A recovered read returns normally within the same round. Exhaustion remains failure and uses the existing checkpoint behavior; this change does NOT claim guaranteed restart after persistent failure. No official provider limits, prediction code, scoring, keys or source sessions are changed. Past forecasts are never regenerated.

## Tests and limits
New focused suite: 12 tests passed locally after observed red failures. Includes real subprocess pipes, status classification, denial/unknown stop, bounded retry, same original AES ciphertext and metadata through local Git independent readback, and idempotent second capture without any extra GET or write. The prior four PR272 mocks of an unclassified error were superseded by the stronger classified suite; all six existing CLI tests are retained. Existing live-artifact tests now use explicit 5xx for retry and keep unknown denial closed.

The historical source bundle omits web/research assets, so broad local tests cannot establish full-repository success. Full GitHub CI must pass at the final candidate SHA before release. A fixture pass is not future race-day P1 completion. Main RELEASE_SHA and matching workflow-run source pins must be updated together after promotion. The recorded 136 P0 / 9 P1 scope is unchanged.
