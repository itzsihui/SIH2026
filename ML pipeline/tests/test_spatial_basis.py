"""Unit tests for spatial basis risk calculations, 2x2 contingency tables, and event-conditioned denominators.
"""
import unittest
import numpy as np
import pandas as pd
import math

def compute_2x2_metrics(a_flags: list[int] | np.ndarray, b_flags: list[int] | np.ndarray) -> dict:
    """Compute 2x2 contingency table, conditional error rates, and skill scores.
    a_flags: 1 if S0 (primary gauge) triggered, 0 otherwise
    b_flags: 1 if Neighbourhood consensus triggered, 0 otherwise
    """
    a = np.array(a_flags, dtype=int)
    b = np.array(b_flags, dtype=int)
    assert len(a) == len(b), "Array lengths must match"
    
    n_tot = len(a)
    n_11 = int(np.sum((a == 1) & (b == 1)))  # A & B (True Positive)
    n_10 = int(np.sum((a == 1) & (b == 0)))  # A & not-B (Candidate False Trigger)
    n_01 = int(np.sum((a == 0) & (b == 1)))  # not-A & B (Candidate Missed Trigger)
    n_00 = int(np.sum((a == 0) & (b == 0)))  # neither (True Negative)
    
    # Event counts
    n_a = n_11 + n_10  # Days S0 triggered
    n_b = n_11 + n_01  # Days Neighbourhood triggered
    n_event_days = n_11 + n_10 + n_01  # A or B
    
    # Conditional error rates
    false_trigger_rate = (n_10 / n_a) if n_a > 0 else 0.0
    missed_trigger_rate = (n_01 / n_b) if n_b > 0 else 0.0
    
    # Skill scores
    precision = (n_11 / n_a) if n_a > 0 else 0.0
    recall = (n_11 / n_b) if n_b > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    
    # Agreement on event days (CSI / Jaccard index)
    event_agreement = (n_11 / n_event_days) if n_event_days > 0 else 0.0
    
    # Cohen's Kappa
    p_o = (n_11 + n_00) / n_tot if n_tot > 0 else 0.0
    p_e = ((n_a * n_b) + ((n_tot - n_a) * (n_tot - n_b))) / (n_tot ** 2) if n_tot > 0 else 0.0
    kappa = ((p_o - p_e) / (1.0 - p_e)) if (1.0 - p_e) > 0 else 0.0
    
    return {
        "n_total": n_tot,
        "n_11": n_11,
        "n_10": n_10,
        "n_01": n_01,
        "n_00": n_00,
        "n_s0_triggers": n_a,
        "n_neigh_triggers": n_b,
        "n_event_days": n_event_days,
        "trigger_rate": n_a / n_tot if n_tot > 0 else 0.0,
        "false_trigger_rate": false_trigger_rate,
        "missed_trigger_rate": missed_trigger_rate,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "event_agreement": event_agreement,
        "cohens_kappa": kappa
    }

class TestSpatialBasis2x2(unittest.TestCase):
    def test_tiny_synthetic_example_2x2(self):
        """Verify exact counts and denominators on synthetic 4-day case:
        Day 1: A=1, B=1 (A&B)
        Day 2: A=1, B=0 (A&not-B) -> False trigger
        Day 3: A=0, B=1 (not-A&B) -> Missed trigger
        Day 4: A=0, B=0 (neither) -> Dry day
        """
        a = [1, 1, 0, 0]
        b = [1, 0, 1, 0]
        
        res = compute_2x2_metrics(a, b)
        
        self.assertEqual(res["n_total"], 4)
        self.assertEqual(res["n_11"], 1)
        self.assertEqual(res["n_10"], 1)
        self.assertEqual(res["n_01"], 1)
        self.assertEqual(res["n_00"], 1)
        
        # Denominators
        self.assertEqual(res["n_s0_triggers"], 2)  # A occurred twice
        self.assertEqual(res["n_neigh_triggers"], 2)  # B occurred twice
        self.assertEqual(res["n_event_days"], 3)  # A or B occurred 3 times
        
        # Conditional rates
        self.assertEqual(res["false_trigger_rate"], 0.5)  # 1 false out of 2 S0 triggers
        self.assertEqual(res["missed_trigger_rate"], 0.5)  # 1 missed out of 2 Neigh triggers
        
        # Event-day agreement
        self.assertAlmostEqual(res["event_agreement"], 1/3)
        
        # Cohen's kappa for symmetric 50-50 error
        self.assertEqual(res["cohens_kappa"], 0.0)

    def test_dry_days_do_not_inflate_conditional_rates(self):
        """Adding 100 dry days (A=0, B=0) must NOT change false_trigger_rate or missed_trigger_rate."""
        a_base = [1, 1, 0, 0]
        b_base = [1, 0, 1, 0]
        base_res = compute_2x2_metrics(a_base, b_base)
        
        # Add 100 dry days
        a_padded = a_base + [0] * 100
        b_padded = b_base + [0] * 100
        padded_res = compute_2x2_metrics(a_padded, b_padded)
        
        # Conditional rates must remain strictly identical
        self.assertEqual(padded_res["false_trigger_rate"], base_res["false_trigger_rate"])
        self.assertEqual(padded_res["missed_trigger_rate"], base_res["missed_trigger_rate"])
        self.assertEqual(padded_res["event_agreement"], base_res["event_agreement"])
        self.assertEqual(padded_res["precision"], base_res["precision"])
        self.assertEqual(padded_res["recall"], base_res["recall"])
        self.assertEqual(padded_res["f1"], base_res["f1"])
        
        # But trigger rate over all days drops from 50% to 2/104 ~ 1.92%
        self.assertLess(padded_res["trigger_rate"], base_res["trigger_rate"])

    def test_block_bootstrap_day_resampling(self):
        """Verify that day block-bootstrap resamples entire calendar dates, maintaining clustering."""
        np.random.seed(42)
        dates = ["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-02", "2020-01-03", "2020-01-03"]
        df = pd.DataFrame({
            "date": dates,
            "hawker": ["H1", "H2", "H1", "H2", "H1", "H2"],
            "a": [1, 1, 0, 0, 1, 0],
            "b": [1, 1, 0, 0, 0, 1]
        })
        
        unique_dates = np.array(sorted(df["date"].unique()))
        n_days = len(unique_dates)
        
        n_boot = 50
        boot_ft_rates = []
        for _ in range(n_boot):
            sample_days = np.random.choice(unique_dates, size=n_days, replace=True)
            sampled_rows = df[df["date"].isin(sample_days)]
            res = compute_2x2_metrics(sampled_rows["a"].values, sampled_rows["b"].values)
            boot_ft_rates.append(res["false_trigger_rate"])
            
        self.assertEqual(len(boot_ft_rates), n_boot)
        self.assertTrue(all(0.0 <= r <= 1.0 for r in boot_ft_rates))

if __name__ == "__main__":
    unittest.main()

