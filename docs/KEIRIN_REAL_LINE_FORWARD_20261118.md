# KEIRIN 実連係履歴と未来同一レース A/B/C 比較（2026-11-18 JST）

## 目的

A = 既存PR71の保存済み従来モデル、B = 6局面/勝ち上がり条件による段階別研究、C = B＋先頭と番手/3番手の実連係履歴。将来の同じrace_id・as_of・公式締切・事前登録母数で3方式を独立保存して評価する。PR #291はDraft維持、保護main・正式モデル重みは変更しない。

## 今回の実資料2レース（「想定ライン」であって実走の追走結果ではない）

| 過去レース | 公開の並び予想 | 先頭→番手の登録番号 |
| --- | --- | --- |
| 2026-11-09 武雄2R | 5-3-6 | 神尾敬冬 015709 → 三ッ井武 014525 |
| 2026-11-10 武雄4R | 7-4-3 | 神尾敬冬 015709 → 三ッ井武 014525 |

照合先： 
- 選手登録番号 https://www.keirin.jp/pc/racerprofile?snum=015709 と https://keirin.jp/pc/racerprofile?snum=014525
- 武雄11/09 https://keirin.tokyo-sports.co.jp/list/race/20261108_30916 と https://keirin.netkeiba.com/race/entry/?race_id=202611098402
- 武雄11/10 https://keirin.kdreams.jp/takeo/racedetail/8420261109020004/?pageType=yoso と https://keirin.tokyo-sports.co.jp/list/race/20261109_32344

2026-11-18に公開資料を確認して手作業転記。サイト公開時点の原本HTML SHA・実映像のSHA・独立確認された実際の追走位置は取得していない。予想ライン・出走と実走連係は別。着順・決まり手だけからHELD/GAPPED/SWITCHEDを作ることは禁止。

## 今回の差分

- docs/evidence/2026-11-18/keirin_takeo_public_planned_pairs_v1.json：2件の実資料に対応する予想ライン、選手登録番号、公開ソース、追走UNKNOWN
- race_ai/keirin_real_line_evidence.py：登録番号/役割/二つ以上の別ホストのソース/重複・将来混入・偽の追走結果を検査するオフライン研究アダプター
- tests/test_keirin_line_cohesion.py：SOURCE日付だけを確認した場合はJST翌日から有効、実ラベル0件を維持、改ざん・同一レース重複・架空成功を拒否する回帰

パケットのハッシュは転記内容のハッシュであって公開元サイトの真正な原本SHAではない。外部ソースの独立アーカイブ検証を通せるまでは自動学習に採用しない。独立ソース検証ができても「並び予想」を追走成功ラベルに格上げしない。

## 未完の本番ゲート

1. 既存の私的保存済み映像を原本SHAつきで再生し、先頭・番手・3番手の車番/登録ID・打鐘/ホーム/バック/4角・追走/離れ/切替を独立ラベル化する。色や着順を正解にしない。
2. 既存line_cohesion.pyの厳格なLABELスキーマに本物のラベルと原本の可用時刻を通し、C研究重みを結果を見ないで凍結する。履歴ゼロは「初連係」「必ず弱い」にはしない。
3. 同じ未来レースのA/B/Cを締切前に別々にAES保存し、別runnerでSHA照合する。事前登録された母数を後から入れ替えない。
4. 公式結果が公開されてから既存keirin_line_three_arm_audit.pyでHit@1、Hit@全点、100円均等条件の仮想ROI、HOLD率を一括比較する。1回的中で性能改善を断定しない。
5. PR #308でmainへ統合した松山7R前段検査とは別に、結果取得→照合→暗号保存→独立読戻し→サイト反映の本番5工程も未完として維持する。

現在の正確な評価：実在2レース分の「並び予想」は記録できた。実映像で認証された追走結果0件、実履歴で補正したCの本番予想0件、未来レースA/B/C正式比較0件。合成CIを本番成功には数えない。


## 2026-11-18 本番ソース再検査と歴史結果の結合（今回の作業）

### 実資料・結果の証拠を追加

- `docs/evidence/2026-11-18/keirin_takeo_public_pair_finishes_v1.json` に、実際の事後結果を公開ソースから転記。11/09 武雄2R 5-3-1（神尾5番1着、三ッ井3番2着・マーク）、11/10 武雄4R 6-2-4（神尾7番6着、三ッ井4番3着）。2つの公開サイトで同じ結果を確認したが、主催者原本の独立認証は未完。
- `race_ai/keirin_real_pair_finish_outcome.py` を実装。前回の「想定ライン」2レースに、今回は「事後の着順」のみを厳格なrace_id/車番で結合する。元のソース確認日時が日付しかなければ、未来予測に採用できるのは翌JST日から。出走前の予想ライン、事後の確定着順、レース中の追走/離れを明示的に分離。
- 結合例は「先頭→番手が1-2着」1件、「別着順」1件。これは実際の途中の追走維持1/2という測定ではない。追走ラベルHELD/GAPPED/SWITCHEDは**0件、全てUNKNOWN**。結果だけを使った自動学習・Cモデルの正式補正は禁止したまま。
- 転記元: [武雄11/09結果](https://www.keirin-mobile.jp/top/result.php?date=20261109&jcode=84&race=02)、[同日別ソース](https://keirinhex.jp/races/20261109/028420261109/)、[武雄11/10結果](https://www.keirin-mobile.jp/top/result.php?date=20261110&jcode=84&race=04)、[同日別ソース](https://www.chariloto.com/keirin/results/84/2026-11-10/)。

### 所有者非公開レビュー資料の実バイト検証

- Library内の武雄2026-11-09 2RのA/B別HTML（各46フレーム）を読み、A側バイトSHA `4bfab49ce7c1beba6840fab40856aaaf9843afdff9077acd2fa723831ccc6469`、B側 `95d6bd402dbce180486952da643584860c76f7ca1669ab459409b39e7ac845eb` が2026-11-15の過去記録と一致した。
- 別々のペイロードであること、同じ46個の宣言されたフレームID順・動画内秒数、各フレームに埋め込まれた表示PNGのバイト内容がA/Bで46/46一致した。
- **元動画のWebMバイト自体は今回再取得・再復号していない。** HTML内のフレームSHA宣言が元の動画と一致することも今回新規証明したわけではない。A/Bは`reviewer_A_pending`/`reviewer_B_pending`、未提出のレビュー材料であり、人間2者による署名済み判定ではない。
- 赤字秘密情報・PNG・座標を保存せず安全な結果を `docs/evidence/2026-11-18/keirin_takeo2r_real_review_packet_readback_redacted.json` に作成。再利用可能な読取専用検証は `scripts/keirin_private_review_pair_readiness.py`。非公開PNGなどをPRに含めない。
- 実際のレビュー独立正解2件・実選手追跡正解・実追走ラベルは依然**0**。これを偽装しない。

### CIとmain本番停止状態

- 研究Draft PR #291の変更を既存`keirin-pr71-owner-autonomous.yml`のsynthetic-ciに登録し、[Run 44128837320](https://github.com/haji84/RACE-AI/actions/runs/44128837320)（HEAD `63814a050fac09b3580d95d4af261f2820b7df84`）でsynthetic-ci **SUCCESS**。新追加の6件のレビュー資料テスト＋8件の結果結合テストを含む研究サブセット95件PASS。これは本番A/B/C予測成功ではない。
- 既存保護mainの[PR71実行44070303901](https://github.com/haji84/RACE-AI/actions/runs/44070303901)ログではstate=`HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT`、`new_pre_race_inputs=0`、`actual_four_model_forecast_saved=false`。Actionsジョブsuccessは本物の4モデル予想成功を表さない。
- mainの[映像独立読戻しRun 44091948744](https://github.com/haji84/RACE-AI/actions/runs/44091948744)は`SOURCE_ARCHIVE_NOT_ATTESTED`。既存のLive本番ソースの証明も別途未合格。
- **現在の正式な未来A/B/C前向き比較件数0**。PRはDraftのまま、main・正式モデル・課金・Secrets・投票には変更なし。

### 次の未完、順序を固定

1. 既存の非公開A/Bレビュー材料から真の実映像ラベルを独立に取得し、選手登録ID/車番・先頭/番手/3番手・仕掛け・HELD/GAPPED/SWITCHEDをフレームと動画SHAに結び付ける。レビューの独立性と出典証明が無ければUNKNOWN。
2. 同一実レースの本物のPR71締切前入力とB/Cの6局面条件を揃え、Cを事前凍結。現時点の公開の「並び予想＋結果」のみではC正式補正をしない。
3. 未来の未使用レースでA/B/C原本を事前登録→AES保存→別runner SHA→公式結果独立取得→`keirin_line_three_arm_audit.py`で同一母数のHit@1/全候補/仮想ROI/HOLD評価。
4. mainでソース拒否・映像保存認証が続くと予想母数0のため、既存ワークフローの回復証拠を優先。エラー回避のための無許可大量アクセスは行わない。
