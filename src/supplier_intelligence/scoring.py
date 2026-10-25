"""
Supplier Risk Scoring Module.

Pure, deterministic risk scoring and factor attribution for supply chain vendors.
Evaluates suppliers across multi-dimensional performance metrics (delivery, quality,
lead time variability, price stability) and generates normalized 0-100 risk scores
with evidence-based explanations.
"""

from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

# Risk Level Constants
RISK_LEVEL_LOW = "low"
RISK_LEVEL_MEDIUM = "medium"
RISK_LEVEL_HIGH = "high"
RISK_LEVEL_CRITICAL = "critical"
RISK_LEVEL_UNKNOWN = "unknown"

# Risk Threshold Constants
THRESHOLD_LOW = 30.0
THRESHOLD_MEDIUM = 60.0
THRESHOLD_HIGH = 80.0

# Metric Orientation Constants
ORIENTATION_HIGHER_IS_BETTER = "higher_is_better"
ORIENTATION_HIGHER_IS_WORSE = "higher_is_worse"

# Default Metric Orientations
DEFAULT_ORIENTATIONS: Dict[str, str] = {
    # Delivery metrics
    "on_time_delivery_rate": ORIENTATION_HIGHER_IS_BETTER,
    "fulfillment_rate": ORIENTATION_HIGHER_IS_BETTER,
    "quality_score": ORIENTATION_HIGHER_IS_BETTER,
    "late_rate": ORIENTATION_HIGHER_IS_WORSE,
    "delay_days": ORIENTATION_HIGHER_IS_WORSE,
    "avg_delay_days": ORIENTATION_HIGHER_IS_WORSE,
    # Quality metrics
    "defect_rate": ORIENTATION_HIGHER_IS_WORSE,
    "rejection_rate": ORIENTATION_HIGHER_IS_WORSE,
    "return_rate": ORIENTATION_HIGHER_IS_WORSE,
    # Lead time & Inventory
    "lead_time_days": ORIENTATION_HIGHER_IS_WORSE,
    "lead_time_std": ORIENTATION_HIGHER_IS_WORSE,
    "lead_time_cv": ORIENTATION_HIGHER_IS_WORSE,
    "stockout_rate": ORIENTATION_HIGHER_IS_WORSE,
    # Financial metrics
    "price_variability": ORIENTATION_HIGHER_IS_WORSE,
    "cost_variance": ORIENTATION_HIGHER_IS_WORSE,
    "margin_risk": ORIENTATION_HIGHER_IS_WORSE,
}

# Standard Reference Bounds (used for domain-informed normalization)
TARGET_BOUNDS: Dict[str, tuple[float, float]] = {
    "on_time_delivery_rate": (0.70, 1.0),
    "fulfillment_rate": (0.80, 1.0),
    "defect_rate": (0.00, 0.08),
    "rejection_rate": (0.00, 0.08),
    "return_rate": (0.00, 0.08),
    "late_rate": (0.00, 0.25),
    "delay_days": (0.0, 14.0),
    "avg_delay_days": (0.0, 14.0),
    "lead_time_days": (5.0, 60.0),
    "lead_time_std": (0.0, 10.0),
    "lead_time_cv": (0.0, 0.50),
    "price_variability": (0.00, 0.30),
    "cost_variance": (0.00, 0.30),
}

# Default Weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "on_time_delivery_rate": 0.35,
    "defect_rate": 0.25,
    "lead_time_std": 0.20,
    "price_variability": 0.20,
}


def _classify_risk_level(score: float) -> str:
    """Classify 0-100 risk score into standard risk tier."""
    if np.isnan(score):
        return RISK_LEVEL_UNKNOWN
    if score < THRESHOLD_LOW:
        return RISK_LEVEL_LOW
    if score < THRESHOLD_MEDIUM:
        return RISK_LEVEL_MEDIUM
    if score < THRESHOLD_HIGH:
        return RISK_LEVEL_HIGH
    return RISK_LEVEL_CRITICAL


def _normalize_metric_value(
    val: float,
    col: str,
    col_min: float,
    col_max: float,
    orientation: str,
) -> float:
    """
    Normalize metric value to a 0-100 risk score deterministically.
    Higher returned score = higher risk.
    """
    if np.isnan(val) or np.isinf(val):
        return np.nan

    # Case 1: Check known domain target bounds first if available
    if col in TARGET_BOUNDS:
        t_min, t_max = TARGET_BOUNDS[col]
        if t_max > t_min:
            scaled = (val - t_min) / (t_max - t_min)
            scaled = float(np.clip(scaled, 0.0, 1.0))
            if orientation == ORIENTATION_HIGHER_IS_BETTER:
                return round((1.0 - scaled) * 100.0, 2)
            else:
                return round(scaled * 100.0, 2)

    # Case 2: Dynamic min-max scaling across suppliers
    if np.isnan(col_min) or np.isnan(col_max) or col_max == col_min:
        # Single supplier or constant column with no reference target
        # Neutral baseline risk is 50.0
        return 50.0

    scaled = (val - col_min) / (col_max - col_min)
    scaled = float(np.clip(scaled, 0.0, 1.0))
    if orientation == ORIENTATION_HIGHER_IS_BETTER:
        return round((1.0 - scaled) * 100.0, 2)
    else:
        return round(scaled * 100.0, 2)


def score_suppliers(
    supplier_metrics_df: pd.DataFrame,
    supplier_col: str = "supplier_id",
    metric_columns: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    Score suppliers quantitatively based on performance metrics.

    Args:
        supplier_metrics_df: DataFrame containing supplier metrics.
        supplier_col: Name of the supplier identifier column (default: "supplier_id").
        metric_columns: Optional explicit list of metric columns to include.
        weights: Optional dictionary mapping metric name to positive float weight.

    Returns:
        DataFrame with one row per supplier containing:
        - supplier_id (or specified supplier_col): Supplier identifier
        - risk_score: Float 0-100 (higher = riskier), or NaN if unknown
        - risk_level: "low" | "medium" | "high" | "critical" | "unknown"
        - factor_scores: Dict[str, float] of metric -> 0-100 risk contribution
        - reasons: List[str] of human-readable, evidence-based explanations
        - data_coverage: Float 0.0-1.0 representing proportion of available weighted metrics

    Raises:
        ValueError: If input is not a DataFrame, empty, missing supplier_col, has invalid weights,
                    or specified metric columns are not found in the DataFrame.
    """
    # 1. Input Validation
    if not isinstance(supplier_metrics_df, pd.DataFrame):
        raise ValueError("supplier_metrics_df must be a pandas DataFrame")

    if supplier_metrics_df.empty:
        raise ValueError("supplier_metrics_df must be a non-empty pandas DataFrame")

    if supplier_col not in supplier_metrics_df.columns:
        raise ValueError(f"Supplier column '{supplier_col}' not found in DataFrame")

    # Never mutate input DataFrame
    df = supplier_metrics_df.copy()

    # 2. Determine Metric Columns & Weights
    if weights is not None:
        if not isinstance(weights, dict) or len(weights) == 0:
            raise ValueError("weights must be a non-empty dictionary")
        for k, v in weights.items():
            if not isinstance(v, (int, float)) or np.isnan(v) or v <= 0:
                raise ValueError(
                    f"Weight for '{k}' must be a strictly positive number, got {v}"
                )
            if k not in df.columns:
                raise ValueError(
                    f"Metric column '{k}' specified in weights not found in DataFrame"
                )
        active_weights = {k: float(v) for k, v in weights.items()}
        cols_to_score = list(active_weights.keys())
    elif metric_columns is not None:
        if not isinstance(metric_columns, list) or len(metric_columns) == 0:
            raise ValueError("metric_columns must be a non-empty list of column names")
        for col in metric_columns:
            if col not in df.columns:
                raise ValueError(f"Metric column '{col}' not found in DataFrame")
        cols_to_score = list(metric_columns)
        # Allocate weights: use DEFAULT_WEIGHTS where present, otherwise equal weighting
        active_weights = {}
        for col in cols_to_score:
            active_weights[col] = DEFAULT_WEIGHTS.get(col, 1.0)
    else:
        # Auto-detect: prioritize known default metric columns present in df
        matching_defaults = [col for col in DEFAULT_WEIGHTS.keys() if col in df.columns]
        if matching_defaults:
            cols_to_score = matching_defaults
            active_weights = {col: DEFAULT_WEIGHTS[col] for col in cols_to_score}
        else:
            # Fall back to all numeric columns except supplier_col
            numeric_cols = [
                c
                for c in df.columns
                if c != supplier_col and pd.api.types.is_numeric_dtype(df[c])
            ]
            if not numeric_cols:
                raise ValueError(
                    "No numeric metric columns found in DataFrame to score"
                )
            cols_to_score = numeric_cols
            active_weights = {col: 1.0 for col in cols_to_score}

    # Normalize active weights sum to 1.0
    total_configured_weight = sum(active_weights.values())

    # 3. Handle Duplicate Suppliers (aggregation rule: mean of numeric columns)
    if df[supplier_col].duplicated().any():
        agg_rules: Dict[str, Any] = {}
        for col in df.columns:
            if col == supplier_col:
                continue
            if col in cols_to_score:
                agg_rules[col] = "mean"
            else:
                agg_rules[col] = "first"
        df = df.groupby(supplier_col, as_index=False).agg(agg_rules)

    # 4. Clean Numeric Columns and Compute Column Extrema
    cleaned_data: Dict[str, pd.Series] = {}
    col_extrema: Dict[str, tuple[float, float]] = {}

    for col in cols_to_score:
        # Convert non-numeric/invalid to NaN
        s = pd.to_numeric(df[col], errors="coerce")
        # Replace inf/-inf with NaN
        s = s.replace([np.inf, -np.inf], np.nan)
        cleaned_data[col] = s
        valid_s = s.dropna()
        if not valid_s.empty:
            col_extrema[col] = (float(valid_s.min()), float(valid_s.max()))
        else:
            col_extrema[col] = (np.nan, np.nan)

    # 5. Row-by-Row Score Computation
    results = []

    for idx, row in df.iterrows():
        supplier_id = row[supplier_col]
        factor_scores: Dict[str, float] = {}
        reasons: List[str] = []
        available_weights = 0.0
        weighted_score_sum = 0.0

        for col in cols_to_score:
            val = cleaned_data[col].iloc[idx]
            weight = active_weights[col]
            orientation = DEFAULT_ORIENTATIONS.get(col, ORIENTATION_HIGHER_IS_WORSE)

            if pd.isna(val):
                continue

            c_min, c_max = col_extrema[col]
            factor_score = _normalize_metric_value(val, col, c_min, c_max, orientation)

            if np.isnan(factor_score):
                continue

            factor_scores[col] = factor_score
            available_weights += weight
            weighted_score_sum += factor_score * weight

            # Generate evidence-based reason
            col_display = col.replace("_", " ").title()
            if col == "on_time_delivery_rate":
                target_str = "target: 95%"
                reasons.append(
                    f"{col_display} is {val:.1%} ({target_str}, risk score: {factor_score:.1f}/100)"
                )
            elif "rate" in col:
                reasons.append(
                    f"{col_display} is {val:.1%} (risk score: {factor_score:.1f}/100)"
                )
            elif "days" in col:
                reasons.append(
                    f"{col_display} is {val:.1f} days (risk score: {factor_score:.1f}/100)"
                )
            else:
                reasons.append(
                    f"{col_display} is {val:.2f} (risk score: {factor_score:.1f}/100)"
                )

        # Compute Data Coverage (share of configured weights with usable data)
        data_coverage = (
            round(available_weights / total_configured_weight, 4)
            if total_configured_weight > 0
            else 0.0
        )

        if available_weights == 0.0 or len(factor_scores) == 0:
            final_risk_score = float("nan")
            risk_level = RISK_LEVEL_UNKNOWN
            reasons.append(
                "Insufficient data: no usable metrics available for risk assessment"
            )
        else:
            # Renormalize weights across available metrics only
            final_risk_score = round(weighted_score_sum / available_weights, 2)
            risk_level = _classify_risk_level(final_risk_score)

            if data_coverage < 0.5:
                reasons.insert(
                    0,
                    f"Low data coverage ({data_coverage:.0%}): risk assessment based on partial metrics",
                )

        results.append(
            {
                supplier_col: supplier_id,
                "risk_score": final_risk_score,
                "risk_level": risk_level,
                "factor_scores": factor_scores,
                "reasons": reasons,
                "data_coverage": data_coverage,
            }
        )

    return pd.DataFrame(results)
