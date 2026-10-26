"""
src/data_gen/fraud_injector.py
-------------------------------
Injects 5 synthetic fraud patterns into a legitimate MFS transaction dataset.

Patterns:
  1. otp_sim_swap    : SIM-hijack then midnight cash-out from new device
  2. mule_chain      : Rapid A->B->C->D send_money chains + final cash_out
  3. cashout_ring    : Compromised agent processes burst of cash_outs
  4. structuring     : Just-below-50K repeated sends from same customer
  5. impossible_geo  : Same account transacts 100km+ apart within 30 min

Usage:
    from src.data_gen.fraud_injector import FraudInjector
    injector = FraudInjector(seed=42)
    fact_with_fraud = injector.inject(fact_df, dim_customer, dim_agent)
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.data_gen.generator import (
    ALL_DISTRICTS,
    DISTRICT_GEO,
    DIVISION_GEO,
    DISTRICT_TO_DIVISION,
    _get_district_geo,
    _make_time_id,
    _fee_for_txn,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# District distance helper (Haversine)
# ---------------------------------------------------------------------------

_R_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km between two coordinates."""
    phi1, phi2 = map(lambda x: x * np.pi / 180, [lat1, lat2])
    dphi = (lat2 - lat1) * np.pi / 180
    dlam = (lon2 - lon1) * np.pi / 180
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * _R_KM * np.arcsin(np.sqrt(a))


def _districts_far_apart(d1: str, d2: str, min_km: float = 100.0) -> bool:
    """Return True if two districts are at least min_km apart."""
    def _geo(d: str) -> tuple[float, float]:
        if d in DISTRICT_GEO:
            return DISTRICT_GEO[d]
        div = DISTRICT_TO_DIVISION.get(d, "Dhaka")
        return DIVISION_GEO.get(div, (23.81, 90.41))

    lat1, lon1 = _geo(d1)
    lat2, lon2 = _geo(d2)
    return _haversine_km(lat1, lon1, lat2, lon2) >= min_km


# Pre-compute pairs of far-apart districts for pattern 5
_FAR_PAIRS: list[tuple[str, str]] = [
    (d1, d2)
    for i, d1 in enumerate(ALL_DISTRICTS)
    for d2 in ALL_DISTRICTS[i + 1:]
    if _districts_far_apart(d1, d2, min_km=100.0)
]

# ---------------------------------------------------------------------------
# FraudInjector
# ---------------------------------------------------------------------------


class FraudInjector:
    """
    Injects synthetic fraud rows into a legitimate fact_transactions DataFrame.

    All added/modified rows are appended; transaction_ids are re-indexed
    at the end to maintain uniqueness.

    Args:
        seed: Random seed for reproducibility.
        fraud_rate: Target overall fraud rate (default 0.026 = 2.6%).
    """

    def __init__(self, seed: int = 42, fraud_rate: float = 0.026) -> None:
        self._rng = np.random.default_rng(seed)
        random.seed(seed)
        self.fraud_rate = fraud_rate
        # Fraction of fraud budget allocated to each pattern
        self._pattern_weights = {
            "otp_sim_swap": 0.31,   # ~0.8% of total
            "mule_chain":   0.23,   # ~0.6%
            "cashout_ring": 0.19,   # ~0.5%
            "structuring":  0.15,   # ~0.4%
            "impossible_geo": 0.12, # ~0.3%
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inject(
        self,
        fact: pd.DataFrame,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Inject all 5 fraud patterns into the fact table.

        Args:
            fact:         Legitimate transactions (is_fraud=False).
            dim_customer: Customer dimension.
            dim_agent:    Agent dimension.

        Returns:
            Combined DataFrame with legitimate + fraud rows, shuffled by timestamp.
        """
        n_legit = len(fact)
        total_fraud_target = int(n_legit * self.fraud_rate / (1 - self.fraud_rate))
        logger.info(
            "Injecting fraud: %d legitimate rows -> target %d fraud rows (%.1f%%)",
            n_legit, total_fraud_target, self.fraud_rate * 100,
        )

        fraud_frames: list[pd.DataFrame] = []

        for pattern, weight in self._pattern_weights.items():
            n_pattern = max(1, int(total_fraud_target * weight))
            logger.info("  Pattern %-20s -> %d rows", pattern, n_pattern)
            fn = getattr(self, f"_inject_{pattern}")
            fraud_df = fn(fact, dim_customer, dim_agent, n_pattern)
            fraud_frames.append(fraud_df)

        all_fraud = pd.concat(fraud_frames, ignore_index=True)

        # Combine and re-index transaction_id
        combined = pd.concat([fact, all_fraud], ignore_index=True)
        combined = combined.sort_values("time_id").reset_index(drop=True)
        combined["transaction_id"] = range(1, len(combined) + 1)

        n_fraud = combined["is_fraud"].sum()
        actual_rate = n_fraud / len(combined) * 100
        logger.info(
            "Injection complete: total=%d fraud=%d (%.2f%%)",
            len(combined), n_fraud, actual_rate,
        )
        return combined

    # ------------------------------------------------------------------
    # Pattern 1 — OTP / SIM-Swap scam
    # ------------------------------------------------------------------

    def _inject_otp_sim_swap(
        self,
        fact: pd.DataFrame,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
        n: int,
    ) -> pd.DataFrame:
        """
        Fraud: SIM-swapped account drains wallet at night via cash_out.

        Characteristics:
        - hour in [0, 1, 2, 3, 4] (midnight to 4am)
        - channel = app (device fingerprint mismatch — new device)
        - receiver_district != sender_district
        - amount near tier2 daily limit (15,000-24,999 BDT)
        - cash_out txn_type_id = 3
        """
        active_agents = dim_agent[dim_agent["is_active"]]["agent_id"].values
        customers = dim_customer.sample(min(n, len(dim_customer)), random_state=int(self._rng.integers(9999))).copy()

        rows: list[dict[str, Any]] = []
        base_ts = datetime(2024, 1, 15)  # start injecting from mid-Jan

        for i in range(n):
            cust = customers.iloc[i % len(customers)]
            # Random date in 2024
            day_offset = int(self._rng.integers(0, 350))
            # Midnight hour: 0-4
            hour = int(self._rng.integers(0, 5))
            minute = int(self._rng.integers(0, 60))
            ts = datetime(2024, 1, 1) + timedelta(days=day_offset, hours=hour, minutes=minute)

            sender_dist = cust["district"]
            # Pick a far-away receiver district
            far_dists = [d for d in ALL_DISTRICTS if _districts_far_apart(sender_dist, d, 80.0)]
            receiver_dist = self._rng.choice(far_dists) if far_dists else self._rng.choice(ALL_DISTRICTS)

            amount = round(float(self._rng.uniform(15_000, 24_999)), 2)
            agent_id = int(self._rng.choice(active_agents))
            lat, lon = _get_district_geo(receiver_dist)  # device at receiver location
            ts_min = ts.replace(second=0, microsecond=0)

            rows.append({
                "txn_ref":           f"FRD{ts.strftime('%Y%m%d')}{i:06d}A",
                "customer_id":       int(cust["customer_id"]),
                "agent_id":          agent_id,
                "time_id":           _make_time_id(ts_min),
                "txn_type_id":       3,          # cash_out
                "amount_bdt":        amount,
                "fee_bdt":           _fee_for_txn("cash_out", amount),
                "channel":           "app",
                "status":            "success",
                "sender_district":   sender_dist,
                "receiver_district": receiver_dist,
                "location_lat":      lat,
                "location_lon":      lon,
                "device_fingerprint": int(self._rng.integers(1_000_000, 9_999_999)),  # NEW device
                "is_fraud":          True,
                "fraud_pattern":     "otp_sim_swap",
                "created_at":        datetime.now(),
            })

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Pattern 2 — Mule account chain
    # ------------------------------------------------------------------

    def _inject_mule_chain(
        self,
        fact: pd.DataFrame,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
        n: int,
    ) -> pd.DataFrame:
        """
        Fraud: Funds hop through 3-5 new mule accounts before cash-out.

        Characteristics:
        - Chain length: 3-5 accounts (send_money each hop)
        - Final hop: cash_out via agent
        - All accounts in chain have account_age_days < 30
        - Same amount flows through each hop
        - Time between hops: 1-3 minutes
        """
        active_agents = dim_agent[dim_agent["is_active"]]["agent_id"].values
        # Find or simulate new/mule customers (age < 30 days)
        new_custs = dim_customer[dim_customer["account_age_days"] < 30]
        if len(new_custs) < 5:
            # Fall back to all customers if not enough new ones
            new_custs = dim_customer

        rows: list[dict[str, Any]] = []
        chains_to_make = max(1, n // 4)  # avg chain length ~4 txns

        for c_idx in range(chains_to_make):
            chain_len = int(self._rng.integers(3, 6))  # 3 to 5 hops
            day_offset = int(self._rng.integers(0, 350))
            hour = int(self._rng.integers(9, 23))
            minute = int(self._rng.integers(0, 60))
            base_time = datetime(2024, 1, 1) + timedelta(days=day_offset, hours=hour, minutes=minute)

            amount = round(float(self._rng.uniform(5_000, 20_000)), 2)
            district = self._rng.choice(ALL_DISTRICTS)

            # Mule customers for this chain
            chain_custs = new_custs.sample(
                min(chain_len, len(new_custs)), replace=True,
                random_state=int(self._rng.integers(9999))
            )

            for hop in range(chain_len):
                cust = chain_custs.iloc[hop % len(chain_custs)]
                ts = base_time + timedelta(minutes=hop * int(self._rng.integers(1, 4)))
                ts_min = ts.replace(second=0, microsecond=0)

                is_last = (hop == chain_len - 1)
                txn_type = 3 if is_last else 1  # cash_out for final hop
                agent_id = int(self._rng.choice(active_agents)) if is_last else None

                rows.append({
                    "txn_ref":           f"FRD{ts.strftime('%Y%m%d')}{c_idx:04d}M{hop}",
                    "customer_id":       int(cust["customer_id"]),
                    "agent_id":          agent_id,
                    "time_id":           _make_time_id(ts_min),
                    "txn_type_id":       txn_type,
                    "amount_bdt":        amount,
                    "fee_bdt":           _fee_for_txn("cash_out" if is_last else "send_money", amount),
                    "channel":           "agent" if is_last else "app",
                    "status":            "success",
                    "sender_district":   district,
                    "receiver_district": district,
                    "location_lat":      None,
                    "location_lon":      None,
                    "device_fingerprint": None,
                    "is_fraud":          True,
                    "fraud_pattern":     "mule_chain",
                    "created_at":        datetime.now(),
                })

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Pattern 3 — Cash-out ring (agent velocity spike)
    # ------------------------------------------------------------------

    def _inject_cashout_ring(
        self,
        fact: pd.DataFrame,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
        n: int,
    ) -> pd.DataFrame:
        """
        Fraud: Compromised agent processes burst cash_outs for many customers.

        Characteristics:
        - 1-3 compromised agents
        - Each processes 20-40 cash_outs within 1-2 hours
        - Customer accounts are new (age < 60 days) or dormant
        - Amounts varied but all below 10,000 BDT (below reporting threshold)
        - Low-traffic district agent with high volume
        """
        # Pick 1-3 compromised agents from low-traffic districts
        low_traffic_divs = ["Rangpur", "Barisal", "Sylhet"]
        compromised_mask = dim_agent["division"].isin(low_traffic_divs)
        compromised_pool = dim_agent[compromised_mask & dim_agent["is_active"]]
        if len(compromised_pool) == 0:
            compromised_pool = dim_agent[dim_agent["is_active"]]

        n_rings = max(1, n // 25)
        rows: list[dict[str, Any]] = []

        for ring_idx in range(n_rings):
            agent = compromised_pool.sample(1, random_state=int(self._rng.integers(9999))).iloc[0]
            txns_in_ring = int(self._rng.integers(20, 41))

            day_offset = int(self._rng.integers(0, 350))
            hour_start = int(self._rng.integers(8, 20))
            ring_start = datetime(2024, 1, 1) + timedelta(days=day_offset, hours=hour_start)

            # New/dormant customers for this ring
            new_custs = dim_customer[dim_customer["account_age_days"] < 60]
            if len(new_custs) < txns_in_ring:
                new_custs = dim_customer

            ring_custs = new_custs.sample(
                min(txns_in_ring, len(new_custs)), replace=True,
                random_state=int(self._rng.integers(9999))
            )

            for t in range(min(txns_in_ring, n - len(rows))):
                cust = ring_custs.iloc[t % len(ring_custs)]
                ts = ring_start + timedelta(minutes=int(self._rng.integers(0, 90)))
                ts_min = ts.replace(second=0, microsecond=0)
                amount = round(float(self._rng.uniform(1_000, 9_999)), 2)

                rows.append({
                    "txn_ref":           f"FRD{ts.strftime('%Y%m%d')}{ring_idx:03d}R{t:03d}",
                    "customer_id":       int(cust["customer_id"]),
                    "agent_id":          int(agent["agent_id"]),
                    "time_id":           _make_time_id(ts_min),
                    "txn_type_id":       3,  # cash_out
                    "amount_bdt":        amount,
                    "fee_bdt":           _fee_for_txn("cash_out", amount),
                    "channel":           "agent",
                    "status":            "success",
                    "sender_district":   agent["district"],
                    "receiver_district": agent["district"],
                    "location_lat":      None,
                    "location_lon":      None,
                    "device_fingerprint": None,
                    "is_fraud":          True,
                    "fraud_pattern":     "cashout_ring",
                    "created_at":        datetime.now(),
                })
                if len(rows) >= n:
                    break
            if len(rows) >= n:
                break

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Pattern 4 — Structuring / Smurfing
    # ------------------------------------------------------------------

    def _inject_structuring(
        self,
        fact: pd.DataFrame,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
        n: int,
    ) -> pd.DataFrame:
        """
        Fraud: Repeated just-below-50K transactions from same customer within 24h.

        Characteristics:
        - Amount: 45,000-49,999 BDT (just below 50K BFIU threshold)
        - 3-6 transactions per cluster from same customer to same receiver
        - Within 24-hour window
        - Mix of send_money and payment types
        """
        customers = dim_customer.copy()
        n_clusters = max(1, n // 4)
        rows: list[dict[str, Any]] = []

        for cl_idx in range(n_clusters):
            cust = customers.sample(1, random_state=int(self._rng.integers(9999))).iloc[0]
            cluster_size = int(self._rng.integers(3, 7))

            day_offset = int(self._rng.integers(0, 350))
            hour_start = int(self._rng.integers(8, 18))
            cluster_start = datetime(2024, 1, 1) + timedelta(days=day_offset, hours=hour_start)

            # Fixed receiver district per cluster (same target)
            receiver_dist = self._rng.choice(ALL_DISTRICTS)

            for t in range(min(cluster_size, n - len(rows))):
                # Spread transactions over up to 20 hours within the day
                ts = cluster_start + timedelta(hours=int(self._rng.integers(0, 20)), minutes=int(self._rng.integers(0, 60)))
                ts_min = ts.replace(second=0, microsecond=0)
                # Structuring amount: just below threshold
                amount = round(float(self._rng.uniform(45_000, 49_999)), 2)
                # Alternate between send_money (1) and payment (4)
                txn_type = 1 if t % 2 == 0 else 4

                rows.append({
                    "txn_ref":           f"FRD{ts.strftime('%Y%m%d')}{cl_idx:04d}S{t}",
                    "customer_id":       int(cust["customer_id"]),
                    "agent_id":          None,
                    "time_id":           _make_time_id(ts_min),
                    "txn_type_id":       txn_type,
                    "amount_bdt":        amount,
                    "fee_bdt":           0.0,
                    "channel":           "app",
                    "status":            "success",
                    "sender_district":   cust["district"],
                    "receiver_district": receiver_dist,
                    "location_lat":      None,
                    "location_lon":      None,
                    "device_fingerprint": None,
                    "is_fraud":          True,
                    "fraud_pattern":     "structuring",
                    "created_at":        datetime.now(),
                })
                if len(rows) >= n:
                    break
            if len(rows) >= n:
                break

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Pattern 5 — Impossible geography
    # ------------------------------------------------------------------

    def _inject_impossible_geo(
        self,
        fact: pd.DataFrame,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
        n: int,
    ) -> pd.DataFrame:
        """
        Fraud: Two transactions from same account in locations 100km+ apart
        within 30 minutes (physically impossible travel time).

        Characteristics:
        - Both transactions via app channel (location data present)
        - Time gap: 5-29 minutes
        - Distance: >100 km
        - Amounts: normal range (not suspicious individually)
        """
        if not _FAR_PAIRS:
            logger.warning("No far district pairs found; skipping impossible_geo")
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []

        for i in range(n // 2):  # each fraud event = 2 transactions
            cust = dim_customer.sample(1, random_state=int(self._rng.integers(9999))).iloc[0]
            day_offset = int(self._rng.integers(0, 350))
            hour = int(self._rng.integers(8, 22))
            minute = int(self._rng.integers(0, 50))
            ts1 = datetime(2024, 1, 1) + timedelta(days=day_offset, hours=hour, minutes=minute)

            # Second transaction: 5-29 minutes later
            gap_minutes = int(self._rng.integers(5, 30))
            ts2 = ts1 + timedelta(minutes=gap_minutes)

            # Pick two far-apart districts
            pair_idx = int(self._rng.integers(len(_FAR_PAIRS)))
            dist1, dist2 = _FAR_PAIRS[pair_idx]
            lat1, lon1 = _get_district_geo(dist1)
            lat2, lon2 = _get_district_geo(dist2)

            amount1 = round(float(self._rng.uniform(500, 10_000)), 2)
            amount2 = round(float(self._rng.uniform(500, 10_000)), 2)
            device_fp = int(self._rng.integers(100_000, 999_999))

            for j, (ts, dist, lat, lon, amount) in enumerate([
                (ts1, dist1, lat1, lon1, amount1),
                (ts2, dist2, lat2, lon2, amount2),
            ]):
                ts_min = ts.replace(second=0, microsecond=0)
                rows.append({
                    "txn_ref":           f"FRD{ts.strftime('%Y%m%d')}{i:05d}G{j}",
                    "customer_id":       int(cust["customer_id"]),
                    "agent_id":          None,
                    "time_id":           _make_time_id(ts_min),
                    "txn_type_id":       1,   # send_money
                    "amount_bdt":        amount,
                    "fee_bdt":           0.0,
                    "channel":           "app",
                    "status":            "success",
                    "sender_district":   dist,
                    "receiver_district": self._rng.choice(ALL_DISTRICTS),
                    "location_lat":      lat,
                    "location_lon":      lon,
                    "device_fingerprint": device_fp,  # same device, different location
                    "is_fraud":          True,
                    "fraud_pattern":     "impossible_geo",
                    "created_at":        datetime.now(),
                })

            if len(rows) >= n:
                break

        return pd.DataFrame(rows)
