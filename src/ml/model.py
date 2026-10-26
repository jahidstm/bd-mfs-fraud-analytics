"""
src/ml/model.py
---------------
Isolation Forest anomaly detection model for Bangladesh MFS fraud detection.

Why Isolation Forest?
  - Unsupervised-friendly: works well even when fraud labels are scarce/noisy
  - No class-weight tuning needed; contamination param handles imbalance
  - Fast inference: suitable for real-time scoring
  - Interpretable anomaly score (distance from root in random trees)

Model pipeline:
  1. Load features via build_features() (time-based split, no leakage)
  2. Scale features with StandardScaler (fitted ONLY on train)
  3. Train IsolationForest on TRAIN set (all data, semi-supervised)
  4. Convert raw anomaly scores to 0-1 probability-like fraud_score
  5. Sweep decision threshold on TRAIN to maximise F1
  6. Evaluate on held-out TEST set — report PR-AUC, Precision@K, F1
  7. Save model + scaler to models/isolation_forest.pkl

Synthetic data caveat (documented):
  Because fraud labels were injected with deterministic rules,
  the model will learn these patterns perfectly -> inflated metrics.
  In production with real data, expect PR-AUC ~0.35-0.55.

Usage:
    python -m src.ml.model
    from src.ml.model import train_model, load_model
"""

import logging
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import StandardScaler

from src.db.connection import get_engine
from src.ml.features import build_features, FEATURE_COLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ml.model")

MODEL_PATH = Path("models/isolation_forest.pkl")


# -------------------------------------------------------------------------
# Metric helpers
# -------------------------------------------------------------------------

def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k_pct: float) -> float:
    k = max(1, int(len(y_true) * k_pct / 100))
    top_k = np.argsort(scores)[::-1][:k]
    return float(np.mean(y_true[top_k]))


def scores_to_fraud_prob(raw_scores: np.ndarray) -> np.ndarray:
    """
    IsolationForest.decision_function() returns negative scores
    (more negative = more anomalous). Convert to [0, 1] where
    1.0 = highest fraud probability.
    """
    # Negate so larger = more anomalous
    negated = -raw_scores
    # Min-max normalise to [0, 1]
    s_min, s_max = negated.min(), negated.max()
    if s_max == s_min:
        return np.zeros_like(negated)
    return (negated - s_min) / (s_max - s_min)


def find_optimal_threshold(y_true: np.ndarray, fraud_probs: np.ndarray) -> float:
    """Sweep 50 thresholds between p10 and p99 of score distribution."""
    low, high = np.percentile(fraud_probs, 10), np.percentile(fraud_probs, 99)
    best_f1, best_thresh = 0.0, 0.5
    for t in np.linspace(low, high, 50):
        preds = (fraud_probs >= t).astype(int)
        if preds.sum() == 0:
            continue
        f = f1_score(y_true, preds, zero_division=0)
        if f > best_f1:
            best_f1, best_thresh = f, t
    logger.info(f"Optimal threshold: {best_thresh:.4f} (train F1={best_f1:.4f})")
    return best_thresh


def evaluate_model(y_true: np.ndarray, fraud_probs: np.ndarray,
                   threshold: float, label: str = "") -> dict:
    preds = (fraud_probs >= threshold).astype(int)

    pr_auc    = average_precision_score(y_true, fraud_probs)
    p_at_5    = precision_at_k(y_true, fraud_probs, 5)
    p_at_10   = precision_at_k(y_true, fraud_probs, 10)
    f1        = f1_score(y_true, preds, zero_division=0)
    precision = precision_score(y_true, preds, zero_division=0)
    recall    = recall_score(y_true, preds, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, preds).ravel()

    metrics = dict(pr_auc=pr_auc, p_at_5=p_at_5, p_at_10=p_at_10,
                   f1=f1, precision=precision, recall=recall,
                   tp=int(tp), fp=int(fp), fn=int(fn), tn=int(tn))

    print(f"\n{'='*62}")
    print(f"  ISOLATION FOREST EVALUATION REPORT {label}")
    print(f"{'='*62}")
    print(f"  Primary metric  — PR-AUC:          {pr_auc:.4f}")
    print(f"  Analyst metrics — Precision@5%:    {p_at_5:.4f}  ({p_at_5*100:.1f}%)")
    print(f"                    Precision@10%:   {p_at_10:.4f}  ({p_at_10*100:.1f}%)")
    print(f"  Threshold:        {threshold:.4f}")
    print(f"  Precision:        {precision:.4f}   Recall:  {recall:.4f}   F1: {f1:.4f}")
    print(f"  Confusion Matrix: TP={tp:,}  FP={fp:,}  FN={fn:,}  TN={tn:,}")
    print(f"{'='*62}")
    return metrics


# -------------------------------------------------------------------------
# Train
# -------------------------------------------------------------------------

def train_model(engine=None) -> dict:
    """Train, evaluate, save and return test metrics."""
    if engine is None:
        engine = get_engine()

    X_train, y_train, X_test, y_test, split_date = build_features(engine)

    # --- Scale features (fit ONLY on train) --------------------------------
    logger.info("Scaling features with StandardScaler (fit on train only)...")
    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_test_sc  = scaler.transform(X_test)       # no leakage: uses train stats

    # --- Train Isolation Forest --------------------------------------------
    # contamination ≈ observed fraud rate in train set
    contamination = float(y_train.mean())
    logger.info(f"Training IsolationForest (contamination={contamination:.4f}, n_estimators=200)...")
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train_sc)
    logger.info("Training complete.")

    # --- Score on train (for threshold tuning) ----------------------------
    train_raw    = model.decision_function(X_train_sc)
    train_probs  = scores_to_fraud_prob(train_raw)
    threshold    = find_optimal_threshold(y_train.values, train_probs)

    train_metrics = evaluate_model(y_train.values, train_probs, threshold, "[TRAIN]")

    # --- Score on test (final evaluation) ---------------------------------
    test_raw    = model.decision_function(X_test_sc)
    test_probs  = scores_to_fraud_prob(test_raw)
    test_metrics = evaluate_model(y_test.values, test_probs, threshold, "[TEST — held-out]")

    # --- Baseline comparison ----------------------------------------------
    BASELINE_PR_AUC = 0.398  # from Task 4.2 rule-based detector
    improvement = test_metrics["pr_auc"] - BASELINE_PR_AUC
    print(f"\n  vs Rule-Based Baseline (PR-AUC {BASELINE_PR_AUC:.3f}): "
          f"{'IMPROVEMENT' if improvement > 0 else 'DEGRADATION'} "
          f"of {abs(improvement):.4f} ({improvement/BASELINE_PR_AUC*100:+.1f}%)\n")

    # --- Synthetic data caveat -------------------------------------------
    print("  [!] SYNTHETIC DATA CAVEAT: Fraud labels were deterministically")
    print("  injected using rules that partially overlap with model features.")
    print("  Real-world PR-AUC on unseen fraud will be lower (~0.35-0.55).")
    print("  This is a portfolio demonstration, not a production model.\n")

    # --- Feature importance proxy (mean anomaly contribution) ------------
    logger.info("Computing approximate feature importances via score correlation...")
    feat_corr = []
    for i, col in enumerate(FEATURE_COLS):
        corr = float(np.corrcoef(X_train_sc[:, i], train_probs)[0, 1])
        feat_corr.append((col, abs(corr), corr))
    feat_corr.sort(key=lambda x: x[1], reverse=True)
    print("  Top features by correlation with anomaly score (train):")
    for col, abs_c, c in feat_corr[:10]:
        direction = "higher=more suspicious" if c > 0 else "lower=more suspicious"
        print(f"    {col:<28} r={c:+.4f}  ({direction})")
    print()

    # --- Save model artifact ----------------------------------------------
    MODEL_PATH.parent.mkdir(exist_ok=True)
    artifact = {
        "model": model,
        "scaler": scaler,
        "threshold": threshold,
        "feature_cols": FEATURE_COLS,
        "split_date": split_date,
        "contamination": contamination,
        "test_pr_auc": test_metrics["pr_auc"],
        "baseline_pr_auc": BASELINE_PR_AUC,
        "train_shape": X_train.shape,
        "test_shape": X_test.shape,
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(artifact, f)
    logger.info(f"Model saved to {MODEL_PATH}")

    return test_metrics


def load_model() -> dict:
    """Load saved model artifact from disk."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No model found at {MODEL_PATH}. Run train_model() first.")
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    train_model()
