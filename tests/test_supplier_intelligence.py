"""
Tests for Supplier Intelligence module (src/supplier_intelligence/scoring.py).
"""

import numpy as np
import pandas as pd
import pytest

from src.supplier_intelligence.scoring import (
    score_suppliers,
    RISK_LEVEL_LOW,
    RISK_LEVEL_MEDIUM,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_CRITICAL,
    RISK_LEVEL_UNKNOWN,
)


@pytest.fixture
def sample_supplier_df() -> pd.DataFrame:
    """Standard multi-supplier test dataset with realistic metrics."""
    return pd.DataFrame(
        {
            "supplier_id": ["SUP-001", "SUP-002", "SUP-003", "SUP-004"],
            "on_time_delivery_rate": [0.98, 0.85, 0.72, 0.94],
            "defect_rate": [0.01, 0.03, 0.07, 0.02],
            "lead_time_std": [1.5, 3.2, 8.0, 2.0],
            "price_variability": [0.05, 0.12, 0.28, 0.08],
        }
    )


def test_score_range_and_output_structure(sample_supplier_df):
    """Verify return format, column presence, and 0-100 score bounds."""
    result = score_suppliers(sample_supplier_df)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 4
    expected_cols = {
        "supplier_id",
        "risk_score",
        "risk_level",
        "factor_scores",
        "reasons",
        "data_coverage",
    }
    assert set(result.columns) == expected_cols

    for _, row in result.iterrows():
        score = row["risk_score"]
        assert 0.0 <= score <= 100.0
        assert row["risk_level"] in {
            RISK_LEVEL_LOW,
            RISK_LEVEL_MEDIUM,
            RISK_LEVEL_HIGH,
            RISK_LEVEL_CRITICAL,
        }
        assert isinstance(row["factor_scores"], dict)
        assert isinstance(row["reasons"], list)
        assert len(row["reasons"]) > 0
        assert 0.0 <= row["data_coverage"] <= 1.0


def test_orientation_correctness(sample_supplier_df):
    """Verify worse metrics lead to strictly higher risk scores."""
    result = score_suppliers(sample_supplier_df)
    score_map = dict(zip(result["supplier_id"], result["risk_score"]))

    # SUP-001 has high on-time delivery (98%) and low defect rate (1%) -> should be lowest risk
    # SUP-003 has low on-time delivery (72%) and high defect rate (7%) -> should be highest risk
    assert score_map["SUP-001"] < score_map["SUP-002"]
    assert score_map["SUP-002"] < score_map["SUP-003"]
    assert score_map["SUP-001"] < score_map["SUP-003"]


def test_custom_weights_change_results(sample_supplier_df):
    """Verify changing weights alters composite scores according to priority."""
    # Heavy on-time delivery weight
    delivery_heavy = score_suppliers(
        sample_supplier_df,
        weights={"on_time_delivery_rate": 0.90, "defect_rate": 0.10},
    )
    # Heavy defect rate weight
    defect_heavy = score_suppliers(
        sample_supplier_df,
        weights={"on_time_delivery_rate": 0.10, "defect_rate": 0.90},
    )

    score_del = dict(zip(delivery_heavy["supplier_id"], delivery_heavy["risk_score"]))
    score_def = dict(zip(defect_heavy["supplier_id"], defect_heavy["risk_score"]))

    # Scores should differ when weights shift
    assert score_del["SUP-002"] != score_def["SUP-002"]


def test_weight_renormalization_on_missing_metrics():
    """Verify weights renormalize over available metrics and report coverage accurately."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-A", "SUP-B"],
            "on_time_delivery_rate": [0.95, np.nan],
            "defect_rate": [np.nan, 0.02],
            "lead_time_std": [2.0, 3.0],
            "price_variability": [0.10, 0.10],
        }
    )

    result = score_suppliers(df)
    row_a = result[result["supplier_id"] == "SUP-A"].iloc[0]
    row_b = result[result["supplier_id"] == "SUP-B"].iloc[0]

    # SUP-A is missing defect_rate (weight 0.25) -> coverage should be 0.75
    assert row_a["data_coverage"] == 0.75
    assert "defect_rate" not in row_a["factor_scores"]
    assert "on_time_delivery_rate" in row_a["factor_scores"]
    assert not np.isnan(row_a["risk_score"])

    # SUP-B is missing on_time_delivery_rate (weight 0.35) -> coverage should be 0.65
    assert row_b["data_coverage"] == 0.65
    assert "on_time_delivery_rate" not in row_b["factor_scores"]
    assert "defect_rate" in row_b["factor_scores"]
    assert not np.isnan(row_b["risk_score"])


def test_all_missing_supplier_results_in_unknown():
    """A supplier with no usable metrics gets risk_level 'unknown' and risk_score NaN, NEVER 'low'."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-GHOST"],
            "on_time_delivery_rate": [np.nan],
            "defect_rate": [None],
            "lead_time_std": [np.nan],
            "price_variability": [np.nan],
        }
    )

    result = score_suppliers(df)
    row = result.iloc[0]

    assert np.isnan(row["risk_score"])
    assert row["risk_level"] == RISK_LEVEL_UNKNOWN
    assert row["data_coverage"] == 0.0
    assert any(
        "Insufficient data" in r or "no usable metrics" in r for r in row["reasons"]
    )


def test_single_supplier_no_division_by_zero():
    """Verify single supplier scoring operates deterministically without zero division."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-SOLO"],
            "on_time_delivery_rate": [0.95],
            "defect_rate": [0.02],
            "lead_time_std": [2.5],
            "price_variability": [0.10],
        }
    )

    result = score_suppliers(df)
    assert len(result) == 1
    score = result.iloc[0]["risk_score"]
    assert not np.isnan(score)
    assert 0.0 <= score <= 100.0


def test_constant_columns_no_division_by_zero():
    """Verify constant column values across all suppliers do not cause division by zero."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-1", "SUP-2", "SUP-3"],
            "on_time_delivery_rate": [0.90, 0.90, 0.90],
            "defect_rate": [0.03, 0.03, 0.03],
        }
    )

    result = score_suppliers(
        df, metric_columns=["on_time_delivery_rate", "defect_rate"]
    )
    assert len(result) == 3
    for score in result["risk_score"]:
        assert not np.isnan(score)
        assert 0.0 <= score <= 100.0


def test_inf_negative_and_non_numeric_handling():
    """Verify inf, -inf, and invalid non-numeric strings are handled gracefully as NaN."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-WEIRD-1", "SUP-WEIRD-2"],
            "on_time_delivery_rate": [np.inf, "invalid_string"],
            "defect_rate": [-np.inf, 0.04],
            "lead_time_std": [2.0, 3.0],
            "price_variability": [0.05, 0.05],
        }
    )

    result = score_suppliers(df)
    assert len(result) == 2
    for _, row in result.iterrows():
        assert not np.isnan(row["risk_score"])
        assert 0.0 <= row["risk_score"] <= 100.0


def test_duplicate_suppliers_aggregation():
    """Verify duplicate supplier entries are aggregated (mean) and output has exactly 1 row per supplier."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-DUP", "SUP-DUP"],
            "on_time_delivery_rate": [0.90, 1.00],  # Mean = 0.95
            "defect_rate": [0.04, 0.02],  # Mean = 0.03
            "lead_time_std": [2.0, 4.0],  # Mean = 3.0
            "price_variability": [0.10, 0.10],  # Mean = 0.10
        }
    )

    result = score_suppliers(df)
    assert len(result) == 1
    assert result.iloc[0]["supplier_id"] == "SUP-DUP"
    factor_scores = result.iloc[0]["factor_scores"]
    assert "on_time_delivery_rate" in factor_scores


def test_input_dataframe_not_mutated():
    """Verify score_suppliers does not modify the input DataFrame in-place."""
    original_df = pd.DataFrame(
        {
            "supplier_id": ["SUP-1", "SUP-2"],
            "on_time_delivery_rate": [0.95, 0.80],
            "defect_rate": [0.01, 0.05],
        }
    )
    copy_df = original_df.copy(deep=True)

    _ = score_suppliers(original_df)
    pd.testing.assert_frame_equal(original_df, copy_df)


def test_determinism():
    """Verify score_suppliers is pure and completely deterministic across repeated executions."""
    df = pd.DataFrame(
        {
            "supplier_id": ["SUP-A", "SUP-B"],
            "on_time_delivery_rate": [0.95, 0.75],
            "defect_rate": [0.02, 0.08],
            "lead_time_std": [2.0, 5.0],
            "price_variability": [0.05, 0.20],
        }
    )

    res1 = score_suppliers(df)
    res2 = score_suppliers(df)
    pd.testing.assert_frame_equal(res1, res2)


def test_reasons_contain_actual_evidence_values(sample_supplier_df):
    """Verify generated explanations cite specific numeric values from the input data."""
    result = score_suppliers(sample_supplier_df)
    row_001 = result[result["supplier_id"] == "SUP-001"].iloc[0]
    reasons_text = " ".join(row_001["reasons"])

    assert "98.0%" in reasons_text or "98%" in reasons_text
    assert "risk score" in reasons_text.lower()


def test_invalid_inputs_raise_clear_value_errors(sample_supplier_df):
    """Verify invalid parameters raise explicit ValueError exceptions."""
    # Non-DataFrame
    with pytest.raises(ValueError, match="must be a pandas DataFrame"):
        score_suppliers([{"supplier_id": "SUP-1"}])

    # Empty DataFrame
    with pytest.raises(ValueError, match="must be a non-empty"):
        score_suppliers(pd.DataFrame())

    # Missing supplier column
    with pytest.raises(ValueError, match="Supplier column 'vendor_id' not found"):
        score_suppliers(sample_supplier_df, supplier_col="vendor_id")

    # Negative weight
    with pytest.raises(ValueError, match="strictly positive"):
        score_suppliers(sample_supplier_df, weights={"on_time_delivery_rate": -0.5})

    # Zero weight
    with pytest.raises(ValueError, match="strictly positive"):
        score_suppliers(sample_supplier_df, weights={"on_time_delivery_rate": 0.0})

    # Non-existent column in weights
    with pytest.raises(ValueError, match="not found in DataFrame"):
        score_suppliers(sample_supplier_df, weights={"non_existent_column": 1.0})

    # Non-existent column in metric_columns
    with pytest.raises(ValueError, match="not found in DataFrame"):
        score_suppliers(sample_supplier_df, metric_columns=["unknown_metric"])
