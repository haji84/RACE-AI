# 引継ぎ差分の検証

基準は先行PR #327の `345f0ac8`、その後の `912947a3` の17変更も保全した。新しい分類器を作らず既存PDCAへ統合した。独立レビューで発見した締切後の正規化原本の流用を排除し、初周の全順序と前方部分列の矛盾、完全な仕掛け列と整合する部分観測の重複を同じ既存照合で処理する。参考事例を「復元済み原本」と表示する字段も除いた。

## 最終の関連検査

次の **203検査が成功、失敗0・エラー0**。先行更新の履歴、全着順分布、戦術観測、番手・多段階、独立採点と、今回のアダプター・時刻・SHA・既存着順互換を含む。

```bash
python -m unittest \
  tests.test_keirin_flow_evaluation tests.test_keirin_forward_score \
  tests.test_keirin_race_development tests.test_keirin_research_ledger \
  tests.test_keirin_research_cohort_score tests.test_keirin_rider_context \
  tests.test_keirin_rider_context_study tests.test_keirin_ranking_adjustment \
  tests.test_keirin_small_ticket_budget tests.test_keirin_result_unread_method \
  tests.test_keirin_evidence_selection tests.test_keirin_forward_scenarios \
  tests.test_keirin_nationwide_auto_generator tests.test_keirin_confidence \
  tests.test_keirin_authored_confidence tests.test_keirin_confidence_storage \
  tests.test_keirin_joint_finish tests.test_keirin_tactical_observations \
  tests.test_keirin_rider_profile_study tests.test_keirin_form_fall_blind_pdca \
  tests.test_keirin_official_owner_view -q
```

CLI `--help` の追加引数、`git diff --check`、文書の相対リンク、参考caseと結果証拠の実バイトSHAを確認した。西武園参考は既存PDCAで再実行し、reference_grade=B、正式grade=null、placing.formal=false、正式成績加算0件。精度改善・全国本番完走の検査ではない。

## 広範囲の検査で分かった制約

統合前に実行した `python -m unittest discover -s tests -p 'test_keirin*.py' -q` は **1,549検査、失敗1・エラー8・skip11**。全件合格とは報告しない。[機械可読記録](validation.json)。

- `test_keirin_cloud_owner_source_cycle`、`test_keirin_cloud_pr71_state`、`test_keirin_cloud_pr71_variable`、`test_keirin_day_four_model_audit`、`test_keirin_licensed_source_readiness`：現チェックアウトに旧pinの `race_ai.keirin_pr71_four_model_rank` がない。
- `test_keirin_source_gap_plan`：旧pinの `race_ai.keirin_allowed_delivery` がない。
- `test_keirin_verified_prior_day_bootstrap`：旧pinの `race_ai.keirin_daily_public_catalog` がない。
- `test_keirin_note_browser.NoteBrowserTests.setUpClass`：このローカル環境にPlaywright Chromiumが未導入。
- `test_keirin_official_owner_view.OfflineOwnerView.test_world_readable_output_folder_and_private_key_are_rejected`：umask0077のため、試験用にmkdir0755したフォルダが実際には0700になり、正常なprivate出力を誤って失敗期待していた。単独でも再現した。**合成の負例だけをchmod0755する修正後、同テストを含む9件が成功**。実際のprivate出力コード、鍵、権限契約は変更していない。

旧pinが必要な検査は元のcheckoutを行う既存CI環境で扱う。mainのモデルpinを入れ替えてこの環境へ合わせたり、これら8エラーを通過扱いにしたりしない。関連追加検査は依存導入済みの既存venvを使うCIステップへ接続した。GitHub CIの合否は実際の最終HEADで別に確認する。

最終ソース `c7831244b231e77ebbbe7f7525c048551268573e` の [GitHub CI 45612583162](https://github.com/haji84/RACE-AI/actions/runs/45612583162) はsuccess。keirin_coreの全ステップが実行され、新規観測アダプターの検査を含むfixture検証が成功した。実データ本番完走の証明とは区別する。
