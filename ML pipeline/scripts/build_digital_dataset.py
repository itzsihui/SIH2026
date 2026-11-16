"""Build a versioned digital-only research dataset; raw files stay unchanged."""
import argparse
import json
from pathlib import Path
from src.daycover.dataset_pipeline import build


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',action='append',help='Source CSV; repeat for all parts. Default: supplied three files.')
    parser.add_argument('--config',default='configs/dataset-v1.json')
    parser.add_argument('--out',required=True,help='New output version directory; existing directories are never overwritten.')
    args=parser.parse_args()
    files=args.input or sorted(str(p) for p in Path('dataset').glob('DayCover_transactions_part_*.csv'))
    print(json.dumps(build(files,args.out,args.config),indent=2))


if __name__=='__main__':main()
