# Saved model switching

The owner wants to select a model and see that model's prediction. Existing detail controls mix model/stage/history, offer only originals stored on the current race and leave the race list fixed to each race's default. Preserve the current deployed opening-date and explanation improvements while adding explicit model controls.

Use a model selector on the race list and detail/research views. It selects a model for the sport and updates tickets, explanation and comparison together. Keep the existing original-index selector for stage/history compatibility. Remember chosen originals by identity per race/model through switching and feed updates. An unavailable selected model shows a clear missing prediction state. Catalogue entries and retired models do not become generated predictions.

Constraints: GitHub only, existing private feed/key, immutable originals/history/portraits, unchanged result and financial modules. No model execution, new provider, permission or fee. Use stored predictions exclusively. Keep active model catalogue denominators unchanged.

- [x] Read selection/rendering paths and preserve current published app/ui-model changes.
- [x] Add failing pure/browser regressions: model B changes tickets and rationale, race navigation keeps the model, unavailable B never shows A, original version choice survives returning, retired models remain absent, 320/390/1440px fit.
- [x] Implement pure model option/resolution helpers and the two visible selection surfaces, preserving existing original selector indices and stable identity handling.
- [x] Verify related model/result/UI/WebCrypto regressions and review the change.
- [x] Publish scoped frontend assets, verify HTTP bytes and private real-data model switching with count-only Actions checks, record evidence and preserve unrelated draft work.
