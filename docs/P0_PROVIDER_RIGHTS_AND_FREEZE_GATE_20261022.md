# P0 source rights and independent-freeze gate (2026-10-22 JST)

Scope: Issue #67; offline comparison work in PR #72. This is a **source/purpose review**, not a license, API key, permission to scrape, schedule extraction, or approval to transmit, train, or publish data.

## Official primary sources reviewed

| Sport | Official primary policy / available download | What was confirmed | Automated collection | Private retention | AI training | Public derived projection |
|---|---|---|---|---|---|---|
| Boat | https://www.boatrace.jp/owpc/pc/extra/policy.html ; https://boatrace.jp/owpc/pc/extra/data/download.html | Official site offers race-card and result downloads plus racer statistics. Site policy limits uses beyond statutory exceptions or specific permissions. Download availability alone does not authorize our workflow. | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** |
| Keirin | https://keirin.jp/sp/dfw/portal/guest/policy/index.html | Copyright and reuse restrictions; no general machine-collection or prediction-model rights grant established here. | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** |
| Autorace | https://autorace.jp/policy/ | Site prohibits reuse, reproduction, and redistribution without advance permission, subject to applicable law. No feed/data-pipeline grant established. | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** |
| Horse (NAR) | https://www.keiba.go.jp/terms.html ; https://www.keiba.go.jp/qa.html ; https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf | Official NAR describes ZIP/CSV downloads for entries, race lists, payouts and separate odds. NAR FAQ explicitly restricts commercial reuse and modified republication of race information; a download feature is **not** a blanket reuse or training license. | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** |
| Horse (JRA) | https://jra.jp/use/ | The policy identifies copyright restrictions on protected media; a permission grant for this precise data collection, model training, and redistribution workflow was **not** located/verified. | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** | **UNVERIFIED / BLOCKED** |

Public visibility does **not** itself imply authorization to repeatedly obtain, store, train, or redistribute information, whether for free or for a fee. The distinction between unprotectable facts and protectable compilation/media, contract restrictions, and site terms may require legal review; no legal conclusion about every form of private individual analysis is asserted here.

## Potential data route, subject to purpose-specific review

* Boat: investigate the official program/result download for provenance and machine-readable fields; verify separately if automated ingestion, retention and model training are permitted. **No actual download or processing in this PR.**
* NAR: documented ZIP/CSV is worth reviewing as a data delivery format, but must not be mistaken for grant to republish, bulk ingest, or train. The CSV family includes a separate odds file: reject it from prediction ingestion by allowlist, not by manually hiding the odds column.
* Keirin, Autorace, JRA: request permission or provider-approved delivery terms for the exact data purpose. An ordinary site's human-viewing license is not a machine-use approval.
* For each approved provider: record publisher, authoritative rights evidence URL/document, granted uses (view/fetch/retention/train/derivative display), format, rate limits, total request/byte cap, timezone, update lag, retention limit, charges, expiry and revocation. Unknown => fail closed *for that source and use*.

## Multi-source schedule audit and independent freeze

PR #72's offline CLI accepts a supplied primary `--reference`, independent supplied `--secondary-reference`, and `--ledger` for an AUDIT_ONLY snapshot. It reports venue-only-in-source A/B, race numbers reported by only A/B, unknown counts and existing ledger discrepancies. It does not contact the sources or authenticate their rights, dates or identities. Different updates of one underlying vendor are **not** independent proof; record publication/observation times, canonical venue names and event date separately before real production admissions.

No evidence-proven real cutoff can currently be asserted from these manual files. Pre-cutoff freeze requires:
1. A permission-admitted and timestamped input snapshot excluding odds/popularity/market features; exact race identity, official sales cutoff and start separately.
2. All valid ordered trifecta candidates, fixed maximum 8, versioned model and immutable prediction SHA-256.
3. A distinct independent trusted writer/verifier with authenticated server receipt of hash, race identity and server issuance time **earlier than** the official sales cutoff. Retrying after cutoff cannot generate a new counted forecast. GitHub commit times and editable JSON flags by themselves are not sufficient.
4. Read-back of the same bytes/receipt, append-only result revisions, no prediction edits and proof-aware UI projection.
5. Only then a prospective live race E2E; never mislabel the historical/manual/synthetic checks as realized predictions.

**2026-10-22 review outcome:** 0 newly admitted providers; no external receipt signed or checked; no live forecast frozen. No new costs, public deployment or betting activity.
