# 2026-11-22 JST：既存Aの学習版と、固定した33件の前向き比較

**11/22の所有者判断**：「WINticketにこだわらなくてもいいよ」。WINTICKETの403解除を開発・精度評価・製品完成の必須条件から外し、既に承認済みのKdreams/netkeirinを中心に続ける。WINTICKETの拒否履歴は保全する。この判断はBOATの別の取得停止や登録済み比較条件を変えない。

**精度改善は未実証。** 既存競輪Aの係数だけを学習し、原本を保持した比較用候補を実装した。選定に使った55件のHit@8は元モデル20/55・学習版20/55で変わらない。11/22の過去分15件は元7/15・学習版6/15だった。係数を凍結した33件の締切前予想はGitHubへ暗号化保存済みで、**15:19 JSTに19件を実照合し、元6/19・学習版6/19、残り14件待ち**。12:24の0確定/33待ちから結果だけを更新し、予想・係数・固定分母は変えていない。未確定を損失や0%にしない。

## 実装と入力の範囲

- 既存 `marks-ordinal-plus-observed-rider-strength-v1` の印・競走得点・近況・H/Bの4係数と同一ライン加点だけを学習した。着順係数、入力変換、元A/B生成器、元予想、採点、登録model familyは維持する。本番既定値へ接続していない。
- 既存4競技学習器の `fit_chronological()` は、締切だけで区切るとvalidation/testへ境界以前の入力が入る不具合があった。各期間の `as_of` 下限を追加し、未来の情報が評価へ混ざる経路を拒否した。
- 暗号文53パケットと145観測を検証。Python3.11/3.12で実際の元A/Bを完全再生し、両者の和集合145件を確認した。3.12のfloat合算差を誤差許容で通していない。公開されるハッシュは内容・結合の照合用で、発行元署名ではない。
- 学習は11/20の30レース、選定は11/21の55レース。保存時刻が最初のvalidation入力に間に合わない学習ラベル1件は、元31件の記録を保持したまま学習から除外した。アーカイブ取り込み予想、欠落、保留、結果の後に取得した入力は学習分母へ入れない。
- 正解は既存Kdreams/netkeirin二次資料の一致であり、公式settlementではない。過去11件で公式保存観測との一致を別確認したが、全レースの公式認証へ一般化しない。

## 固定した選定と測定

学習側の順位損失を、非負・合計1の4係数と0〜0.25のライン加点に制約して最適化した。正則化0/0.1/1の固定候補と変更しないbaselineを、同じ8点のvalidation Hit@8、同率時の正解順位、baselineからの距離の順に選ぶ。最終日ラベルを引数に取らない。

| 対象 | 比較可能件数 | 元A Hit@8 | 学習版 Hit@8 | 解釈 |
| --- | ---: | ---: | ---: | --- |
| 11/21 選定用 | 55 | 20/55 (36.36%) | 20/55 (36.36%) | 的中増加なし。正解平均順位58.709→55.145は選定用の順位指標 |
| 11/22 既に締切を過ぎた別日入力 | 15、別に1保留 | 7/15 (46.67%) | 6/15 (40.00%) | 生成時点がレース後の遡及評価。凍結後に初めてラベルを読んだが前向き実績ではない |
| 11/22 実際に締切前保存した固定33件 | 19確定・14待ち | 6/19 (31.58%) | 6/19 (31.58%) | 15:19 JST時点。固定分母33を保持し、未確定を不的中と数えない |

候補選定後の係数・対象レースは変更していない。33件中27件は8点集合、11件は1位候補が元Aから変わる。変化した件数は的中増加の証拠ではない。確率校正、Brier/loglossの改善、有意な改善、本番昇格はいずれも未証明。

## 締切前保存と再検証

- 候補作成：11/22 **11:47:46 JST**。生成コードは `ea63ea27743a5e782d7872838cc22298c485b503`、候補SHAは `476dbf8a216553183c9d9e37c2433562aeaf0ec14c6f2c656cf913392fef3233`。
- 保存commit：[`68ca11f366fa3a7500f00afacfe4ffaa1fdbc7c4`](https://github.com/haji84/RACE-AI/commit/68ca11f366fa3a7500f00afacfe4ffaa1fdbc7c4)。GitHub APIの実cipher読戻し時刻 **11:51:26 JST**。全33件の掲載締切 **12:07〜20:25 JST** より前である。
- 2,860,076 byteの[暗号化パッケージ](candidate-package-55145fa03758396ff978abaf681aeed808e5e1825a4fcf29bf0ac0203c146b6a.json)に学習/選定原本、係数、予想、lockを保管。既存表示受取人のP-256/HKDF/AES-GCMを使い、実Git本文、cipher SHA、復号認証、各file SHAを独立読戻しした。本番state key/RSA秘密鍵は取得・使用していない。
- 全33件の固定manifest SHAは `c5e612e7ac3c934888e5c057b0996a6e3c1a58941bab1fa56ac21fd2e695b1dd`。元の入力50件中16件は既に締切後、1件は封緘猶予不足で除外した。結果を見て対象を減らせない。
- GitHub Dateとローカル観測は独立した署名付き時刻証人ではない。掲載締切も主催者の実発売終了の認証とは区別する。正式model admission/T15全件実証には使わない。

[候補lock](candidate-lock.json)・[実Git読戻し](candidate-git-readback.json)・[凍結後の変更件数](frozen-change-counts.json)・[別日評価](locked-day22-evaluation.json)・[固定33件の採点](frozen-forward-audit.json)。`learning-before-final-labels.json` の未Git保存stateは初回測定時点の記録として残し、その後の保存を読戻し証拠で示す。

## 結果回収と採点の継続方法

既存mainの[run44979508136](https://github.com/haji84/RACE-AI/actions/runs/44979508136)を1回実行し、正常終了を確認した。二次資料の結果6件の改訂を暗号化保存した。予想取得46GET・結果222GETと、別の旧PR71公式SP処理5,208要求は既存処理の実通信であり、新研究コードの取得0件と混同しない。旧PR71は入力不足のHOLDで、生成数などはnull。WINTICKET要求は0件、403解除の証拠ではない。[安全な実run集計](actual-result-refresh.json)。

結果収集は既存main Actionsを利用する。新しい採点CLI自体はcronへ追加しておらず、以下の読み取り専用手順を用意した。元の固定パッケージを本人の表示鍵でローカル復号し、既存Noteの認証済み改訂列から最新結果を解決してprivate JSONへ出した後、リポジトリrootで実行する。

```sh
python -m scripts.keirin_existing_model_accuracy_audit \
  --artifact /absolute/private/candidate.json \
  --forecasts /absolute/private/future_shadows.json \
  --results /absolute/private/latest_results.json \
  --expected-candidate-sha256 476dbf8a216553183c9d9e37c2433562aeaf0ec14c6f2c656cf913392fef3233 \
  --expected-forecast-sha256 c5e612e7ac3c934888e5c057b0996a6e3c1a58941bab1fa56ac21fd2e695b1dd \
  --git-observed-at 2026-11-22T02:51:26+00:00 \
  --private-root /absolute/private/new-audit-directory
```

入力fileは0600、出力rootは0700とし、既存reportを上書きしない。このCLIは既存PDCAの券検証・採点関数を再利用し、新しい評価権威やモデル系統を作らない。固定候補・全33件のdigest、元Aと学習版の完全再生、同一8点、時計、出走者と結果の結合を検査する。公開するのは集計だけで、未確定/保留は別カウンターとなる。コマンドの時刻証拠は呼出側で検証する必要があり、CLI自身がGitHub時刻を認証するわけではない。

研究用fitterだけはNumPy2.4.6/SciPy1.17.1を使う。今回の実検証は隔離したPython3.11.17環境で実施した。新たな課金・本番dependencyやworkflow graphの変更はない。

### 15:19 JSTの結果更新

既存main8646afの[run44992650227](https://github.com/haji84/RACE-AI/actions/runs/44992650227)はcompleted/success、WINTICKET要求0。新しい参考9件の生成・暗号化保存を確認した。一方、4日分の結果処理は120秒の枠を使い切り、121件を確認しても変更0件で、今回の33件は採点できなかった。[実run集計](approved-sources-main-followup.json)。

そこで変更しない既存 `collect_results(days=[当日], ...)` をローカルで実行した。公開済みの当日開催リンクをたどり、既存 `result_checks` の通常の照合間隔を維持した。68レースを観測し、68GET・31件確認（29二次資料一致/2未掲載）、7件は照合間隔待ち・30件は将来の掲載締切で保留した。拒否0・時間枠超過なし、21観測の改訂を保存した。元の `validate_result_delta` / 暗号化 / CAS保存 / Git読戻しを使用し、全既存entryと原予想を保全した。取得に秘密鍵は使用していない。

当日結果の保存headは `ff9b31b3e91e5a27cd09453657f1338c57f8dce0`。その新しいcipherを既存表示鍵でローカル認証・改訂列検証後、元の固定33件と候補のdigestを要求する採点CLIで再比較した。**19件中、両方的中6・両方不的中13・元だけ的中0・学習版だけ的中0**。14件は待ち、統計的改善の支持はnullである。

この当日確認は新しいcronや予想の再生成ではない。今回追加したのは運用上の結果取得と文書・集計で、取得器/学習器/採点器の製品コードは変更していない。採点の既存10テストを再実行し成功した。以前の742テスト成功と、この追加の10テストを別の検査記録として扱う。

[当日取得と暗号化保存](current-day-result-refresh.json)・[15:19の固定33件実採点](frozen-forward-audit-followup-20261122T0619.json)。学習や評価選定への11/22ラベルの再使用、本番重み切替、登録BOAT比較への合算は行っていない。

## 検査、保全、残件

独立reviewで見つかった学習側5件と採点側2件の重要事項は、失敗する回帰検査を先に確認して修正済み。既存57moduleと追加3moduleの **742テスト成功**、警告をerror扱いとした。host既定umask0077では既存permission fixtureの意図した0755が0700になり、変更前mainでも同じ1件が失敗するため、検査processだけumask0022で実行した。秘密fileの0600/0700と製品guardは不変。[検査](validation.json)・[review](review.json)・[原本と環境](preservation-and-environment.json)。

登録済みBOAT比較は **11/19 12:15:30〜11/24 12:15:30 JST、100組・5日・10会場日** を維持する。最新observer44780867312はHISTORYでHOLD、現在の有効組数はnull。最後の有効11/19 reportの0件を現在値と誤記しない。最新の凍結source run44948138024はcompleted/successでも、controlは403のAUTHORIZATION_WAIT・完了0ラウンドである。今回の33件を登録済みBOATの分母へ足さず、producer操作・停止解除・counter resetを行わない。[現在監査](registered-study-current-audit.json)。

コードと証拠は既存PR8の同じbranchへ保存する。PR8本体は既にmerge済みであり、今回の研究追加はprotected mainへの統合・本番重み切替ではない。元offlineの未push2commitは引き続きUNRESTORED。

**全GOALは未完了。** 11/21時点の公式競輪44未対応/9未処理、他3競技を含む全件×全既存適用モデル/T15、実機iPhone13Pro受入、独立6艇識別・校正、前向き精度改善が残る。WINTICKET自身の403は未解除だが、上記の最新所有者判断により必須の完成条件にはしない。今回の11/22一覧観測68件や参考10件を、11/21公式57件の44/9の解消と数えない。新規UI公開・投票・本番重み切替は行っていない。
