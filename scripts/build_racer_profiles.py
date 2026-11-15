"""Compile already acquired public official references; no network or forecasts."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin
from race_ai.boat_racer_term import extract_term,parse_term,term_info
from race_ai.racer_profiles import parse_basic_profile,parse_current_grades,build_catalogue

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--term',required=True)
    parser.add_argument('--roster',type=Path,required=True);parser.add_argument('--basic-dir',type=Path,required=True)
    parser.add_argument('--basic-receipts',type=Path,required=True);parser.add_argument('--web',type=Path,default=Path('web'))
    args=parser.parse_args();portraits=json.loads((args.web/'data/racer-portraits.json').read_text());identities={p['registration']:p for p in portraits['people']}
    raw=args.archive.read_bytes();rows=parse_term(extract_term(raw,term=args.term),term=args.term)
    roster=json.loads(args.roster.read_text());grades={}
    for page in roster['pages']:
        raw_page=(args.roster.parent/page['snapshot']).read_bytes();assert hashlib.sha256(raw_page).hexdigest()==page['sha256']
        parsed=parse_current_grades(raw_page)
        for reg,row in parsed.items():
            assert reg not in grades or grades[reg]==row,'CONFLICTING_CURRENT_RACER_IDENTITY'
            grades[reg]=row
    assert len(grades)==len(roster['people'])
    receipts=json.loads(args.basic_receipts.read_text());basics={}
    for receipt in receipts:
        reg=receipt['registration'];raw_page=(args.basic_dir/('profile-'+reg+'.html')).read_bytes();assert hashlib.sha256(raw_page).hexdigest()==receipt['sha256']
        basics[reg]=parse_basic_profile(raw_page,registration=reg,expected_name=identities[reg]['name'])
        basics[reg]['captured_at']=receipt['captured_at']
    source=dict(url=term_info(args.term)['source_url'],sha256=hashlib.sha256(raw).hexdigest(),
        captured_at=max([roster['captured_at']]+[r['captured_at'] for r in receipts]),
        current_grade_source=dict(url=roster['source_url'],captured_at=roster['captured_at'],pages=[dict(url=roster['source_url'] if p['url']=='first' else urljoin('https://www.boatrace.jp',p['url']),sha256=p['sha256']) for p in roster['pages']]),
        basic_sources=receipts)
    doc=build_catalogue(rows,portraits,basics,grades,source)
    encoded=json.dumps(doc,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (args.web/'data/racer-profiles.json').write_text(encoded+'\n')
    script="/* Public official athlete references, never private race inputs. */\n'use strict';\n(()=>{const data="+encoded+";if(typeof module==='object'&&module.exports)module.exports=data;else globalThis.RaceRacerProfileData=data;})();\n"
    (args.web/'racer-profiles-data.js').write_text(script)
    print(json.dumps({'profiles':len(doc['people']),'with_term':sum(p['term'] is not None for p in doc['people']),'basic_only':sum(p['term'] is None for p in doc['people']),'json_bytes':len(encoded.encode()),'period':doc['period']}))

if __name__=='__main__':main()
