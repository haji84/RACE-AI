"""Read-only GitHub run for a newly added freeze anchor; NOT proof of cutoff."""
import json,os,re,subprocess
from pathlib import Path

PAT=re.compile(r"audit/freezes/\d{4}-\d{2}-\d{2}/[a-f0-9]{64}\.json\Z")
class WitnessError(ValueError):pass
def unique(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise WitnessError("duplicate anchor key")
        d[k]=v
    return d
def validate(path,payload):
    if not PAT.fullmatch(path) or len(payload)>10000:
        raise WitnessError("bad path/size")
    try:obj=json.loads(payload,object_pairs_hook=unique)
    except WitnessError:raise
    except ValueError as e:raise WitnessError("invalid anchor") from e
    if not isinstance(obj,dict) or set(obj)!={"schema","race_id","prediction_sha256","cutoff_at"}:
        raise WitnessError("unexpected anchor fields")
    if obj["schema"]!="RACE_AI_GITHUB_FREEZE_ANCHOR_V1":
        raise WitnessError("anchor schema mismatch")
    if not isinstance(obj["race_id"],str) or not 8<=len(obj["race_id"])<=250:
        raise WitnessError("invalid race ID")
    if not isinstance(obj["prediction_sha256"],str) or not re.fullmatch(r"[a-f0-9]{64}",obj["prediction_sha256"]):
        raise WitnessError("prediction SHA missing")
    from datetime import datetime
    try:t=datetime.fromisoformat(obj["cutoff_at"].replace("Z","+00:00"))
    except (ValueError,AttributeError) as e:raise WitnessError("bad cutoff") from e
    if t.utcoffset() is None:raise WitnessError("cutoff timezone missing")
    return True
def run():
    if os.environ.get("GITHUB_EVENT_NAME")!="push":
        raise WitnessError("push event required")
    sha=os.environ.get("GITHUB_SHA","")
    if not re.fullmatch(r"[a-f0-9]{40}",sha):
        raise WitnessError("actual GitHub event SHA required")
    def git(*a):return subprocess.check_output(["git",*a],text=True).strip()
    if git("rev-parse","HEAD")!=sha:
        raise WitnessError("checkout/event SHA mismatch")
    changed=git("diff-tree","--no-commit-id","--name-status","-r","HEAD").splitlines()
    if not changed:raise WitnessError("no anchors in pushed commit")
    for line in changed:
        status,separator,path=line.partition("\t")
        if not separator or status!="A":
            raise WitnessError("only append-only new files permitted")
        validate(path,Path(path).read_bytes())
    print("STRUCTURE_OK_NOT_INDEPENDENT_CUTOFF_PROOF")
    print("RUN_ID",os.environ.get("GITHUB_RUN_ID","unknown"))
    print("COMMIT",sha)
if __name__=="__main__":run()
