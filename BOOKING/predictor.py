"""
Predictor for Booking System (BOOKING/predictor.py)

Provides PREDICTORFUNCTION — a DataFrame -> performance labels function
that the bookingUI.py streamlit app depends on.

Uses historical signal_score data to compute expected performance per AP/hour,
with an overload penalty for high student counts.
"""

import pandas as pd
import numpy as np

PERF_RANK = {'Very Poor': 0, 'Weak': 1, 'Poor': 1, 'Fair': 2, 'Good': 3,
             'Excellent': 4, 'Excellent+': 5, 'Excellent++': 6}

SCORE_THRESHOLDS = [
    (0.95, 'Excellent++'),
    (0.90, 'Excellent+'),
    (0.80, 'Excellent'),
    (0.70, 'Good'),
    (0.50, 'Fair'),
    (0.00, 'Poor'),
]


def _score_to_label(score: float) -> str:
    for threshold, label in SCORE_THRESHOLDS:
        if score >= threshold:
            return label
    return 'Poor'


def PREDICTORFUNCTION(input_df: pd.DataFrame) -> list[tuple[int, str]]:
    """Predict performance for each hour in the input DataFrame.

    Parameters
    ----------
    input_df : pd.DataFrame
        Must contain columns: swarm_name, hour, snapshot_ts, client_count, overloaded
        (client_count and overloaded are injected by bookingUI.py)

    Returns
    -------
    list[tuple[int, str]]
        List of (hour, performance_label) tuples.
    """
    if input_df.empty:
        return []

    results = []
    for hour in sorted(input_df['hour'].unique()):
        hour_df = input_df[input_df['hour'] == hour]
        if hour_df.empty:
            continue

        # Use historical signal_score average
        if 'signal_score' in hour_df.columns and hour_df['signal_score'].notna().any():
            avg_score = float(hour_df['signal_score'].mean())
        else:
            numeric_cols = hour_df.select_dtypes(include=[np.number]).columns
            available = [c for c in numeric_cols if c not in ('hour', 'client_count', 'overloaded')]
            if available:
                avg_score = float(hour_df[available].mean().mean())
                avg_score = max(0.0, min(1.0, avg_score / 100.0))
            else:
                avg_score = 0.5

        avg_n = float(hour_df['client_count'].mean()) if 'client_count' in hour_df.columns else 0
        overloaded = bool(hour_df['overloaded'].any()) if 'overloaded' in hour_df.columns else False

        penalty = 0.0
        if overloaded or avg_n > 50:
            penalty = 0.15
        if avg_n > 100:
            penalty = 0.30

        final_score = max(0.0, avg_score - penalty)
        label = _score_to_label(final_score)
        results.append((int(hour), label))

    return results
