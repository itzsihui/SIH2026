"""Local canonical NEA ingestion. Does not aggregate, decide, bill or settle.

Examples: python -m scripts.ingest_nea_telemetry --kind rain --date 2026-11-15
          python -m scripts.ingest_nea_telemetry --resume WEATHER-RUN-... --max-pages 10
          python -m scripts.ingest_nea_telemetry --health
"""
import argparse
from datetime import date
import json

from src.daycover.weather_ingestion import Ingestor, source_health


def ingest_snapshot(kind, *, repository=None, client=None):
    runner=Ingestor(repository,client)
    result=runner.run(runner.start(kind))
    if result['status']!='complete':
        raise ValueError('Weather ingestion failed; inspect persisted run '+result['id'])
    return result


def ingest_psi_readings(**kwargs):
    return ingest_snapshot('psi',**kwargs)


def ingest_rainfall_readings(**kwargs):
    return ingest_snapshot('rain',**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=('rain','psi'))
    parser.add_argument('--date',type=date.fromisoformat)
    parser.add_argument('--resume')
    parser.add_argument('--max-pages',type=int,default=50)
    parser.add_argument('--health',action='store_true')
    args=parser.parse_args()
    if args.health:
        if args.kind or args.date or args.resume:
            parser.error('--health cannot be combined with ingestion arguments')
        result=source_health()
        print(json.dumps(result))
        return 0 if all(r['status']=='available_provisional' for r in result.values()) else 2
    if args.resume and (args.kind or args.date):
        parser.error('--resume uses its persisted kind/date; do not override them')
    if not args.resume and not args.kind:
        parser.error('--kind is required for a new run')
    runner=Ingestor()
    rid=args.resume or runner.start(args.kind,args.date)
    result=runner.run(rid,max_pages=args.max_pages)
    print(json.dumps(result))
    return 0 if result['status']=='complete' else 2


if __name__=='__main__':
    raise SystemExit(main())
