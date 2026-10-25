# Private whole-wire retention handoff and evidence

## Goal and scope

Base770a620d8e73de0bb7d9d09e8bb52e8282ddaa93 closed the consumed public
submission-intent unit: exact-head465 tests, separate reviews and739-check
byte/restore audit. Those facts are not private cloud retention or real E2E.
Owner defers device/cost checks and authorizes remaining local development.
Existing source, paid/cloud, Access/security, publication and main gates remain.

Add two local read-only APIs in race_ai/private_wire_retention.py with focused tests.
prepare_retention_handoff loads the original case using its independently
expected request SHA, then prepares a deterministic destination/policy-bound
WHOLE four-model wire request. verify_retention_evidence reconstructs that
binding and checks supplied exact bytes, protected-readback attestation and a
separate independent receipt. No writer, reader transport, default endpoint,
registry, resource/schema mutation, model inference, source fetch or background
operation belongs in this unit. The old case, Race28 submission API/schema,
models/codec, odds and held33 remain unchanged.

D independently criticized the design in the private race29 design report,
SHA256 b029d22bf4450a4091aafde0586a24f87207118f32c4d60e696b6dd1866b5a6d.
The odds cache intentionally overwrites rows and cannot be reused as a vault.
Reusing the original typed wire and validated loader is the relevant asset.

## Immutable request and admission

The exact versioned request binds case request/delivery/wire hashes and byte
count, unchanged transport schema, source policy hash, model source pin, all
four original ordered model IDs/versions/prediction hashes, original persisted
time/cutoff, destination, retention policy and prospective coordinator binding.
No prediction recomputation, ordinary JSON fallback, wrapper/reencoding,
truncation/splitting or replacement hashes are allowed. Return the actual
original wire in private memory only after admission; public summaries contain
no wire, source records, credentials, owner email or account/resource IDs.

Destination has opaque bounded destination/owner refs, an audited adapter
contract SHA256 and an explicit positive exact-int byte cap no larger than the
unchanged codec4MiB bound. The entire wire must fit. These are code caps, not
Cloudflare platform limits, actual allowance or an admitted deployment.
Retention policy has a bounded policy ref, explicit aware retain_until after
cutoff, and protection/immutability policy SHA256s. No duration is invented.

Source/storage admission must cover the original source purposes and this
specific destination/protection/retention horizon. Owner/destination and
prospective coordinator admission are separate exact-True capabilities; all
default to denial. A callback argument is an independently owned bounded copy;
mutation, cycles, excessive strings/metadata, nonfinite values and exceptions
deny safely without private exception material or unbounded post-comparison.
Reuse existing reviewed bounds, typed loader and no-follow private path checks.
Their callbacks do not authenticate actual OS ACL or remote owner protection.

## Acyclic prospective coordinator decision

coordinator_binding is a separately admitted PRE_PUBLIC_BASE_ONLY claim, with
opaque coordinator ref, base_binding_sha256 and a versioned contract SHA256.
Its base contract must bind this case/wire, all four ORIGINAL public plans and
the exact private destination before any public intent. It explicitly excludes
the retention request/receipt hashes so the dependency graph is acyclic.
Supply the whole expected request and complete reconstructed original-plan
digest binding to admit_coordinator. That digest covers all four actual ordered
plans; the independent coordinator must compare its own expected binding.
Do not call this the current Race28 manifest identity, reuse model1's public
intent, create a second attempt registry, or silently reinterpret a V1 store.

The current public dispatcher does not enforce a retention prerequisite.
This pure adapter neither creates nor authenticates a shared coordinator.
An absent genuine admission denies; a fictional fixture admission creates no
coordinator. Later real orchestration must durably consume a distinct
case-wide storage intent and bind accepted whole-wire evidence before every
public model intent. That integration and global recovery remain undelivered.

The stable request SHA is domain-separated over bounded finite canonical JSON
of the exact request. Exclude current clock, random nonce, auto-generated key
and receipt. Identical preparation yields the same request identity; repeating
it never grants a resend. Local prepared/observed times remain separate.

## Read-only evidence contract

Require original typed bytes, not a hash-only response. Readback metadata binds
request SHA, destination, exact opaque immutable object/version, wire hash and
byte count, observed_at and independently admitted reader attestation ref.
The separate receipt binds those same identities plus committed_at,
retained_until, protection/immutability policies and issuer ref; its bounded
opaque proof bytes go only to the explicitly supplied independent verifier.
Do not guess a provider signature/clock scheme or synthesize missing receipt
fields from runtime Date, ETag, client claims or a later successful GET.

Original persisted_at <= independently attested committed_at < official
cutoff, readback observed_at >= committed_at and both no later than the fresh
aware observation clock. Attested retained_until covers requested retain_until.
Preparation rechecks a monotonic aware clock after slow admissions and requires
now before cutoff. Historical verification can run after cutoff and gives no
new write, source-purpose or public-release authority.

Metadata/proof resource caps and exact schemas are frozen in C's API handoff
before production code: <=64KiB canonical metadata/proof, <=512-byte opaque
refs, strict SHA lengths/types, bool/int distinction and original codec bound.
Opaque refs are not URLs, paths, tokens or executable destinations. Unknown,
oversized, partial, altered/rehashed, mismatched or unadmitted evidence remains
RETENTION_UNVERIFIED_DO_NOT_WRITE under the same original request identity.
No polling, object discovery, nonce reset, retry permission or automatic I/O.

## Honest results and acceptance

Preparation is NOT_SENT_NO_WRITE_AUTHORITY. Verification may report local
whole-wire equality and receipt/readback admission BY_CALLBACK. Every stronger
cloud retention, source-rights authentication, producer authenticity, global
exactly-once, official prediction and scoring eligibility flag remains false.
Bytes seen at one instant do not prove durable retention, actual owner-only
Access, immutable policy enforcement or independent server time.

Use one authored original BOAT case and recording/supplied fictional evidence;
actual unchanged pinned models/codec run once for that checkpoint. Test default
denial before actionable bytes, all model/destination/policy/base bindings,
insufficient cap/horizon, exact byte and proof mismatches, late verification,
slow/rollback clocks, callback mutation/resource/private-error handling and
deterministic repeated preparation without inference/writer/network/registry.
Root adds a small fictional CLI to existing read-only CI after API freeze.
Independent review, final local/hosted checks, new-unit restore audit and Issue68
record follow. Actual lawful full input, approved deployed backend/coordinator,
independent future retention/result evidence, formal review/main and98% remain
separate unmet acceptance conditions; device/cost deferral is not a pass.
