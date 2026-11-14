"""Read saved PDCA originals in the existing personal UI, with no collection."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .boat_pdca_projection import project_pdca
from .boat_pdca_state import PdcaState
from .local_forecast_server import make_server,_asset_bytes
from scripts.boat_history_collect import private_root,save

WEB=Path(__file__).resolve().parents[1]/'web'


class SavedPdcaService:
    saved_only=True
    automatic_supported=False

    def __init__(self,path):
        state=PdcaState(path)
        try:self.view=project_pdca(state)
        finally:state.close()

    def saved_projection(self):return deepcopy(self.view)

    def status(self):return dict(ready=False,saved_only=True,capabilities={})

    def generate(self,*_):raise PermissionError('SAVED_ORIGINALS_READ_ONLY')


def export_view(view,output,*,web_root=WEB):
    """A private, self-contained file; script hashes keep the existing CSP strict."""
    html=_asset_bytes(web_root,'index.html').decode()
    styles=_asset_bytes(web_root,'style.css').decode()
    scripts=[]
    for name in ('forecast-audit-model.js','product-data.js','existing-model-catalog.js','ui-model.js','saved-performance.js','racer-portraits-data.js','racer-portraits.js','racer-profiles-data.js','racer-profiles.js','racer-daily.js','app.js'):
        body=_asset_bytes(web_root,name).decode()
        if name=='racer-portraits.js':
            from .racer_portraits import inline_script
            body=inline_script(body,lambda path:_asset_bytes(web_root,path),view=view)
        if name=='racer-daily.js':
            daily=json.loads(_asset_bytes(web_root,'data/racer-daily.json'))
            encoded=json.dumps(daily,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
            if body.count('const embedded = null;')!=1:raise ValueError('SAVED_DAILY_SCRIPT_INVALID')
            body=body.replace('const embedded = null;','const embedded = '+encoded+';')
        if re.search('</script',body,re.I):raise ValueError('SAVED_VIEW_SCRIPT_INVALID')
        scripts.append(body)
        html=html.replace('<script defer src="./'+name+'"></script>','')
    if re.search('</style',styles,re.I):raise ValueError('SAVED_VIEW_STYLE_INVALID')
    def pin(body):return "'sha256-"+base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()+"'"
    html=html.replace('<link rel="stylesheet" href="./style.css">','<style>'+styles+'</style>')
    html=html.replace("script-src 'self'","script-src "+' '.join(map(pin,scripts)))
    html=html.replace("style-src 'self'","style-src "+pin(styles)).replace("connect-src 'self'","connect-src 'none'")
    raw=json.dumps(view,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('<','\\u003c')
    content='<script type="application/json" id="race-ai-private-saved-data">'+raw+'</script>\n'
    content+='\n'.join('<script>'+body+'</script>' for body in scripts)
    html=html.replace('</body>',content+'\n</body>')
    output=Path(output);private_root(output.absolute().parent);save(output,html.encode())
    return dict(saved_races=len(view['records']),saved_predictions=sum(1+len(r.get('comparison_predictions',[])) for r in view['records']))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--export',type=Path)
    parser.add_argument('--port',type=int,default=8875)
    args=parser.parse_args(argv);service=SavedPdcaService(args.state)
    if args.export:
        print(json.dumps(export_view(service.saved_projection(),args.export)));return 0
    with make_server(service,port=args.port,automatic=False) as server:
        print('RACE AI saved originals: '+server.origin,flush=True)
        server.serve_forever()
    return 0


if __name__=='__main__':raise SystemExit(main())
