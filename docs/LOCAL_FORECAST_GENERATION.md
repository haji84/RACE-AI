# ボタン不要の連続予想と保存原本の表示

既存PR71の個人用アプリ。実入力の発見→既存nativeモデル→私有保存→原本の表示を接続する。2026-11-05の追加指示に従い、固定GET回数・論理24巡・65分・日付境界による終了を撤廃した。実装と、稼働先への適用・実測は[最新状況](RACE_AI_LATEST_STATUS.md)で分けて記録する。

## 起動と生成場所

LinuxまたはWindows WSL2、Python3.11以上、libarchiveまたは既存lhafileランタイム、固定PR64/PR72参照コードが必要。私有保存はLinuxの権限・no-follow・`/proc/self/fd`を使うため、通常のWindows Pythonでは動かない。

本人PC内で生成する場合は既存launcherを使う。

```bash
python scripts/start_local_forecast.py --check
python scripts/start_local_forecast.py
```

`--check`は依存・保存先の確認だけで、取得・推論を開始しない。通常起動はnativeモードで、HTTP待受の開始後に自動巡回する。生成ボタンやブラウザを開く操作は開始条件ではない。

既存GitHub workflowを生成元にし、クラウドのsupervisorで引き継ぐ場合はmodule CLIでモードを明示する。

```bash
python -m race_ai.local_forecast_server \
  --private-dir /absolute/private/app \
  --automatic-mode github \
  --supervisor-dir /absolute/private/supervisor
```

GitHubモードの画面は、認証したartifactをSHA照合した私有projectionを読む。画面用serviceでは当日入力providerやnative生成を重ねず、GET表示・JSON読込が予想を再計算しない。初回同期前、検証失敗、未取得の競技・時点は不明/未接続を示す。静的な`web/index.html`だけなら従来のJSON閲覧で、Python推論やsupervisorは動かない。

そのサーバーを起動したPCの`http://127.0.0.1:8765/`を開く。クラウド内の127.0.0.1は手元PCのURLではない。外部向けbind・一般公開は追加していない。終了はCtrl+C。ブラウザを閉じてもサーバー側巡回は止まらず、PC/クラウド環境自体が停止すればこの仕組みも停止する。

## 論理巡回と物理worker

- 固定45回/取得処理・累積240回のGET停止はなく、上限metadataはPython `None`/JSON `null`。実際の取得数・累計・巡回数は記録し、負数・bool・カウンター減少を拒否する。
- 通常180秒を基本に、次のT−15/T−10や発見時刻を見て確認する。公式Bを更新して新たに見つかった適格レースの欠けたP0を埋める。保存済みのモデル版・Top8・SHAを再生成/上書きしない。
- 論理巡回は24巡や65分で終了しない。JST日付変更時は旧日の原本・件数・待機状態を保存して日別処理を引き継ぐ。取得→推論→保存確認のtransactionは対象日を固定し、実時計が変われば`DAY_HANDOFF`を返す。別日の入力を旧日の予想へ混ぜない。
- 既存GitHub workflowの物理workerはプラットフォーム上限360分内で動く。330分の事前handoffと24batchの実装上の区切りは、同じworkflowの次workerへ渡す境界であり、全論理巡回の終了上限ではない。
- クラウド側GitHubSupervisorは既存認証actorで現在のrun・queued状態・独立原本を確認し、確認済みHEADを親に持つcommitを作り、forceなしで同じtriggerを追記する。既存workflow・同一concurrency・単一writerを維持し、別workflow・新PAT・外部サービスを作らない。`GITHUB_TOKEN`自身のpushでworkflowが再帰起動すると仮定しない。
- 物理worker切替は`WORKER_HANDOFF`として日付変更と区別する。追加GETを加算せず、先に生成できた原本は独立保存・検証して保全する。旧workerの完了と後続起動を、後続予想の生成成功とは数えない。
- 私有保存先はprocess lockでwriterを1件に制限する。別マシンのGitHubとnativeローカルのlockは共有されないため、同じ対象を重複収集する2経路を同時起動しない。

連続運転の構造を実装したことは、24時間の実運転・全日無欠落の証明ではない。物理環境の稼働、取得元の提供、認証・利用条件、適格な入力、原本の保管と検証の達成状況を、時点付きの実測で記録する。

## T−15～T−10の保存目標と待機

P1は締切15分前から10分前の対象を優先し、同じphase内では締切順に処理する。3予想/5試行による打切りはなく、適格な対象すべてを確認する。未公開の1レースが他の対象を塞がない。T−10後も間に合う場合は210秒より前の遅延fallbackとして区別し、210秒以内は新規保存しない。

- 正常200の未公開展示と既知のbeforeinfo404はレース別のpublication待機を記録する。通常の待機はT−10の最終確認を1度早められるが、取得元のRetry-Afterを短縮しない。
- 429はRate Limit待機、5xx/通信障害は間隔を延ばす一時待機。即時再試行・別endpointへの迂回を行わない。
- 401/403は認証・利用条件の確認待機、出典/本文/保存状態の不整合は要確認待機。古いretry時刻や日付変更で解除しない。
- 待機理由、次回確認/再試行時刻、次の締切、取得数、元データ取得/生成/保存の実時刻を表示する。時刻不足はUNKNOWN、未保存はNOT_SAVED、目標後の保存はLATEで区別する。本人の画面へ見えた時刻の独立受領証明とはしない。

## 原本と再起動の保全

既定のnative保存先はLinuxホーム内の`.local/share/race-ai-owner`。`--private-dir`で絶対pathを指定できる。私有ディレクトリ0700・ファイル0600、Git外で保持する。`private-seed`は初回だけ検証し、既存原本を上書きしない。

V1の正常な24巡/65分/日付/数値GET上限による終了は、旧ファイルの実バイトとSHA・旧理由を残してV2へ移行する。取得数・累計・原本をゼロにしない。中断・真正性不一致・時刻逆行・認証等の確認待機は、policy変更として解除しない。checkpointが消えた場合も既存lockの初期化記録から継続性の欠落を検知し、初回へ戻さない。

LZH/HTMLとmetadataを解析前に私有保存する。最初に検証したレースのprogram行は元sourceとchecksumで結び、元raw/metadataを再検証する。発見更新で過去のcutoff・出走者・特徴を置き換えず、不整合は理由付きで保持する。推論後・commit時にも実時計と締切余裕を確認し、遅延原本を作り直して有効に見せない。

## 表示・競技・検証の範囲

BOAT P0は公式Bから既存観測相性2モデル、P1は公式racelist/beforeinfoが揃う対象から既存A/B2・C-lite1・観測相性2へ接続する。他のBOATモデルで実履歴・学習物等が不足すれば未予想。競輪・オート・競馬の適格な当日入力は未接続で、BOATの事実から別競技の特徴を作らない。

競技・P0/P1選択は保存原本の表示操作。自動管理中の生成POSTは拒否する。更新で金額入力・購入候補確定・原本SHA選択・タブ・手動JSON表示を消さず、候補の日付/レースが変わる場合は保留する。購入候補確定は実投票ではない。

ローカル保存、GitHub artifact受領、公式結果、研究学習版、手入力購入は別々に扱う。未校正確率・未検証回収率・学習版優位性・本番採用を認定しない。具体的な保存件数と最終試験は[最新状況](RACE_AI_LATEST_STATUS.md)の時点付き記録を参照。過去配布ZIPは固定snapshotで、新コードの反映や最新件数への更新を自動保証しない。

全4競技×全適用モデル×全レース、全日P1、恒久私有保管、実機Safari、前向き精度改善は未達。今回の連続運転コードを、それらの完了や一般公開・main統合・実投票・本番モデル切替とは扱わない。
