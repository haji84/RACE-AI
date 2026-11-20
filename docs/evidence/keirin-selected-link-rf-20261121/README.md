# 同一レースの参照パラメーターを検証する限定修正

実取得run44789444126/main12cfでは38/57を維持し、追加の参考予想は0件だった。選択中の同一HTTPS host/path/race_idに唯一 `rf=courselist` が付いた1件を確認した。競走見出し、明示級班、競走名、9車の出走者は一致する。

この既知の参照表記をActiveリンクの比較だけで扱う。未知・重複・空パラメーター、別競走、別path、fragment、曖昧な選択は拒否する。canonical本体の厳密照合は変えず、実在する2件のresults.html矛盾もHOLDを維持する。原本・時刻・入力schema・既存モデル・重み・既定動作・workflowは変えない。

[オフライン実原本再生](offline-real-replay.json)は旧57件の挙動と39カードbyteを維持、新19件は1正常/18HOLD。ネットワークを遮断したcollector再生は1参考出力を作るが、新しい実運転とは数えない。[独立レビュー](review.json)とroot131テストは成功。通常保護merge後、既存運転の生成・暗号化Git読戻しを別に確認する。

既存PR8の元head3d7977d689ac34df117201aa642afab652f49ddaはmainの祖先であり、古いtreeは再適用しない。[元14path/metadata](original-pr8.json)を保存する。並行main243469の公式全国処理等は保全する。実ソース・予想原本・鍵はこの証拠群に含めない。
