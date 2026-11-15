# RACE AI 会場ナビ・選手カルテ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 会場・レース・選手・直前情報を少ない操作で確認できる、RACE AI 独自の閲覧画面を公開する。

**Architecture:** 既存の読み取り専用データと JavaScript/CSS を使う。純粋な会場・公式リンク・情報有無の関数を `ui-model.js` に追加し、`app.js` が会場ナビ・選手カルテ・情報ショートカットを描画する。保存原本や暗号化ビューの形式は変えない。

**Tech Stack:** Vanilla JavaScript, CSS, native dialog/details, Node test runner, Playwright/Chromium, existing Python saved-view packaging, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-07-race-navigation-profile-design.md`

## Global Constraints

- GitHubのみを使う。Cloudflare・Vercel・新たな課金サービス・権限変更は使わない。
- 暗号化された保存予想・所有者リンク・原本のSHA・結果改訂・買い目の状態を保持する。元データの会場コードを表示の都合で書き換えない。
- 作成済み1,669名のイラストと名前の厳密な対応を保持する。「イラスト」の余分なラベルを戻さない。
- 推測したAI評価、確率、オッズ、利益、成績、天候を見栄えのために表示しない。
- 公開ブランチやテスト証跡に私有の予想原本・鍵・SQLite・結果原文を含めない。検証には架空のUI用データを使う。
- mainへのマージや他の作業の上書きは行わず、既存のPR・公開手順を使う。

## Review Focus

- 未取得の会場を選んだ後の日付変更でも会場を維持し、開催なしと誤表示しない。
- 登録番号・名前の矛盾、合成出走者を実在選手の写真・公式リンクへ結び付けない。
- 補足の展示観測を保存予想の入力に昇格させず、F/Lやゼロ値と未取得を区別する。
- 選手カルテの開閉や同会場内のレース移動で買い目編集と選択中の原本を失わない。
- 不正な端末設定、期間に複数日が含まれる場合、情報のないレースでも全画面を描画できる。

## Task 1: 読み取り専用の会場・情報モデル

**Files:** Modify `web/ui-model.js`; create `tests/race_explorer.test.cjs`.

**Interfaces:** `venueOverview(records, {sport, now, favorites})` returns `{venue, count, favorite, nextRace}` entries; BOAT includes all 24 venues plus imported unknown names. `raceInformation(row, {supplementalPreview})` returns four `{key,label,available,detail}` entries for participants/preview/outlook/history. `boatRaceLinks(row)` returns `{kind,label,url}` entries only for a non-synthetic BOAT race with valid, consistent day/venue/R metadata.

- [x] Write tests for favorite ordering, absent venues, future/unknown deadlines, immutable input, partial information and known 24 venue URLs. Assert conflicting IDs, malformed dates, synthetic and other-sport rows yield no BOAT links.
- [x] Run `node --test tests/race_explorer.test.cjs`; expect assertions to fail because the new behavior is absent.
- [x] Implement these functions without new dependencies or mutations of stored records.
- [x] Run `node --test tests/race_explorer.test.cjs tests/ui_model.test.js`; expect all tests to pass; commit.

## Task 2: 選手カルテ

**Files:** Modify `web/app.js`, `web/style.css`; create `tests/race_explorer_browser.test.cjs`.

**Interfaces:** `participantCard` preserves its existing return type and portrait binding, adding a real athlete-detail button outside the settings gallery. `openParticipant(person, race, opener)` creates/reuses a native dialog; closing restores focus. The card's optional noninteractive mode keeps gallery anchors free of nested buttons.

- [x] Add browser cases for opening a named athlete, reading saved metrics including zero, closing by button/Esc and focus return; check invalid identities and synthetic people never gain a genuine profile link. A UI-only fixture supplies exact names and clearly invented values, never a real forecast.
- [x] Run `EXPLORER_SECTION=profiles node tests/race_explorer_browser.test.cjs`; expect missing interaction assertions to fail.
- [x] Implement the profile dialog, labeled data groups, strict official-profile link, and keyboard/accessibility behavior.
- [x] Run the profile browser cases and existing portrait browser test; expect pass at 320/390/1440px; commit.

## Task 3: マイ会場・レース切り替え・情報ショートカット

**Files:** Modify `web/app.js`, `web/index.html`, `web/style.css`, `tests/race_explorer_browser.test.cjs`, `tests/venue_names_browser.test.cjs`.

**Interfaces:** Use Task 1 functions. `openRace(id, tab="outlook")` preserves existing calls while allowing card shortcuts and the same-venue/day race switcher. `chooseVenue(venue, toggle)` drives the existing venue filter. Only favorite sport/venue identifiers extend the existing preference object.

- [x] Add failing browser tests for home→venue→race→preview, favorite persistence without forecast storage, empty venue/day behavior, same-day race switching, return-to-list filters, matching official link parameters, and unchanged draft tickets.
- [x] Run `EXPLORER_SECTION=navigation node tests/race_explorer_browser.test.cjs`; expect the new navigation assertions to fail.
- [x] Add home/main venue panels, the selected venue heading and favorite control, exact-date race buttons, availability shortcuts and safe official links. Keep missing race slots disabled rather than inventing records.
- [x] Run all explorer browser cases and venue-name browser cases; expect pass; commit.

## Task 4: 情報配置・直前情報・回帰確認と公開

**Files:** Modify `web/index.html`, `web/app.js`, `web/style.css`, relevant browser tests and `.github/workflows/forecast-audit-ui.yml`; update this plan's completion boxes.

**Interfaces:** Existing control IDs, saved-view hooks, dataset schema and asset list remain compatible. Native details organize operational/model explanations; connected generation controls remain available. Preview data retains its existing main/supplementary boundary and observation timestamps.

- [x] Add browser cases showing actual preview values/F/L, zero values and invalid supplemental-context rejection; run before changing the preview presentation and verify the intended failure.
- [x] Move venue/search controls above cards, simplify mobile spacing, provide a compact weather/preview view, retain source details behind a disclosure, and make profiles/cards/tabs usable by keyboard and touch.
- [x] Add the explorer browser to the existing UI workflow. Run the existing UI unit command, `tests/ui_browser.test.js`, explorer/portrait/venue/results/saved-page browsers and Python `tests.test_saved_pages`/`tests.test_saved_pdca_view`; inspect mobile and PC screenshots and commit.
- [x] Request one fresh whole-change review against this plan/spec. Resolve material findings, preserving source/deadline/identity gates.
- [x] Rebase onto the latest existing PR branch without replacing concurrent work, push normally, and use `refresh_site_assets` against the current pinned Pages parent. Verify all ciphertext trees/manifest fields are unchanged, new HTTP asset hashes match, and the deployed explorer browser passes.
