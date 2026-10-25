# Race33 implementation plan

Base b71bb7138bd416e2cb1a222ccdb2980d62f987d7 in existing PR72 worktree.
Owner directed autonomous local completion with device/cost deferred. Preserve
all external Human Gates and the held33 stop. No new worktree/PR/service needed.

1. Freeze P0_DURABLE_RETENTION_PREREQUISITE_20261025.md and independent design
   criticism98754568..., including stable full-slot assignment and acyclic B/C.
2. C: meaningful REDs for original-wire prerequisite before public consumption;
   implement fixed version2 in the sole existing attempt owner, three APIs,
   strict replay and shared original writer/ACK/recovery. No Git/push.
3. Root: fictional end-to-end integration/legacy fixture/CLI/workflow, no real
   source/remote storage/readback fabrication or default authority.
4. D independently tests/criticizes exact final code; preserve initial findings,
   fix minimal defects with RED/GREEN. Parent full tests then ordinary serialized
   existing draft push after fresh source-smoke/deploy guards.
5. Exact-head hosted CI, A source/evidence/restore audit, Issue68, next dependency.
   No account/cost/device checks, external deploy/security/main actions here.

Reviewed boundary correction before freeze: proposal timestamps alone lost the
last local observation after slow gates. Preserve innerC/B/R, bind final local
guards in immutable C/E row envelopes and M/action identities, then permit only
bounded SQL commit/cleanup. Preserve original P2 and meaningful slow-gate REDs;
test receipt lower bound and restart/intent highwater after final callbacks.
This local evidence correction grants no physical-clock/durability authority.
