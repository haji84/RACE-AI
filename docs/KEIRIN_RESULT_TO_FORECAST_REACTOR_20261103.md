# KEIRIN result event -> research PDCA -> next-race forecast outbox

Status: IMPLEMENTED AS A RESEARCH ADAPTER, NOT LIVE / NOT A COMPLETE PRODUCT.
This is an incremental addition to existing Draft PR #72. No new PR, no main merge.

## Files

- `race_ai/keirin_result_reactor.py`
- `tests/test_keirin_result_reactor.py` (synthetic cases)
- Existing `race_ai/keirin_result_delivery.py` (provider-supplied normalized intake)
- Existing `race_ai/evaluation_result_revision_bridge.py` (result revision chain)

## Event-driven flow

1. The owner private runtime receives a result event from a separately authorized, authenticated source. This repository never scrapes it.
2. Existing `build_research_batch` normalizes the bytes; its `admission` dictionary is a validation contract, **not** legal permission by itself.
3. `react_to_result_delivery(batch, future_races, now, forecast_reference, ...)` computes `research_hit8`, never formal Hit@8.
4. A FINAL_NORMAL/no-refund result event triggers only after an independent result-attestation callback binds the observation SHA and admitted uses.
5. Candidate future races are sorted by official cutoff. A future entry requires an independently checked pre-race source snapshot, scoped permission and private immutable forecast readback. Late / missing cutoff / frozen entries are denied.
6. The earliest eligible races receive an 8-pick forecast *intent*, not a prediction, via an owner-only atomic append/create-once outbox. Readback must match exactly. A stable race+cutoff idempotency key prevents duplicate jobs on replay.
7. An actual forecast worker, when implemented in a trusted owner environment, must independently revalidate official cutoff, authorization, snapshot, old forecast state and external pre-cutoff freeze receipt before generating any candidate. Proposed models A and B remain separately frozen and evaluated.

## Verification

```bash
python -m unittest discover -s tests -p 'test_evaluation_keirin_result_delivery.py' -v
python -m unittest discover -s tests -p 'test_keirin_result_reactor.py' -v
```

The tests use only fabricated results, rights receipts and private queue mocks. Passing synthetic tests never proves an official result was retrieved, a real data-use grant exists, a model executed, prediction accuracy improved or a remote service deployed.

## Deployment blockers

- **Not resolved:** rightsholder/data-feed permission for machine acquisition, private retention, result analysis and ML training; frequency and pricing limits; provider-specific signed source evidence.
- **Not resolved:** real trusted provider feed and credentialed owner-private storage/queue.
- **Not resolved:** worker for actual real model execution, immutable forecast readback, third-party timestamped seal and PR #71 model / cutoff queue integration.
- **Not resolved:** end-to-end future-race real-data evaluation, failure recovery, provider correction handling and operations monitoring.

Do NOT turn on unsanctioned scheduled scraping or publish raw records. No auto-wagering, charges, automatic main merge or public deployment. Contact the rightsholder or licensed provider for purpose-specific rights before adding an HTTP collector.

Official policy: https://keirin.jp/pc/dfw/portal/guest/policy/index.html
