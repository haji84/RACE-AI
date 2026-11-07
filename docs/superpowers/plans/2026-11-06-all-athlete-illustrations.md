# All-athlete illustrations implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Progress lives in `/workspace/scratch/portrait-all/progress.md`; generated images and reference metadata are durable local files.

**Goal:** Create and deploy the approved style for all 1,669 BOAT RACE athletes from the union of the pinned 1,643-person term roster and the official current 1,657-person search listing (26 additions), preserving the first six.

**Architecture:** Verified profile photographs → ordered reference sheets → image-generated 5×5 / 6×6 portrait atlases → registration/cell registry → existing static cards. A canonical JSON catalogue produces the browser data module and fixed Python asset allowlist. Progress is resumable and coverage is explicit.

**Tech stack:** Existing Python/Playwright, image generation tool, vanilla JavaScript/CSS, WebP and GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-06-all-athlete-illustrations-design.md`.

## Global constraints

- No new paid provider, runtime generation API, credentials, Cloudflare/Vercel, permissions, forecasting or main merge.
- Reuse six approved assets; original references and prediction plaintext never enter public Git.
- Preserve encrypted view blobs and owner-link fields during normal CAS publication.
- Keep actual per-athlete/photo/batch states and stop on real upstream or generation limits.

## Review focus

- A different ordering, duplicate ID/cell, or changed reference must not assign another person's face.
- Missing photographs or partial generation must not be labelled completed.
- Atlas clipping must isolate one cell at all three supported viewport widths.
- Many athletes must not force downloading or embedding every atlas for one race.
- Concurrent source/Pages changes and prior standalone portraits must survive updates.

### Task 1: Reference inventory and generation

- [x] Verify the pinned official term file and all target identities; persist reference results and checkpoints with bounded polite requests.
- [x] Prepare and inspect the first ordered reference sheet and generate the matching approved-style atlas; verify ordering, appearance and clipping.
- [x] Generate all remaining sheets using the same process, reusing every completed artifact. Record tool failures/limits and source-unavailable cases explicitly.

### Task 2: Scalable catalogue and atlas rendering

Files: new canonical `web/data/racer-portraits.json`, generated `web/racer-portraits-data.js`, catalogue builder; update `web/racer-portraits.js`, `web/app.js`, `web/style.css`, `web/index.html`, Python portrait assets/offline support and their tests.

- [x] Write failing identity/cell/coverage/catalogue validation and real browser atlas-isolation tests.
- [x] Implement immutable ready-entry lookups, precise atlas-cell CSS, searchable/paged source gallery and actual coverage counts.
- [x] Derive local/Pages asset lists from the validated catalogue; embed only required atlas assets in offline views, keeping CSP strict.
- [x] Pass portrait/packaging/offline/local-server tests and browser checks without touching model logic.

### Task 3: Final review and deployment

- [x] Review the whole change with a fresh reviewer; fix material findings with regressions.
- [ ] Preserve concurrent source edits, update existing PR71 and refresh current Pages assets by CAS.
- [ ] Verify HTTP asset hashes, ciphertext identity, complete target coverage and real deployed browser rendering; report the exact created/missing counts.
