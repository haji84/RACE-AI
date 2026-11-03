# RACE-AI 競輪 永続クラウド台帳: OIDC / Cloudflare D1

## 完成した工程
Cloudflare専用D1 `race-ai-keirin-private-research` を新規作成し、2026-11-03 の実データから自動発見された8場76RのレースIDを保存。Cloudflare APIの別セッションで競輪場別件数を読み戻して一致した。
Cloudflare Worker `race-ai-keirin-private-state` をデプロイ。D1バインディング名は OWNER_DB。preview URLは無効。一般公開HTTP GETは /health の非機密情報のみ。/v1/cohort と /v1/status はGitHub ActionsのOIDC署名を必要とする。

## 認証条件
GitHub発行のRS256 OIDC JWTのJWKS署名、issuer/audience/exp/iat、repository haji84/RACE-AI、repository_id 1416489937、ref refs/heads/main、workflow_ref keirin-d1-oidc-bridge.yml、event_name push/schedule/workflow_dispatch をすべて照合。外部に固定トークンやGitHub PATを置かない。
Cloudflare WorkerのURL: https://race-ai-keirin-private-state.qq-1130034.workers.dev 。本URLの存在は「競輪予想の一般公開」ではなく、認証付きプライベート状態APIを指す。

## GitHub Actions
`.github/workflows/keirin-d1-oidc-bridge.yml` はPR時はno-network単体テスト。保護mainへの統合直後のpush、および毎日05:24・07:24 JSTのscheduleと手動起動で、開催日別ページを一度だけ取得し、当日レースIDの全件をD1へ送る。予想原本、生HTML、オッズ、個人データは送らない。

## 明示的な未達
Cloudflare D1への実OIDC認証付き書き込みが成功したか、`main`からの本物のrunを確認するまでは未達。
本Workerでは予想の暗号化原本、公式結果の確定、独立時刻証明、PDCA学習、次レース予想計算をまだ公開・保存しない。
2026-11-03以降の全競輪場をリアルタイムに無人予想する完成条件は未達。私的利用であっても利用先のアクセス制限回避・過負荷は認めない。

## 制限
新たなWorkers/D1の有料プラン変更、独立課金設定、自動投票、mainの強制統合はしていない。D1の無料枠はあるがユーザーCloudflare課金履歴の閲覧権限がないため現在の課金プランは未確認。
Sources: https://docs.github.com/en/actions/reference/security/oidc , https://developers.cloudflare.com/d1/platform/pricing/
