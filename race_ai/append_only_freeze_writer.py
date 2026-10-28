"""Opt-in, create-only GitHub fingerprint writer; never a timing witness."""
import base64
from datetime import datetime,timezone
import hashlib,json,re
from urllib.parse import quote
from urllib.request import Request,urlopen

REPO="haji84/RACE-AI"
BASE="https://api.github.com/repos/"+REPO
class FreezeWriteError(ValueError):pass

def _t(t):
    try:v=datetime.fromisoformat(t.replace("Z","+00:00"))
    except (ValueError,AttributeError) as e:raise FreezeWriteError("bad timestamp") from e
    if v.utcoffset() is None:raise FreezeWriteError("naive timestamp")
    return v.astimezone(timezone.utc)

def _bytes(value):
    return (json.dumps(value,sort_keys=True,separators=(",",":"),
                       ensure_ascii=False,allow_nan=False)+"\n").encode("utf-8")

def prepare_anchor(binding,model_id,generated_at,persisted_at):
    if not isinstance(binding,dict) or binding.get("schema")!="RACE_AI_P0_SOURCE_MODEL_BINDING_V1":
        raise FreezeWriteError("PR72 binding required")
    rows=[x for x in binding.get("models",[]) if x.get("model_id")==model_id]
    if len(rows)!=1:raise FreezeWriteError("one model required")
    m=rows[0];sha=m.get("prediction_sha256");deadline=binding.get("model_claimed_cutoff_at")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha):
        raise FreezeWriteError("prediction hash missing")
    if not _t(generated_at)<=_t(persisted_at)<_t(deadline):
        raise FreezeWriteError("local creation after cutoff")
    if binding.get("external_freeze_verified") is not False or binding.get("eligible_for_scoring") is not False:
        raise FreezeWriteError("untrusted proof promotion")
    race=binding.get("model_race_id");day=binding.get("event_date_jst")
    if not isinstance(race,str) or not race or not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d\d-\d\d",day):
        raise FreezeWriteError("race identity or day absent")
    anchor={"schema":"RACE_AI_GITHUB_FREEZE_ANCHOR_V1","race_id":race,
            "prediction_sha256":sha,"cutoff_at":deadline}
    name=hashlib.sha256((race+"\0"+model_id+"\0"+sha).encode()).hexdigest()
    return {"path":f"audit/freezes/{day}/{name}.json","anchor":anchor,
            "status":"PREPARED_NOT_WRITTEN","eligible_for_hit_at_8":False}

def submit_anchor(prepared,branch,token,independent_release_check,request=None):
    if not isinstance(prepared,dict) or prepared.get("status")!="PREPARED_NOT_WRITTEN":
        raise FreezeWriteError("unprepared anchor")
    if not callable(independent_release_check) or independent_release_check(prepared) is not True:
        raise FreezeWriteError("source/public release not independently approved")
    if not isinstance(branch,str) or not re.fullmatch(r"[a-zA-Z0-9._/-]{1,100}",branch) or ".." in branch or "//" in branch:
        raise FreezeWriteError("existing safe branch required")
    if not isinstance(token,str) or len(token)<20:
        raise FreezeWriteError("private GitHub token required")
    path=prepared["path"]
    if not re.fullmatch(r"audit/freezes/\d{4}-\d\d-\d\d/[a-f0-9]{64}\.json",path):
        raise FreezeWriteError("anchor path invalid")
    raw=_bytes(prepared["anchor"])
    base=BASE+"/contents/"+quote(path,safe="/")
    def transport(url,method,data=None):
        req=Request(url,data=data,method=method,headers={
            "Accept":"application/vnd.github+json",
            "Content-Type":"application/json",
            "User-Agent":"RACE-AI-proof-writer/1",
            "Authorization":"Bearer "+token})
        with urlopen(req,timeout=12) as response:
            if response.geturl()!=url:raise FreezeWriteError("GitHub redirect")
            payload=response.read(100001)
            if len(payload)>100000:raise FreezeWriteError("oversized GitHub response")
            return json.loads(payload)
    sender=request or transport
    body=_bytes({"message":"audit: create forecast hash fingerprint",
                 "content":base64.b64encode(raw).decode("ascii"),"branch":branch})
    result=sender(base,"PUT",body) # no SHA field, existing file is rejected
    commit=result.get("commit",{}).get("sha") if isinstance(result,dict) else None
    if not isinstance(commit,str) or not re.fullmatch(r"[a-f0-9]{40}",commit):
        raise FreezeWriteError("server commit SHA missing")
    check=sender(base+"?ref="+commit,"GET",None)
    if not isinstance(check,dict) or check.get("encoding")!="base64" or check.get("type")!="file":
        raise FreezeWriteError("pinned readback unavailable")
    try:seen=base64.b64decode("".join(check["content"].split()),validate=True)
    except (ValueError,KeyError) as exc:raise FreezeWriteError("bad pinned readback") from exc
    if seen!=raw:raise FreezeWriteError("immutable content mismatch")
    return {"path":path,"commit_sha":commit,"prediction_sha256":prepared["anchor"]["prediction_sha256"],
            "model_race_id":prepared["anchor"]["race_id"],
            "run_id":None,"external_server_time":None,
            "eligible_for_hit_at_8":False,
            "status":"COMMIT_EXISTS_BUT_PRE_CUTOFF_PROOF_UNVERIFIED"}
