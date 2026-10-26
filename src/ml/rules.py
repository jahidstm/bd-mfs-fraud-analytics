"""
src/ml/rules.py
---------------
Rule-based fraud detection baseline for Bangladesh MFS transactions.

Rules implemented (each produces a risk signal 0 or 1):
  R1 - MIDNIGHT_CASHOUT     : cash_out between midnight and 4am
  R2 - NEAR_THRESHOLD       : amount in [20000, 24999] (structuring signal)
  R3 - CROSS_DISTRICT_HIGH  : sender_district != receiver_district AND amount > 10000
  R4 - NEW_ACCOUNT_CASHOUT  : account < 90 days old AND is cash_out
  R5 - HIGH_VELOCITY        : more than 5 transactions in same day by customer
  R6 - LARGE_AMOUNT         : amount > 1 standard deviation above type mean
  R7 - AWAY_FROM_HOME       : customer transacting from non-home district at midnight

Combined rule score: count of rules triggered (0-7).
Threshold sweep: finds optimal integer threshold maximising F1 on train set.

Evaluation metrics (no accuracy-only reporting):
  - Precision-Recall AUC (PR-AUC) — primary metric for imbalanced fraud data
  - Precision@K (K=5%, K=10% of test set by risk score) — analyst efficiency
  - F1 score at optimal threshold
  - Confusion matrix at optimal threshold

Usage:
    python -m src.ml.rules
    from src.ml.rules import RuleBasedDetector
"""

import logging
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)

from src.db.connection import get_engine
from src.ml.features import build_features

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ml.rules")


class RuleBasedDetector:
    """
    Deterministic rule-based fraud scorer.
    Each rule contributes 1 point to the composite risk score.
    """

    def __init__(self, threshold: int = 2):
        self.threshold = threshold
        self.rule_names = [
            "R1_midnight_cashout",
            "R2_near_threshold",
            "R3_cross_district_high_amt",
            "R4_new_account_cashout",
            "R5_high_velocity",
            "R6_large_amount",
            "R7_away_from_home_midnight",
        ]

    def _apply_rules(self, X: pd.DataFrame) -> pd.DataFrame:
        """Returns a boolean DataFrame with one column per rule."""
        rules = pd.DataFrame(index=X.index)

        # R1: Cash-out between midnight and 4am
        rules["R1"] = (X["is_midnight"] == 1) & (X["txn_type_encoded"] == 4)

        # R2: Amount near regulatory threshold (structuring signal)
        rules["R2"] = X["amount_near_threshold"] == 1

        # R3: Cross-district AND high amount (> 10K BDT)
        rules["R3"] = (X["is_cross_district"] == 1) & (X["amount_bdt"] > 10000)

        # R4: New account (<90 days) doing cash_out
        rules["R4"] = (X["is_new_account_90d"] == 1) & (X["txn_type_encoded"] == 4)

        # R5: High daily velocity (> 5 txns in same day)
        rules["R5"] = X["cust_txn_count_24h"] > 5

        # R6: Amount more than 1.5 std devs above type mean (encoded in z-score)
        rules["R6"] = X["amount_zscore"] > 1.5

        # R7: Away-from-home district AND midnight
        rules["R7"] = (X["is_away_from_home"] == 1) & (X["is_midnight"] == 1)

        return rules.astype(int)

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Returns composite risk score (0-7, sum of fired rules)."""
        rules_df = self._apply_rules(X)
        return rules_df.sum(axis=1).values

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Binary prediction at configured threshold."""
        return (self.score(X) >= self.threshold).astype(int)

    def rule_coverage(self, X: pd.DataFrame) -> pd.DataFrame:
        """Returns per-rule hit rate for explainability."""
        rules_df = self._apply_rules(X)
        return pd.DataFrame({
            "rule": self.rule_names,
            "hits": rules_df.sum().values,
            "hit_rate_pct": (100 * rules_df.mean()).round(2).values,
        })


def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k_pct: float) -> float:
    """Precision@K: of top K% by score, what fraction are actual fraud?"""
    k = max(1, int(len(y_true) * k_pct / 100))
    top_k_idx = np.argsort(scores)[::-1][:k]
    return float(np.mean(y_true[top_k_idx]))


def find_optimal_threshold(y_true: np.ndarray, scores: np.ndarray) -> int:
    """Sweep integer thresholds 1-7, pick the one maximising F1."""
    best_f1, best_thresh = 0.0, 2
    for t in range(1, 8):
        preds = (scores >= t).astype(int)
        if preds.sum() == 0:
            continue
        f = f1_score(y_true, preds, zero_division=0)
        if f > best_f1:
            best_f1, best_thresh = f, t
    return best_thresh


def evaluate(y_true: np.ndarray, scores: np.ndarray, preds: np.ndarray, label: str = "") -> dict:
    """Compute and print the full evaluation report."""
    pr_auc      = average_precision_score(y_true, scores)
    p_at_5      = precision_at_k(y_true, scores, 5)
    p_at_10     = precision_at_k(y_true, scores, 10)
    f1          = f1_score(y_true, preds, zero_division=0)
    precision   = precision_score(y_true, preds, zero_division=0)
    recall      = recall_score(y_true, preds, zero_division=0)
    cm          = confusion_matrix(y_true, preds)

    tn, fp, fn, tp = cm.ravel()

    metrics = {
        "pr_auc": pr_auc, "p_at_5": p_at_5, "p_at_10": p_at_10,
        "f1": f1, "precision": precision, "recall": recall,
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
    }

    print(f"\n{'='*60}")
    print(f" RULE-BASED BASELINE EVALUATION REPORT {label}")
    print(f"{'='*60}")
    print(f"  Primary metric  — PR-AUC:        {pr_auc:.4f}")
    print(f"  Analyst metrics — Precision@5%:  {p_at_5:.4f}  ({p_at_5*100:.1f}% of top-5% are fraud)")
    print(f"                    Precision@10%: {p_at_10:.4f}  ({p_at_10*100:.1f}% of top-10% are fraud)")
    print(f"  Threshold metrics — Precision:   {precision:.4f}")
    print(f"                      Recall:      {recall:.4f}")
    print(f"                      F1:          {f1:.4f}")
    print(f"  Confusion Matrix:")
    print(f"    TP={tp:,}  FP={fp:,}")
    print(f"    FN={fn:,}  TN={tn:,}")
    print(f"{'='*60}\n")
    return metrics


def run_rules():
    logger.info("Starting Rule-Based Baseline Detector...")

    engine = get_engine()
    X_train, y_train, X_test, y_test, split_date = build_features(engine)

    detector = RuleBasedDetector()

    # 1. Find optimal threshold on TRAIN set
    train_scores   = detector.score(X_train)
    opt_threshold  = find_optimal_threshold(y_train.values, train_scores)
    logger.info(f"Optimal threshold (from train sweep): {opt_threshold}")
    detector.threshold = opt_threshold

    # 2. Evaluate on TRAIN
    train_preds = detector.predict(X_train)
    train_metrics = evaluate(y_train.values, train_scores, train_preds, label="[TRAIN]")

    # 3. Evaluate on TEST (held-out temporal window)
    test_scores  = detector.score(X_test)
    test_preds   = detector.predict(X_test)
    test_metrics = evaluate(y_test.values, test_scores, test_preds, label="[TEST]")

    # 4. Rule coverage breakdown
    coverage = detector.rule_coverage(X_test)
    print("\nRule Coverage on Test Set:")
    print(coverage.to_string(index=False))

    # 5. Score distribution
    score_dist = pd.Series(test_scores).value_counts().sort_index()
    print(f"\nRisk Score Distribution (Test):")
    for sc, cnt in score_dist.items():
        fraud_in_score = int(y_test.values[test_scores == sc].sum())
        print(f"  Score {sc}: {cnt:>5,} txns  ({fraud_in_score:>4} fraud)")

    print(f"\nNOTE: Metrics are elevated vs real-world because labels were")
    print(f"synthetically injected with deterministic patterns that align")
    print(f"with rules (temporal leakage from label generation, not from split).")
    print(f"Baseline PR-AUC of {test_metrics['pr_auc']:.3f} should be beaten by the ML model.\n")

    return test_metrics


if __name__ == "__main__":
    run_rules()
