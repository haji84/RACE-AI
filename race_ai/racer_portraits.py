"""Validated portrait catalogue, fixed local assets, and bounded offline selection."""
import base64
import json
from pathlib import Path
import re

WEB = Path(__file__).resolve().parents[1] / 'web'
IDENTITY_FIELDS = ('registration_no','registration_number','registration_id','racer_registration_id','racer_id','participant_id')


def _need(condition):
    if not condition:raise ValueError('PORTRAIT_CATALOGUE_INVALID')


def validate_catalogue(doc):
    _need(type(doc) is dict and set(doc)=={'schema','total','roster_sha256','assets','people'})
    _need(doc['schema']=='RACE_AI_RACER_PORTRAITS_V2' and type(doc['total']) is int and 0<doc['total']<=10000)
    _need(type(doc['roster_sha256']) is str and re.fullmatch('[a-f0-9]{64}',doc['roster_sha256']))
    _need(type(doc['people']) is list and len(doc['people'])==doc['total'] and type(doc['assets']) is dict and len(doc['assets'])<=2000)
    for name,entry in doc['assets'].items():
        _need(type(name) is str and re.fullmatch(r'assets/racer-portraits/(?:boat-\d{4}|sheet-\d{4})\.webp',name))
        _need(type(entry) is dict and set(entry)=={'sha256','bytes'} and type(entry['sha256']) is str
              and re.fullmatch('[a-f0-9]{64}',entry['sha256']) and type(entry['bytes']) is int and 0<entry['bytes']<=4000000)
    ids=set();used=set();cells=set();geometry={}
    for person in doc['people']:
        _need(type(person) is dict)
        base={'registration','name','aliases','state'}
        ready={'asset','source_url','source_photo_sha256','atlas'}
        _need(set(person)==base|(ready if person.get('state')=='READY' else set()))
        number=person['registration']
        _need(type(number) is str and re.fullmatch(r'\d{4}',number) and number not in ids);ids.add(number)
        _need(type(person['name']) is str and 0<len(person['name'])<=100 and type(person['aliases']) is list
              and 0<len(person['aliases'])<=8 and all(type(n) is str and 0<len(n)<=100 for n in person['aliases'])
              and person['name'] in person['aliases'] and len(set(person['aliases']))==len(person['aliases']))
        _need(person['state'] in ('READY','PENDING','SOURCE_UNAVAILABLE'))
        if person['state']!='READY':continue
        file=person['asset'];_need(type(file) is str and file in doc['assets']);used.add(file)
        _need(person['source_url']=='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban='+number)
        _need(type(person['source_photo_sha256']) is str and re.fullmatch('[a-f0-9]{64}',person['source_photo_sha256']))
        atlas=person['atlas']
        if atlas is None:_need(file=='assets/racer-portraits/boat-'+number+'.webp');continue
        _need(type(atlas) is dict and set(atlas)=={'columns','rows','slot'})
        columns,rows,slot=atlas['columns'],atlas['rows'],atlas['slot']
        _need(type(columns) is int and columns in (5,6) and type(rows) is int and rows==columns
              and type(slot) is int and 0<=slot<columns*rows and (file,slot) not in cells)
        _need(file not in geometry or geometry[file]==(columns,rows));geometry[file]=(columns,rows);cells.add((file,slot))
    _need(used==set(doc['assets']))
    return doc


def files_from_catalogue(doc):
    validate_catalogue(doc)
    return ('racer-portraits.js','racer-portraits-data.js','data/racer-portraits.json')+tuple(sorted(doc['assets']))


def needed_assets(doc,view):
    validate_catalogue(doc)
    if view.get('dataset_status')=='SYNTHETIC_ONLY':return ()
    by={p['registration']:p for p in doc['people'] if p['state']=='READY'};needed=set()
    for race in view.get('records',[]):
        if not isinstance(race,dict) or race.get('sport')!='boat' or race.get('scope')=='synthetic' or race.get('synthetic') is True:continue
        for person in race.get('participants',[]) or []:
            if not isinstance(person,dict) or person.get('placeholder'):continue
            ids=[person[key] for key in IDENTITY_FIELDS if key in person]
            if not ids or any(type(n) is not str or n!=ids[0] for n in ids):continue
            entry=by.get(ids[0])
            if entry is None:continue
            name=person.get('name')
            if name is not None and (type(name) is not str or ''.join(name.split()) not in [''.join(n.split()) for n in entry['aliases']]):continue
            needed.add(entry['asset'])
    return tuple(sorted(needed))


CATALOGUE=validate_catalogue(json.loads((WEB/'data/racer-portraits.json').read_text()))
REGISTRATIONS=tuple(p['registration'] for p in CATALOGUE['people'] if p['state']=='READY')
IMAGES=tuple(sorted(CATALOGUE['assets']))
FILES=files_from_catalogue(CATALOGUE)


def inline_script(body, read, *, view=None):
    """Embed only the view's necessary assets; an atlas is included once."""
    marker = 'const embedded = null;'
    if body.count(marker) != 1:
        raise ValueError('SAVED_PORTRAIT_SCRIPT_INVALID')
    paths=IMAGES if view is None else needed_assets(CATALOGUE,view)
    images = {path: 'data:image/webp;base64,' + base64.b64encode(read(path)).decode('ascii') for path in paths}
    return body.replace(marker, 'const embedded = ' + json.dumps(images, separators=(',', ':')) + ';')
