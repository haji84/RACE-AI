/* Generated from race_ai.existing_model_coverage.active_catalog; catalogue only, no model execution. */
(function (root) {
  "use strict";
  const catalog = {
  "schema": "RACE_AI_EXISTING_MODEL_CATALOG_V1",
  "source": "race_ai.existing_model_coverage.active_catalog",
  "counts_only": true,
  "models": [
    {
      "model_id": "boat-display-rating-PL-reference-v1-UNVALIDATED",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "same-race official exhibition and program",
      "required_input_ja": "同一レースの公式展示・出走表"
    },
    {
      "model_id": "boat-course-motor-shadow-v0.1-UNTRAINED",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "same-race official exhibition and program",
      "required_input_ja": "同一レースの公式展示・出走表"
    },
    {
      "model_id": "boat-local-start-course-shadow-v0.1-UNTRAINED",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "local win rate and start observations",
      "required_input_ja": "当該場の勝率・スタート観測値"
    },
    {
      "model_id": "boat-course-entry-method-scenarios-v0.1-UNTRAINED",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "verified pre-as-of racer entry/course/method history",
      "required_input_ja": "取得時点以前の検証済み進入・コース・決まり手履歴"
    },
    {
      "model_id": "boat-comprehensive-v1",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "complete timestamped form/course/start ratings and conditions",
      "required_input_ja": "時刻付きの近況・コース・スタート評価と気象条件"
    },
    {
      "model_id": "boat-scenario-mixture-v1",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "complete timestamped form/course/start ratings and conditions",
      "required_input_ja": "時刻付きの近況・コース・スタート評価と気象条件"
    },
    {
      "model_id": "boat-observed-pairwise-factor-v1",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "verified program or exhibition observations with explicit missing fields",
      "required_input_ja": "欠測を明示した検証済み出走表・展示観測値"
    },
    {
      "model_id": "boat-observed-pairwise-start-v1",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "verified program or exhibition observations with explicit missing fields",
      "required_input_ja": "欠測を明示した検証済み出走表・展示観測値"
    },
    {
      "model_id": "multisport-factor-interaction-v1",
      "applicable_sports": [
        "boat",
        "keirin",
        "autorace",
        "horse"
      ],
      "required_input": "complete per-participant features and environment snapshot",
      "required_input_ja": "全出走者の特徴量と環境の同時点スナップショット"
    },
    {
      "model_id": "multisport-scenario-ensemble-v1",
      "applicable_sports": [
        "boat",
        "keirin",
        "autorace",
        "horse"
      ],
      "required_input": "complete per-participant features and environment snapshot",
      "required_input_ja": "全出走者の特徴量と環境の同時点スナップショット"
    },
    {
      "model_id": "multisport-conditional-duel-v1",
      "applicable_sports": [
        "boat",
        "keirin",
        "autorace",
        "horse"
      ],
      "required_input": "complete per-participant features and environment snapshot",
      "required_input_ja": "全出走者の特徴量と環境の同時点スナップショット"
    },
    {
      "model_id": "multisport-race-trajectory-v1",
      "applicable_sports": [
        "boat",
        "keirin",
        "autorace",
        "horse"
      ],
      "required_input": "complete per-participant features and environment snapshot",
      "required_input_ja": "全出走者の特徴量と環境の同時点スナップショット"
    },
    {
      "model_id": "multisport-chronological-ranker-v1",
      "applicable_sports": [
        "boat",
        "keirin",
        "autorace",
        "horse"
      ],
      "required_input": "genuine fitted artifact plus complete current snapshot",
      "required_input_ja": "実入力で学習した保存済みモデルと完全な当該時点入力"
    },
    {
      "model_id": "autorace-personal-observed-baseline-v1",
      "applicable_sports": [
        "autorace"
      ],
      "required_input": "actual prior finish positions; same-race trial for phase B",
      "required_input_ja": "実際の過去着順・試走後版は同一レースの試走値"
    },
    {
      "model_id": "boat-pdca-lane-shadow-v1",
      "applicable_sports": [
        "boat"
      ],
      "required_input": "24 earlier verified same-venue results and new pre-cutoff input",
      "required_input_ja": "同会場の検証済み過去24レース結果と新しい締切前入力"
    }
  ],
  "retired_model_ids": [
    "seller-shadow-v1-20261104"
  ]
};
  const retired = new Set(catalog.retired_model_ids);
  function forDisplay(row) {
    if (!row || typeof row !== "object" || Array.isArray(row)) return row;
    const active = value => value && !retired.has(value.model_id);
    const comparison = (row.comparison_predictions || []).filter(active);
    const prediction = active(row.prediction) ? row.prediction : comparison.shift() || null;
    const view = {...row, prediction, comparison_predictions: comparison};
    if (Array.isArray(row.dispatch_slots)) view.dispatch_slots = row.dispatch_slots.filter(active);
    return view;
  }
  Object.defineProperty(catalog, "forDisplay", {value: forDisplay, enumerable: false});
  for (const model of catalog.models) { Object.freeze(model.applicable_sports); Object.freeze(model); }
  Object.freeze(catalog.models); Object.freeze(catalog.retired_model_ids); Object.freeze(catalog);
  if (typeof module === "object" && module.exports) module.exports = catalog;
  else root.RaceExistingModelCatalog = catalog;
})(typeof globalThis !== "undefined" ? globalThis : this);
