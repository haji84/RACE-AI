"""Public official athlete references, separate from all saved race inputs."""
from datetime import date
import hashlib
import re
from .boat_observation_context import _Tree
from .boat_racer_term import term_info

FILES=('data/racer-profiles.json','racer-profiles-data.js','racer-profiles.js')

def _need(ok):
    if not ok:raise ValueError('RACER_PROFILE_SOURCE_INVALID')

def _name(value):return ''.join(value.split())

def parse_basic_profile(raw,*,registration,expected_name):
    _need(type(raw) is bytes and 0<len(raw)<=500000 and re.fullmatch(r'[0-9]{4}',registration))
    tree=_Tree();tree.feed(raw.decode('utf-8'));root=tree.root
    names=list(root.find('p','racer1_bodyName'));blocks=list(root.find('dl','list3'))
    _need(len(names)==len(blocks)==1 and _name(names[0].text())==_name(expected_name))
    labels=list(blocks[0].find('dt'));values=list(blocks[0].find('dd'));_need(len(labels)==len(values) and len({_name(k.text()) for k in labels})==len(labels))
    fields={_name(k.text()):v.text().strip() for k,v in zip(labels,values)}
    _need(fields.get('登録番号')==registration and fields.get('級別') in ('A1級','A2級','B1級','B2級'))
    birthday=fields.get('生年月日','').replace('/','-');_need(date.fromisoformat(birthday).isoformat()==birthday)
    _need(bool(fields.get('支部')))
    number=lambda key: int(re.fullmatch(r'(\d+)(?:cm|kg|期)',fields[key])[1]) if key in fields and re.fullmatch(r'(\d+)(?:cm|kg|期)',fields[key]) else None
    return dict(registration=registration,name=_name(names[0].text()),birth_date=birthday,grade=fields['級別'][:2],branch=fields['支部'],
                height_cm=number('身長'),weight_kg=number('体重'),training_term=number('登録期'),
                source_url='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban='+registration,
                source_sha256=hashlib.sha256(raw).hexdigest())

def parse_current_grades(raw):
    tree=_Tree();tree.feed(raw.decode('utf-8'));out={}
    for card in tree.root.find('div','photoGallery3_body'):
        ids=list(card.find('p','photoGallery3_bodyNumber'));names=list(card.find('p','photoGallery3_bodyName'));grades=list(card.find('p','photoGallery3_bodyClass'))
        _need(len(ids)==len(names)==len(grades)==1)
        number=ids[0].text().strip();grade=re.findall(r'\b(?:A1|A2|B1|B2)\b',grades[0].text())
        _need(re.fullmatch(r'[0-9]{4}',number) and number not in out and len(grade)==1)
        out[number]=dict(name=_name(names[0].text()),grade=grade[0])
    _need(bool(out));return out

def build_catalogue(term_rows,portraits,basic_profiles,current_grades,source):
    _need(term_rows and len({p['racer_id'] for p in term_rows})==len(term_rows))
    period=term_info(term_rows[0]['term']);_need(all(p['term']==period['term'] for p in term_rows))
    by={p['racer_id']:p for p in term_rows};people=[];seen=set();cohort_n=[0]*6;cohort_top2=[0]*6
    for raw in term_rows:
        for c in raw['courses']:
            _need(len(c['finish_counts'])==6 and sum(c['finish_counts'])<=c['entry_n'])
            cohort_n[c['course']-1]+=c['entry_n'];cohort_top2[c['course']-1]+=sum(c['finish_counts'][:2])
    for identity in portraits['people']:
        reg=identity['registration'];_need(reg not in seen and re.fullmatch(r'[0-9]{4}',reg));seen.add(reg)
        row=by.get(reg);profile=basic_profiles.get(reg);grade=current_grades.get(reg)
        _need(row is not None or profile is not None)
        if grade:_need(_name(grade['name']) in [_name(n) for n in identity['aliases']] and grade['grade'] in ('A1','A2','B1','B2'))
        if profile:_need(profile['registration']==reg and _name(profile['name']) in [_name(n) for n in identity['aliases']])
        basic=dict(profile) if profile else dict(birth_date=row['birth_date'],branch=row['branch'],height_cm=row['height_cm'],weight_kg=row['weight_kg'],training_term=row['training_term'],grade=row['recorded_class'])
        if grade:basic['grade']=grade['grade']
        basic['grade_basis']='OFFICIAL_SEARCH' if grade else 'OFFICIAL_PROFILE' if profile else 'TERM_RECORDED'
        term=None
        if row:
            courses=[]
            for c in row['courses']:
                n=c['entry_n'];wins,seconds,thirds=c['finish_counts'][:3]
                courses.append(dict(course=c['course'],starts=n,wins=wins,seconds=seconds,thirds=thirds,
                    win_percent=wins/n*100 if n else None,top2_percent=c['official_top2_percent'] if n else None,
                    top3_percent=(wins+seconds+thirds)/n*100 if n else None,
                    average_st=c['mean_st'] if n else None,start_rank=c['mean_start_rank'] if n else None))
            n=row['starts'];top3=sum(c['wins']+c['seconds']+c['thirds'] for c in courses);_need(top3<=n)
            term=dict(record_sha256=row['record_sha256'],recorded_name=_name(row['name']),recorded_grade=row['recorded_class'],
                win_rate=row['national_win_rate'],top2_percent=row['national_top2_percent'],top3_percent=top3/n*100 if n else None,
                average_st=row['mean_st'],starts=n,wins=row['wins'],finals=row['finals'],victories=row['victories'],courses=courses)
        people.append(dict(registration=reg,name=identity['name'],basic=basic,term=term))
    return dict(schema='RACE_AI_RACER_PROFILES_V1',captured_at=source.get('captured_at'),
                period=dict(term=period['term'],start=period['period_start'],end=period['period_end']),source=source,
                cohort_top2_percent=[w/n*100 if n else None for w,n in zip(cohort_top2,cohort_n)],people=people)
