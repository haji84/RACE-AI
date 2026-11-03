"""One acknowledged research GET from one published third-party result page."""
import argparse
import json
from race_ai.keirin_mobile_one_shot import ACK, MobileProbeError, probe_one

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ymd",required=True)
    ap.add_argument("--venue",type=int,required=True)
    ap.add_argument("--race",type=int,required=True)
    ap.add_argument("--route",choices=("new","legacy"),default="new")
    ap.add_argument("--ack-single-personal-research-get",action="store_true",required=True)
    args=ap.parse_args(argv)
    try:
        report=probe_one(args.ymd,args.venue,args.race,acknowledgement=(
            ACK if args.ack_single_personal_research_get else ""),
            route=args.route)
    except MobileProbeError as error:
        print(json.dumps({"schema":"RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1",
             "status":"TECHNICAL_SOURCE_UNAVAILABLE", "reason":str(error),
             "official_result_authenticated":False,
             "result_training_enabled":False,"prediction_generated":False}))
        return 2
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
