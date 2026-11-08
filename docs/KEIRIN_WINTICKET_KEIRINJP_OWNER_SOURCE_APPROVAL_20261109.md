# RACE-AI: WINTICKET / KEIRIN.JPの本人使用確認（2026-11-09）

## 方針
本人は2026-11-09に「ウィンチケット、KEIRIN.JPは使用できる。OKだ！」と明示した。
この確認は、RACE-AIによる**本人限定・私的研究用途での公開画面の確認および本人が正当に保存した観測情報の入力**に反映する。これをプロバイダが無人クローリング、非公開API解析、商用データ再販売、サイト情報一括コピーを許可した証明にはしない。

- **KEIRIN.JP**：大会・開催日・レース・車番・公式結果の第一照合元。公開ページに無い情報は存在すると決めつけない。
- **WINTICKET**：出走表、選手成績、公開オッズ表、レース映像・過去の結果の補助確認元。動画の利用条件は、個別用途と保存方法で別途確認する。
- 楽天/Kドリームスは従来のユーザー方針により利用しない。
- 入力の事前監査は7車347項目／9車437項目。必須要素や取得時刻が不明なら未確認のまま残す。
- 買い目候補の能力・展開予測にはオッズを入れない。予想SHAが確定した後、実測オッズを別経路で変動券の研究選定へ投入する。

## 実際に確認した公開情報
- WINTICKET「本日 2026-11-09 出走表一覧」には青森11/8～11/10開催が載っている: https://www.winticket.jp/keirin/racecard/
- WINTICKET「本日 2026-11-09 オッズ一覧」も青森の各レースを掲載: https://www.winticket.jp/keirin/odds/
- WINTICKETヘルプ「オッズはいつから見られますか？」では発売開始後、概ね発売当日の朝に表示すると案内: https://www.winticket.jp/support/bet
- ただし**青森3Rの全210通りが時刻付きで正しく取得・非公開保存された証拠は未確認**。オッズ一覧の存在は完全な券種データとは違う。

## 利用条件の一次情報
- KEIRIN.JPサイトポリシー: https://keirin.jp/pc/dfw/portal/guest/policy/index.html
  - 私的利用を超える無断の複製/転用、対価を得る利用等を制限。
- WINTICKET利用規約第15条: https://www.winticket.jp/terms
  - 無承認のプログラム解析・無権限アクセス・営利目的利用等を制限。
- 本人が利用できると判断したことは尊重するが、**外部サービス提供者による機械アクセスの個別許諾まで確認したとは主張しない**。禁止事項に抵触しない用途で処理する。

## 既存コードへの反映
- `race_ai/keirin_owner_approved_sources.py` はWINTICKETとKEIRIN.JPの正規HTTPSホストだけを選択する純粋な入力プロファイル。ネットワーク接続を行わない。
- `scripts/keirin_permissioned_owner_agent.py` に `--owner-approved-source-profile owner-approved-winticket-keirinjp-20261109` を追加。必ず `--personal-manual --owner-private-use-confirmed` と組み合わせる。入手済みCSV/観測から既存の私的研究エンジンに渡す。プロファイル単体ではAPI通信しない。
- `race_ai/keirin_owner_saved_csv.py`：入手済み出走表CSVの取り込みと部分347項目監査。
- `race_ai/keirin_owner_odds_csv.py`：入手済み全210/504券CSVの完全性・SHA・締切前チェック。
- `race_ai/keirin_licensed_api_ingest.py`：**別途、本物の無人API利用権限と正規提供エンドポイントを検証した場合だけ**、1回GETの正規供給モードへ進む。

### 参考 CLI（本人の保護済み永続実行環境のみ）

```bash
python -m scripts.keirin_permissioned_owner_agent \
  --db "/absolute/private/owner.sqlite3" \
  --inbox "/absolute/private" \
  --personal-manual \
  --owner-private-use-confirmed \
  --owner-approved-source-profile owner-approved-winticket-keirinjp-20261109
```

これはWeb自動取得コマンドではない。公開GitHubリポジトリや一時的なGitHub-hosted runnerに平文のDBや観測ファイルを置かない。GitHub暗号化運転の本番開始を意味しない。

## 完成判定
- 本人の2サイト利用方針の登録：対応済み。
- 本人保存の出走情報と全210券オッズを扱うコード：既存機能を再利用。
- 2サイトのAPI連続取得許諾・当日完全オッズ取得：未検証。
- 本番2方式の締切前SHA保存とAEAD読戻し、独立時刻証明：未達。
- 新規公開平文・自動投票・課金：なし。
