# Official-profile athlete illustrations implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Track completed steps and decisions in the task ledger.

**Goal:** Display approved, faithful athlete illustrations in the existing site.

**Architecture:** A fixed local illustration registry resolves sport/registration/name to an asset. Shared Python asset declarations keep local serving, offline export and encrypted Pages packaging consistent. A presentation-only Pages refresh retains existing ciphertext and owner-link metadata.

**Tech stack:** Existing vanilla JS/CSS, Python, losslessly encoded WebP, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-06-official-racer-illustrations-design.md`

## Global constraints

- Six initial official-profile illustrations; never claim full athlete coverage.
- GitHub only; no new fees, services, permissions, workflow runs or main merge.
- Keep every encrypted view and owner-link field unchanged during asset refresh.
- No official photo requests from the browser; no private forecast data in public evidence.

## Review focus

- The same registration in another sport must not resolve to a boat athlete.
- Conflicting IDs/names and synthetic records must not show another real person.
- Image errors and missing assets retain usable, accessible cards at 320/390/1440px.
- Offline exports must include portraits without external file requests.
- Concurrent Pages updates must not be overwritten or erase historical ciphertext.

### Task 1: Registry and portrait cards

Files: new `web/racer-portraits.js`, `web/assets/racer-portraits/boat-<registration>.webp`, `tests/racer_portraits.test.cjs`, `tests/racer_portraits_browser.test.cjs`; modify `web/app.js`, `web/index.html`, `web/style.css`.

Interface: `RaceRacerPortraits.get(race, participant) -> {registration,name,src,sourceUrl}|null`; `RaceRacerPortraits.all` is the immutable six-entry catalogue.

- [ ] Write and run failing tests for real identity lookup, conflicting IDs/names, synthetic/other sport rejection and unknown IDs.
- [ ] Finish five portraits from each athlete's verified official photo, preserving the approved sample and generated originals.
- [ ] Implement registry, local images, responsive cards, explicit preparation fallback, settings coverage and image-error behavior.
- [ ] Verify real browser rendering, fallback and all six assets at 320/390/1440px; run existing Node contracts.

### Task 2: Packaging and deployment

Files: new `race_ai/racer_portraits.py`; modify `race_ai/local_forecast_server.py`, `race_ai/saved_pdca_view.py`, `race_ai/saved_pages.py`, `tests/test_saved_pages.py`, and relevant offline/local-server tests.

Interface: `refresh_site_assets(repo, *, expected_parent, transport=None) -> receipt`, reads the fixed Pages branch and updates only reviewed presentation assets/manifest hashes. It does not decrypt, regenerate or read original forecasts or keys.

- [ ] Write failing tests for portrait packaging/serving/offline inclusion and ciphertext-preserving CAS refresh.
- [ ] Implement fixed asset declarations and bounded presentation refresh; preserve exact cipher bytes and all owner metadata.
- [ ] Run targeted Python regressions and encrypted Pages browser checks; review the whole change with a fresh reviewer.
- [ ] Preserve concurrent source edits, update existing PR71 without main merge, and publish presentation assets to the current `gh-pages` head by CAS.
- [ ] Verify live asset hashes, retained ciphertext hashes and actual deployed portrait rendering using an invented local browser import only.
