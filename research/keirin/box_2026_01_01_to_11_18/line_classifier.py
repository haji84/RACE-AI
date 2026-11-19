"""Race result x *published/pre-race* line forecast classifier.

Requires a source-bound lineup snapshot.  It does NOT reconstruct line formation
from surnames, regions, tactics, or the winning numbers. No video claims.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter

class InvalidLineup(ValueError):
    pass


def classify_order(lines: list[list[int]], order: list[int], starters: list[int] | None = None) -> dict:
    """Classify a single ordered 3-entrant result against a captured lineup.

    Every entrant is represented in `lines`; a rider with no teammates is a
    one-element line. `starters` should contain the actually-started numbers.
    Example: lines=[[1,4,6], [2,5], [3], [7]], order=[4,1,3].
    """
    if not isinstance(lines,list) or not lines or not all(isinstance(line,list) and line for line in lines):
        raise InvalidLineup('LINES_MISSING_OR_EMPTY')
    for l in lines:
        if any(not isinstance(n,int) or isinstance(n,bool) or n<1 or n>9 for n in l):
            raise InvalidLineup('INVALID_RIDER_ID')
    members=[n for line in lines for n in line]
    if len(members)!=len(set(members)):
        raise InvalidLineup('DUPLICATE_RIDER_IN_LINES')
    if starters is not None and set(members)!=set(starters):
        raise InvalidLineup('LINEUP_STARTERS_NOT_MATCHED')
    if len(order)!=3 or len(set(order))!=3 or any(n not in members for n in order):
        raise InvalidLineup('INVALID_TOP3_ORDER')
    line_of={n:i for i,line in enumerate(lines) for n in line}
    line_ids=[line_of[n] for n in order]
    unique_count=len(set(line_ids))
    if unique_count==1:
        kind='SAME_LINE_3'
    elif unique_count==2:
        kind='SAME_LINE_2_PLUS_OTHER'
    else:
        kind='THREE_DIFFERENT_LINES'
    positions=[]
    for place,n in enumerate(order,1):
        lineup=lines[line_of[n]]
        positions.append({'finish_position':place,'rider':n,'line_number':line_of[n]+1,
                          'line_size':len(lineup),'starting_line_position':lineup.index(n)+1,
                          'starting_role':'SINGLE' if len(lineup)==1 else ('LEADER' if lineup.index(n)==0 else ('SECOND' if lineup.index(n)==1 else 'THIRD_OR_LATER'))})
    counts=Counter(line_ids)
    paired_line=next((lid for lid,c in counts.items() if c==2),None)
    pair_places=[i+1 for i,lid in enumerate(line_ids) if lid==paired_line] if paired_line is not None else []
    paired_members=[order[i-1] for i in pair_places]
    pair_source_positions=[lines[paired_line].index(n)+1 for n in paired_members] if paired_line is not None else []
    return {
        'winning_order':'-'.join(map(str,order)), 'class':kind,
        'complete_three_rider_line':unique_count==1 and len(lines[line_ids[0]])==3,
        'three_from_line_of_4_or_more':unique_count==1 and len(lines[line_ids[0]])>3,
        'same_line_pair_finish_positions':pair_places,
        'same_line_pair_adjacent_in_pre_race_order':paired_line is not None and abs(pair_source_positions[0]-pair_source_positions[1])==1,
        'singleton_top3_places':[x['finish_position'] for x in positions if x['starting_role']=='SINGLE'],
        'finish_positions':positions,
        'lineup_is_pre_race_forecast_not_video_observation':True,
    }


def classify_race(lines: list[list[int]], payouts: list[dict], starters: list[int] | None=None) -> dict:
    if not payouts:
        raise InvalidLineup('NO_SETTLED_PAYOUT')
    outcomes=[]
    for p in payouts:
        order=p['order']
        if isinstance(order,str):
            order=[int(x) for x in order.split('-')]
        d=classify_order(lines,order,starters=starters)
        d['payout_yen_per_100']=p.get('yen')
        outcomes.append(d)
    return {'outcomes':outcomes,
            'classes_seen':sorted(set(x['class'] for x in outcomes)),
            'has_multiple_line_classes_due_to_ties':len(set(x['class'] for x in outcomes))>1,
            'lineup_source_required':True}


def main():
    import argparse
    ap=argparse.ArgumentParser(description='Classify actual winners against a published lineup snapshot')
    ap.add_argument('input_json',type=Path)
    args=ap.parse_args()
    payload=json.loads(args.input_json.read_text(encoding='utf-8'))
    if not payload.get('lineup_source_url') or not payload.get('lineup_captured_at'):
        raise InvalidLineup('PROVENANCE_URL_AND_CAPTURE_TIME_REQUIRED')
    result=classify_race(payload['lines'],payload['payouts'],payload.get('starters'))
    print(json.dumps({'race_key':payload.get('race_key'),'lineup_source_url':payload['lineup_source_url'],
         'lineup_captured_at':payload['lineup_captured_at'],**result},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
