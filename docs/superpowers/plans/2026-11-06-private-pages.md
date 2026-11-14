# Private saved predictions on Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Give the owner an HTTPS URL that opens the existing 156-race saved predictions while keeping all public data encrypted.

**Architecture:** Pure existing projection → separate view-only AES-GCM key → static Pages assets/ciphertext. The key stays in the owner URL fragment. Classic branch publication uses existing Git credentials without adding Actions token permissions.

**Tech Stack:** Existing Python/cryptography, Web Crypto, vanilla UI, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-06-private-pages-design.md`

## Global Constraints

- GitHub only; no raw originals, root/view key, plaintext forecast data in public Git/artifacts/logs/caches.
- Existing owner root key, canonical state refs, original predictions and active worker are unchanged.
- Separate public/private output directories; only `gh-pages`, non-force/CAS publication. No main merge, fees, access-role or Actions permission changes.
- Static verified saved snapshot, research flags intact. Possession of the secret URL permits viewing; no login or live-update claim.

## Review Focus

- A publication folder containing a key or plaintext must be rejected before network writes.
- Malformed/huge envelope, changed cipher, wrong key and external/path-manipulated URLs must not load data or leak fragment values.
- Existing hash navigation, brand and skip links must preserve the private URL across page changes and reload.
- A concurrent or unrelated existing Pages ref must never be reset or overwritten silently.
- A green code CI is separate from actual Pages deployment and real decrypted display verification.

### Task 1: Private Pages bundle

Create `race_ai/saved_pages.py`, `scripts/boat_saved_pages.py`, `tests/test_saved_pages.py`.

Interfaces: `build_site(state_path,public_dir,private_dir,*,expected_source_sha256) -> public metadata`; `publish_site(repo,public_dir,*,initialize,expected_parent) -> public Git receipt`. No method returns/logs the secret URL; private files hold its key and fragment. Use exact existing `_asset_bytes` and pure projection, bounded AES-GCM envelope, reviewed asset allowlist, separate hardcoded Pages Git transport reusing destination/rewrite/CAS checks.

- [ ] Write failing invented-state tests: decrypt equality with all four original variants; no key/plaintext outside private output; bad source fingerprint; symlink/extra file/modified asset/unsafe envelope rejection; immutable ciphertext name; first/CAS publication with local bare Git.
- [ ] Run RED, implement minimal builder/publisher, run GREEN and commit.

### Task 2: Browser decrypt and existing UI

Create `web/saved-view-crypto.js`, `tests/saved_pages_browser.test.js`; modify `web/app.js`, add test call in the existing UI workflow.

Interfaces: `SavedViewCrypto.read(path,fragment) -> Promise<saved view>`; strict `#saved=<sha>.<key>` and fixed same-origin `./views/<sha>.json`. `race-ai-encrypted-saved-view` meta enables the loader and secret-preserving navigation. Existing unencrypted mode stays unchanged.

- [ ] Write browser RED for automatic decrypted startup, four exact variants, all seven pages/reload/brand/skip links, wrong/missing key and tampering, no key in requests/storage/errors, no POST/external requests.
- [ ] Implement minimum loader/UI changes; test browser GREEN and existing UI regressions; commit.

### Task 3: Actual Pages deployment

- [ ] Fresh review required before using real data or enabling Pages; fix confirmed Important/Critical issues.
- [ ] Build actual bundle from already-synchronized source content `6d13d191adc7185c0c20e7b9a1162a7793bd2462cdb5b1aa8eaa9eb51f5b41f0`; verify all624 originals after decrypt locally, never expose key in public evidence.
- [ ] Publish code in existing Draft PR71 after preserving concurrent changes; run full existing CI.
- [ ] Publish exact reviewed public bundle to hardcoded `gh-pages`, configure classic GitHub Pages with existing credentials, preserve all security permissions, verify deployed asset/cipher hashes and actual browser Top8.
- [ ] Report the working owner link privately, existing snapshot time/coverage, and any remaining concrete deployment gate. No false live/accuracy/retention claims.
