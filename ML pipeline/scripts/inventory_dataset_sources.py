"""Checksum and summarize local source copies; no downloads or feature joins."""
import argparse
import csv
import json
from pathlib import Path
from src.daycover.dataset_pipeline import digest,save


def inventory(root, catalog, output):
    root=Path(root);catalog=Path(catalog);output=Path(output)
    if output.exists():raise ValueError('Choose a new inventory file; existing artifacts stay unchanged.')
    spec=json.loads(catalog.read_text());records=[]
    for category,group in spec['local_categories'].items():
        for name in group['paths']:
            path=root/name
            record={'path':name,'category':category,'provenance_class':group['provenance_class'],
                    'origin_verified':False,'licence':'not_verified_for_this_local_copy','access_date':spec['checked_on'],
                    'attribution':group['verification'],'present':path.is_file()}
            if path.is_file():
                days=set();rows=0
                with path.open(encoding='utf-8-sig',newline='') as stream:
                    reader=csv.DictReader(stream);record['columns']=reader.fieldnames
                    for row in reader:
                        rows+=1
                        if row.get('date'):days.add(row['date'])
                record.update(sha256=digest(path),bytes=path.stat().st_size,rows=rows,
                              distinct_dates=len(days),date_min=min(days) if days else None,date_max=max(days) if days else None,
                              exhaustive_daily_coverage=False)
            records.append(record)
    output.parent.mkdir(parents=True,exist_ok=True)
    save(output,{'schema_version':'daycover.source-inventory.v1','catalog_sha256':digest(catalog),
                 'sources':records,'research_candidates':spec['research_candidates'],
                 'canonical_policy_effect':False,'features_generated':False})
    return len(records)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default='.')
    p.add_argument('--catalog',default='data/sources-v1.json');p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps({'inventoried_files':inventory(a.root,a.catalog,a.out)}))


if __name__=='__main__':main()
