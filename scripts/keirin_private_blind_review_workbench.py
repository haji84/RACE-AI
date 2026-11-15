"""Build a self-contained OFFLINE annotation workbench for one blind reviewer.

Source: an owner-private, authenticated PR291 review packet produced by
keirin_blind_video_review_packets.py. NEVER run this on public Actions or
publish generated HTML: it embeds ORIGINAL private frame PNGs (not predictions).
The UI never uses HTTP, external scripts, browser storage, or result data.
Human annotations are DRAFTS, never independent ground truth by themselves.
Two genuine separately identified reviewers and owner-side signature/receipt
admission remain mandatory.
"""
from __future__ import annotations

from argparse import ArgumentParser
import base64
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from race_ai.keirin_blind_rider_holdout_gate import REVIEW_SCHEMA

MANIFEST_SCHEMA="RACE_AI_KEIRIN_PRIVATE_BLIND_REVIEW_PACKET_V1"
DRAFT_SCHEMA="RACE_AI_KEIRIN_PRIVATE_BLIND_ANNOTATION_DRAFT_V1"
SHA=re.compile(r"^[0-9a-f]{64}$")
FILE=re.compile(r"^source_[0-9]{3}\.png$")


class WorkbenchError(ValueError):
    pass


def need(value,reason):
    if not value:raise WorkbenchError(reason)


def private(path,*,is_dir=False):
    p=Path(path)
    need((p.is_dir() if is_dir else p.is_file()) and
         not p.is_symlink() and p.stat().st_mode&0o077==0 and
         p.parent.is_dir() and p.parent.stat().st_mode&0o077==0,
         "PRIVATE_PACKET_MUST_REMAIN_OWNER_ONLY")
    return p


def checked_packet(packet_dir):
    p=private(packet_dir,is_dir=True)
    manifest_file=private(p/"manifest.json")
    form_file=private(p/"review_UNFINISHED.json")
    manifest_bytes=manifest_file.read_bytes()
    manifest=json.loads(manifest_bytes)
    form=json.loads(form_file.read_bytes())
    need(type(manifest) is dict and
         manifest.get("schema")==MANIFEST_SCHEMA and
         manifest.get("does_not_contain_model_predictions_or_rider_labels") is True and
         manifest.get("independent_review_completed") is False and
         type(manifest.get("frames")) is list and
         1<=len(manifest["frames"])<=600,
         "REVIEW_SOURCE_MANIFEST_NOT_BLIND")
    need(type(form) is dict and
         form.get("schema")==REVIEW_SCHEMA and
         form.get("independent_source_frame_read") is False and
         form.get("reviewed_at") is None and
         form.get("review_sha256") is None and
         type(form.get("frames")) is list and
         len(form["frames"])==len(manifest["frames"]),
         "REVIEW_SOURCE_FORM_NOT_UNFINISHED")
    for key in ("race_id","recording_sha256","proposal_sha256","reviewer_id"):
        need(type(manifest.get(key)) is str and
             manifest[key]==form.get(key),
             "REVIEW_SOURCE_MANIFEST_FORM_MISMATCH")
    need(form.get("target_kind") in ("JERSEY_COLOR_REGION","RIDER_FULL_BODY"),
         "INVALID_REVIEW_TARGET_KIND")
    frames=[]
    for i,(meta,row) in enumerate(zip(manifest["frames"],form["frames"])):
        need(type(meta) is dict and type(row) is dict and
             set(meta)=={"frame_sha256","source_image_file",
                         "png_bytes_sha256","recording_sec"} and
             type(meta["source_image_file"]) is str and
             FILE.fullmatch(meta["source_image_file"]) and
             meta["source_image_file"]==f"source_{i:03d}.png" and
             type(meta["frame_sha256"]) is str and
             SHA.fullmatch(meta["frame_sha256"]) and
             type(meta["png_bytes_sha256"]) is str and
             SHA.fullmatch(meta["png_bytes_sha256"]) and
             row=={"frame_sha256":meta["frame_sha256"],
                   "exhaustive_visible_targets":False,
                   "annotations":[]},
             "BLIND_FRAME_METADATA_OR_UNFINISHED_LABEL_INVALID")
        file=private(p/meta["source_image_file"])
        image=file.read_bytes()
        need(len(image)<=2_000_000 and
             image.startswith(b"\x89PNG\r\n\x1a\n") and
             sha256(image).hexdigest()==meta["png_bytes_sha256"],
             "PRIVATE_SOURCE_IMAGE_SHA_INVALID")
        frames.append({
            "frame_sha256":meta["frame_sha256"],
            "recording_sec":meta["recording_sec"],
            "image_data_url":"data:image/png;base64,"+
              base64.b64encode(image).decode("ascii"),
        })
    return {
        "draft_schema":DRAFT_SCHEMA,
        "race_id":form["race_id"],
        "recording_sha256":form["recording_sha256"],
        "proposal_sha256":form["proposal_sha256"],
        "reviewer_id":form["reviewer_id"],
        "target_kind":form["target_kind"],
        "packet_manifest_sha256":sha256(manifest_bytes).hexdigest(),
        "frames":frames,
    }


HTML=r"""<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KEIRIN オフライン独立映像レビュー</title>
<style>
:root{color-scheme:dark;font:15px -apple-system,BlinkMacSystemFont,"Hiragino Kaku Gothic ProN",sans-serif;background:#121a23;color:#edf3f7}
body{margin:0 auto;padding:16px;max-width:1080px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
h1{font-size:1.3rem;margin:.3rem 0}p{line-height:1.55}
small,.muted{color:#adc1cd}
button,select,input{font:inherit;border-radius:7px;border:1px solid #536c7b;background:#1f3441;color:#fff;padding:9px}
button{cursor:pointer}button:hover{background:#2b5066}button:focus-visible{outline:3px solid #ffbf59}
.primary{background:#006f84}.primary:disabled{opacity:.35;cursor:not-allowed}
.panel{border:1px solid #345364;border-radius:12px;padding:13px;margin-top:12px}
#stage{position:relative;width:100%;background:#02070b;touch-action:none;line-height:0;user-select:none}
#photo{width:100%;display:block;pointer-events:none}
#layer{position:absolute;inset:0;width:100%;height:100%;touch-action:none}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
label{display:inline-flex;gap:6px;align-items:center}
table{width:100%;border-collapse:collapse}td,th{padding:8px 5px;text-align:left;border-bottom:1px solid #3b5360}
.warning{border-left:4px solid #dfae66;padding-left:10px;background:#30271c}
.error{color:#ff9696}
.badge{background:#29475a;border-radius:5px;padding:3px 7px;font-variant-numeric:tabular-nums}
#frameSelect{max-width:100%}
fieldset{border:1px solid #4e6776;border-radius:9px}legend{font-weight:600}
@media(max-width:600px){body{padding:9px}td,th{font-size:12px}button{padding:7px}}
</style>
</head>
<body>
<header><h1>競輪映像 独立レビュー</h1><span class="badge" id="progress"></span></header>
<p class="warning">この画面は非公開の元フレームです。検出モデルの予測は一切表示しません。<b>全フレームの対象領域</b>を描いてください。分からない車番・順位は UNKNOWN。別のレビュアーの回答やレース結果を見ずに作業してください。AIや同一人物による2回の回答は独立レビューではありません。</p>
<div class="panel controls">
<button id="prev" type="button">前のフレーム</button>
<select id="frameSelect" aria-label="フレーム"></select>
<button id="next" type="button">次のフレーム</button>
<span id="timestamp" class="muted"></span>
</div>
<div class="panel">
<div id="stage" aria-label="映像。ドラッグして対象領域を囲む">
<img id="photo" alt="非公開元フレーム"><canvas id="layer"></canvas>
</div>
<p class="muted">画像をドラッグして<b>ジャージ色の領域</b>を囲む。選手全身の枠ではありません。位置や車番が不明でも枠を記録できます。</p>
<div class="controls">
<label>車番 <select id="car"><option value="UNKNOWN">UNKNOWN</option></select></label>
<label>根拠 <select id="evidence"><option value="UNKNOWN">不明</option><option value="VISIBLE_DIGIT">車番数字を視認</option><option value="INDEPENDENT_MULTIFRAME_ID">別フレームで確認</option><option value="COLOR_ONLY">服色のみ</option></select></label>
<label>走行順位 <select id="rank"><option value="UNKNOWN">UNKNOWN</option></select></label>
<label>ライン <select id="line"><option value="UNKNOWN">UNKNOWN</option><option value="LINE_FRONT">先頭</option><option value="SECOND_WHEEL">番手</option><option value="THIRD_WHEEL">3番手</option><option value="INDEPENDENT">単独</option></select></label>
</div>
<p id="addHelp" class="muted">上の選択内容が次に描く枠に付く。車番を選ぶなら根拠も選択。</p>
<div class="controls">
<button id="undo" type="button">最後の枠を削除</button>
<button id="clear" type="button">このフレームの枠を全削除</button>
<label><input type="checkbox" id="exhaustive"> 映っている対象を全員確認した（候補漏れなし）</label>
</div>
<div id="annotations" role="status"></div>
</div>
<div class="panel">
<div class="controls">
<button type="button" id="exportDraft">途中保存 JSON</button>
<label>途中保存を再読込 <input id="importDraft" type="file" accept=".json,application/json"></label>
<button type="button" class="primary" id="exportFinal" disabled>全フレーム完了のJSONを出力</button>
</div>
<p class="muted">ダウンロードしたJSONにも映像の画像データは含めません。ただし注釈座標を含むため非公開で保管すること。ここで出力しても署名・独立確認は未完了です。外部への通信やブラウザ保存はしません。</p>
<p id="status" class="error" aria-live="polite"></p>
</div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const seed=JSON.parse(document.getElementById("payload").textContent);
const frames=seed.frames;
let n=0;
let reviews=frames.map(f=>({
 frame_sha256:f.frame_sha256,exhaustive_visible_targets:false,annotations:[]
}));
const $=id=>document.getElementById(id);
const photo=$("photo"),canvas=$("layer"),ctx=canvas.getContext("2d");
let drag=null;
for(let k=1;k<=9;k++){
 for(let id of ["car","rank"]){const o=document.createElement("option");o.value=String(k);o.textContent=String(k);$(id).appendChild(o);}
}
frames.forEach((f,i)=>{let o=document.createElement("option");o.value=String(i);o.textContent=String(i+1)+" / "+frames.length; $("frameSelect").appendChild(o)});
function status(message){$("status").textContent=message||""}
function render(){
 const r=reviews[n],f=frames[n];
 $("frameSelect").value=String(n);
 $("timestamp").textContent="録画 "+f.recording_sec+"秒・レビュー担当 "+seed.reviewer_id;
 photo.src=f.image_data_url;
 $("exhaustive").checked=r.exhaustive_visible_targets;
 $("prev").disabled=n===0;
 $("next").disabled=n===frames.length-1;
 draw();
 const total=reviews.filter(x=>x.exhaustive_visible_targets).length;
 $("progress").textContent=total+"/"+reviews.length+"フレーム確認";
 $("exportFinal").disabled=total!==reviews.length;
 const target=$("annotations");target.textContent="";
 const table=document.createElement("table"),head=document.createElement("tr");
 for(let name of ["番号","車番","根拠","位置","ライン","操作"]){let t=document.createElement("th");t.textContent=name;head.appendChild(t)}table.appendChild(head);
 r.annotations.forEach((a,i)=>{
  const tr=document.createElement("tr");
  for(const field of [String(i+1),String(a.car_number),a.number_evidence,String(a.race_position),a.line_role]){
   const td=document.createElement("td");td.textContent=field;tr.appendChild(td);
  }
  const td=document.createElement("td"),b=document.createElement("button");b.type="button";b.textContent="削除";
  b.addEventListener("click",()=>{r.annotations.splice(i,1);r.exhaustive_visible_targets=false;render()});td.appendChild(b);tr.appendChild(td);table.appendChild(tr);
 });
 target.appendChild(table);
}
function xy(ev){
 const rect=canvas.getBoundingClientRect();
 return [Math.min(1,Math.max(0,(ev.clientX-rect.left)/rect.width)),
         Math.min(1,Math.max(0,(ev.clientY-rect.top)/rect.height))];
}
function draw(){
 const rect=canvas.getBoundingClientRect(),dpr=Math.max(1,window.devicePixelRatio||1);
 if(!rect.width||!rect.height)return;
 canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);
 ctx.setTransform(dpr,0,0,dpr,0,0);
 ctx.clearRect(0,0,rect.width,rect.height);ctx.lineWidth=2;
 for(const [i,a] of reviews[n].annotations.entries()){
  const [x,y,w,h]=a.bbox_xywh;
  ctx.strokeStyle="#f8dc68";
  ctx.strokeRect(x*rect.width,y*rect.height,w*rect.width,h*rect.height);
  ctx.fillStyle="#091622";ctx.fillRect(x*rect.width,y*rect.height,33,19);
  ctx.fillStyle="#fff";ctx.font="12px sans-serif";ctx.fillText(String(i+1),x*rect.width+3,y*rect.height+14);
 }
 if(drag){
  const [sx,sy]=drag.start,[ex,ey]=drag.current;
  ctx.strokeStyle="#68e4fb";ctx.strokeRect(Math.min(sx,ex)*rect.width,Math.min(sy,ey)*rect.height,
   Math.abs(ex-sx)*rect.width,Math.abs(ey-sy)*rect.height);
 }
}
photo.addEventListener("load",draw);
window.addEventListener("resize",draw);
canvas.addEventListener("pointerdown",ev=>{
 if(ev.button!==0 && ev.pointerType==="mouse")return;
 ev.preventDefault();const point=xy(ev);drag={id:ev.pointerId,start:point,current:point};
 canvas.setPointerCapture(ev.pointerId);draw();
});
canvas.addEventListener("pointermove",ev=>{if(!drag||drag.id!==ev.pointerId)return;drag.current=xy(ev);draw()});
canvas.addEventListener("pointerup",ev=>{
 if(!drag||drag.id!==ev.pointerId)return;
 ev.preventDefault();const [x0,y0]=drag.start,[x1,y1]=xy(ev);
 drag=null;
 const [x,y,w,h]=[Math.min(x0,x1),Math.min(y0,y1),Math.abs(x1-x0),Math.abs(y1-y0)];
 if(w<.005||h<.005){status("枠が小さすぎる。もう少し広く囲んでください");draw();return}
 const car=$("car").value,reason=$("evidence").value,rank=$("rank").value,line=$("line").value;
 if((car==="UNKNOWN") !== (reason==="UNKNOWN")){status("車番が不明なら根拠も不明に。車番を選ぶ場合は根拠を選んでください");draw();return}
 reviews[n].annotations.push({
  bbox_xywh:[x,y,w,h].map(v=>Math.round(v*1e6)/1e6),
  car_number:car==="UNKNOWN"?"UNKNOWN":Number(car),
  number_evidence:reason,
  race_position:rank==="UNKNOWN"?"UNKNOWN":Number(rank),
  line_role:line
 });
 // A previously selected car must never silently carry into the next
 // rectangle or frame. Make each number/evidence assignment deliberate.
 for(const id of ["car","evidence","rank","line"])$(id).value="UNKNOWN";
 reviews[n].exhaustive_visible_targets=false;status("");render();
});
$("undo").addEventListener("click",()=>{reviews[n].annotations.pop();reviews[n].exhaustive_visible_targets=false;render()});
$("clear").addEventListener("click",()=>{reviews[n].annotations=[];reviews[n].exhaustive_visible_targets=false;render()});
$("exhaustive").addEventListener("change",ev=>{reviews[n].exhaustive_visible_targets=ev.target.checked;render()});
$("prev").addEventListener("click",()=>{n=Math.max(0,n-1);render()});
$("next").addEventListener("click",()=>{n=Math.min(frames.length-1,n+1);render()});
$("frameSelect").addEventListener("change",e=>{n=Number(e.target.value);render()});
function draft(){
 return {
  schema:seed.draft_schema,
  race_id:seed.race_id,
  recording_sha256:seed.recording_sha256,
  proposal_sha256:seed.proposal_sha256,
  reviewer_id:seed.reviewer_id,
  target_kind:seed.target_kind,
  packet_manifest_sha256:seed.packet_manifest_sha256,
  frames:reviews
 };
}
function download(complete){
 if(complete&&!reviews.every(r=>r.exhaustive_visible_targets)){status("全フレームの確認チェックが必要");return}
 const data=JSON.stringify(draft(),null,2)+"\n";
 const blob=new Blob([data],{type:"application/json"});
 const url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download=seed.race_id+"_"+seed.reviewer_id+"_"+(complete?"READY":"DRAFT")+".json";
 document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
 status("保存したJSONは非公開で保管してください。独立した署名と所有者検証は別工程です。");
}
$("exportDraft").addEventListener("click",()=>download(false));
$("exportFinal").addEventListener("click",()=>download(true));
$("importDraft").addEventListener("change",async ev=>{
 const file=ev.target.files[0];if(!file)return;
 try{
  if(file.size>2_000_000)throw Error("JSONサイズが大きすぎる");
  const obj=JSON.parse(await file.text());
  if(obj.schema!==seed.draft_schema||obj.race_id!==seed.race_id||
    obj.recording_sha256!==seed.recording_sha256||
    obj.proposal_sha256!==seed.proposal_sha256||
    obj.reviewer_id!==seed.reviewer_id||
    obj.packet_manifest_sha256!==seed.packet_manifest_sha256||
    obj.target_kind!==seed.target_kind||!Array.isArray(obj.frames)||
    obj.frames.length!==frames.length)throw Error("別のレース・レビュアーのJSONです");
  if(obj.frames.some((r,i)=>r.frame_sha256!==frames[i].frame_sha256||
    !Array.isArray(r.annotations)||typeof r.exhaustive_visible_targets!=="boolean"))
    throw Error("フレーム一覧が一致しません");
  reviews=obj.frames;n=0;status("途中保存の回答を復元。未確認・車番不明はそのまま確認してください。");render();
 }catch(e){status("復元拒否: "+e.message)}
 ev.target.value="";
});
render();
</script>
</body></html>""";


def build(*,packet_dir,output_file):
    info=checked_packet(packet_dir)
    dest=Path(output_file)
    need(dest.parent.is_dir() and dest.parent.stat().st_mode&0o077==0 and
         not dest.exists() and not dest.is_symlink(),
         "PRIVATE_WORKBENCH_MUST_BE_CREATE_ONCE")
    payload=json.dumps(info,ensure_ascii=False,separators=(",",":"))
    payload=payload.replace("</","<\\/")
    page=HTML.replace("__PAYLOAD__",payload).encode("utf-8")
    need(len(page)<=150_000_000,"WORKBENCH_TOO_LARGE_FOR_LOCAL_BROWSER")
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    with os.fdopen(os.open(dest,flags,0o600),"wb") as f:
        f.write(page);f.flush();os.fsync(f.fileno())
    need(dest.read_bytes()==page,"PRIVATE_WORKBENCH_READBACK_FAILED")
    return {
        "race_id":info["race_id"],"reviewer_id":info["reviewer_id"],
        "source_image_count":len(info["frames"]),
        "workbench_sha256":sha256(page).hexdigest(),
        "frame_source_manifest_sha256":info["packet_manifest_sha256"],
        "contains_unencrypted_private_video_frames":True,
        "allowed_to_upload_to_public_GitHub":False,
        "prediction_boxes_or_CI_result_visible":False,
        "second_independent_review_completed":False,
        "reviewer_identity_cryptographically_attested":False,
    }


def main():
    p=ArgumentParser()
    p.add_argument("--private-packet-dir",type=Path,required=True)
    p.add_argument("--private-html-output",type=Path,required=True)
    x=p.parse_args()
    report=build(packet_dir=x.private_packet_dir,output_file=x.private_html_output)
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
