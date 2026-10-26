"""
src/data_gen/generator.py
--------------------------
Base legitimate MFS transaction generator for Bangladesh synthetic dataset.

Generates:
  - DIM_CUSTOMER   : ~5,000 unique customers
  - DIM_AGENT      : ~500 unique agents
  - DIM_TIME       : derived from transaction timestamps
  - DIM_TRANSACTION_TYPE : 5 types (send_money, cash_in, cash_out, payment, add_money)
  - FACT_TRANSACTIONS    : 50K+ legitimate transactions (is_fraud=False)

Fraud injection is handled separately by fraud_injector.py (Task 1.3).

Usage (via scripts/generate_dataset.py):
    from src.data_gen.generator import TransactionGenerator
    gen = TransactionGenerator()
    datasets = gen.generate()
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from faker import Faker

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bangladesh geographic constants
# ---------------------------------------------------------------------------

DIVISIONS: dict[str, list[str]] = {
    "Dhaka": [
        "Dhaka", "Gazipur", "Narayanganj", "Manikganj", "Munshiganj",
        "Narsingdi", "Tangail", "Kishoreganj", "Mymensingh", "Netrokona",
        "Jamalpur", "Sherpur", "Faridpur", "Gopalganj", "Madaripur",
        "Rajbari", "Shariatpur",
    ],
    "Chittagong": [
        "Chittagong", "Cox's Bazar", "Rangamati", "Bandarban", "Khagrachhari",
        "Feni", "Lakshmipur", "Noakhali", "Comilla", "Chandpur", "Brahmanbaria",
    ],
    "Sylhet": ["Sylhet", "Habiganj", "Moulvibazar", "Sunamganj"],
    "Rajshahi": [
        "Rajshahi", "Chapainawabganj", "Natore", "Naogaon", "Bogura",
        "Joypurhat", "Sirajganj", "Pabna",
    ],
    "Khulna": [
        "Khulna", "Bagerhat", "Satkhira", "Jessore", "Narail", "Magura",
        "Jhenaidah", "Kushtia", "Chuadanga", "Meherpur",
    ],
    "Barisal": [
        "Barisal", "Bhola", "Patuakhali", "Pirojpur", "Jhalokati", "Barguna",
    ],
    "Rangpur": [
        "Rangpur", "Dinajpur", "Thakurgaon", "Panchagarh", "Nilphamari",
        "Lalmonirhat", "Kurigram", "Gaibandha",
    ],
    "Mymensingh": ["Mymensingh", "Jamalpur", "Netrokona", "Sherpur"],
}

# Approximate centroid lat/lon for each district (subset; others get division centroid)
DISTRICT_GEO: dict[str, tuple[float, float]] = {
    "Dhaka": (23.8103, 90.4125),
    "Gazipur": (23.9999, 90.4253),
    "Narayanganj": (23.6238, 90.5001),
    "Chittagong": (22.3569, 91.7832),
    "Cox's Bazar": (21.4272, 92.0058),
    "Sylhet": (24.8949, 91.8687),
    "Rajshahi": (24.3636, 88.6241),
    "Khulna": (22.8456, 89.5403),
    "Barisal": (22.7010, 90.3535),
    "Rangpur": (25.7466, 89.2513),
    "Mymensingh": (24.7471, 90.4203),
    "Comilla": (23.4607, 91.1809),
    "Bogura": (24.8510, 89.3697),
    "Noakhali": (22.8696, 91.0994),
    "Jessore": (23.1667, 89.2167),
    "Dinajpur": (25.6279, 88.6338),
}

DIVISION_GEO: dict[str, tuple[float, float]] = {
    "Dhaka": (23.8103, 90.4125),
    "Chittagong": (22.3569, 91.7832),
    "Sylhet": (24.8949, 91.8687),
    "Rajshahi": (24.3636, 88.6241),
    "Khulna": (22.8456, 89.5403),
    "Barisal": (22.7010, 90.3535),
    "Rangpur": (25.7466, 89.2513),
    "Mymensingh": (24.7471, 90.4203),
}

# Flat list of all districts with their division
DISTRICT_TO_DIVISION: dict[str, str] = {
    district: division
    for division, districts in DIVISIONS.items()
    for district in districts
}

ALL_DISTRICTS: list[str] = list(DISTRICT_TO_DIVISION.keys())

# Population-weighted district probabilities (Dhaka-heavy, mimicking MFS usage patterns)
def _build_district_weights() -> list[float]:
    dhaka_w = 0.35
    dhaka_count = sum(1 for d in ALL_DISTRICTS if DISTRICT_TO_DIVISION[d] == "Dhaka")
    other_count = len(ALL_DISTRICTS) - dhaka_count
    other_w = (1.0 - dhaka_w) / other_count if other_count > 0 else 0.0
    raw = [
        dhaka_w / dhaka_count if DISTRICT_TO_DIVISION[d] == "Dhaka" else other_w
        for d in ALL_DISTRICTS
    ]
    total = sum(raw)
    return [w / total for w in raw]  # normalize to sum exactly 1.0

DISTRICT_WEIGHTS: list[float] = _build_district_weights()

# Transaction type definitions
TXN_TYPES: list[dict[str, Any]] = [
    {
        "txn_type_id": 1,
        "type_name": "send_money",
        "max_limit_bdt": 25000.0,
        "daily_limit_bdt": 25000.0,
        "requires_agent": False,
        "description": "Peer-to-peer wallet transfer",
    },
    {
        "txn_type_id": 2,
        "type_name": "cash_in",
        "max_limit_bdt": 30000.0,
        "daily_limit_bdt": 30000.0,
        "requires_agent": True,
        "description": "Deposit cash to wallet via agent",
    },
    {
        "txn_type_id": 3,
        "type_name": "cash_out",
        "max_limit_bdt": 25000.0,
        "daily_limit_bdt": 25000.0,
        "requires_agent": True,
        "description": "Withdraw cash from wallet via agent",
    },
    {
        "txn_type_id": 4,
        "type_name": "payment",
        "max_limit_bdt": 50000.0,
        "daily_limit_bdt": 50000.0,
        "requires_agent": False,
        "description": "Merchant / utility bill payment",
    },
    {
        "txn_type_id": 5,
        "type_name": "add_money",
        "max_limit_bdt": 50000.0,
        "daily_limit_bdt": 200000.0,
        "requires_agent": False,
        "description": "Bank-to-wallet top-up",
    },
]

# Probability of each transaction type (calibrated to Bangladesh MFS report 2023)
TXN_TYPE_PROBS: list[float] = [0.30, 0.22, 0.26, 0.15, 0.07]

# KYC tier daily limits
KYC_TIERS: dict[str, dict[str, Any]] = {
    "tier1": {"prob": 0.25, "daily_limit": 500.0},
    "tier2": {"prob": 0.60, "daily_limit": 30_000.0},
    "tier3": {"prob": 0.15, "daily_limit": 200_000.0},
}

# ---------------------------------------------------------------------------
# Config dataclass (loaded from .env)
# ---------------------------------------------------------------------------


@dataclass
class GeneratorConfig:
    """Configuration parameters for the TransactionGenerator."""

    seed: int = field(default_factory=lambda: int(os.getenv("DATA_SEED", "42")))
    num_transactions: int = field(
        default_factory=lambda: int(os.getenv("NUM_TRANSACTIONS", "55000"))
    )
    num_customers: int = 5000
    num_agents: int = 500
    start_date: datetime = field(
        default_factory=lambda: datetime(2024, 1, 1)
    )
    end_date: datetime = field(
        default_factory=lambda: datetime(2024, 12, 31, 23, 59, 59)
    )
    output_dir: Path = field(
        default_factory=lambda: Path("data/raw")
    )

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_district_geo(district: str) -> tuple[float, float]:
    """Return (lat, lon) for a district, with small random jitter."""
    if district in DISTRICT_GEO:
        lat, lon = DISTRICT_GEO[district]
    else:
        division = DISTRICT_TO_DIVISION.get(district, "Dhaka")
        lat, lon = DIVISION_GEO.get(division, (23.8103, 90.4125))
    return (
        round(lat + random.uniform(-0.3, 0.3), 6),
        round(lon + random.uniform(-0.3, 0.3), 6),
    )


def _random_bd_phone(rng: np.random.Generator) -> str:
    """Generate a random Bangladeshi mobile number (01XXXXXXXXX)."""
    prefixes = ["013", "014", "015", "016", "017", "018", "019"]
    prefix = prefixes[rng.integers(len(prefixes))]
    suffix = "".join([str(d) for d in rng.integers(0, 10, size=8)])
    return prefix + suffix


def _hash_nid(phone: str) -> int:
    """Deterministic NID hash from phone (no real NID used)."""
    return int(hashlib.md5(phone.encode()).hexdigest()[:8], 16)


def _build_timestamps(
    n: int,
    start: datetime,
    end: datetime,
    rng: np.random.Generator,
) -> list[datetime]:
    """
    Generate n transaction timestamps with realistic intraday distribution.

    Peak hours: 8-13 and 17-20 (higher probability).
    Non-peak and overnight hours: lower probability.
    Month-end (25th-31st): 20% more transactions.
    """
    total_seconds = int((end - start).total_seconds())
    raw_ts: list[datetime] = []

    while len(raw_ts) < n:
        batch_size = min((n - len(raw_ts)) * 3, 200_000)
        offsets = rng.integers(0, total_seconds, size=batch_size)
        candidates = [start + timedelta(seconds=int(s)) for s in offsets]

        for ts in candidates:
            if len(raw_ts) >= n:
                break
            hour = ts.hour
            day = ts.day
            # Peak hour boost
            is_peak = hour in set(range(8, 14)) | set(range(17, 21))
            # Month-end boost
            is_month_end = day >= 25
            # Overnight suppression
            is_overnight = hour < 6

            accept_prob = 1.0
            if is_peak:
                accept_prob *= 1.8
            if is_month_end:
                accept_prob *= 1.2
            if is_overnight:
                accept_prob *= 0.15

            # Normalize: cap at 1.0 (rejection sampling)
            accept_prob = min(accept_prob / 2.0, 1.0)
            if rng.random() < accept_prob:
                raw_ts.append(ts)

    return sorted(raw_ts[:n])


def _make_time_id(ts: datetime) -> int:
    """Convert timestamp to integer time_id in YYYYMMDDHHmmss format."""
    return int(ts.strftime("%Y%m%d%H%M%S"))


def _fee_for_txn(txn_type: str, amount: float) -> float:
    """Calculate transaction fee in BDT (Bangladesh MFS rate schedule)."""
    fee_map: dict[str, float] = {
        "send_money": 0.0,          # free P2P (bKash model)
        "cash_in": 0.0,             # free cash-in
        "cash_out": 0.0185,         # 1.85% (typical MFS rate)
        "payment": 0.0,             # free merchant payment
        "add_money": 0.0,           # free bank-to-wallet
    }
    rate = fee_map.get(txn_type, 0.0)
    fee = round(amount * rate, 2)
    return min(fee, 30.0) if txn_type == "cash_out" else fee  # cap fee at 30 BDT


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------


class TransactionGenerator:
    """
    Generates synthetic Bangladesh MFS (Mobile Financial Service) transactions.

    All output is deterministic given the same seed. This class generates only
    LEGITIMATE transactions (is_fraud=False). Fraud injection is done by
    FraudInjector (Task 1.3).

    Example:
        >>> gen = TransactionGenerator()
        >>> datasets = gen.generate()
        >>> datasets["fact_transactions"].shape
        (55000, 19)
    """

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self.config = config or GeneratorConfig()
        self._rng = np.random.default_rng(self.config.seed)
        self._fake = Faker("en_US")
        Faker.seed(self.config.seed)
        random.seed(self.config.seed)
        logger.info(
            "TransactionGenerator initialised | seed=%d | n=%d",
            self.config.seed,
            self.config.num_transactions,
        )

    # ------------------------------------------------------------------
    # Dimension generators
    # ------------------------------------------------------------------

    def generate_dim_transaction_type(self) -> pd.DataFrame:
        """Return the static transaction type dimension table."""
        df = pd.DataFrame(TXN_TYPES)
        logger.info("DIM_TRANSACTION_TYPE: %d rows", len(df))
        return df

    def generate_dim_customer(self) -> pd.DataFrame:
        """
        Generate DIM_CUSTOMER with realistic Bangladesh demographics.

        Returns:
            DataFrame with columns matching DIM_CUSTOMER schema.
        """
        n = self.config.num_customers
        districts = self._rng.choice(
            ALL_DISTRICTS, size=n, p=DISTRICT_WEIGHTS
        )
        divisions = [DISTRICT_TO_DIVISION[d] for d in districts]

        # KYC tier assignment
        tier_probs = [v["prob"] for v in KYC_TIERS.values()]
        tiers = self._rng.choice(list(KYC_TIERS.keys()), size=n, p=tier_probs)

        # Account ages: mixture of new and old accounts
        # 20% new (<90 days), 80% established
        account_ages = np.where(
            self._rng.random(n) < 0.20,
            self._rng.integers(1, 90, size=n),
            self._rng.integers(90, 1825, size=n),  # up to 5 years
        )

        # Registration timestamps (up to 5 years before end_date)
        reg_offsets = account_ages * 86400  # seconds
        registered_at = [
            self.config.end_date - timedelta(seconds=int(s))
            for s in reg_offsets
        ]

        phones = [_random_bd_phone(self._rng) for _ in range(n)]

        records = {
            "customer_id": list(range(1, n + 1)),
            "customer_code": [f"CUST-{i:05d}" for i in range(1, n + 1)],
            "name": [self._fake.name() for _ in range(n)],
            "phone": phones,
            "district": districts.tolist(),
            "division": divisions,
            "account_age_days": account_ages.tolist(),
            "kyc_tier": tiers.tolist(),
            "linked_nid_hash": [_hash_nid(p) for p in phones],
            "registered_at": registered_at,
        }
        df = pd.DataFrame(records)
        logger.info("DIM_CUSTOMER: %d rows", len(df))
        return df

    def generate_dim_agent(self) -> pd.DataFrame:
        """
        Generate DIM_AGENT with realistic Bangladesh agent network.

        Returns:
            DataFrame with columns matching DIM_AGENT schema.
        """
        n = self.config.num_agents
        districts = self._rng.choice(
            ALL_DISTRICTS, size=n, p=DISTRICT_WEIGHTS
        )
        divisions = [DISTRICT_TO_DIVISION[d] for d in districts]

        agent_types = self._rng.choice(
            ["retailer", "super_agent", "distributor"],
            size=n,
            p=[0.80, 0.15, 0.05],
        )

        # 95% agents are active
        is_active = self._rng.random(n) < 0.95

        # Commission rate: 1.0-1.5% for retailers, 0.8-1.2% for super_agents
        commission_rates = np.where(
            agent_types == "retailer",
            self._rng.uniform(1.0, 1.5, n),
            self._rng.uniform(0.8, 1.2, n),
        )

        reg_days_ago = self._rng.integers(180, 2000, size=n)
        registered_at = [
            self.config.end_date - timedelta(days=int(d))
            for d in reg_days_ago
        ]

        records = {
            "agent_id": list(range(1, n + 1)),
            "agent_code": [f"AGT-{i:05d}" for i in range(1, n + 1)],
            "district": districts.tolist(),
            "division": divisions,
            "agent_type": agent_types.tolist(),
            "is_active": is_active.tolist(),
            "commission_rate": commission_rates.round(4).tolist(),
            "registered_at": registered_at,
        }
        df = pd.DataFrame(records)
        logger.info("DIM_AGENT: %d rows", len(df))
        return df

    def generate_dim_time(self, timestamps: list[datetime]) -> pd.DataFrame:
        """
        Derive DIM_TIME from a list of transaction timestamps.

        Args:
            timestamps: Sorted list of datetime objects.

        Returns:
            DataFrame with unique time dimension rows.
        """
        # Deduplicate to minute-level for manageability
        unique_ts = sorted(
            {ts.replace(second=0, microsecond=0) for ts in timestamps}
        )

        records = []
        for ts in unique_ts:
            records.append(
                {
                    "time_id": _make_time_id(ts),
                    "ts": ts,
                    "hour": ts.hour,
                    "day_of_week": ts.weekday(),
                    "day_name": ts.strftime("%A"),
                    "week_of_year": ts.isocalendar()[1],
                    "month": ts.month,
                    "month_name": ts.strftime("%B"),
                    "quarter": (ts.month - 1) // 3 + 1,
                    "year": ts.year,
                    # Bangladesh weekend: Friday (4) and Saturday (5)
                    "is_weekend": ts.weekday() in (4, 5),
                    "is_peak_hour": ts.hour in set(range(8, 14)) | set(range(17, 21)),
                    "is_month_end": ts.day >= 28,
                }
            )
        df = pd.DataFrame(records).drop_duplicates(subset=["time_id"])
        logger.info("DIM_TIME: %d unique rows", len(df))
        return df

    # ------------------------------------------------------------------
    # Fact table generator
    # ------------------------------------------------------------------

    def generate_fact_transactions(
        self,
        dim_customer: pd.DataFrame,
        dim_agent: pd.DataFrame,
    ) -> tuple[pd.DataFrame, list[datetime]]:
        """
        Generate FACT_TRANSACTIONS with only legitimate transactions.

        Args:
            dim_customer: Generated customer dimension.
            dim_agent:    Generated agent dimension.

        Returns:
            Tuple of (fact_transactions DataFrame, list of raw timestamps).
        """
        n = self.config.num_transactions
        logger.info("Generating %d legitimate transactions...", n)

        # --- Timestamps ---
        timestamps = _build_timestamps(
            n, self.config.start_date, self.config.end_date, self._rng
        )

        # --- Transaction types ---
        txn_type_ids = self._rng.choice(
            [t["txn_type_id"] for t in TXN_TYPES],
            size=n,
            p=TXN_TYPE_PROBS,
        )
        txn_type_names = {t["txn_type_id"]: t["type_name"] for t in TXN_TYPES}

        # --- Customer sampling (Pareto: 20% of customers do 60% of txns) ---
        customer_ids_all = dim_customer["customer_id"].values
        customer_probs = self._rng.dirichlet(
            np.ones(len(customer_ids_all)) * 0.5
        )
        customer_ids = self._rng.choice(
            customer_ids_all, size=n, p=customer_probs
        )

        # --- Agent sampling (only for cash_in and cash_out) ---
        active_agents = dim_agent[dim_agent["is_active"]]["agent_id"].values
        agent_ids: list[int | None] = []
        for tid in txn_type_ids:
            tname = txn_type_names[tid]
            if tname in ("cash_in", "cash_out"):
                agent_ids.append(
                    int(self._rng.choice(active_agents))
                )
            else:
                agent_ids.append(None)

        # --- Amounts: lognormal distribution calibrated to Bangladesh MFS ---
        # Mean log-amount ~7.5 (e^7.5 ~ 1800 BDT), sigma ~1.2
        raw_amounts = np.exp(self._rng.normal(loc=7.5, scale=1.2, size=n))
        # Clip to [10, 30000] BDT for legitimate transactions
        amounts = np.clip(raw_amounts, 10.0, 30_000.0).round(2)

        # --- Channels ---
        channels = self._rng.choice(
            ["app", "ussd", "agent"],
            size=n,
            p=[0.55, 0.25, 0.20],
        )
        # Force agent channel for cash_in/cash_out
        for i, tid in enumerate(txn_type_ids):
            if txn_type_names[tid] in ("cash_in", "cash_out"):
                channels[i] = "agent"

        # --- Status (98% success, 1.5% failed, 0.5% reversed) ---
        statuses = self._rng.choice(
            ["success", "failed", "reversed"],
            size=n,
            p=[0.98, 0.015, 0.005],
        )

        # --- Geographic data ---
        cust_district_map = dict(
            zip(dim_customer["customer_id"], dim_customer["district"])
        )
        sender_districts = [cust_district_map[cid] for cid in customer_ids]
        # Receiver: 80% same district, 20% random (for variety)
        receiver_districts: list[str] = []
        for sd in sender_districts:
            if self._rng.random() < 0.80:
                receiver_districts.append(sd)
            else:
                receiver_districts.append(
                    self._rng.choice(ALL_DISTRICTS)
                )

        # Geo coordinates with jitter
        lats: list[float] = []
        lons: list[float] = []
        for sd, ch in zip(sender_districts, channels):
            if ch == "app":
                lat, lon = _get_district_geo(sd)
                lats.append(lat)
                lons.append(lon)
            else:
                lats.append(None)  # type: ignore[arg-type]
                lons.append(None)  # type: ignore[arg-type]

        # Device fingerprints (app only, unique per customer device)
        cust_device_map: dict[int, int] = {}
        device_fps: list[int | None] = []
        for cid, ch in zip(customer_ids, channels):
            if ch == "app":
                if cid not in cust_device_map:
                    cust_device_map[cid] = int(
                        self._rng.integers(100_000, 999_999)
                    )
                device_fps.append(cust_device_map[cid])
            else:
                device_fps.append(None)

        # --- Transaction references ---
        txn_refs = [
            f"TXN{ts.strftime('%Y%m%d')}{i:06d}"
            for i, ts in enumerate(timestamps, start=1)
        ]

        # --- Fees ---
        fees = [
            _fee_for_txn(txn_type_names[tid], amt)
            for tid, amt in zip(txn_type_ids, amounts)
        ]

        # --- Time IDs ---
        time_ids = [
            _make_time_id(ts.replace(second=0, microsecond=0))
            for ts in timestamps
        ]

        df = pd.DataFrame(
            {
                "transaction_id": list(range(1, n + 1)),
                "txn_ref": txn_refs,
                "customer_id": customer_ids,
                "agent_id": agent_ids,
                "time_id": time_ids,
                "txn_type_id": txn_type_ids,
                "amount_bdt": amounts,
                "fee_bdt": fees,
                "channel": channels,
                "status": statuses,
                "sender_district": sender_districts,
                "receiver_district": receiver_districts,
                "location_lat": lats,
                "location_lon": lons,
                "device_fingerprint": device_fps,
                "is_fraud": False,
                "fraud_pattern": None,
                "created_at": datetime.now(),
            }
        )

        logger.info(
            "FACT_TRANSACTIONS: %d rows | fraud=0 | channels=%s",
            len(df),
            df["channel"].value_counts().to_dict(),
        )
        return df, timestamps

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def generate(self) -> dict[str, pd.DataFrame]:
        """
        Run full data generation pipeline for legitimate transactions.

        Returns:
            Dict with keys: fact_transactions, dim_customer, dim_agent,
            dim_time, dim_transaction_type.
        """
        logger.info("=== Starting base data generation (legitimate only) ===")

        dim_txn_type = self.generate_dim_transaction_type()
        dim_customer = self.generate_dim_customer()
        dim_agent = self.generate_dim_agent()
        fact, timestamps = self.generate_fact_transactions(dim_customer, dim_agent)
        dim_time = self.generate_dim_time(timestamps)

        datasets = {
            "fact_transactions": fact,
            "dim_customer": dim_customer,
            "dim_agent": dim_agent,
            "dim_time": dim_time,
            "dim_transaction_type": dim_txn_type,
        }

        # Save to CSV
        for name, df in datasets.items():
            out_path = self.config.output_dir / f"{name}.csv"
            df.to_csv(out_path, index=False)
            logger.info("Saved %s -> %s (%d rows)", name, out_path, len(df))

        logger.info("=== Base generation complete ===")
        return datasets
