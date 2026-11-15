# Owner-key recipient sync and saved predictions in the existing UI

The owner explicitly requested real PDCA synchronization and visible saved predictions, and confirmed `RACE_AI_STATE_KEY` is configured. Actions has already authenticated real racer checkpoints with that key. The current managed workspace has no key binding. Do not ask for another GitHub secret, export its value, replace it or put plaintext originals in public GitHub. Continue in PR71, GitHub only, with the existing active worker unchanged.

## Chosen approach

Use the existing owner secret inside the existing Actions workflow. Derive a domain-separated X25519 receiving key from its 32 bytes using HKDF-SHA256; only the public receiving key leaves Actions. Local delivery uses ephemeral X25519 + HKDF-SHA256 + AES-256-GCM to that recipient, binding repository, recipient key id, generation/previous cipher, plaintext SHA and transfer identity as authenticated data. This is encrypted transport to the existing owner's key, never a replacement state key. Actions restores the exact existing journal privately, verifies it, and seals the canonical snapshot with the existing production `PdcaState.checkpoint` AES-GCM format and the original `RACE_AI_STATE_KEY`.

Alternative local owner-key-file publication already exists but requires a second credential binding. Exporting the Actions key, a public/test substitute key, plaintext artifact transport and new providers are excluded. The owner asked to proceed; the selected transport is an implementation choice within that authorized GitHub-only synchronization.

## Trust and bounds

- Receiving public key must be pinned to the exact receiver document bytes and a separately authenticated same-repository Actions artifact, run id and reviewed source-head SHA. The operator/orchestrator obtains artifact metadata/digest with the connected GitHub API, verifies downloaded ZIP SHA, unique bounded members and exact document SHA before calling encryption. A self-supplied public-key manifest is not independently authenticated.
- Receiver document contains schema, repository id `1416489937`, production mode, public key/key id and actual Actions run/head identity. HKDF uses a fixed purpose/domain string and repository salt. No key is derived from a public identifier alone.
- Canonical JSON with exact allowed fields, strict canonical Base64, 12-byte GCM nonce and full 16-byte tag. Bound compressed and inflated bytes using existing state bounds, and cap public Git blobs below 100 MiB. Invalid recipient/root key, wrong scope, hash, path or identity rejects with fixed codes and no plaintext output/reset.
- Private input must already be an existing valid production PDCA journal. Preserve all pair JSON bytes, physical completion receipts, source/archive versions, racer DB and result/score revisions. No forecast regeneration or retrospective timestamp claims.
- A dedicated same-repository `state/boat-pdca-transfer` ref holds immutable encrypted incoming blobs and public metadata. Canonical generations remain on `state/boat-pdca-encrypted-history`; neither ref is main/PR or the active worker trigger. Validate all fetch/push URLs; normal non-force/CAS updates only.
- Existing canonical head is a required independently accepted parent for subsequent generations. The receiving job authenticates/decrypts previous canonical state and runs the existing `_no_regression` before emitting the next checkpoint. First publication requires explicit initialization and refuses an unexpected existing head.
- The encrypted final checkpoint and count-only attestation leave the producer as an artifact. A second runner authenticates it with the owner secret, runs `_audit`, verifies inventory/replay and emits a count-only proof. Locally publish only these already-encrypted bytes after authenticating both artifacts to the same run/reviewed source head and their independent digests. This does not require exporting the root key.
- Final `audit/state/boat-pdca-production-input.json` pins the canonical immutable commit/cipher SHA/scope and is verified by the existing production readback job. Missing input/key yields explicit HOLD. Whole CI success is not proof of real handoff unless the production readback report says it verified it.

## Existing website

Repository inspection identifies the existing personal UI under `web/` and loopback `local_forecast_server`, not a confirmed public site URL. A concise asynchronous request for the intended URL is pending. Reuse that existing UI and its private read-only projection; no Sites/Cloudflare/Vercel deployment, new hosting, raw public assets or permission changes.

Add a pure projection of authenticated PDCA pairs to the existing private research-view contract: 156 race records, baseline/history as distinct `variant` values, unchanged model ids, exact stored Top8/hash/as-of/receipt clocks, participants and retained result observations. Existing UI already distinguishes `variant` and treats this schema as research. Missing values remain missing; formal receipt and accuracy flags stay false. Projection never predicts, fetches race sources or scores again.

Connect the projection to the existing local read-only API/file import, with a runnable private preview when possible. Preserve existing automation processes and never start a second live collector. The actual external URL/host still needs identification before publishing or claiming that the user's site is updated. No ordinary public access to originals is inferred from a request to view them personally.

## Acceptance

Concurrent canonical generation 1 holds another worker's Fukuoka6R trial. The next transfer must append the incoming original journal to that restored state, preserve canonical active heads, retain every incoming file version and source head selection in a content-addressed source manifest, and stop on conflicting immutable identities. Independent restore pins the source content hash from its own checkout and checks its complete contribution. Same-race differing result revisions append deterministic comparison scores before audit; this never regenerates forecasts or replaces historical rows. Publication uses the exact previous canonical parent and a normal fast-forward push.

Invented data tests: recipient/root substitution, tamper/size/JSON/Base64/path/hash/scope errors, unchanged originals, version preservation, repeated scores, first/subsequent publication, expected parent and Git destination checks, missing-key/input GET0 and no private output/logs.

Actual acceptance: authenticate Actions receiver; encrypt and deliver existing local state; producer and second-runner restore; publish canonical owner-key checkpoint; existing production readback proves all 156 originals and latest retained scores; verify site projection Top8 against those same originals. No model promotion, accuracy claim, independent pre-cutoff attestation claim or indefinite-retention claim follows from synchronization.
