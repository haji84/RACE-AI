# KEIRIN personal, noncommercial research mode (2026-11-03)

Status: implementable **offline** personal study and review mode. Does not claim an authorized bulk data feed or an operating live prediction loop.

## Legal distinction checked against official materials

- KEIRIN.JP site policy explicitly exempts copying that is permitted by copyright law, including "私的使用のための複製". It separately refuses unauthorized compensation-based use beyond private use. Source: https://keirin.jp/pc/dfw/portal/guest/policy/index.html
- Japanese Copyright Act Article 30 permits copies for private use subject to exceptions. Article 30-4 contains rules for non-enjoyment information analysis, with limits for unfair harm to the copyright owner's interests. Primary reference: https://laws.e-gov.go.jp/law/345AC0000000048
- **A user making a single private local research copy is not automatically required to hold a separate commercial API licence.** This is not a universal authorization for high-rate automated GET, bypassing access controls, use of a separate provider's membership content, redistribution or paid services. Source-specific service terms and access behavior must still be checked. This document is an engineering distinction, not individualized legal advice.
- `keirin-mobile.jp` is a different content provider. Its own service conditions are not inferred from KEIRIN.JP.

## New private mode on existing Draft PR #72

- `race_ai/keirin_personal_research_once.py`: in-memory comparison using the existing single-result research auditor. The user only asserts `USER_PRIVATE_NONCOMMERCIAL_RESEARCH`; a fabricated rights token is **not** demanded.
- `scripts/keirin_personal_research_once.py`: offline CLI reads one operator-selected source observation JSON and unchanged pre-cutoff research baseline; writes a **new** private file once using `O_EXCL` (mode 0600), no overwrite and no provider HTTP calls.
- `tests/test_keirin_personal_research_once.py`: compares a fictional single race, checks it remains unofficial, rejects changed race identities and pending/ambiguous results, and proves create-only storage.
- Existing `race_ai/keirin_mobile_one_shot.py` performs only an explicitly selected, separately triggered 1-GET format probe, not automatic repeated source collection.
- No change to main branch, source provider permissions, paid plans, live training, automated wagers or public publication.

## One-race private study command

First obtain an **already existing** one-race result probe JSON through a personal access path where use is allowed, or via the existing one-shot research probe if its site terms permit it. Keep the original dated research baseline unchanged.

```bash
python -m scripts.keirin_personal_research_once \
  --reference /private/keirin_20261103_forecasts.json \
  --candidate /private/one_race_probe.json \
  --race-id 202611033601 \
  --cutoff-at '2026-11-03T08:45:00+09:00' \
  --output /private/20261103_odawara01_personal_audit.json \
  --personal-only
```

The result is explicitly marked `RESEARCH_ONLY_PROVIDER_CANDIDATE`. It does not claim official result authentication or externally witnessed immutable forecast storage, and therefore `formal_hit_at_8_all` stays `null`.

## Optional one-click research fetch, explicit and single-race

The same local tool also supports `--fetch-one` to issue **one** user-requested GET from the already implemented, bounded single-page result adapter. This is **not** a scheduler. Confirm the chosen provider's applicable site terms and the page is accessible without bypassing restrictions.

```bash
python -m scripts.keirin_personal_research_once \
  --reference /private/keirin_20261103_forecasts.json \
  --fetch-one --route legacy \
  --ymd 20261103 --venue 36 --race-no 1 \
  --race-id 202611033601 \
  --cutoff-at '2026-11-03T08:45:00+09:00' \
  --output /private/odawara1r_one_fetch_study.json \
  --personal-only
```

The adapter performs preflight date/race/reference checks *before* contacting the site, accepts at most one page (500KB/8s), rejects redirect and unavailable data, and writes only a private research comparison. It does not record a confirmed official result or permit bulk calls simply because this command succeeds.

## What personal mode does NOT solve

- Real-time permitted recurring data collection, including per-provider usage limits and technical protections
- The full valid pre-race 7/9-rider feature snapshot for PR #71's non-fabricated required inputs
- Authenticated owner-private job runner and independent external timestamp receipt
- Official confirmed race result / corrections with audited provenance, complete daily denominator
- Automatic result-to-next-forecast real-race continuous deployment

## Next real acceptance

Prove exactly **one future race** with (1) a pre-cutoff PR #71 feature snapshot, (2) actual PR #71 algorithm run, (3) original private create-only save plus independent timestamp before official cutoff, (4) post-race officially confirmed result and research/official comparison with source evidence. Keep previous odds-blind forecast immutable; never retrofit after observing the result. Continuous collection stays disabled until source-specific terms and technical behavior are separately reviewed.
