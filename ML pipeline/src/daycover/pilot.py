"""Deterministic simulation decisions over an explicit registered contract."""
from .contracts import M1_VERSION, simulation_contract
from .rules import haze_payout, rain_daily

# Compatibility exports are copies, never the execution source of truth.
RULES = simulation_contract(M1_VERSION).rules()
CONTRACT = simulation_contract(M1_VERSION).terms


def decide(peril, rain, psi, yesterday, closed, used, *, version=M1_VERSION):
    """Return status, amount, reason. Selection resolves only registered adapters."""
    contract = simulation_contract(version)
    rules, terms = contract.rules(), contract.terms
    if peril not in ('rain', 'haze'):
        raise ValueError('Unsupported paying peril.')
    if closed:
        return 'SUPPRESSED', 0, 'Scheduled closure: no benefit and no cap consumed.'
    if peril == 'rain':
        if rain is None:
            return 'PENDING', 0, 'No complete valid daily gauge total; awaiting data.'
        hit, reason = rain_daily(rain, rules)
        amount = rules.rain_payout if hit else 0
        capped = used['rain'] >= rules.rain_cap_days_per_year
    else:
        if psi is None or (rules.haze_tier1_psi <= psi < rules.haze_tier2_psi and yesterday is None):
            return 'PENDING', 0, 'Missing regional PSI evidence; awaiting data.'
        _, amount, reason = haze_payout(psi, yesterday, rules)
        capped = used['haze_days'] >= rules.haze_cap_days_per_year or used['haze_sgd'] >= rules.haze_cap_amount_per_year
        amount = min(amount, rules.haze_cap_amount_per_year - used['haze_sgd'])
    if capped:
        return 'CAPPED', 0, 'Policy-year benefit limit reached.'
    amount = min(amount, terms['combined_cap_sgd'] - used['total'])
    return ('TRIGGERED', amount, reason) if amount > 0 else ('NO_TRIGGER', 0, reason)
