"""Digital dataset gates, reproducibility, quarantine and split isolation."""
import csv
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from src.daycover.dataset_pipeline import HEADER, build, digest, normalize, partition, validate_config
from scripts.inventory_dataset_sources import inventory

CONFIG=Path('configs/dataset-v1.json')


def sample(**overrides):
    row=dict(zip(HEADER,['TX1','2025-01-01 12:00:00','2025-01-01','ST1','HC1','south','drinks','SGQR_NETS_SIM','7.89','0.50','0','synthetic_calibrated_to_imda_aggregate']))
    row.update(overrides);return row


def write(path,rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=HEADER);writer.writeheader();writer.writerows(rows)
    return path


def load(path):return json.loads(path.read_text())


def test_digital_only_no_cash_estimate_and_source_immutable(tmp_path):
    raw=write(tmp_path/'source.csv',[sample(),sample(transaction_id='TX2',payment_method='CASH_SIM'),sample(transaction_id='TX3',payment_method='mystery'),sample(transaction_id='TX4',payment_method='')])
    checksum=digest(raw);out=tmp_path/'version';result=build([raw],out,CONFIG)
    rows=list(csv.DictReader((out/'digital_receipts.csv').open()))
    assert len(rows)==1 and rows[0]['amount_cents']=='789'
    assert 'cash' not in ','.join(rows[0]).lower() and 'margin' not in ','.join(rows[0]).lower()
    assert rows[0]['timestamp_sgt'].endswith('+08:00') and rows[0]['provenance_class']=='calibrated_synthetic'
    assert result['counts']['cash_excluded']==1 and result['counts']['quarantined_rows']==2
    assert result['row_accounting_balanced'] and digest(raw)==checksum
    assert load(out/'manifest.json')['models_trained'] is False
    with pytest.raises(ValueError,match='already exists'):build([raw],out,CONFIG)


@pytest.mark.parametrize('change,reason',[
    ({'amount_sgd':'NaN'},'invalid_amount_or_margin_assumption'),
    ({'amount_sgd':'1.001'},'invalid_amount_or_margin_assumption'),
    ({'amount_sgd':'-5'},'invalid_amount_or_margin_assumption'),
    ({'gross_margin_rate_assumed':'1.1'},'invalid_amount_or_margin_assumption'),
    ({'timestamp_sgt':'2025-01-01'},'invalid_timestamp_or_trading_day'),
    ({'date':'2025-02-30'},'invalid_timestamp_or_trading_day'),
    ({'date':'2025-01-02'},'invalid_timestamp_or_trading_day'),
    ({'refund_flag':'1'},'refund_requires_original_receipt_link'),
    ({'refund_flag':'yes'},'invalid_refund_flag'),
    ({'psi_region':'unknown'},'invalid_region'),
    ({'data_origin':'real_singapore'},'provenance_mismatch'),
    ({'stall_id':'=bad()'},'invalid_identifier'),
    ({'payment_method':'SPLIT'},'unknown_payment_method')])
def test_invalid_inputs_are_not_guessed(change,reason):
    with pytest.raises(ValueError,match=reason):normalize(sample(**change),load(CONFIG))


def test_timezone_normalization():
    r,_=normalize(sample(timestamp_sgt='2024-12-31T16:01:00Z'),load(CONFIG))
    assert r['trading_day']=='2025-01-01' and r['timestamp_sgt']=='2025-01-01T00:01:00+08:00'


def test_duplicates_across_parts_and_conflicts_remove_original(tmp_path):
    a=write(tmp_path/'a.csv',[sample(),sample(transaction_id='TX2')])
    b=write(tmp_path/'b.csv',[sample(),sample(transaction_id='TX2',amount_sgd='8.00')])
    out=tmp_path/'out';r=build([b,a],out,CONFIG)
    assert r['counts']['accepted_digital_rows']==1
    assert r['counts']['duplicate_receipt']==1 and r['counts']['conflicting_receipt_ids']==1
    assert r['counts']['conflict_prior_rows_excluded']==1 and r['row_accounting_balanced']


def test_merchant_mapping_conflict_excludes_all_merchant_rows(tmp_path):
    raw=write(tmp_path/'source.csv',[sample(),sample(transaction_id='TX2',centre_id='OTHER')])
    r=build([raw],tmp_path/'out',CONFIG)
    assert r['counts']['accepted_digital_rows']==0
    assert r['counts']['merchant_conflict_rows_excluded']==2


def test_malformed_extra_column_is_quarantined(tmp_path):
    raw=write(tmp_path/'source.csv',[sample()])
    text=raw.read_text().splitlines();raw.write_text(text[0]+'\n'+text[1]+',unexpected\n')
    r=build([raw],tmp_path/'out',CONFIG)
    assert r['counts']['quarantined_rows']==1 and r['counts']['reason:malformed_row']==1


def test_bad_header_does_not_publish_partial_version(tmp_path):
    raw=tmp_path/'bad.csv';raw.write_text('unexpected\nvalue\n')
    with pytest.raises(ValueError,match='header'):build([raw],tmp_path/'out',CONFIG)
    assert not (tmp_path/'out').exists() and not list(tmp_path.glob('.digital-build-*'))


def test_rebuild_is_byte_reproducible_and_outputs_verified(tmp_path):
    raw=write(tmp_path/'source.csv',[sample(),sample(transaction_id='TX2',date='2025-11-01',timestamp_sgt='2025-11-01 09:00:00')])
    for name in ('first','second'):build([raw],tmp_path/name,CONFIG)
    for p in (tmp_path/'first').iterdir():assert p.read_bytes()==(tmp_path/'second'/p.name).read_bytes()
    m=load(tmp_path/'first/manifest.json')
    for name,sha in m['outputs'].items():assert digest(tmp_path/'first'/name)==sha


def test_forward_time_and_merchant_holdout_are_disjoint():
    cfg=load(CONFIG);groups={}
    for i in range(100):
        merchant='merchant:'+str(i)
        for day,expected in [('2025-08-31','train'),('2025-09-01','validation'),('2025-11-01','test')]:
            temporal,group,split=partition(merchant,day,cfg)
            assert temporal==expected
            assert groups.setdefault(merchant,group)==group
            if group=='holdout':assert split=='merchant_holdout'
            else:assert split==expected
    assert set(groups.values())=={'development','holdout'}


@pytest.mark.parametrize('key,value', [('provenance_class','observed_foreign'),('currency','USD'),('digital_methods',{'CASH_SIM':'cash'}),('test_start','2025-01-01')])
def test_unreviewed_source_and_config_changes_fail_closed(key,value):
    cfg=deepcopy(load(CONFIG));cfg[key]=value
    with pytest.raises(ValueError):validate_config(cfg)


def test_inventory_marks_missing_and_does_not_assert_completeness(tmp_path):
    raw=tmp_path/'raw.csv';raw.write_text('date,value\n2025-01-01,3\n2025-01-03,4\n')
    catalog=tmp_path/'catalog.json';catalog.write_text(json.dumps({'checked_on':'2026-11-16','local_categories':{'rain':{'paths':['raw.csv','missing.csv'],'provenance_class':'official_singapore','verification':'unverified legacy copy'}},'research_candidates':[]}))
    out=tmp_path/'inventory.json';assert inventory(tmp_path,catalog,out)==2
    report=load(out);assert report['sources'][0]['distinct_dates']==2
    assert report['sources'][0]['exhaustive_daily_coverage'] is False
    assert report['sources'][1]['present'] is False


def test_input_change_during_build_discards_output(tmp_path,monkeypatch):
    from src.daycover import dataset_pipeline as pipeline
    raw=write(tmp_path/'source.csv',[sample()]);original=pipeline.normalize;changed=False
    def mutate(row,config):
        nonlocal changed
        result=original(row,config)
        if not changed:
            changed=True
            with raw.open('a') as f:f.write('\n')
        return result
    monkeypatch.setattr(pipeline,'normalize',mutate)
    with pytest.raises(ValueError,match='Source changed'):build([raw],tmp_path/'out',CONFIG)
    assert not (tmp_path/'out').exists()


def test_config_change_during_build_discards_output(tmp_path,monkeypatch):
    from src.daycover import dataset_pipeline as pipeline
    raw=write(tmp_path/'source.csv',[sample()]);cfg=tmp_path/'config.json';cfg.write_text(CONFIG.read_text())
    original=pipeline.normalize
    def mutate(row,config):
        result=original(row,config);cfg.write_text(cfg.read_text()+'\n');return result
    monkeypatch.setattr(pipeline,'normalize',mutate)
    with pytest.raises(ValueError,match='Adapter/config changed'):build([raw],tmp_path/'out',cfg)
    assert not (tmp_path/'out').exists()


def test_cash_conflict_cannot_sneak_a_digital_receipt_into_training(tmp_path):
    raw=write(tmp_path/'source.csv',[sample(),sample(payment_method='CASH_SIM')])
    r=build([raw],tmp_path/'out',CONFIG)
    assert r['counts']['accepted_digital_rows']==0
    assert r['counts']['conflicting_receipt_ids']==1 and r['row_accounting_balanced']
