"""Bounded real-model repair of existing controller code in an isolated copy.
No generated patch is pushed. No eval/exec: a small expression AST is
re-serialized from fixed terminals before trusted Node acceptance tests run.
"""
import hashlib, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("existing_ai_trial",ROOT/"scripts/completion-ai-trial.py")
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
SOURCE=ROOT/"scripts/completion-controller.mjs"
SOURCE_BLOB="5d3eafc0df48ada28a75ca30114838d342c4240c"
ANCHOR1='export function isVerifiedDone(requirement, mainSha) {\n'
ANCHOR2='typeof e.reference === "string" && e.reference.length > 0;'
TERMS={
 "acceptance":["Array.isArray(requirement.acceptance)","requirement.acceptance.length","0"],
 "reference":["e.reference.trim().length","e.reference.length","0"]
}
OPERATORS=["===","!==",">=","<=","&&","||",">","<","!","(",")"]
REGRESSION=["tests/completion-controller.test.mjs","tests/completion-controller.e2e.test.mjs","tests/ai09-review-handoff.test.mjs"]
def digest(b):return hashlib.sha256(b).hexdigest()
def duplicate_keys(pairs):
 result={}
 for k,v in pairs:
  if k in result:raise ValueError("DUPLICATE_JSON_KEY")
  result[k]=v
 return result

def parse_expression(raw,task):
 if not isinstance(raw,str) or len(raw)>512:raise ValueError("EXPRESSION_SIZE")
 permitted=sorted(TERMS[task]+OPERATORS,key=len,reverse=True)
 tokens=[];pos=0
 while pos<len(raw):
  if raw[pos].isspace():pos+=1;continue
  token=next((t for t in permitted if raw.startswith(t,pos)),None)
  if token is None:raise ValueError("EXPRESSION_TOKEN")
  tokens.append(token);pos+=len(token)
  if len(tokens)>64:raise ValueError("EXPRESSION_TOKEN_LIMIT")
 index=0
 def take(): 
  nonlocal index
  if index>=len(tokens):raise ValueError("EXPRESSION_END")
  t=tokens[index];index+=1;return t
 def parse(level=0,depth=0):
  nonlocal index
  if depth>16:raise ValueError("EXPRESSION_DEPTH")
  if level==3:
   t=take()
   if t=="!":return ("not",parse(3,depth+1))
   if t=="(":
    node=parse(0,depth+1)
    if take()!=")":raise ValueError("EXPRESSION_PAREN")
    return node
   if t not in TERMS[task]:raise ValueError("EXPRESSION_ATOM")
   return ("term",t)
  node=parse(level+1,depth+1)
  choices=({"||"},{"&&"},{"===","!==",">","<",">=","<="})[level]
  count=0
  while index<len(tokens) and tokens[index] in choices:
   op=take();right=parse(level+1,depth+1);node=("binary",op,node,right);count+=1
   if level==2 and count>1:raise ValueError("CHAINED_COMPARISON")
  return node
 tree=parse()
 if index!=len(tokens):raise ValueError("EXPRESSION_TRAILING")
 def render(node):
  if node[0]=="term":return node[1]
  if node[0]=="not":return "(!"+render(node[1])+")"
  return "("+render(node[2])+" "+node[1]+" "+render(node[3])+")"
 return render(tree)

def model_expression(raw,task):
 if not isinstance(raw,str) or len(raw)>2048:raise ValueError("MODEL_RESPONSE_SIZE")
 payload=json.loads(raw,object_pairs_hook=duplicate_keys)
 if not isinstance(payload,dict) or set(payload)!={"expression"}:raise ValueError("MODEL_RESPONSE_SCHEMA")
 return parse_expression(payload["expression"],task)

def original():
 raw=SOURCE.read_bytes()
 blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
 if blob!=SOURCE_BLOB:raise ValueError("SOURCE_PIN_CHANGED")
 source=raw.decode()
 if source.count(ANCHOR1)!=1 or source.count(ANCHOR2)!=1:raise ValueError("SOURCE_ANCHOR_NOT_UNIQUE")
 return source

def patch(source,expressions):
 # Only AST-rendered expressions enter the fixed insertion/replacement sites.
 expected=original()
 if source!=expected:raise ValueError("SOURCE_BYTES_CHANGED")
 if "acceptance" in expressions:
  expression=parse_expression(expressions["acceptance"],"acceptance")
  source=source.replace(ANCHOR1,ANCHOR1+"  if ("+expression+") return false;\n",1)
 if "reference" in expressions:
  if "acceptance" not in expressions:raise ValueError("DEPENDENCY_NOT_VERIFIED")
  expression=parse_expression(expressions["reference"],"reference")
  source=source.replace(ANCHOR2,'typeof e.reference === "string" && '+expression+';',1)
 return source

def node(args,cwd):
 env={"PATH":os.environ["PATH"],"HOME":str(cwd),"TMPDIR":str(cwd),"TEMP":str(cwd),"TMP":str(cwd)}
 result=subprocess.run(["node",*args],cwd=cwd,env=env,capture_output=True,text=True,timeout=60)
 return result

def cases(candidate,stage,cwd):
 return node([str(ROOT/"tests/completion-developer-cases.mjs"),str(candidate),stage],cwd)

def setup_copy(directory):
 directory.mkdir()
 for name in ["scripts/completion-controller.mjs","scripts/ai09-review-handoff.mjs",*REGRESSION]:
  dest=directory/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
 return directory/"scripts/completion-controller.mjs"

def baseline(directory):
 source=original()
 candidate=setup_copy(directory)
 if candidate.read_text()!=source:raise ValueError("BASELINE_COPY_MISMATCH")
 checks={}
 for task,message in [("acceptance","EMPTY_OR_MALFORMED_ACCEPTANCE_MUST_NOT_COMPLETE"),("reference","BLANK_REFERENCE_MUST_NOT_COMPLETE")]:
  r=cases(candidate,task,directory)
  if r.returncode!=1 or message not in r.stderr or "AssertionError" not in r.stderr:raise ValueError("EXPECTED_BASELINE_DEFECT_NOT_REPRODUCED_"+task)
  checks[task]={"expected_failure":message,"exit_code":r.returncode,"log_sha256":digest((r.stdout+r.stderr).encode())}
 regression=node(["--test",*REGRESSION],directory)
 if regression.returncode!=0 or "# tests 14" not in regression.stdout or "# fail 0" not in regression.stdout:raise ValueError("BASELINE_REGRESSION_FAILED")
 return checks

def save(path,value):
 temp=path.with_suffix(".tmp")
 temp.write_text(json.dumps(value,indent=2)+"\n");os.replace(temp,path)

def run(output,diagnostic=False):
 if output.exists():raise ValueError("OUTPUT_ALREADY_EXISTS")
 output.mkdir(parents=True)
 model=backend.identity()
 receipt={"kind":"BOUNDED_EXISTING_CONTROLLER_REPAIR_V1","model":model,"source_blob":SOURCE_BLOB,
          "general_autonomous_developer":False,"generated_patch_pushed":False,"canonical_writeback":False,
          "deployment":False,"completed":[],"attempts":[],"status":"RUNNING"}
 save(output/"receipt.json",receipt)
 source=original();expressions={}
 receipt["baseline"]=baseline(output/"baseline")
 candidate=setup_copy(output/"candidate")
 save(output/"receipt.json",receipt)
 requirements={
 "acceptance":"A completion requirement must have a nonempty Array of acceptance criteria. Write a REJECTION condition, evaluated before acceptance.every: true for [], null, missing, object, string; false for a nonempty array.",
 "reference":"A verified evidence reference must contain non-whitespace text. Write an ACCEPTANCE condition: false for empty or whitespace-only string, true for 'run/123' and ' run/123 '. The preceding existing typeof string guard is preserved."
 }
 try:
  for task in (["acceptance"] if diagnostic else ["acceptance","reference"]):
   if task=="reference" and receipt["completed"]!=["acceptance"]:raise ValueError("DEPENDENCY_NOT_VERIFIED")
   feedback=""
   for attempt in ([1] if diagnostic else [1,2]):
    backend.identity()
    prompt=("Repair one existing JavaScript completion predicate. Return ONLY a JSON object with exactly one key expression, containing a JavaScript boolean expression. No markdown or prose.\n"+
      "Task: "+requirements[task]+"\nAllowed atoms: "+json.dumps(TERMS[task])+
      "\nAllowed operators: ! && || === !== < <= > >= and parentheses. No other identifier, property, call, literal, assignment or statement.\n"+
      "Existing function:\n"+source[source.index(ANCHOR1):source.index("\nexport function recordFailure")]+
      "\n"+feedback)
    started=time.monotonic()
    response=backend.api("/api/generate",{"model":backend.MODEL,"prompt":prompt,"stream":False,"keep_alive":"5m","format":"json","options":{"temperature":0,"seed":17,"num_predict":256,"num_ctx":4096}})
    if response.get("done") is not True or response.get("model")!=backend.MODEL or response.get("done_reason")!="stop" or type(response.get("eval_count")) is not int or response["eval_count"]<=0:raise ValueError("INFERENCE_RECEIPT_INVALID")
    raw=response.get("response")
    if not isinstance(raw,str):raise ValueError("MODEL_RESPONSE_INVALID")
    record={"task":task,"attempt":attempt,"model_response":raw,"prompt_sha256":digest(prompt.encode()),"response_sha256":digest(raw.encode()),"eval_count":response["eval_count"],"elapsed_seconds":round(time.monotonic()-started,3)}
    try:
     expression=model_expression(raw,task)
     proposed={**expressions,task:expression}
     candidate.write_text(patch(source,proposed))
     for accepted in [*receipt["completed"],task]:
      checked=cases(candidate,accepted,candidate.parents[1])
      if checked.returncode:
       record["verification_output"]=(checked.stdout+checked.stderr)[-6000:]
       raise ValueError("INDEPENDENT_ACCEPTANCE_FAILED")
     regression=node(["--test",*REGRESSION],candidate.parents[1])
     if regression.returncode!=0 or "# tests 14" not in regression.stdout or "# fail 0" not in regression.stdout:raise ValueError("EXISTING_REGRESSION_FAILED")
     record.update(accepted=True,expression=expression,candidate_sha256=digest(candidate.read_bytes()),existing_tests_passed=14,acceptance_stages=[*receipt["completed"],task])
    except (ValueError,json.JSONDecodeError) as e:
     record.update(accepted=False,error=str(e))
     candidate.write_text(patch(source,expressions))
    receipt["attempts"].append(record);save(output/"receipt.json",receipt)
    if diagnostic:
     receipt["status"]="DIAGNOSTIC_ONLY";receipt["task_continuation"]=False
     save(output/"receipt.json",receipt);print(json.dumps(receipt));return
    if record["accepted"]:
     expressions[task]=expression;receipt["completed"].append(task);save(output/"receipt.json",receipt);break
    feedback="The previous proposal failed syntax or independent acceptance. Obey the permitted atoms/operators and stated requirement."
   else:raise ValueError("TASK_FAILED_AFTER_TWO_ATTEMPTS")
  if SOURCE.read_text()!=source:raise ValueError("REPOSITORY_SOURCE_MODIFIED")
  receipt["status"]="PASS";receipt["next_task_transition_verified"]=True
  save(output/"receipt.json",receipt)
  print(json.dumps(receipt))
 except Exception:
  receipt["status"]="BLOCKED";save(output/"receipt.json",receipt);print(json.dumps(receipt));raise

def self_test():
 valid={"acceptance":"!Array.isArray(requirement.acceptance) || requirement.acceptance.length === 0","reference":"e.reference.trim().length > 0"}
 for task,expression in valid.items():
  rendered=model_expression(json.dumps({"expression":expression}),task)
  assert parse_expression(rendered,task)==rendered
 for raw in ["process.exit()", "requirement.constructor", "0;process.exit()", "0 //comment", "0 /*x*/", "0 = 0", "0,0","0 0", "0 > 0 > 0", "(" * 30+"0"+")"*30, "! "*70+"0"]:
  try:parse_expression(raw,"acceptance")
  except ValueError:pass
  else:raise AssertionError("unsafe expression accepted")
 for raw in ['{"expression":"0","extra":true}','{"expression":"0","expression":"0"}','{"expression":null}']:
  try:model_expression(raw,"acceptance")
  except (ValueError,json.JSONDecodeError):pass
  else:raise AssertionError("unsafe JSON accepted")
 with tempfile.TemporaryDirectory() as d:
  base=Path(d);baseline(base/"baseline")
  candidate=setup_copy(base/"positive");candidate.write_text(patch(original(),valid))
  for task in valid:assert cases(candidate,task,candidate.parents[1]).returncode==0
  assert node(["--test",*REGRESSION],candidate.parents[1]).returncode==0
 # Transport is replaced only in this self-test; these are not inference receipts.
 import contextlib, io
 original_api=backend.api
 calls=[]
 def stub(path,payload=None,timeout=150):
  if path=="/api/tags":return {"models":[{"name":backend.MODEL,"digest":backend.DIGEST}]}
  assert payload["format"]=={"type":"object","properties":{"expression":{"type":"string","maxLength":512}},"required":["expression"],"additionalProperties":False},"SCHEMA_CONSTRAINED_GENERATION_REQUIRED"
  task="acceptance" if "REJECTION condition" in payload["prompt"] else "reference"
  calls.append(task)
  return {"model":backend.MODEL,"done":True,"done_reason":"stop","eval_count":1,"response":json.dumps({"expression":valid[task]})}
 try:
  backend.api=stub
  with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
   out=Path(d)/"success";run(out)
   assert calls==["acceptance","reference"]
   assert json.loads((out/"receipt.json").read_text())["completed"]==["acceptance","reference"]
  calls.clear()
  def failing(path,payload=None,timeout=150):
   if path=="/api/tags":return stub(path,payload,timeout)
   calls.append("acceptance")
   return {"model":backend.MODEL,"done":True,"done_reason":"stop","eval_count":1,"response":'{"expression":"0"}'}
  backend.api=failing
  with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
   try:run(Path(d)/"failed")
   except ValueError as e:assert str(e)=="TASK_FAILED_AFTER_TWO_ATTEMPTS"
   else:raise AssertionError("failed task advanced")
  assert calls==["acceptance","acceptance"]
  calls.clear()
  with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
   out=Path(d)/"diagnostic";run(out,diagnostic=True)
   record=json.loads((out/"receipt.json").read_text())
   assert calls==["acceptance"] and record["status"]=="DIAGNOSTIC_ONLY" and record["completed"]==[]
   assert record["attempts"][0]["accepted"] is False and record["task_continuation"] is False
 finally:backend.api=original_api
 print("SELF_TEST_PASS: strict grammar, baseline defects, dependency and rejection; NOT model evidence")

if __name__=="__main__":
 if sys.argv[1:]==["--self-test"]:self_test()
 elif len(sys.argv)==3 and sys.argv[1] in ("--output","--diagnose"):run(Path(sys.argv[2]).resolve(),diagnostic=sys.argv[1]=="--diagnose")
 else:raise SystemExit("usage: --self-test | --output PATH | --diagnose PATH")
