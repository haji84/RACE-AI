"""Export private joined racer profiles from existing databases; no source GET."""
import argparse
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_racer_database import RacerDatabase,MAX_DB
from race_ai.boat_racer_research_profile import assemble_profile
from race_ai.boat_history_store import HistoryStore,wire
from race_ai.boat_racer_term import term_info
from race_ai.teiai_history import need
from scripts.boat_history_collect import private_root,save


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history-db',type=Path,required=True);p.add_argument('--racer-db',type=Path,required=True)
    p.add_argument('--racer-db-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    need(args.history_db.is_file() and not args.history_db.is_symlink(),'EXISTING_HISTORY_REQUIRED_NO_RESET')
    need(args.racer_db.is_file() and not args.racer_db.is_symlink() and args.racer_db.stat().st_size<=MAX_DB,'BOUNDED_RACER_DATABASE_REQUIRED')
    racers=RacerDatabase.restore(args.racer_db.read_bytes(),expected_sha256=args.racer_db_sha256)
    history=HistoryStore(args.history_db);root=private_root(args.output);now=datetime.now(timezone.utc).isoformat()
    try:
        rows=[r for day in history._selected(now) for r in day['facts']]
        ids={r['racer_id'] for r in rows}|{r[0] for r in racers.db.execute('SELECT DISTINCT racer_id FROM racers')}
        term_urls={term_info(r[0])['source_url'] for r in racers.db.execute('SELECT DISTINCT term FROM racers')}
        allow=lambda url,rights,purpose:url in term_urls and rights=='OFFICIAL_DOWNLOAD_PERSONAL_RESEARCH' and purpose=='analysis'
        counts=dict(profiles=0,with_official_term=0,with_recent_opportunities=0)
        for reg in sorted(ids):
            profile=assemble_profile(history,racers,reg,as_of=now,allow_source=allow)
            save(root/(reg+'.json'),(wire(profile)+'\n').encode())
            counts['profiles']+=1;counts['with_official_term']+=profile['official_term'] is not None
            counts['with_recent_opportunities']+=bool(profile['recent_history']['opportunities'])
        report=dict(schema='RACE_AI_PRIVATE_JOINED_RACER_PROFILE_COUNTS_V1',as_of=now,**counts,
            unresolved_opportunities=sum(r.get('participation')=='UNRESOLVED' for r in rows),
            all_career_history_complete=False,current_active_registry_complete=False,features_applied_to_predictions=False)
        save(root/'profile-counts.json',(wire(report)+'\n').encode());print(wire(report))
    finally:racers.db.close();history.close()


if __name__=='__main__':main()
