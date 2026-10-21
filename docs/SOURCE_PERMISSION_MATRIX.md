# Source and completeness gates — 2026-10-21

No real HTTP source is admitted in this unit. `permission_fetch` fails before calling transport even when an arbitrary ALLOW string is passed. This avoids fabricating a rights grant from an unverified flag. Synthetic fixtures are authored here and contain no actual participant/source material.

| Sport | Required fields/source candidates (not fetch authority) | Collection | Private storage | Training | Derived display | Raw/video | Frequency/cost/freshness |
|---|---|---|---|---|---|---|---|
|Boat|Existing official day/racelist/B/history, own register IDs, course/ST, motors/period, exhibition, weather, authoritative sales cutoff, result/refund revision|Prior owner approvals remain exact source/purpose scoped; new adapter mapping NOT_ADMITTED|Prior private paths preserved; new pipeline unverified|UNKNOWN for new pipeline|UNKNOWN|No raw redistribution; video separate scope|No new calls; historical schedules never fresh witnesses|
|Keirin|Official schedule,7/9 entries, ID/points, S/H/B, style/line/position, bank/wind, scratches, cutoff, official outcome|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN / no video|0 HTTP; max/TTL to be approved|
|Autorace|Official schedule, entries, handicap, trial/start, machine/maintenance, wet/dry track/weather, scratches/cutoff/results|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN / no video|0 HTTP; max/TTL to be approved|
|Horse JRA/local|Organizer-specific calendar, horse/jockey/trainer, field, weight/distance/going, historic form/pace/work (licensed only), changes/cutoff/results|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN / no video|0 HTTP; max/TTL to be approved|
|Synthetic fixture|4 authored sport schemas, exact synthetic dates/source/hash/revision, unavailable rating, cancellations/results|ALLOW local fixture|ALLOW temporary CI SQLite|Fixed untrained baseline only|ALLOW synthetic evidence clearly labeled|No actual material|No upstream calls; bounded5minCI; no artifact upload|

Required admission record for each real provider: exact provider/URLs, collection vs viewing vs retention vs training vs derivative/raw/video, evidence URI + independently verified grant/date/purpose, expiry, request/byte ceilings, refresh cadence/budget and error handling. UNKNOWN/DENY/expired proof => stop that purpose before I/O. Robots/public accessibility do not establish legal permission.

Source identity and freshness must accompany normalized facts: sport/organizer/venue/meeting/JST date/race number/revision, participant IDs, status/offering, actual sales cutoff distinct from start, published/observed/fetched/registered/as-of, source hash/transform/permission ID, unavailable reasons. Each sport's real coverage remains UNKNOWN, not 0 or no-event. Discovery failure cannot delete a race or prove no meeting.

Current blockers: canonical permitted adapters for each sport, external private append-only writer/current authorization and independent persistence-time receipt, approved budget enforcement and cross-run restore; actual future pre-cutoff/official-result E2E for each sport. Prior PR64 held33 are not a workaround. No current real-data E2E is claimed.
