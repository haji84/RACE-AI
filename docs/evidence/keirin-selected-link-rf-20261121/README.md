# 選択リンク修正と実運転の証拠（2026-11-21 JST）

既存PR8をmain d44a11257e61d3b539d7d033a93c27e0ea429746へ通常保護mergeした。実在する同一レースのActiveリンクの `rf=courselist` のみを扱い、canonical本体・競走ID・時刻・出走者・grade・既存既定動作は維持した。未知/重複/空パラメーター、別競走/別path/fragment/曖昧選択は拒否する。root131検査と独立69検査・35追加例が成功。PR20checks=8success/12skip、main74checks=10success/64skip、失敗0。[review](review.json)・[PR CI](final-pr-ci.json)・[main CI](final-main-ci.json)・[通常merge](actual-protected-merge.json)。

## 実際の保存と表示

- [PR71実行44794110022](actual-pr71-cycle.json)：45GET、追加参考1件、11/21は39/57、並び17/canonical1保留。二次資料結果129一致/3保留を維持。旧PR71全入力はHOLDでnullを0にしない。
- [追加参考の独立表示読戻し](actual-class-forecast-readback.json)：raw/見出し/PROGRAM出典、A12/B11点、掲載締切前の生成とGit可視性を確認。正式全モデル/学習改善は証明しない。
- [公式全国実行44794841056の取得](actual-official-14659765247.json)：697事前テスト後300GET、全国分母57、A/B原本4/補正3を保管。残り44未対応/9取得待ち。新しく観測したA3・A1/A2・L1の一次資料は、全種目のadmissionには未接続。
- [別ランナーの暗号文確認](actual-official-14658717573.json)：4/補正3。RSA復号とplaintext親結合はこのジョブ単独でfalse、後続の認証済みpublisher/独立した表示検証と区別。
- [公式原本の表示発行](actual-official-publication.json)・[表示鍵による厳密読戻し](actual-official-display-readback.json)：57分母/4原本/補正3、全原本の封緘・Git可視性が掲載締切前。providerGET0の発行。production RSA/state keyをlocal使用しない。
- [当日結果確認](actual-official-settlement.json)：期限到来する適格原本なし、採点0/GET0。過去の固定1レース・4方式比較完了は別資料へ保持。
- [実公開画面390/1440px](final-action-live-browser.json)：全国57行/参考39行、過去75/57件、129一致/3保留、JS例外0・鍵送信0・provider通信0。物理iPhone受入は未確認。
- [Pages14資産の実HTTP](pages-http-live-proof.json)・[発行](current-main-pages-publication.json)・[旧9エントリー/blob保全](original-preservation.json)。f603の原本identityと暗号文を保全。

## 保留する完成項目

[全GOAL監査](actual-goal-audit.json)は未完了を明記。WINTICKET自身403、BOAT取得停止、全4競技・全レース・全既存適用モデル/T15保存と結果、未対応競輪44件・未処理9件、独立6艇識別/校正/強さ接続、物理iPhone13Pro、登録済み11/24終了の前向き改善は未達。参考39件や公式入力4件で代用しない。旧offline2commitは[再fetch記録](offline-original-recheck.json)でもUNRESTORED。

[旧57/新19原本のsocket停止再生](offline-real-replay.json)は実運転と区別する。canonical矛盾を受理へ変えていない。[元PR8 head3d7977と14path/metadata](original-pr8.json)を保全し、旧treeは再適用しない。並行243469までの公式結果・全国・4方式表示と原本は正常mergeで保持した。main保護・固定BOAT S・stop/counter・source/model pins・既存workflowをこの差分では変更しない。新PR・新課金・投票・本番重み切替は0。

このruntime追記は同じ既存PR8のブランチに保存する。mainへの直接push/保護回避や新PRは行わない。source/forecast原本・鍵は含めない。
