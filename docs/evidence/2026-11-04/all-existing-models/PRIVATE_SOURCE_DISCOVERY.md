# 私有実予想の保存先調査（2026-11-04 JST）

ユーザーの「わからんから調べて」を受けて調査。私有パス・資格情報・買い目をpublic文書へ転記せず、元ファイルを推測生成/改変していない。

## 分かったこと

1. 既存PR72の `docs/OWNER_PRIVATE_REAL_READBACK_20261103.md` は、本人Libraryの `keirin_20261103_forecasts.json` を以前の別環境で実バイト読戻ししたと記録している。58,754bytes、whole-file SHA256 `0a5d1d244e86ba98ab37640a9da83fb825cf2021b15eb2a05899d8fcf94eb4e2`、76レースの研究バンドル。これは**過去の保存記録**で、今回の接続から現在のLibrary内の存在/内容を直接確認できた意味ではない。
2. オート20原本のprivate_library_path/元ファイルSHAが既存の公開監査メタデータにある。basenameとSHAの存在だけを照合し、私有フルパスをこの文書へ再転載していない。現在の接続環境に一致する元ファイルはなかった。
3. GitHubの `state/keirin-encrypted-history` を実際にfetch。head `2c0f9edfe069ce8a190a348c4497c4ed906bd30a`、latest.jsonは `mode=synthetic / generation=1`。実私有予想の暗号化原本として使用せず、鍵を作成/抽出/変更せず、ciphertextも復号していない。
4. 現環境のlibrary-files/shared/downloadsは空。既知の競輪JSON・結果XLSX/PDFとオート20原本のbasenameを、workspace/tmp/agentの利用可能ディレクトリでファイル名だけ探索したが一致なし。認証/設定/セッション/依存キャッシュは探索から除外。2つの読取不可な一時ディレクトリは残るため、未マウント端末や世界中の保存先に存在しないとは断定しない。
5. 探索では3個のDBファイル名を確認したが、存在だけで実予想原本とは扱わない。既知のengine.sqliteと8レース/4予想のprojected.jsonは合成実験であり、後者も明示SYNTHETIC_ONLY。実原本に読み替えない。
6. この接続でChatGPT Libraryを読むツールは提供されておらず、ファイルのマウントもない。GitHub API用api.github.comは現行ポリシーで未許可。通信先追加は下書き保存済みだが現在へ未適用。Git操作と公開Webの証拠読取は成功している。

## 接続の準備と受入

既存PR72 commit `7a432e5acc4d3495a0e82bd79726929e2f8085fe` の `owner_private_file_reader.py` と既存12テストを同一内容でPR71へ再利用した。パス逸脱、symlink、ハードリンク、元SHA不一致、読取途中の変更、重複レース/券/JSONキー等を拒否。本文やパスをエラーログへ出さず、source GETや原本書込みはしない。12テストが成功。

本人Libraryの該当JSONを、この会話の実行環境に添付/接続できれば、先に記録されたwhole-file SHAと照合して読む。秘密鍵やトークンのチャット貼付は不要。原本をpublic Git配下へ保存せず、必要なら非Gitの本人専用作業領域へ元バイトを保って置く。接続先の存在が分からないまま架空の絶対パスを入力済みにしない。

readerのexit2は研究バンドルの元バイト読戻し成功、exit3は拒否。研究バンドルをレース別に後から切り分け、当時の個別SHA/締切前外部receiptを新造しない。whole-file一致だけで正式凍結やsource利用許諾が証明されたことにはならない。

**今回の実原本読戻し0件。** 実機Safariに接続するiPhone/MacやWebKit実行系もこの環境にはなく、実施済みのChromium操作をSafari実機受入と呼んでいない。新しい外部サービス、課金、公開、権限解除で埋め合わせていない。

## 展示後原本JSONの追跡（追加調査）

- 展示後BOAT原本は、既存run41801993716などの巡回別forecast artifact内の `national.json`。各回の増分であり、最終round21の予想0件を当日全予想0件に読み替えない。全体の対応は `continuity.json` の原artifact/SHA参照から復元する。
- 例：18:36チェックポイントの予想artifact13311386530（既存記録のZIP SHA256 `9838c0ee57a2eb9024d2e1e664d1f60b909ca3bfc5b503137b0343dc8202e183`）。今回のGitHub APIメタデータ読取は通常gh経路で実行したが `Get https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/13311386530: Forbidden`。実ZIP/JSONバイトは今回まだ取得できていない。
- 保存済み下書きにapi.github.comは追加済みだが、実行中環境のcustom allowed hostsは空のまま。下書き保存と現環境適用を混同しない。トークンを取り出したりproxy設定を回避していない。
- /mnt、/media、/data、/var/tmp、共有/Downloads/Documents候補を追加探索。存在する追加rootのJSON/アーカイブは0、既知原本の一致も0。以前と今回のオート原本/PDCA計22件について、記録された絶対パスも直接照合して不在。既存のprivateフルパスは再転載しない。
- 別writerの92f3572/b9f7d70の新しいPDCA監査SHA記録をfast-forwardで保全。これもprivate_library_pathとSHAのメタデータであり原本本文ではない。
