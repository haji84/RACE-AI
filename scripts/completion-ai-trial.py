"""Real local-model constrained code generation; never exec/eval generated code."""
import ast, hashlib, json, operator, os, sys, time, urllib.request
from pathlib import Path
MODEL="qwen2.5-coder:3b"
DIGEST="f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225"
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.FloorDiv:operator.floordiv}
ALLOWED={ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.BinOp,ast.UnaryOp,ast.UAdd,ast.USub,ast.Name,ast.Load,ast.Constant,*OPS}
TASKS=[
 {"id":"add","args":["a","b"],"requirement":"Return the sum of the two integers.","cases":[((0,0),0),((-3,8),5),((-7,-9),-16),((1000,2000),3000)]},
 {"id":"sum_to","args":["n"],"requirement":"For integer n >= 0 return the integer sum from 0 through n inclusive using one arithmetic expression.","cases":[((n,),sum(range(n+1))) for n in range(31)]+[((100,),5050)]}
]
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k): raise ValueError("REDIRECT_FORBIDDEN")
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def api(path,payload=None,timeout=150):
 if path not in ("/api/tags","/api/generate"): raise ValueError("ENDPOINT_NOT_ALLOWED")
 req=urllib.request.Request("http://127.0.0.1:11434"+path,data=None if payload is None else json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
 with OPENER.open(req,timeout=timeout) as r:
  raw=r.read(65537)
  if len(raw)>65536: raise ValueError("RESPONSE_TOO_LARGE")
 return json.loads(raw)
def identity():
 matched=[m for m in api("/api/tags",timeout=5).get("models",[]) if m.get("name")==MODEL]
 if len(matched)!=1 or str(matched[0].get("digest","")).removeprefix("sha256:")!=DIGEST: raise ValueError("MODEL_IDENTITY_MISMATCH")
 return {"name":MODEL,"digest":DIGEST}
def clean(raw):
 if len(raw.encode())>4096: raise ValueError("CODE_TOO_LARGE")
 lines=raw.strip().splitlines()
 if lines and lines[0] in ("```python","```"):
  if len(lines)<3 or lines[-1]!="```": raise ValueError("INVALID_CODE_FENCE")
  return "\n".join(lines[1:-1])
 return raw.strip()
def expression(code,task):
 tree=ast.parse(code)
 nodes=list(ast.walk(tree))
 if len(nodes)>128 or any(type(n) not in ALLOWED for n in nodes): raise ValueError("AST_NOT_ALLOWED")
 if len(tree.body)!=1 or type(tree.body[0]) is not ast.FunctionDef: raise ValueError("ONE_FUNCTION_REQUIRED")
 fn=tree.body[0]; a=fn.args
 if fn.name!=task["id"] or fn.decorator_list or fn.returns or getattr(fn,"type_params",[]) or fn.type_comment: raise ValueError("SIGNATURE_INVALID")
 if a.posonlyargs or a.vararg or a.kwonlyargs or a.kwarg or a.defaults or a.kw_defaults or [x.arg for x in a.args]!=task["args"] or any(x.annotation or x.type_comment for x in a.args): raise ValueError("ARGS_INVALID")
 if len(fn.body)!=1 or type(fn.body[0]) is not ast.Return: raise ValueError("ONE_RETURN_REQUIRED")
 for n in nodes:
  if type(n) is ast.Name and n.id not in task["args"]: raise ValueError("UNKNOWN_NAME")
  if type(n) is ast.Constant and (type(n.value) is not int or abs(n.value)>10000): raise ValueError("CONSTANT_INVALID")
 return fn.body[0].value
def interpret(node,names,depth=0):
 if depth>20: raise ValueError("EXPRESSION_TOO_DEEP")
 if type(node) is ast.Constant: result=node.value
 elif type(node) is ast.Name: result=names[node.id]
 elif type(node) is ast.BinOp and type(node.op) in OPS: result=OPS[type(node.op)](interpret(node.left,names,depth+1),interpret(node.right,names,depth+1))
 elif type(node) is ast.UnaryOp and type(node.op) in (ast.UAdd,ast.USub):
  result=interpret(node.operand,names,depth+1)
  if type(node.op) is ast.USub: result=-result
 else: raise ValueError("EXPRESSION_INVALID")
 if type(result) is not int or abs(result)>10**12: raise ValueError("RESULT_OUT_OF_BOUNDS")
 return result
def verify(code,task):
 expr=expression(code,task)
 for args,expected in task["cases"]:
  if interpret(expr,dict(zip(task["args"],args)))!=expected: raise ValueError("FIXED_TEST_FAILED")
 return len(task["cases"])
def save(path,receipt):
 tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(receipt,indent=2)+"\n");os.replace(tmp,path)
def run(path):
 if path.exists(): raise ValueError("RECEIPT_ALREADY_EXISTS")
 path.parent.mkdir(parents=True,exist_ok=True)
 model=identity()
 receipt={"kind":"BOUNDED_LOCAL_MODEL_CODEGEN_V1","model":model,"general_developer_agent":False,"generated_code_execution":"restricted_ast_interpreter_only","deployment":False,"attempts":[],"completed":[],"status":"RUNNING"}
 save(path,receipt)
 try:
  for task in TASKS:
   if task["id"]=="sum_to" and receipt["completed"]!=["add"]: raise ValueError("DEPENDENCY_NOT_VERIFIED")
   feedback=""
   for attempt in (1,2):
    identity()
    prompt=("Write exactly one Python function, no prose or markdown, imports, annotations, defaults, decorators or docstrings. Body must be one return statement. Expression may use only argument names, integer constants, parentheses, +, -, *, //; no calls, loops, conditionals, attributes or indexing.\nSignature: def "+task["id"]+"("+", ".join(task["args"])+"):\nRequirement: "+task["requirement"]+"\n"+feedback)
    started=time.monotonic()
    response=api("/api/generate",{"model":MODEL,"prompt":prompt,"stream":False,"keep_alive":"5m","options":{"temperature":0,"seed":17,"num_predict":256,"num_ctx":2048}})
    if response.get("done") is not True or response.get("model")!=MODEL or response.get("done_reason")!="stop" or type(response.get("eval_count")) is not int or response["eval_count"]<=0: raise ValueError("INFERENCE_RECEIPT_INVALID")
    raw=response.get("response")
    if not isinstance(raw,str): raise ValueError("MODEL_RESPONSE_INVALID")
    record={"task_id":task["id"],"attempt":attempt,"elapsed_seconds":round(time.monotonic()-started,3),"raw_sha256":hashlib.sha256(raw.encode()).hexdigest(),"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"eval_count":response["eval_count"],"model_digest":DIGEST}
    try:
     code=clean(raw);record["code"]=code;record["code_sha256"]=hashlib.sha256(code.encode()).hexdigest()
     record["tests_passed"]=verify(code,task);record["accepted"]=True
    except (ValueError,SyntaxError,ZeroDivisionError) as e:
     record["accepted"]=False;record["failure_type"]=type(e).__name__
    receipt["attempts"].append(record)
    if record["accepted"]:
     receipt["completed"].append(task["id"]);save(path,receipt);break
    save(path,receipt)
    feedback="Previous answer failed syntax or correctness tests. Correct it while obeying every restriction."
   else: raise ValueError("MODEL_TASK_FAILED_AFTER_TWO_ATTEMPTS")
  receipt["status"]="PASS";save(path,receipt);print(json.dumps(receipt))
 except Exception:
  receipt["status"]="BLOCKED";save(path,receipt);raise
def self_test():
 import tempfile
 assert verify("def add(a,b):\n return a+b",TASKS[0])==4
 assert verify("def sum_to(n):\n return n*(n+1)//2",TASKS[1])==32
 bad=["import os\ndef add(a,b):\n return a+b","def add(a,b):\n return abs(a)","def add(a,b):\n return a.real","def add(a,b):\n return c","def add(a,b):\n return 10001","def add(a,b):\n return a-b","def add(a,b):\n return True","def add(a,b):\n return "+"+".join(["a"]*140),"def add(a,b):\n return "+"("*22+"a"+"+1)"*22]
 for code in bad:
  try: verify(code,TASKS[0])
  except (ValueError,SyntaxError): pass
  else: raise AssertionError("unsafe/incorrect code accepted")
 try: clean("```python\ndef add(a,b): return a+b")
 except ValueError: pass
 else: raise AssertionError("unclosed fence")
 # Stub transport only in self-test, never in live run.
 global api
 original=api
 with tempfile.TemporaryDirectory() as directory:
  calls=[]
  def stub(path,payload=None,timeout=150):
   if path=="/api/tags": return {"models":[{"name":MODEL,"digest":DIGEST}]}
   calls.append(payload["prompt"])
   code="def add(a,b):\n return a+b" if len(calls)==1 else "def sum_to(n):\n return n*(n+1)//2"
   return {"done":True,"model":MODEL,"done_reason":"stop","eval_count":10,"response":code}
  api=stub
  try:
   p=Path(directory)/"receipt.json";run(p)
   assert len(calls)==2 and json.loads(p.read_text())["completed"]==["add","sum_to"]
   calls.clear()
   def failing(path,payload=None,timeout=150):
    if path=="/api/tags": return {"models":[{"name":MODEL,"digest":DIGEST}]}
    calls.append(1);return {"done":True,"model":MODEL,"done_reason":"stop","eval_count":10,"response":"def add(a,b):\n return a-b"}
   api=failing
   try: run(Path(directory)/"failed.json")
   except ValueError as e: assert str(e)=="MODEL_TASK_FAILED_AFTER_TWO_ATTEMPTS"
   else: raise AssertionError("failed model accepted")
   assert len(calls)==2
  finally: api=original
 print("SELF_TEST_PASS: verifier rejection, bounded retries, dependency and receipt")
if __name__=="__main__":
 if sys.argv[1:]==["--self-test"]: self_test()
 elif len(sys.argv)==3 and sys.argv[1]=="--output": run(Path(sys.argv[2]))
 else: raise SystemExit("usage: --self-test | --output PATH")
