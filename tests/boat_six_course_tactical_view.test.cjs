const fs=require("node:fs");const assert=require("node:assert/strict");
const html=fs.readFileSync("web/boat-six-course-tactics-research.html","utf8");
for(const s of ["connect-src 'none'","まくり差し","5・6コース","逃がし率",
"チルト角度・スタート展示の進入","カド受け","前付けした時・外へ押し出された時",
"今節の予選得点・暫定順位","RACE_AI_BOAT_EVENT_QUALIFYING_CONTEXT_V1",
"RACE_AI_BOAT_P1_DYNAMIC_TACTICAL_CONTEXT_V1","A/B/C同一レース比較","仮想収支/円","保存済み従来予想","最終の突破確定ではありません","3連単120通りの研究用確率","1号艇の1着率","来期級別・過去A級実績・出走間隔","frameGradeMap","正式確定待ち","休養理由は不明","確率合計","校正済み・実未来精度改善の証拠はまだありません"])
assert.ok(html.includes(s),s);
assert.doesNotMatch(html,/\bfetch\s*\(|\bXMLHttpRequest\b|<script[^>]+\bsrc=/);
assert.ok(html.includes("textContent"));
const inline=html.match(/<script>([\s\S]*?)<\/script>/);assert.ok(inline);
new Function(inline[1]);console.log("Source-free 6-course view contract PASS");
