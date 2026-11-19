# KEIRIN official-results connection independent from new A/B card capture

## Decision and scope

The owner wants all nationwide A/B predictions and results to be unattended. This
change fixes an unnecessarily coupled gate in `.github/workflows/keirin-nationwide-ab-auto.yml`.
It **does not** turn on provider access, reissue keys, bypass a 403/429, replace
source rights, or claim nationwide production completion.

After this change `github-only-research-results` can run on the existing
ten-minute trusted-main schedule (or an explicit `mode=run` dispatch) for
previously frozen original forecasts when these existing repository variables
are **both** explicitly `true`:

- `RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED`: allows append-only encrypted Git-state
  settlement and readback.
- `RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED`: owner's explicit opt-in for
  approved official-result acquisition. This switch is **not evidence** of
  the publisher granting machine-use rights.

The historical S3 prefix must remain empty. The existing private RSA PEM
Secret is required; use only the previously verified
`RACE_AI_KEIRIN_PRIVATE_RSA_PEM`. The result worker retains the trusted
repository/main guard, its separate result-source cutoff checks and GitHub
evidence verification. It requires no new A/B prediction in the same run.
Missing and unverified original proofs remain HOLD, never scored losses.

New prediction capture still requires the separate conjunction:

- `RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED == true`
- `RACE_AI_AB_PUBLIC_CAPTURE_ENABLED == true`
- `RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED == true`
- the legacy source S3 prefix is empty

The capture path additionally requires the official-source opt-in at its
trusted source boundary; neither switch alone supplies a permitted, complete
model input source. The known current normalizer requires real published
line groups and marks, riders, competition points, observed recent form,
H/B counts and riding styles. The official day schedule currently supplies
the registered races, rider IDs and cutoff clocks, **not** all those model
fields. Existing Kdreams/netkeirin transport restrictions must remain intact.

## Observed non-secret evidence

- Existing RSA Secret pin and canonical state-branch read: TRUE in
  [run 44453751790, attempt 2](https://github.com/haji84/RACE-AI/actions/runs/44453751790).
- Three A/B capture opt-ins and the official-source opt-in were FALSE in
  that read-only verification; provider requests and state writes were zero.
- Official results and pre-race cards cannot be declared connected by
  this code review. A new real future race needs immutable forecast, a
  distinct runner SHA check, verified official final result/cutoff, and
  authenticated owner-side A/B scoring.
- Official site policy: https://keirin.jp/pc/dfw/portal/guest/policy/index.html
- netkeirin terms: https://keirin.netkeiba.com/info/kiyaku/
  Source-use permission, publisher denial and reproduction restrictions
  must be established separately; never treat a technical GET as permission.

## Acceptance after legitimate source access is established

1. Same registered daily cohort N across official calendar, A/B no-forecast
   states, durable encrypted predictions and results.
2. Original saved before each actual cutoff, SHA independently restored.
3. Official result/refund/revision matched to the immutable original in an
   independently authenticated owner run.
4. Full daily counts for settled, cancelled, refunded, missing inputs, HOLD
   and NO_FORECAST; missing cases must not enter the scored denominator.
5. Repeat on a future real date. Test success, site response presence or an
   enabled GitHub variable is **not** this acceptance.

The GitHub connector used by this task does not expose repository-variable
write APIs or Actions workflow-dispatch creation. Therefore no variables were
changed, no live provider request or state write was performed for this patch,
and the result-only activation remains an **owner-side repository setting**
after the publisher/source constraints are satisfied.
