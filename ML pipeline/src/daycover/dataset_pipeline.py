"""Reproducible digital-only research adapter. Never touches the policy ledger."""
import csv
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

HEADER = 'transaction_id timestamp_sgt date stall_id centre_id psi_region stall_type payment_method amount_sgd gross_margin_rate_assumed refund_flag data_origin'.split()
FIELDS = 'receipt_id merchant_id centre_id trading_day timestamp_sgt currency amount_cents payment_method provenance_class country source_file source_row time_split merchant_split split'.split()
VERSION = 'daycover.digital-receipts.v1'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)+'\n')


def validate_config(config):
    if config['schema_version']!=VERSION or config['provenance_class']!='calibrated_synthetic' or config['source_origin']!='synthetic_calibrated_to_imda_aggregate':
        raise ValueError('This adapter supports only the supplied synthetic source; foreign/real sources need distinct reviewed adapters.')
    if (config['country'],config['currency'],config['timezone'])!=('SG','SGD','Asia/Singapore'):raise ValueError('Unsupported source geography/currency/timezone.')
    if not config['digital_methods'] or set(config['digital_methods']) & set(config['cash_methods']):raise ValueError('Digital and cash mappings must be explicit and disjoint.')
    if any('cash' in x.lower() for x in config['digital_methods']):raise ValueError('Cash is never an allowed digital method.')
    if not 0<config['merchant_holdout_percent']<100:raise ValueError('Invalid merchant holdout.')
    if date.fromisoformat(config['validation_start'])>=date.fromisoformat(config['test_start']):raise ValueError('Split cutoffs must be ordered.')
    date.fromisoformat(config['access_date'])
    if not re.fullmatch(r'[a-z0-9_]{3,80}',config['source_namespace']):raise ValueError('Invalid source namespace.')


def partition(merchant, day, config):
    bucket=int(hashlib.sha256((config['split_seed']+'|'+merchant).encode()).hexdigest(),16)%100
    group='holdout' if bucket<config['merchant_holdout_percent'] else 'development'
    temporal='train' if day<config['validation_start'] else 'validation' if day<config['test_start'] else 'test'
    # Holdout merchants are never part of training, including their early receipts.
    return temporal,group,'merchant_holdout' if group=='holdout' else temporal


def normalize(row, config):
    if set(row)!=set(HEADER) or any(v is None for v in row.values()):raise ValueError('malformed_row')
    method=row['payment_method']
    if method in config['cash_methods']:return None,'cash_excluded'
    if method not in config['digital_methods']:raise ValueError('unknown_payment_method')
    for key in ('transaction_id','stall_id','centre_id','stall_type'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',row[key]):raise ValueError('invalid_identifier')
    if row['data_origin']!=config['source_origin']:raise ValueError('provenance_mismatch')
    if row['psi_region'] not in ('north','south','east','west','central'):raise ValueError('invalid_region')
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?',row['timestamp_sgt']):raise ValueError()
        at=datetime.fromisoformat(row['timestamp_sgt'])
        if at.tzinfo:at=at.astimezone(ZoneInfo(config['timezone']))
        else:at=at.replace(tzinfo=ZoneInfo(config['timezone']))
        trading_day=date.fromisoformat(row['date'])
        if at.date()!=trading_day:raise ValueError()
    except (ValueError,TypeError):raise ValueError('invalid_timestamp_or_trading_day') from None
    if row['refund_flag'] not in ('0','1'):raise ValueError('invalid_refund_flag')
    if row['refund_flag']=='1':raise ValueError('refund_requires_original_receipt_link')
    try:
        amount=Decimal(row['amount_sgd'])*100
        margin=Decimal(row['gross_margin_rate_assumed'])
        if not amount.is_finite() or amount<=0 or amount!=amount.to_integral_value() or amount>10**12:raise ValueError()
        if not margin.is_finite() or not 0<=margin<=1:raise ValueError()
    except (InvalidOperation,ValueError):raise ValueError('invalid_amount_or_margin_assumption') from None
    merchant=config['source_namespace']+':'+row['stall_id'];day=trading_day.isoformat()
    temporal,group,split=partition(merchant,day,config)
    return {'receipt_id':config['source_namespace']+':'+row['transaction_id'],'merchant_id':merchant,
            'centre_id':config['source_namespace']+':'+row['centre_id'],'trading_day':day,'timestamp_sgt':at.isoformat(),
            'currency':config['currency'],'amount_cents':int(amount),'payment_method':config['digital_methods'][method],
            'provenance_class':config['provenance_class'],'country':config['country'],
            'time_split':temporal,'merchant_split':group,'split':split},None


def build(inputs, output, config_path):
    inputs=sorted((Path(p).resolve() for p in inputs),key=lambda p:p.name)
    output=Path(output).resolve();config_path=Path(config_path).resolve()
    config_checksum=digest(config_path);adapter_checksum=digest(__file__)
    config=json.loads(config_path.read_text());validate_config(config)
    if not inputs or len({p.name for p in inputs})!=len(inputs):raise ValueError('Distinct named input files are required.')
    if output.exists():raise ValueError('Output already exists; choose a new version directory. No overwrite allowed.')
    if any(output==p or output in p.parents for p in inputs):raise ValueError('Output must be separate from raw sources.')
    sources=[{'file':p.name,'sha256':digest(p),'bytes':p.stat().st_size,'source':config['source_namespace'],
              'access_date':config['access_date'],'licence':config['licence'],'attribution':config['attribution']} for p in inputs]
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.digital-build-',dir=output.parent))
    counts=Counter({k:0 for k in ('source_rows','accepted_digital_rows','cash_excluded','quarantined_rows','duplicate_receipt','conflicting_receipt','conflict_prior_rows_excluded','conflicting_receipt_ids','conflicting_merchants','merchant_conflict_rows_excluded')});methods=Counter();merchants={};split_counts=Counter();min_day=None;max_day=None
    try:
        with tempfile.TemporaryDirectory(prefix='daycover-digital-audit-') as scratch:
            conn=sqlite3.connect(str(Path(scratch)/'audit.sqlite3'))
            try:
                conn.execute('PRAGMA journal_mode=OFF');conn.execute('PRAGMA synchronous=OFF')
                conn.execute('CREATE TABLE seen (id TEXT PRIMARY KEY, sha TEXT NOT NULL, conflict INTEGER NOT NULL DEFAULT 0)')
                conn.execute('CREATE TABLE accepted (id TEXT PRIMARY KEY, merchant TEXT NOT NULL, day TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL)')
                conn.execute('CREATE TABLE merchant (id TEXT PRIMARY KEY, signature TEXT NOT NULL, conflict INTEGER NOT NULL DEFAULT 0)')
                with (stage/'quarantine.csv').open('w',newline='') as q:
                    reject=csv.writer(q);reject.writerow(['source_file','source_row','record_sha256','reason'])
                    for path in inputs:
                        with path.open(encoding='utf-8-sig',newline='') as stream:
                            reader=csv.DictReader(stream)
                            if reader.fieldnames!=HEADER:raise ValueError('Unsupported source header: '+path.name)
                            for number,row in enumerate(reader,2):
                                counts['source_rows']+=1;methods[row.get('payment_method') or '<missing>']+=1
                                raw=json.dumps(row,sort_keys=False,separators=(',',':'));sha=hashlib.sha256(raw.encode()).hexdigest()
                                key=row.get('transaction_id')
                                if key:
                                    old=conn.execute('SELECT sha,conflict FROM seen WHERE id=?',(key,)).fetchone()
                                    if old:
                                        reason='duplicate_receipt' if old[0]==sha and not old[1] else 'conflicting_receipt'
                                        if reason=='conflicting_receipt':
                                            conn.execute('UPDATE seen SET conflict=1 WHERE id=?',(key,))
                                            counts['conflict_prior_rows_excluded']+=conn.execute('DELETE FROM accepted WHERE id=?',(config['source_namespace']+':'+key,)).rowcount
                                        counts[reason]+=1;reject.writerow([path.name,number,sha,reason]);continue
                                    conn.execute('INSERT INTO seen(id,sha) VALUES (?,?)',(key,sha))
                                try:record,reason=normalize(row,config)
                                except ValueError as exc:
                                    counts['quarantined_rows']+=1;counts['reason:'+str(exc)]+=1
                                    reject.writerow([path.name,number,sha,str(exc)]);continue
                                if reason:counts[reason]+=1;continue
                                record.update(source_file=path.name,source_row=number)
                                signature=json.dumps([row[k] for k in ('centre_id','psi_region','stall_type')])
                                prior=conn.execute('SELECT signature FROM merchant WHERE id=?',(record['merchant_id'],)).fetchone()
                                if prior and prior[0]!=signature:conn.execute('UPDATE merchant SET conflict=1 WHERE id=?',(record['merchant_id'],))
                                elif not prior:conn.execute('INSERT INTO merchant(id,signature) VALUES (?,?)',(record['merchant_id'],signature))
                                conn.execute('INSERT INTO accepted VALUES (?,?,?,?,?)',(record['receipt_id'],record['merchant_id'],record['trading_day'],record['timestamp_sgt'],json.dumps(record,sort_keys=True)))
                        conn.commit()
                conflicts=conn.execute('SELECT COUNT(*) FROM seen WHERE conflict=1').fetchone()[0]
                bad_merchants=conn.execute('SELECT COUNT(*) FROM merchant WHERE conflict=1').fetchone()[0]
                removed=conn.execute('SELECT COUNT(*) FROM accepted a JOIN merchant m ON m.id=a.merchant WHERE m.conflict=1').fetchone()[0]
                counts['conflicting_receipt_ids']=conflicts;counts['conflicting_merchants']=bad_merchants;counts['merchant_conflict_rows_excluded']=removed
                with (stage/'digital_receipts.csv').open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
                    for (payload,) in conn.execute('SELECT a.payload FROM accepted a JOIN merchant m ON m.id=a.merchant WHERE m.conflict=0 ORDER BY a.day,a.at,a.id'):
                        record=json.loads(payload);writer.writerow(record);counts['accepted_digital_rows']+=1
                        split_counts[record['split']]+=1
                        merchants[record['merchant_id']]=record['merchant_split']
                        min_day=min(min_day or record['trading_day'],record['trading_day']);max_day=max(max_day or record['trading_day'],record['trading_day'])
                save(stage/'splits.json',{'schema_version':'daycover.splits.v1','seed':config['split_seed'],
                     'validation_start':config['validation_start'],'test_start':config['test_start'],'merchant_assignment':dict(sorted(merchants.items())),
                     'row_counts':dict(split_counts),'fit_rule':'Fit transformations/models on split=train only. Holdout merchants never enter training; evaluate their future test window separately.',
                     'receipt_grouping':'All duplicates/conflicts resolved before split. Line-item sources require grouping by namespaced merchant+receipt before any split.',
                     'features_generated':False})
            finally:conn.close()
        if any(digest(p)!=s['sha256'] for p,s in zip(inputs,sources)):raise ValueError('Source changed during build; output discarded.')
        accounted=sum(counts[k] for k in ('accepted_digital_rows','cash_excluded','quarantined_rows','duplicate_receipt','conflicting_receipt','conflict_prior_rows_excluded','merchant_conflict_rows_excluded'))
        if accounted!=counts['source_rows']:raise ValueError('Audit row accounting failed; output discarded.')
        quality={'schema_version':'daycover.quality.v1','counts':dict(counts),'payment_methods':dict(methods),
                 'date_min':min_day,'date_max':max_day,'merchant_count':len(merchants),'split_counts':dict(split_counts),
                 'row_accounting_balanced':True,'empty_splits':[k for k in ('train','validation','test','merchant_holdout') if not split_counts[k]],
                 'cash_included':False,'refunds_accepted':False,'zero_sales_imputed':False,'margin_features_generated':False,
                 'training_ready_for_real_world_claims':False,'limitations':['synthetic_only','no_transaction_connector','no_verified_margin_or_weather_loss','raw_licence_unsupplied','refund_links_unavailable','cash_and_unknown_methods_not_used']}
        save(stage/'quality.json',quality)
        if digest(config_path)!=config_checksum or digest(__file__)!=adapter_checksum:raise ValueError('Adapter/config changed during build; output discarded.')
        identity={'config':config,'config_sha256':config_checksum,'sources':sources,'adapter_sha256':adapter_checksum}
        manifest={'schema_version':'daycover.dataset-manifest.v1',**identity,'build_id':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
                  'outputs':{p.name:digest(p) for p in sorted(stage.iterdir())},'provenance_classes':['observed_foreign','official_singapore','calibrated_synthetic','consented_singapore'],
                  'actual_provenance':'calibrated_synthetic','canonical_policy_effect':False,'models_trained':False}
        save(stage/'manifest.json',manifest)
        # No mutation of an existing version; only publish a completely successful build.
        if output.exists():raise ValueError('Output appeared during build; not overwritten.')
        stage.rename(output)
        return {'output':str(output),'build_id':manifest['build_id'],**quality}
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise
