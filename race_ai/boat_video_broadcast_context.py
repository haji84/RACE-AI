"""Time-bound exhibition/commentary priors; never pixel identity or results.

Clothing remains the primary track label. Broadcast rank is a spoken claim,
not a measured image rank. No x-order, missing-number filling or automatic
pass counter links speech to an unidentified rider. Nothing here fetches data.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import math
import re
import unicodedata


SCHEMA='RACE_AI_BOAT_BROADCAST_CONTEXT_V1'
PHASES={'RACE','EXHIBITION_LAP','EXHIBITION_START','UNKNOWN'}
_FIELDS={'text','phase','start_pts','end_pts','available_from_pts','valid_until_pts',
         'audio_pcm_sha256','producer_sha256','producer_kind','exhibition_pass_index'}
_NUMERAL='0-9〇零一二三四五六七八九十百千万億兆'
_BOAT=rf'(?<![{_NUMERAL}])([1-6])(?![{_NUMERAL}])\s*(?:号艇|番艇|番(?!手|人気))'
_RANK=rf'(?:先頭|トップ|(?<![{_NUMERAL}])([1-6])(?![{_NUMERAL}])\s*番手)\s*(?:は|が|も|に|を)?\s*'


def _need(value):
    if not value:raise ValueError('BOAT_BROADCAST_CONTEXT_REJECTED')


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _sha(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}',value) is not None


def parse_commentary(text,*,phase):
    """Conservative Japanese grammar; unknown words are not silently repaired."""
    _need(type(text) is str and len(text)<=20000 and type(phase) is str and phase in PHASES)
    normalized=unicodedata.normalize('NFKC',text).translate(str.maketrans('一二三四五六','123456'))
    out=dict(status='NO_EXPLICIT_IDENTITY_CUE',running_order=[],exhibition_boat_number=None,
             official_result=False,phase=phase)
    if re.search(r'失礼|訂正|言い直|ではなく|じゃなく|ではありません|ではない|じゃありません',normalized):
        out['status']='CORRECTION_REQUIRES_NEW_OBSERVATION';return out
    if re.search(r'[0-9]{2,}\s*(?:号艇|番艇|番手)|号艇\s*(?:か|または|あるいは)\s*[1-6]|ですか|でしょうか|[?？]',normalized):
        out['status']='AMBIGUOUS_COMMENTARY';return out
    if re.search(r'ゴール|確定|着順|結果|リプレイ|前のレース|前走|昨日|でしょう|予想|かもしれ',normalized):
        out['status']='NONCURRENT_OR_PREDICTED_COMMENTARY';return out
    if phase=='EXHIBITION_LAP':
        if re.search(r'展示タイム|着率|全国|人気|説明|解説|について',normalized):return out
        # Bare "1番" in statistics is not a boat. Individual pass shorthand
        # needs an explicit lap-exhibition phrase, unlike running-rank calls.
        explicit=rf'(?<![{_NUMERAL}])([1-6])(?![{_NUMERAL}])\s*(?:号艇|番艇)'
        boats=[int(n) for n in re.findall(explicit,normalized)]
        if not boats:
            shorthand=rf'(?<![{_NUMERAL}])([1-6])(?![{_NUMERAL}])\s*番\s*の?\s*周回展示'
            boats=[int(n) for n in re.findall(shorthand,normalized)]
        if len(set(boats))==1 and not re.search(r'から|まで|スタート展示',normalized):
            out.update(status='EXPLICIT_INDIVIDUAL_EXHIBITION_BOAT',exhibition_boat_number=boats[0])
        return out
    if phase!='RACE':return out
    if re.search(r'展示|人気|オッズ|枠順|出走順',normalized):return out
    pairs=[]
    for match in re.finditer(_RANK+_BOAT,normalized):
        rank=int(match.group(1)) if match.group(1) else 1
        pairs.append((rank,int(match.group(2))))
    if not pairs:
        # An explicit order clause is required; bare boat mentions/times are not ranks.
        match=re.search(r'(?:現在(?:の順位)?は|通過順は|走行順は)\s*'
                        r'([1-6](?:\s*[、,\-]\s*[1-6]){1,5})\s*の順',normalized)
        if match:pairs=list(enumerate(map(int,re.findall('[1-6]',match.group(1))),1))
    unique=set(pairs)
    if len({rank for rank,_ in unique})!=len(unique) or len({boat for _,boat in unique})!=len(unique):
        out['status']='AMBIGUOUS_COMMENTARY';return out
    if pairs:
        out.update(status='ANNOUNCED_RUNNING_ORDER',running_order=[dict(rank=rank,boat_number=boat)
                   for rank,boat in sorted(unique)])
    return out


class BroadcastIdentityContext:
    """Immutable declared cues on the input media's absolute source-PTS clock."""
    def __init__(self,context,*,media_sha256):
        _need(type(context) is dict and set(context)=={'schema_version','media_sha256','exhibition_order','segments'})
        _need(context['schema_version']==SCHEMA and _sha(media_sha256)
              and context['media_sha256']==media_sha256)
        order=context['exhibition_order']
        _need(order is None or type(order) is list and 1<=len(order)<=6
              and all(type(n) is int and 1<=n<=6 for n in order) and len(set(order))==len(order))
        _need(type(context['segments']) is list and len(context['segments'])<=20000)
        checked=[]
        for row in context['segments']:
            _need(type(row) is dict and set(row)==_FIELDS)
            _need(all(_finite(row[k]) for k in ('start_pts','end_pts','available_from_pts','valid_until_pts'))
                  and row['start_pts']<row['end_pts']<=row['available_from_pts']<=row['valid_until_pts'])
            _need(_sha(row['audio_pcm_sha256']) and _sha(row['producer_sha256'])
                  and row['producer_kind'] in ('ASR_LOCAL_UNVERIFIED','HUMAN_TRANSCRIPT','SYNTHETIC_TEST'))
            index=row['exhibition_pass_index']
            _need(index is None or row['phase']=='EXHIBITION_LAP' and order is not None
                  and type(index) is int and 1<=index<=len(order))
            parsed=parse_commentary(row['text'],phase=row['phase'])
            item=deepcopy(row);item['parsed']=parsed
            item['declared_order_number']=None if index is None else order[index-1]
            checked.append(item)
        self._segments=checked
        self._media=media_sha256
        self._context_sha=sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def annotate(self,riders,*,source_pts):
        _need(_finite(source_pts) and type(riders) is dict
              and riders.get('schema_version')=='RACE_AI_RIDER_PART_TRACKS_V1'
              and type(riders.get('tracks')) is list)
        out=deepcopy(riders)
        corrections={}
        for cue in self._segments:
            if (cue['parsed']['status']=='CORRECTION_REQUIRES_NEW_OBSERVATION'
                and cue['available_from_pts']<=source_pts):
                corrections[cue['phase']]=max(corrections.get(cue['phase'],-math.inf),cue['available_from_pts'])
        active=[deepcopy(s) for s in self._segments
                if s['available_from_pts']<=source_pts<=s['valid_until_pts']
                and (s['parsed']['status']=='CORRECTION_REQUIRES_NEW_OBSERVATION'
                     or s['available_from_pts']>corrections.get(s['phase'],-math.inf))]
        # A newer spoken claim supersedes the old boat/rank even after the
        # newer claim itself expires. Expiry must never restore old commentary.
        latest_ranks={};latest_boats={};latest_passes={}
        for cue in self._segments:
            at=cue['available_from_pts'];phase=cue['phase']
            if at>source_pts or at<=corrections.get(phase,-math.inf):continue
            for claim in cue['parsed']['running_order']:
                key=(phase,claim['rank']);latest_ranks[key]=max(latest_ranks.get(key,-math.inf),at)
                key=(phase,claim['boat_number']);latest_boats[key]=max(latest_boats.get(key,-math.inf),at)
            if cue['parsed']['exhibition_boat_number'] is not None or cue['declared_order_number'] is not None:
                latest_passes[phase]=max(latest_passes.get(phase,-math.inf),at)
        ranks={};exhibition=set();flags=set()
        for cue in active:
            parsed=cue['parsed']
            if parsed['status']=='CORRECTION_REQUIRES_NEW_OBSERVATION':
                flags.add('ACTIVE_COMMENTARY_CORRECTION_UNRESOLVED')
            for claim in parsed['running_order']:
                number=claim['boat_number'];rank=claim['rank']
                if (cue['available_from_pts']<latest_ranks[(cue['phase'],rank)]
                    or cue['available_from_pts']<latest_boats[(cue['phase'],number)]):continue
                if (number in ranks and ranks[number]!=rank
                    or any(n!=number and r==rank for n,r in ranks.items())):
                    flags.add('CONFLICTING_ACTIVE_BROADCAST_CUES')
                ranks[number]=rank
            current_pass=cue['available_from_pts']==latest_passes.get(cue['phase'])
            if current_pass and parsed['exhibition_boat_number'] is not None:
                exhibition.add(parsed['exhibition_boat_number'])
            if current_pass and cue['declared_order_number'] is not None:
                exhibition.add(cue['declared_order_number'])
        if len(exhibition)>1:flags.add('CONFLICTING_ACTIVE_BROADCAST_CUES')
        if flags:ranks={};exhibition=set()
        number_counts=Counter(row.get('number') for row in out['tracks'] if type(row.get('number')) is int)
        only_one=(len(out['tracks'])==1 and out['tracks'][0].get('detector_fresh') is True)
        candidate=next(iter(exhibition)) if len(exhibition)==1 and only_one else None
        for row in out['tracks']:
            number=row.get('number')
            cloth_number=(number if type(number) is int and 1<=number<=6
                          and row.get('identity_source')=='CLOTHING_COLOR' and number_counts[number]==1 else None)
            rank=ranks.get(cloth_number) if cloth_number is not None else None
            status='UNBOUND_BROADCAST_CUE'
            if candidate is not None:
                status=('UNCONFIRMED_EXHIBITION_ORDER_PRIOR' if cloth_number is None
                        else 'CLOTHING_BROADCAST_AGREEMENT' if cloth_number==candidate
                        else 'CLOTHING_BROADCAST_CONFLICT')
            elif rank is not None:status='ANNOUNCED_RANK_FOR_EXISTING_CLOTHING_IDENTITY'
            row['broadcast_identity']=dict(status=status,announced_rank=rank,
                exhibition_number_candidate=candidate,identity_label_overridden=False,
                new_clothing_votes_added=0,semantic_binding_validated=False,
                announcement_timing='DECLARED_INTERVAL_LATENCY_UNVALIDATED')
        out['broadcast_context']=dict(schema_version=SCHEMA,media_sha256=self._media,
            context_sha256=self._context_sha,source_pts=source_pts,active_cues=active,
            quality_flags=sorted(flags),rank_scope='ANNOUNCED_NOT_MEASURED_NOT_OFFICIAL_RESULT',
            prediction_eligible=False,production_eligible=False,
            audio_transcription_accuracy_validated=False)
        return out
