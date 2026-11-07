# 残枠実装・実データ検証報告（2026-11-07 JST）

**現行30枠のうち実学習は19枠（BOAT14・HORSE5）、残11枠はAUTO6・KEIRIN5。新19候補の実未来PDCAは0件。別の旧14候補では通常1レース・14組の実未来PDCAが成立している。現行全30枠の完成ではない。** 販売者1枠は所有者の変更で現行対象から除外され、学習済みには加算しない。過去31枠の登録情報・原本・MAC・SHAは保持する。

確認情報の最終追記は2026-11-07 20:28 JST。19枠はローカルだけでなく、実Actions由来の3世代で復元・係数／支持数／holdout／所有者判断の結合を確認した。旧2世代に加え、最新c438世代の原候補3ファイルも既存Git refへ保持・独立読戻し済み。同HEADの初回・限定再実行は全体SUCCESS。ただし実probeは取得上限でHOLDとなり、新しい確定結果は0件である。

## 最新の実証チェックポイント

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

元の署名plan・最大8・ルート・native・checkpointsを変えず、認証済み過去journalから静的CSSだけを再利用する修正を実装し、関連87件と実CJS fixtureによる上限8維持を確認した。次の同一1ケースprobe requestは実8件のjournalを追記済み、まだcapsule未発行。前回terminal＋1秒＋1時間による最早時刻は12:09:07 UTC（21:09:07 JST）。新しい同一HEADの全体CI成功・新しい固定attempt 2・実時計・独立復元を再確認してからだけ送信する。旧UNKNOWN／予約24・旧固定epoch上限32は変更せず、新8件は別epochとして保持する。

### 会場別履歴の追加実データ

11月6日の公表待ちだけを1 GETで追加し、旧7,962原本の再取得は0。[新しい集計](evidence/2026-11-07/nov6-all-racer-venue-grid-counts.json)は2005-01-01〜2026-11-06の7,963原本、1,167,294レース・7,003,764出走行、2,643選手×24場＝63,432プロフィール、実観測58,830組である。[原本群](evidence/2026-11-07/nov6-official-history-retention-counts.json)と[会場別grid](evidence/2026-11-07/nov6-all-racer-grid-retention-counts.json)は既存refのcommit `505800f55176867e8a5a06491fcc18eadca8e070` から独立復元した。既存ファイルの変更・削除0。

catalogはPARSED 7,846＋PARTIAL_SOURCE 117。gridの完全観測日は7,845、未掲載17日・未報告156会場日が残り、完全な全期間とは報告しない。未観測選手・会場の組み合わせも架空の0成績へ置換しない。新しい2つの `*-nov6-research-input.json` と日付延長の `boat-venue-history-dated-research-input.json` で研究用途へ明示参照できる。過去の学習MAC・再現用の既定pointerと、既定モデルは保持する。今回追加した履歴が、既存152原入力の過去特徴量へ遡って入ったとは扱わない。

日付延長V2のCLI・親原本／目録証拠／暗号化受渡しを実装した。実11月7日のmenu/index 2 GET後、既存V1の全原本検証記録 `full_archive_validation` を継承する構造検証で停止した。この不具合を直し、保存済み目録の再GET 0で新日原本1 GETを実行した。原本は公表待ちのままで解析成績へ加算しない。計3 GET・旧原本再GET 0。暗号化目録・親原本・新世代の8ファイルを既存commit `244a7312f1ad32ecf471e35be1c4247e46c5b8ef` から独立復元した。過去の独立復元済み原本群を再利用した新世代検証と、新commit全原本群のActions読戻し待ちを区別する。[実差分取得](evidence/2026-11-07/nov7-dated-history-delta-counts.json)・[保持証拠](evidence/2026-11-07/nov7-dated-history-retention-counts.json)。

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
| 7. テスト | 旧runの合格・失敗証跡は各HEADの履歴として保持。初回19枠runはfit成功／動画fixtureによる全体失敗、08b attempt 1は全体SUCCESS、同attempt 2は取得前cancelled。c438初回・再実行は全体SUCCESS、全Python3,614件（360 skip）、動画283＋185件。ただし実probeはRESULT 0でHOLD。新しい接続コードの全体CIは確認待ち。合成30枠E2Eや固定依存461検査を実30学習・実未来成功とは数えない |
| 8. Actions URL | [旧14実fit 42334526055](https://github.com/haji84/RACE-AI/actions/runs/42334526055)、[元未来保存42336097863](https://github.com/haji84/RACE-AI/actions/runs/42336097863)、[初回19候補42352845874](https://github.com/haji84/RACE-AI/actions/runs/42352845874)、[08b全体検証42355755138](https://github.com/haji84/RACE-AI/actions/runs/42355755138)、[c438の初回・限定再実行42364217725](https://github.com/haji84/RACE-AI/actions/runs/42364217725)。attemptごとの結果を区別する |
| 9. HEAD SHA | 直近全体成功HEADは `c43871ba761c98ad4ba86cfddc1bc2b20585da38`。最新実19候補の学習SHAは `f39104dc8486171d0b8c0d56b97ee788feb0561c1e4a27b81c3d061618c594af`。旧2世代の保持commitは `3761cda8de08055d6a07f8b9d2a928958ce5877e`、第3世代は `9b26d1631aa4b24cd672d1f7bb9234cb6c52ad13`。旧HEAD・初回ローカルSHA・各世代SHAは対応する証跡に保持する |
| 10. 実動作範囲 | 旧14候補は実6/2学習→締切前の基準／学習版独立保存→通常1レースの登録照合→14組PDCA→28暗号化partition別復元まで成立。実19候補はActions3世代でfit・復元・照合し、全3世代の原候補ファイルをGit保持・独立読戻し済み。新19候補の実未来PDCAは0件で、本番運用成功ではない |
| 11. 未完成と原因 | 現行残11枠はAUTO6・KEIRIN5。旧browser件数UNKNOWN／予約24を保持し、無条件の再取得を停止する。新19候補の未来入力・独立保存・公式結果・PDCAと、十分な前向き標本が未実証。最新検証済みc438の全体CIは成功。追加接続コードとCSS再利用修正の新HEAD全体CIは確認待ち。所有者キー復元は確認済みであり、キー不足を原因としない。販売者は現行対象外 |
| 12. 次の最小工程 | 認証済み静的CSSの再利用修正と接続コードを新HEADで全体CI検証する。新19候補は新しい締切前入力にgenuine baselineを結び、独立保存→公式結果→PDCAを検証する。AUTO／KEIRINは旧journalを維持し、明示された限定復旧の実記録に従う。各競技8通常結果が揃った後に、30枠×8＝240原レコード・32独立レースの実6/2fitへ進める。新schedule・上限reset・欠測補完・販売者の再追加は行わない |

## 実証へのリンク

- [19枠の実fitと原レコード数](evidence/2026-11-07/nineteen-native-model-fit-counts.json)
- [初回19枠の実CI候補照合](evidence/2026-11-07/nineteen-native-model-ci-parity-counts.json)
- [旧2世代と第2回収集RESULTの保持・独立復元](evidence/2026-11-07/nineteen-candidates-and-epoch2-retention-counts.json)
- [08b attempt 1全体成功](evidence/2026-11-07/reviewed-head-full-ci-attempt1-counts.json)
- [08b attempt 2の取得前停止・新規送信0](evidence/2026-11-07/expired-fixed-probe-zero-dispatch-counts.json)
- [非BOAT予備7レースの実保存](evidence/2026-11-07/seven-reserve-native-counts.json)
- [旧14候補の通常1レースPDCA](evidence/2026-11-07/fourteen-native-model-future-pdca-counts.json)
- [旧14候補のPDCA・次回検討15件の保持](evidence/2026-11-07/fourteen-native-model-future-pdca-retention-counts.json)

これらは各段階の不変スナップショット。後続の保持・Checks・probe結果は別の証跡へ追加し、元の評価SHAを変更しない。最新c438と11月6日追加履歴の件数証跡を追補した。

## 先行段階の原本保持（履歴）

巡回42342290428は4巡・146/240 GET、lifetime8940 GET／521巡、`BOUNDED_SESSION_END`、source_wait=nullで正常終了した。[当該runのcontrol・continuity照合](evidence/2026-11-07/same-cap-four-round-source-counts.json)。これを別のrunの現在カウンターへ転用しない。その後、[元ZIP／元metadata5件](evidence/2026-11-07/five-original-archives-retention-counts.json)、旧14候補の通常PDCA14件＋次回検討1件、[競馬の追加4通常結果](evidence/2026-11-07/four-new-horse-results-retention-counts.json)を既存refへ保持し、別GitオブジェクトDBで元バイト一致を確認した。

現在残る実学習は11枠である。旧段階の「残17枠」は履歴値としてのみ扱い、新19候補・現行全30枠の実未来評価と十分な標本は引き続き未完了。原本保持、候補世代の追加、モデル除外を、別枠の学習成功や将来性能へ加算しない。


## 復元の実CIと中断時の修正（11月7日21:00 JST）

29eca042／run42369144075は履歴のGit全祖先fetchが180秒上限となって復元job失敗。未発行capsuleのまま後続をcancelし、providerstepはSKIPPED・提供元アクセス0だった。[停止証跡](evidence/2026-11-07/29eca-cancelled-before-provider-counts.json)。履歴・gridの読取りだけを既存VaultGitRepositoryのshallow metadata／必要blob取得へ接続し、writerと保存形式は保持した。[実GitHubの固定manifest読取](evidence/2026-11-07/bounded-history-git-readback-transport-counts.json)は0.893秒・Git object891,789 bytes・鍵読取0・提供元アクセス0で一致。これは全原本群の復元完了ではなく、その新HEAD全体CIは再検証する。

独立reviewで、目録の暗号保存からV2 progress保存までの中断が同じ目録を再取得することも合成で再現した。未commitの既存要求は取得前HOLDとし、保存済み証拠を維持する。完成済みV2と認証済みHTTP待機の既存再開は維持する。新3再現テストをRED→GREEN、履歴・grid・暗号Git境界70件が成功。判定不能な中断を空の新規収集として再試行しない。
