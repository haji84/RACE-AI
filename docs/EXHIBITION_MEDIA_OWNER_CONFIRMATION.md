# 展示映像の非公開解析に関する所有者確認

2026-10-15 JST、所有者は全レースの展示映像解析、オリジナル展示データの予測入力、展示前後の比較を要求した。
展示映像の自動取得・非公開解析に使える配信元・契約・許諾の記録を尋ねたところ、次の確認を得た。

> ファイルパスはないが利用していいと調べたら出てきた。

確認参照は`user-confirmation-2026-10-15-exhibition-private-analysis`。所有者の調査確認に基づく運用上の根拠として記録する。
調査資料や契約書自体は未提供であり、独立した法的監査や配信者による許諾書を取得したとは記録しない。

範囲は公式に公開提供される展示映像の限定取得、解析に必要な一時処理、非公開の艇別特徴抽出と保護されたPreview内での予測入力・検証。
元映像の継続保存・一般公開、写真の公開、認証/DRM/技術的制限の回避、自動投票・決済・Production公開を含めない。
公式数値、各場独自の計測値、映像から推定した値を分け、出典・取得時刻・実保存時刻・計測条件・信頼度を保持する。
映像配信元と具体的な公開パス/CDNの同一性を確認してから、範囲を限定した取得設定へ登録する。

公式説明：[オリジナル展示データの案内](https://www.boatrace.jp/owpc/pc/site/news/2025/07/44414/)、
[BOATCASTサイトポリシー](https://boatcast.jp/static/sitepolicy/index.html)。所有者確認と提供サイトの条件は別の記録として保持する。

## 配信元の実確認

公式BOATCASTの全24場リンクから展示ページへ接続し、鳴門2026-10-15・5Rの公式プレーヤーで5分48秒の展示再生を確認した。公式プレーヤーの録画索引と、プレーヤーが返すstreaksの同プロジェクトHLS配信を確認した。ストリームの一時トークンは記録・出力しない。通常の公開プレーヤーアクセスを使う鳴門限定のリゾルバーを実装し、6Rの索引・メタデータ・HLS親配信表を締切前に確認した。映像セグメントは未取得で、実映像の解析は次工程。再生確認は艇別解析や全レース取得の完了証拠ではない。

オリジナル展示値は同ページで6艇の展示・一周・まわり足・直線を確認。数値ファイルには日付本文・登録番号・締切がなく、正確なURL、6艇名、別途確認した番組によって照合する。元映像と混同せず、数値の正規化版だけを別契約で扱う。
# 限定数値・通常再生リソースの実装範囲追記

同じ所有者確認に基づき、公式BOATCASTの`/txt/{venue}/bc_oriten_{day}_{venue}_{race}.txt`と
`/hp_txt/{venue}/bc_j_tkz_{day}_{venue}_{race}.txt`を、選択した当日レースにつき最大2GETで読み、
6艇名と承認済み番組を照合した正規化値だけを非公開で保存・Previewへ提供する。
元TSVは保存しない。記録に日付本文・登録番号がない制約と、会場ごとに計測定義が異なる制約を保持する。

通常公開プレーヤーの子HLS配信表で確認したidentity AES-128に限り、
`key.streaks.jp`の同じmedia/source IDに結ばれたプレーヤー返却先から16バイトをRAM内で読む。
RFC8216の通常再生処理であり、新規の認証情報作成、DRMライセンス交換、認証回避は行わない。
鍵・鍵URL・配信トークン・元映像・フレームを保持しない。未知の方式・取得先・認証失敗は停止する。
これは提供者との独立した契約確認や法的監査の記録ではない。


## 2026-10-17 別の通常player CDN transport限定登録

最新の所有者指示「通常playerと配信資源の具体対応・許可されたorigin/path形を別の新適格対象で確認し、別の厳密な媒体契約を独立検査してから同一RAM二担当幾何ラベルへ進む」に従い、通常player新9Rの観測へ結ぶ別登録を追加した。登録のcanonical SHAは `5eaa11f6677ecb748cef05f6c9bbc13bb1525d67372628cf4041f2ec6220c1b5`、観測全文SHAは `8e7621c0e345175e905628e3aef7941e7bc3cf245b2dcd25c132fdc59c6952fd`。旧legacy key scopeを一般化しない。

新登録は当日/同会場/観測後6時間以内、同じprojectの各対象自身のexact ref→metadata→master→child、exact media/source/variant/sequence TSと固定query形、私用登録namespaceに限る条件付きtransportである。具体的source scopesはconfigの独立 `normal_player_cdn_transport_registration` に記す。鍵URI/namespace値/鍵bytesは保存しない。namespace hashはraw case-sensitive ASCII HEX32 component単独をpreimageとし、実hashは私用資料だけに置く。namespaceのproject所有者や物理日付/時計を認証したとはしない。identity AES-128のRAM処理以外の認証/DRM/license回避を許可しない。

configのderived_features_public_publish=false、原映像/frame継続保存と一般公開の禁止、既存OIDC/環境/権限/直列化/AllDeployments保護を維持する。新10R実取得はVercel接続が正しい既存teamに403となりfresh当日witnessを得られず、source開始0のまま未実施。映像解析の所有者承認を再要求する事象ではなく、既存保護Preview/APIの接続復旧が必要な状態である。検証/失敗履歴はnormal-player-cdn-stage.jsonと後続PR64/private証拠を参照する。
