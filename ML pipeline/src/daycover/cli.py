"""python -m src.daycover.cli evaluate --date 2019-09-20 | replay --from 2014-04-02 --to 2026-10-01 [--out file.json]"""
import argparse, json
from datetime import date
from . import data
from .engine import evaluate, replay, summarise
from .rules import DEFAULT_RULES, RuleSet


def main(argv=None):
    p = argparse.ArgumentParser(prog="daycover")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate"); e.add_argument("--date", required=True); e.add_argument("--plan", default="haze+rain")
    r = sub.add_parser("replay"); r.add_argument("--from", dest="start", required=True); r.add_argument("--to", dest="end", required=True)
    r.add_argument("--plan", default="haze+rain"); r.add_argument("--rain-mm", type=float); r.add_argument("--out")
    a = p.parse_args(argv)
    rules = DEFAULT_RULES
    if getattr(a, "rain_mm", None):
        rules = RuleSet(rain_daily_mm=a.rain_mm)
    stalls = data.load_stalls(a.plan)
    if a.cmd == "evaluate":
        d = date.fromisoformat(a.date)
        evs = [x.to_dict() for s in stalls for x in evaluate(s, d, rules)]
        print(json.dumps({"date": a.date, "rule_version": rules.version, "events": evs}, indent=2))
        return
    s0, s1 = date.fromisoformat(a.start), date.fromisoformat(a.end)
    # rain only exists for sampled dates: restrict to haze-complete range but evaluate rain where data exists
    evs = replay(stalls, s0, s1, rules)
    summ = summarise(evs, len(stalls), (s1 - s0).days / 365.25)
    summ["note"] = "rain evaluated only on dates present in the 701-date rain sample; elsewhere unknown, not zero"
    print(json.dumps(summ, indent=2))
    if a.out:
        json.dump({"summary": summ, "events": [x.to_dict() for x in evs]}, open(a.out, "w"))


if __name__ == "__main__":
    main()
