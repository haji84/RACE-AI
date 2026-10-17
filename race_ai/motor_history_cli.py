import argparse
import json
from .official_motor_join import load_join

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--motor-file',required=True)
    p.add_argument('--profile-file',action='append',required=True)
    p.add_argument('--motor-source',required=True)
    p.add_argument('--profile-source',action='append',required=True)
    p.add_argument('--profile-name',action='append',help='exact racer name for saved raw HTML profile')
    p.add_argument('--venue',required=True)
    p.add_argument('--motor',type=int,required=True)
    p.add_argument('--target-meet',required=True)
    p.add_argument('--captured-at',required=True)
    p.add_argument('--cohort',type=int,required=True)
    p.add_argument('--cohort-debut-month',required=True)
    a=p.parse_args()
    result=load_join(a.motor_file,a.profile_file,venue=a.venue,motor_no=a.motor,motor_source=a.motor_source,profile_sources=a.profile_source,captured_at=a.captured_at,target_meet_start=a.target_meet,cohort_debut_months={a.cohort:a.cohort_debut_month},expected_profile_names=a.profile_name)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
