# 残枠実装・実データ検証報告（2026-11-07 JST）

**現行30枠のうち実学習は19枠（BOAT14・HORSE5）、残11枠はAUTO6・KEIRIN5。新19候補の実未来PDCAは0件。別の旧14候補では通常1レース・14組の実未来PDCAが成立している。現行全30枠の完成ではない。** 販売者1枠は所有者の変更で現行対象から除外され、学習済みには加算しない。過去31枠の登録情報・原本・MAC・SHAは保持する。

最新の確認対象は `901fb57d2d0f1d0fa0b4051285dca399654a4738`／[run 42371023982](https://github.com/haji84/RACE-AI/actions/runs/42371023982)。2026-11-07 21:39:30 JSTまでにattempt 1／2とも全体SUCCESSを確認した。実第2回AUTO probeは8 GET・全200でも新RESULT 0のHOLD。19枠は実Actions由来の3世代で係数／支持数／holdout／所有者判断を独立照合済みで、最後に原候補3ファイルをGit保持・独立読戻しした世代はc438のままである。コードの全体CI成功を、候補世代の追加保持や実未来PDCA成功へ加算しない。

## 最新の実証チェックポイント

- [901の全体CIと実第2回probe](evidence/2026-11-07/901-full-ci-and-second-bounded-probe-counts.json)：attempt 1は全Python3,714件（360 skip・失敗0、1,427.474秒）、動画283＋185件、UI31件を通過。attempt 2は認証済みの同HEAD初回検証のうち重い2検査を再利用し、軽量検査・実取得・暗号journal読戻し・画面検査を実行して全体SUCCESS。第2回probeの通常結果は0件である。
- [全旧世代を含む日付延長履歴とgridの実Actions読戻し](evidence/2026-11-07/b569-full-history-grid-ci-readback-counts.json)：b569／run42370578793の該当job成功を確認。263か月・掲載7,964日、PARSED7,846／PARTIAL117／公表待ち1日、gridは7,963原本・2,643選手×24場＝63,432セルを復元した。提供元アクセス0。該当job成功をb569全workflow成功とは呼ばない。

- [19枠の実学習](evidence/2026-11-07/nineteen-native-model-fit-counts.json)：152原レコード（BOAT112＋HORSE40）、各枠が共通8実レース・学習6／検証2、後付け派生0。初回ローカル学習SHA `87840763c2ce2656b85b2b09e3c766950bc67db11c9d467f8e7976284fbd7059` は履歴として保持する。既定モデル・既定係数・旧14候補・旧MACを置き換えない。
- [競馬8通常結果の独立認証](evidence/2026-11-07/eight-normal-horse-results-authenticated-counts.json)：実GitHub receipt付きの3 RESULT ZIPを復元し、公式原本を再解析。通常8・特殊2を区別し、特殊結果は通常学習へ加算しない。
- 非BOATの原入力は競馬10・AUTO12・KEIRIN11の計33レース・177 native入力で、締切前保存・独立読戻し済み。入力保存と、結果の確保・実学習・実未来PDCAは別の実績である。

| 実19候補の世代 | 実fit・候補の照合 | 全workflowの確認結果 |
| --- | --- | --- |
| `1a8e0f3b`／[run 42352845874](https://github.com/haji84/RACE-AI/actions/runs/42352845874)／artifact `13565954830` | 19枠の実fit、所有者キーによる復元、ローカルとの係数・支持数・holdout一致を確認 | 後段の合成動画fixtureで失敗。学習成功と全体CI成功を区別する |
| `08b587a2`／[run 42355755138](https://github.com/haji84/RACE-AI/actions/runs/42355755138)／artifact `13567631116` | 同じ19枠の別世代を実fit・復元・照合済み | attempt 1は全体SUCCESS。attempt 2は取得stepへ到達する前にcancelled |
| `c43871ba`／[run 42364217725](https://github.com/haji84/RACE-AI/actions/runs/42364217725)／artifact `13571535349` | 10:34:10 UTCの実保存後、所有者キーで復元し、ローカル19枠との係数・支持数・holdout・所有者MAC結合一致を確認 | attempt 1／2とも全体SUCCESS。attempt 2の実probeは8件・全200だがRESULT 0でHOLD |

最新c438候補のdigestは `sha256:f0bba985e1087f8abab30cb6cc7da7ef331d0be35c0a38836f841aed2d49bcbf`、学習SHAは `f39104dc8486171d0b8c0d56b97ee788feb0561c1e4a27b81c3d061618c594af`。実artifactの期限は2026-11-14 10:34:10 UTCである。Actions保存をGitでの長期保持と同一視しない。

## 保存と取得の状態

- [旧19候補2世代と第2回収集RESULTの保持・独立復元](evidence/2026-11-07/nineteen-candidates-and-epoch2-retention-counts.json)：既存 `state/boat-pdca-transfer` のcommit `3761cda8de08055d6a07f8b9d2a928958ce5877e` へ、不変パスだけを追加した。元候補・元ZIP・元metadataのバイト一致を確認し、既定pointerは更新していない。対象RESULTの追加4件は通常3＋特殊1であり、4通常結果とは数えない。
- 最新c438候補はcommit `9b26d1631aa4b24cd672d1f7bb9234cb6c52ad13` へ追加保持し、原候補3ファイルとのバイト一致と独立Git読戻しを確認した。既定pointer変更0。これは第3世代の候補保持であり、実未来PDCAや新しいRESULTの保持成功ではない。
- [第2回収集run 42349536138](evidence/2026-11-07/actual-second-result-collection-hold-counts.json)は全workflow成功でも、AUTO4・KEIRIN2ケースの実収集は失敗した。既知のJRA GET8件は200、browser実数はUNKNOWN。予約24件、既知8＋予約24の上限32を維持し、0件へ戻さない。実失敗原因は確定できない。
- 旧実装はbrowserの後段検証に失敗すると、返却済みindexと通信件数を暗号journalに残さなかった。同一要求の重複roleでもこの状態を再現できるが、実epochの原因だとは断定しない。新しい診断と厳密な同一応答参照の整理は、失われた旧実数を復元したことにはならない。
- [08bのattempt 1](evidence/2026-11-07/reviewed-head-full-ci-attempt1-counts.json)はcapsule不在で提供元送信0、全体SUCCESS。その後の限定復旧用capsule・消費記録は保持されているが、[attempt 2](evidence/2026-11-07/expired-fixed-probe-zero-dispatch-counts.json)はprovider stepがSKIPPEDのままcancelledとなり、新規提供元送信0だった。「capsuleは現在も未発行」「実probe成功」とは記載しない。

### 実probeと次回の境界

[c438の全CI・実probe証跡](evidence/2026-11-07/c438-full-ci-and-bounded-probe-counts.json)を追加した。attempt 1は全Python3,614件（360 skip、失敗0）、動画283＋185件を含め全体SUCCESS。attempt 2は同じHEADの初回実成功・owner MACを認証して重い2検証だけを再利用し、軽量検査・通常UI取得・実artifact読戻し・画面検査を実行して全体SUCCESSとなった。

実probeは8リクエスト・全HTTP 200・拒否0、対象は `HOLD_UI_OR_SOURCE_UNAVAILABLE`、stopは `REQUEST_LIMIT`。新RESULTは0件。document 1件＋未キャッシュCSS 3件＋背景XHR 4件で対象操作前に上限へ達したことを、暗号化された完全原本から確認した。18ファイル・930,772 bytesを暗号journalに保存し、実artifact `13572350517` を所有者キーで認証した。[元ZIP・元metadata・暗号文のGit保持と独立復元](evidence/2026-11-07/c438-probe-journal-retention-counts.json)はcommit `a8da20a384baad9b789a3cdc1ef33b5248d103bc`。

元の署名plan・最大8・ルート・native・checkpointsを変えず、認証済み過去journalの静的原本をruntime cacheへ再利用する修正を実装し、関連87件と実CJS fixtureで上限8維持を確認した。12:09:07 UTCはc438終了後の第2回用境界として保持する。その第2回は901の固定attempt 2で実行済みであり、現在の次回境界と区別する。

901の実第2回AUTO probeは8 GET・全HTTP 200、document 1件＋背景通信7件で `REQUEST_LIMIT`、対象は `HOLD_UI_OR_SOURCE_UNAVAILABLE`、新RESULT 0件。CSS 3件は認証済みcacheから再利用されたが、結果取得成功には至らなかった。POSTの `NORMAL_READ_IDENTITY` 拒否記録は2件あり、拒否されたendpointはjournalへ保持されていないため経路や失敗原因を推測しない。[認証件数](evidence/2026-11-07/901-probe-journal-authenticated-counts.json)。

実journal artifact `13574582081` のdigestは `sha256:72d1b53eec547a73cff15955e6b7f179f1391283c28d218ca48be95e36e35c79`。元ZIP・元metadata・暗号文は既存refのcommit `710b7437740ae38c05c68fb3a26cb00f4e54a374` へ追加し、元バイト一致と独立Git読戻しを確認した。[保持証跡](evidence/2026-11-07/901-probe-journal-retention-counts.json)。旧browser実数UNKNOWN／予約24・旧固定epoch上限32は変更せず、既知の新8件は別epochへ保持する。

[次の同一1ケースrequest](evidence/2026-11-07/third-auto-probe-preparation-counts.json)は上記journalを追加した未発行の準備で、最大8とlive planを保持する。901 attempt 2のterminal `12:39:30 UTC`＋1秒＋1時間による最早時刻は `13:39:31 UTC`（22:39:31 JST）。新しい同一HEADの初回全体CI成功・新たな固定attempt 2の認証・全prior終了・実時計・独立復元を再確認してからだけ送信する。準備を新しいcapsule発行や提供元送信へ加算しない。

### 会場別履歴の追加実データ

11月6日の公表待ちだけを1 GETで追加し、旧7,962原本の再取得は0。[新しい集計](evidence/2026-11-07/nov6-all-racer-venue-grid-counts.json)は2005-01-01〜2026-11-06の7,963原本、1,167,294レース・7,003,764出走行、2,643選手×24場＝63,432プロフィール、実観測58,830組である。[原本群](evidence/2026-11-07/nov6-official-history-retention-counts.json)と[会場別grid](evidence/2026-11-07/nov6-all-racer-grid-retention-counts.json)は既存refのcommit `505800f55176867e8a5a06491fcc18eadca8e070` から独立復元した。既存ファイルの変更・削除0。

catalogはPARSED 7,846＋PARTIAL_SOURCE 117。gridの完全観測日は7,845、未掲載17日・未報告156会場日が残り、完全な全期間とは報告しない。未観測選手・会場の組み合わせも架空の0成績へ置換しない。新しい2つの `*-nov6-research-input.json` と日付延長の `boat-venue-history-dated-research-input.json` で研究用途へ明示参照できる。過去の学習MAC・再現用の既定pointerと、既定モデルは保持する。今回追加した履歴が、既存152原入力の過去特徴量へ遡って入ったとは扱わない。

日付延長V2のCLI・親原本／目録証拠／暗号化受渡しを実装した。実11月7日のmenu/index 2 GET後、既存V1の全原本検証記録 `full_archive_validation` を継承する構造検証で停止した。この不具合を直し、保存済み目録の再GET 0で新日原本1 GETを実行した。原本は公表待ちのままで解析成績へ加算しない。計3 GET・旧原本再GET 0。暗号化目録・親原本・新世代の8ファイルを既存commit `244a7312f1ad32ecf471e35be1c4247e46c5b8ef` から独立復元した。当初の新8ファイルの独立復元に続き、b569／run42370578793では全旧世代を含む263か月の履歴と11月6日gridの実Actions読戻しも成功した。[全原本群とgridの読戻し件数](evidence/2026-11-07/b569-full-history-grid-ci-readback-counts.json)。公表待ち1日・PARTIAL117日は残り、全期間完全取得や実未来採点とは扱わない。[実差分取得](evidence/2026-11-07/nov7-dated-history-delta-counts.json)・[保持証拠](evidence/2026-11-07/nov7-dated-history-retention-counts.json)。

## 後続の接続実装と検証

[未来baseline・日曜締切・一度限りの復旧手順](NATIVE_FUTURE_BASELINE_AND_REVIEWED_RECOVERY_20261107.md)を実装した。未来比較V4は実19候補、JRA凍結V3とsource packet V2は過去に独立保存されたgenuine baselineと別のBOATキャリアを明示する。原文を元のas-ofで再変換した全native入力、元の所有者判断、各sourceの実開始・完了時計、実artifact読戻しを照合する。

初回19枠runの全Python3,456件（skip310）は成功したが、全workflowは後段動画fixtureで失敗した。その後のfixture修正は6 packet／6復号画像／相異なる6画像・PTS 2.0を固定し、固定依存の動画461件で成功した。さらに08bのattempt 1で全体CI成功を確認した。c438は別に全体SUCCESSを確認したが、実probeは上記HOLDであり、新しい実未来成功へ加算しない。30枠E2Eは合成検証であり、実30枠学習ではない。

19枠向けcash PDCA CLI／既存workflow接続を実装し、BOAT legacy原本＋JRA公式原文→19組採点→暗号化→実形式artifact独立復元の合成E2E（151.743秒）と近傍52件が成功した。V4／19だけを許可し、金額評価禁止のV3／30はHOLDを維持する。全30枠には原ラベルを保持する順位目的だけのCLI・既存Actions接続を実装し、合成30枠の原本→順位評価→暗号化30分割→実形式ZIP読戻しを含む結合35件＋追加1件が成功した。実30枠の未来採点は未実施。その合成検証結果を、実未来結果による採点成功へ加算しない。新19候補の実未来PDCA 0件という状態は変わらない。

## 指定12項目

| 項目 | 実証内容と限界 |
| --- | --- |
| 1. 調査したAPI・経路 | 艇愛の仕様・利用条件・実取得は[既存調査](TEIAI_HISTORY_INTEGRATION.md)を継承し、今回の追加艇愛APIアクセスは0。BOAT公式Kは11月6日の原本1 GET、11月7日のmenu/index 2 GETを別記録へ保存。JRAは凍結カードに実際に公開された結果GETリンク、AUTO・KEIRINは既存の公式通常UI経路を使用する。APIの存在から学習・再配布許諾を推定しない |
| 2. 実取得できたもの | BOAT112原入力、非BOAT33レース・177原入力と実時計・締切前receipt。HORSE公式結果は通常8・特殊2。19枠の実学習に用いたのはBOAT112＋HORSE40＝152原レコード。未提供値は欠測のまま。会場別履歴は上記11月6日までの追加実データを別に保持 |
| 3. 未取得項目 | 残11枠の学習に必要なAUTO／KEIRIN各8通常結果、十分な実未来標本、全期間の欠測・訂正・公表時刻の完全な履歴は未実証。除外済み販売者の定義不足を、現行30枠の残件へ加算しない |
| 4. 正確性と件数 | 艇愛対公式Kの既存照合は2レース・延べ8行／独立7出走に限定。HORSE公式10結果は凍結入力の名簿・日付・場・Rへ照合し、通常8・特殊2。旧14候補の未来通常1レース・6登録選手・14組は、新19候補の未来0件と区別する。全体精度100%や14独立レースとは報告しない |
| 5. 接続特徴量 | 既存nativeの実提供特徴量・母数・欠測・lineageを使い、支持された既存座標だけを学習した。19枠の実fitと各世代の係数・支持数・holdout一致を確認。HORSE5共通8件・6/2は実intakeの独立検証によるもので、フラグだけで保証しない |
| 6. ファイル一覧 | [接続作業の変更一覧](evidence/2026-11-07/remaining-native-model-changed-files.json)。PR71には並行するUI・動画の変更も含まれる。原本・旧MAC・古いmanifestを保持する |
| 7. テスト | 旧runの合格・失敗証跡は各HEADの履歴として保持。初回19枠runはfit成功／動画fixtureによる全体失敗、08b attempt 1は全体SUCCESS、同attempt 2は取得前cancelled。c438初回・再実行は全体SUCCESS、全Python3,614件（360 skip）、動画283＋185件。ただし実probeはRESULT 0でHOLD。901はattempt 1／2とも全体SUCCESS、全Python3,714件（360 skip・失敗0）、動画283＋185件、UI31件。実第2回probeもRESULT 0でHOLD。合成30枠E2EやCI成功を実30学習・実未来成功とは数えない |
| 8. Actions URL | [旧14実fit 42334526055](https://github.com/haji84/RACE-AI/actions/runs/42334526055)、[元未来保存42336097863](https://github.com/haji84/RACE-AI/actions/runs/42336097863)、[初回19候補42352845874](https://github.com/haji84/RACE-AI/actions/runs/42352845874)、[08b全体検証42355755138](https://github.com/haji84/RACE-AI/actions/runs/42355755138)、[c438の初回・限定再実行42364217725](https://github.com/haji84/RACE-AI/actions/runs/42364217725)、[b569全履歴読戻し42370578793](https://github.com/haji84/RACE-AI/actions/runs/42370578793)、[901の初回・第2回probe42371023982](https://github.com/haji84/RACE-AI/actions/runs/42371023982)。attemptとjobごとの結果を区別する |
| 9. HEAD SHA | 直近全体成功HEADは `901fb57d2d0f1d0fa0b4051285dca399654a4738`。最後にGit保持・独立復元した実19候補世代はc438で、その学習SHAは `f39104dc8486171d0b8c0d56b97ee788feb0561c1e4a27b81c3d061618c594af`。旧2世代の保持commitは `3761cda8de08055d6a07f8b9d2a928958ce5877e`、第3世代は `9b26d1631aa4b24cd672d1f7bb9234cb6c52ad13`。旧HEAD・初回ローカルSHA・各世代SHAは対応する証跡に保持する |
| 10. 実動作範囲 | 旧14候補は実6/2学習→締切前の基準／学習版独立保存→通常1レースの登録照合→14組PDCA→28暗号化partition別復元まで成立。実19候補はActions3世代でfit・復元・照合し、全3世代の原候補ファイルをGit保持・独立読戻し済み。新19候補の実未来PDCAは0件で、本番運用成功ではない |
| 11. 未完成と原因 | 現行残11枠はAUTO6・KEIRIN5。旧browser件数UNKNOWN／予約24を保持し、無条件の再取得を停止する。新19候補の未来入力・独立保存・公式結果・PDCAと、十分な前向き標本が未実証。901の全体CIとCSS再利用は実検証済みだが、第2回probeも8 GET・RESULT 0のHOLD。全履歴・grid読戻し成功を、残11枠の結果確保・学習成功へ加算しない。所有者キー復元は確認済みであり、キー不足を原因としない。販売者は現行対象外 |
| 12. 次の最小工程 | 次回requestは未発行の準備であり、13:39:31 UTC以降かつ新HEAD初回全体CI成功・固定attempt 2の認証後だけ許可する。POST拒否の未保存endpointを推測しない。新19候補は新しい締切前入力にgenuine baselineを結び、独立保存→公式結果→PDCAを検証する。AUTO／KEIRINは旧journalを維持し、明示された限定復旧の実記録に従う。各競技8通常結果が揃った後に、30枠×8＝240原レコード・32独立レースの実6/2fitへ進める。新schedule・上限reset・欠測補完・販売者の再追加は行わない |

## 実証へのリンク

- [19枠の実fitと原レコード数](evidence/2026-11-07/nineteen-native-model-fit-counts.json)
- [初回19枠の実CI候補照合](evidence/2026-11-07/nineteen-native-model-ci-parity-counts.json)
- [旧2世代と第2回収集RESULTの保持・独立復元](evidence/2026-11-07/nineteen-candidates-and-epoch2-retention-counts.json)
- [08b attempt 1全体成功](evidence/2026-11-07/reviewed-head-full-ci-attempt1-counts.json)
- [08b attempt 2の取得前停止・新規送信0](evidence/2026-11-07/expired-fixed-probe-zero-dispatch-counts.json)
- [非BOAT予備7レースの実保存](evidence/2026-11-07/seven-reserve-native-counts.json)
- [旧14候補の通常1レースPDCA](evidence/2026-11-07/fourteen-native-model-future-pdca-counts.json)
- [旧14候補のPDCA・次回検討15件の保持](evidence/2026-11-07/fourteen-native-model-future-pdca-retention-counts.json)

これらは各段階の不変スナップショット。後続の保持・Checks・probe結果は別の証跡へ追加し、元の評価SHAを変更しない。c438の不変証跡に加えて、901の全体CI・実第2回probe・journal保持と、b569の全履歴／grid読戻し証跡を追補した。

## 先行段階の原本保持（履歴）

巡回42342290428は4巡・146/240 GET、lifetime8940 GET／521巡、`BOUNDED_SESSION_END`、source_wait=nullで正常終了した。[当該runのcontrol・continuity照合](evidence/2026-11-07/same-cap-four-round-source-counts.json)。これを別のrunの現在カウンターへ転用しない。その後、[元ZIP／元metadata5件](evidence/2026-11-07/five-original-archives-retention-counts.json)、旧14候補の通常PDCA14件＋次回検討1件、[競馬の追加4通常結果](evidence/2026-11-07/four-new-horse-results-retention-counts.json)を既存refへ保持し、別GitオブジェクトDBで元バイト一致を確認した。

現在残る実学習は11枠である。旧段階の「残17枠」は履歴値としてのみ扱い、新19候補・現行全30枠の実未来評価と十分な標本は引き続き未完了。原本保持、候補世代の追加、モデル除外を、別枠の学習成功や将来性能へ加算しない。


## 復元の実CIと中断時の修正（11月7日21:00 JST）

29eca042／run42369144075は履歴のGit全祖先fetchが180秒上限となって復元job失敗。未発行capsuleのまま後続をcancelし、providerstepはSKIPPED・提供元アクセス0だった。[停止証跡](evidence/2026-11-07/29eca-cancelled-before-provider-counts.json)。履歴・gridの読取りだけを既存VaultGitRepositoryのshallow metadata／必要blob取得へ接続し、writerと保存形式は保持した。[実GitHubの固定manifest読取](evidence/2026-11-07/bounded-history-git-readback-transport-counts.json)は0.893秒・Git object891,789 bytes・鍵読取0・提供元アクセス0で一致。この固定manifest検査だけでは全原本群の復元完了とは呼ばない。その後b569の該当jobで全履歴／grid復元を確認し、901ではattempt 1／2の全体CI成功も確認した。

独立reviewで、目録の暗号保存からV2 progress保存までの中断が同じ目録を再取得することも合成で再現した。未commitの既存要求は取得前HOLDとし、保存済み証拠を維持する。完成済みV2と認証済みHTTP待機の既存再開は維持する。新3再現テストをRED→GREEN、履歴・grid・暗号Git境界70件が成功。判定不能な中断を空の新規収集として再試行しない。


## 1レース限定16通信の再検証準備（11月07日22:43 JST）

最新の実取得実績は901／run42371023982の8 GET・RESULT 0／HOLDのまま。保存済み実JSを使った外部通信0のproduction再現で、1R操作直後に結果へ切り替えると非同期renderがProgram／OtherRaceInfoを飛ばす原因を確認した。通常のProgram画面→1R→同じ日・場・RのOtherRaceInfo本文完了→結果の順へ修正した。送信済み応答が通信上限到達後も12秒／85秒の既存時間内に保存を完了し、最終indexの後に予約・原本書込みが走らないことも再現検証した。

[外部通信0の検証](evidence/2026-11-07/auto-ui-race-transition-and-drain-offline-counts.json)は、結果本文だけを明示した合成fixtureとし、15通信分の全応答・原本保存・返却後不変を確認。関連Node35件、既存Python106件、新授権の新旧Python98件と独立レビューが成功した。実RESULT取得、実30枠学習、実未来PDCAへ加算しない。

提供元の公表制限と混同せず、旧8通信契約は維持したまま、元の最大32の範囲内で新V4／最大16・同じAUTO 1レースだけの別授権を実装した。通常日／過去日の実取得日、600秒〜1時間の期限、JST日付越え停止、同HEAD初回全体成功→固定attempt2、全prior原本・実metadata・既知結果、拒否時停止と1時間待機を検証する。旧UNKNOWN24／固定旧epoch上限32、既知の後続8＋8を別々に保持する。

[新requestの準備証跡](evidence/2026-11-07/fixed-sixteen-probe-preparation-counts.json)：request SHA `c89917e055a448b14adba9a26b4f538385b6fbb92c6e1c4665082312be907285`、plan SHA `fe3b07ab24adcedb35a69add742cf34a3bd19699f9fb3e559ed06a3fb5cf0c2c`。4 native／3 checkpoints／4 prior journal、同じ1ケース・URL・利用条件・静的原本を保持。未発行の旧8枠準備905fは履歴へ残し、新暗号planだけを追加。これは取得授権の発行ではなく、新HEADの全体CI待ちである。既存の消費済みcapsuleを更新・再利用しない。

実学習19／30・残AUTO6／KEIRIN5、新19／全30の実未来PDCA 0は変わらない。本番モデル・旧MAC・既定学習pointer・既存の原本は保持する。


## 973の実原本と補助CSV 404（2026-11-07 23:44 JST）

973／run42378920749は初回・限定再実行とも全体SUCCESS。実16通信は15件HTTP200＋補助refund CSV 1件404で、16上限停止ではなくFINISHED。実OtherRaceInfo(11)・RaceResult(14)・通常UIの実DOMはCAPTUREDだったが、Pythonが全responseに200を要求しSOURCE_VALIDATIONでREJECTEDとなった。旧journal/state/countは変更しない。

完全な元原本から必要HTTP・元request・元DOMだけを既存result adapterへ渡し、独立認証済み締切前nativeと登録8選手を照合した。実1レースはrank_confirmed（100円払戻単位は未証明、金額評価不可）。[原本再利用の準備証跡](evidence/2026-11-07/973-actual-result-source-reuse-preparation-counts.json)。合成本文0・新提供元通信0。既存official-results-freeze経路で新しい正式RESULTの暗号保存・独立読戻しを実行する。原本の取得時刻を新しい時刻へ置換せず、新producerの保存証拠と区別する。新RESULT artifact成功前に確定学習原本へ加算しない。


## 実AUTO結果1件の保存完了・次の別ケース（11月8日00:12 JST）

[実run42383095124](https://github.com/haji84/RACE-AI/actions/runs/42383095124)の既存official-results-freezeで、元HTTP・request・実DOMを再取得0で再検証し、RESULT artifact13578691832（digest `sha256:0be88d04dab4ab775b0d394cd4a7854a7b83805e6e3f59528675c9ddf43cdb64`）を14:49:05 UTCに独立保存した。親もfresh API metadata／AES／原native177入力／元source closureを独立再検証し、通常順位1件・登録8人一致。払戻単位未証明のrank_confirmedで、金額評価不可。元source取得14:26:39.308 UTCと新producer保存14:49:05を区別する。[実認証件数](evidence/2026-11-07/973-reused-real-auto-result-authenticated-counts.json)。これは新30学習・新未来予想ではない。実学習19/30のまま、AUTOは必要8通常のうち1、KEIRINは0。

元973 journalの完全ZIP・actual metadataも暗号化してGit `5d8a1e914c2f8e08dd9f403762ba49e1616af074` へ保持、別objectDBで同一bytesを復元した。[保持証跡](evidence/2026-11-07/973-probe-journal-retention-counts.json)。元REJECTED状態、16通信、15×200＋404、旧UNKNOWN24/固定旧epoch32は変更していない。

Python readerは全raw／metadata／台帳／時計／SHA照合を維持し、必須role200を必須としたまま、未参照で同レースのrefund CSV404だけを隔離保持して扱う修正を追加。完備したSOURCE_VALIDATION拒否原本は通信会計だけに再検証できる。データ／cache許可と正常probeは従来どおりCOMPLETEのみ。実DOMの入れ子パスも安全なrelative pathとして復元する。3修正の116テストと独立レビューCLEAR。

1件目の再取得を避け、元から指定されていたAUTO第2ケースを別16枠probeへ準備した。[次の準備](evidence/2026-11-07/historical-auto-case-two-preparation-counts.json)：実取得日2026-11-08 JST／元レース日2026-11-07を区別し、旧4 native・全5 prior・4 checkpoints・原URL／条件／静的原本を保持する。前run terminal14:29:52＋1秒＋1時間の15:29:53 UTC以降、かつ新HEAD初回全体成功・別の固定attempt2を確認後だけ取得する。全5実journalを再認証済み。まだ新capsule未発行／新提供元通信0。
# 2026-11-08 JST 追記：取得再開前のCI失敗を保持

オートの実通常結果1件は、既存の973原本から必要なレスポンスと実DOMを再利用し、別の公式結果artifactへ暗号化保存した。run `42383095124` は全体SUCCESS（HEAD `11d070dd1984e50d8d5bd6fcca738865cdc93b19`）。その実結果は締切前の出走原本8人と照合済みで、金額評価は許可しない。元の973収集journalのREJECTED状態・404原文・全通信履歴は変更していない。

次の別レースを対象とするc06の初回全CIは、Python 3,911件（401 skip）で3つのassertionが失敗した。可変の収集manifestへ追加された新しいpinを、bootstrapテストが固定seedと誤って扱っていた。固定11 pinの独立fixtureへ分離し、累積pin追加と必須pin改変を区別する回帰テストで検証する。成功した初回CIを必要とする取得ゲートは停止し、このHEAD向けの新しい取得権限発行・提供元アクセスは0。[実CI失敗と停止件数](evidence/2026-11-07/c06-first-ci-blocked-before-source-counts.json)。修正後の別HEADで全体検証をやり直し、成功を確認するまで取得を再開しない。

実学習は19/30枠、AUTO通常結果1件、KEIRIN通常結果0件、新しい30枠の実未来PDCAは0件のまま。追加の接続コード・合成テストと、実データ学習・実未来採点は別に記録する。以下の以前の経緯・失敗・SHAは保全する。

今回の将来入力接続には、既存の公式通常UIからAUTO／KEIRINの出走表だけを取得する経路、JRAの新しい公開ページ・そこに明記された出走表リンク・既存ルール資料の取得経路、11月6日BOAT会場別gridを取得前に明示指定する経路を追加した。既存freeze・native入力契約・baseline照合・暗号化保管・実artifact読み戻しを再利用する。既存workflow内の専用jobは、所有者／PR71／attempt 1／必須5job成功／明示prefixとinputを要求する。新しいworkflow・定期実行・外部サービスは追加していない。

将来取得は競技ごとの固定した一度限りの消費markerを通信前に保存する。同じ実験で日付・HEAD・baselineを変えて再発行できない。既知の拒否は取得停止、不明な通信件数は不明のまま上限付きで保持し、元UNKNOWNの会計を置換しない。実際の取得開始・応答・固定as-of・モデル作成時刻・baseline保存証拠を照合し、最後の保存確認から締切まで600秒を確保する。これらの新規経路で実際の未来入力取得・marker発行・30枠採点が成功したとはまだ主張しない。

11月8日JSTの11月7日原本再確認では、保存済み目録を再利用し、対象原本だけ1 HTTP GETを実行した。HTTP 200後、私有の追加operator記録処理がISO時刻文字列へ`isoformat()`を呼ぶ誤りで停止し、応答本文をcatalog・checkpointへ保存できなかった。原文SHA・応答完了時刻は不明で補完しない。元counterと空のattempt11を残し、既存世代10・公表待ち1日・11月6日gridを維持する。再確認を新しい解析成功へ加算せず、同じcounterの削除・reset・自動再実行は行わない。[実失敗と通信会計](evidence/2026-11-07/nov7-dated-recheck-operator-failure-counts.json)。復旧は失敗記録を保全した独立レビュー済みの明示手順で行う。

## 11月7日原本の明示復旧と次のCI修正

独立レビュー済みの実行コードSHA `d7292104adf3098b43391b8ef0d08b945bcfa13190d8b571f590ff4b459e6abf` を使用し、元の失敗・counter・空attempt11を残して、別のattempt12／generation11を作成した。新しい対象原本1 GETは16:34:51.967094Zに保存され、11月の目録7日が解析済み・pending0となった。失われた前の200応答の原文・SHA・完了時計は復元したことにしない。

全会場gridは2005-01-01〜2026-11-07の7,964原本、1,167,426レース・7,004,556出走行・2,643選手×24場＝63,432組を再構築し、暗号化全件読戻しに成功。旧7,962原本は認証済み型付きcacheを再利用し、11月6・7日の2原本だけを解析した。旧grid全ファイルは不変、未掲載17日・未報告156会場日を保持。新gridのGit保持・独立Actions読戻しと未来入力への最新世代接続は別工程で進めている。[実grid件数](evidence/2026-11-07/nov7-actual-grid-build-counts.json)。

02dの初回CIは4,030件（429 skip）で2 errors・1 failureとなり、次のAUTO取得はcap0／通信0で停止した。2件はfixtureの0644権限、1件は暗号末尾が偶然xの場合に改変されないテストが原因。fixtureを明示0600にし、改変をXORで必ず異なる値へ変更した。実環境のumask022で関連45件PASS。保護処理は変更せず、全CIを新HEADで再検証する。今後の全suiteは最初の失敗で終了し、成功時は全件を実行する。[実CI失敗と修正](evidence/2026-11-07/02d-first-ci-blocked-before-source-counts.json)。

## 11月7日までの原本・gridを暗号Gitへ保持

新history `9e611681e582e3760a91150264d3d7a0894a1c080a2e2b48a49344973c353ac0` と新grid `7ea4281b5674e605918536ecf905d726d78c721aa0f6c6ed60d4c51d250d5678` は既存transfer refのcommit `bd932a4d91317c5d8349989a96ddb184938c539d` へ追加保存した。78ファイルすべての実追加A差分・旧244a／5058祖先の保持・独立readerでの原byte一致を確認し、263か月の元世代を再利用した通常の新月復元と、全63,432組・7,964原本のgrid復元に成功。元の保存失敗1 GET、別の成功1 GET、実行済みd729コード・ACK・counter・原文を外側のowner暗号archiveへ保持し、未保存だった原文を再現したとは扱わない。

新しいresearch pointerだけを更新・追加し、canonical履歴・dataset・learningおよび旧Nov6参照は不変。既存Actionsの読戻しstepはNov7参照を優先する。新しい実Actionsの結果はまだ未確認なので、未来入力の新世代witnessは未許可のまま。実jobの全復号・原本照合・grid読戻し完了後に、その正確なmetadata／logを別のliteral witnessとして登録する。[実保持・独立復元](evidence/2026-11-07/nov7-actual-history-grid-retention-counts.json)。

## 新しい未来入力と公式結果の回収経路

未来結果専用の取得・暗号化・原文保持・実artifact読戻しを、既存のfuture jobに追加した。元の30枠予想・origin・native原本を認証し、実際に締切前へ保存された対象だけを取得する。過去のNov7授権を別レースへ使わず、別purposeの一度限りmarkerと32通信を使う。AUTO／KEIRINの通常UIとHORSEの実際に掲載された結果リンクを用い、旧UNKNOWN32、全履歴・既知拒否停止、元時計・source／label結合を保持する。実30暗号化fixture込みの結合45件・job契約35件をumask022でも確認。これは合成検証であり、実未来予想・RESULT・新30枠PDCAはまだ0。

新Nov7 data witnessはrun42395208517／job128471073052の実SUCCESS（17:18:24Z）と正確なmetadata／ログhashへ固定した。旧Nov6 witnessも維持する。入力アダプター27件が成功し、過去の元as-ofより後のdataset・検証時刻・serverjob完了を使う入力は拒否する。ここでのログhashは実MCPのUTF8/BOM付き応答から得た値で、実Actionsの生byte同値は未確認のため、提供元へアクセスしない専用history-witness-check prefixで先に確認する。不一致はHOLDとし、別hashや最新値へ自動切替しない。

553の初回検証はPython4,058件（詳細skip数は実ログ）と動画283＋283件が成功したが、最終ブラウザー検証で閉じた詳細欄の旧表示assertionが失敗し、全体はFAIL／次のAUTO cap0・通信0のまま。所有者の折りたたみ表示を保ち、通常の詳細開閉を使うテストへ更新し、全ブラウザー経路をローカル再検証している。新たなcollector HEADの初回全体成功前に取得を再開しない。

## 現行の研究ページを含む全ブラウザー検証

並行所有者の現行UI版 `ed676742448d9068c12e8cb39b6b87923b0888fc` を保持し、テストだけを更新した。4幅（320／390／1440／1920）の全39チェック、生成・自動・継続更新、残る9 browser scriptがすべて成功。閉じた詳細欄の文字列を表示済みと見なさず、通常の研究ページ遷移から原本SHA・全文JSON・元race／model・正確な時刻を検査して元の表示へ戻る。既存製品UI、モデル、予想原本は変更していない。次の取得用HEADで全CIを実行し、成功前のcap発行・実AUTO取得は引き続き0。[失敗と修正の件数](evidence/2026-11-07/553-ui-contract-failure-and-correction-counts.json)。
