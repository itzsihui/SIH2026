"""Trusted local administration for daily evidence; no settlement or provider calls.
Review commands require an active local reviewer ID. This is a database-admin CLI,
not remote identity authentication; do not expose it as a web command runner.
"""
import argparse
from datetime import date
import json
from src.daycover import daily_evidence as evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('build','show'):
        p=commands.add_parser(name);p.add_argument('kind',choices=('rain','psi'));p.add_argument('station');p.add_argument('day',type=date.fromisoformat)
    p=commands.add_parser('select');p.add_argument('stall');p.add_argument('day',type=date.fromisoformat)
    p=commands.add_parser('mapping');p.add_argument('station_version_id');p.add_argument('start',type=date.fromisoformat);p.add_argument('end',type=date.fromisoformat);p.add_argument('decision',choices=('approved','revoked'));p.add_argument('--reviewer',required=True);p.add_argument('--source-ref',required=True)
    p=commands.add_parser('revision');p.add_argument('observation_id');p.add_argument('--reject',action='store_true');p.add_argument('--reviewer',required=True);p.add_argument('--source-ref',required=True)
    p=commands.add_parser('review');p.add_argument('aggregate_id');p.add_argument('decision',choices=('final','rejected'));p.add_argument('--reviewer',required=True);p.add_argument('--source-ref',required=True)
    p=commands.add_parser('closure');p.add_argument('centre_id');p.add_argument('day',type=date.fromisoformat);p.add_argument('reason',choices=('cleaning','works','explicit_open'));p.add_argument('--source-ref',required=True);p.add_argument('--document-sha256',required=True)
    p=commands.add_parser('review-closure');p.add_argument('closure_id');p.add_argument('decision',choices=('approved','rejected'));p.add_argument('--reviewer',required=True);p.add_argument('--source-ref',required=True)
    args=parser.parse_args()
    if args.command=='build':result=evidence.build_daily(args.kind,args.station,args.day)
    elif args.command=='show':result=evidence.current_daily(args.kind,args.station,args.day)
    elif args.command=='select':result=evidence.select_evidence(args.stall,args.day)
    elif args.command=='mapping':result=evidence.review_mapping(args.station_version_id,args.start,args.end,args.decision,args.reviewer,args.source_ref)
    elif args.command=='revision':result=evidence.review_revision(args.observation_id,args.reviewer,args.source_ref,reject=args.reject)
    elif args.command=='review':result=evidence.review_daily(args.aggregate_id,args.decision,args.reviewer,args.source_ref)
    elif args.command=='closure':result=evidence.propose_closure(args.centre_id,args.day,args.reason!='explicit_open',args.reason,args.source_ref,args.document_sha256)
    else:result=evidence.review_closure(args.closure_id,args.decision,args.reviewer,args.source_ref)
    print(json.dumps(result))


if __name__=='__main__':main()
