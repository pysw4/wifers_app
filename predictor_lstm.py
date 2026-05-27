"""
Predictor5_0 → Similar Day Matching Predictor
===============================================
Replaces the LSTM approach with a similarity-based pattern matching
method that does NOT require real-time data.

Core idea:
  Given a target AP + datetime, find the most similar historical days
  (same day-of-week, similar hour patterns) and use their signal_score
  as the prediction with confidence intervals.

Why this works without real-time data:
  - Only needs historical parquet data (which we have)
  - No streaming/real-time input required
  - Works well for periodic WiFi usage patterns

Usage:
  # Predict for a specific AP at a specific time
  python predictor_lstm.py --ap_name "AP-Name" --target "2026-05-28 14:00:00"

  # Predict next N hours from now
  python predictor_lstm.py --ap_name "AP-Name" --hours 8

  # Evaluate prediction accuracy
  python predictor_lstm.py --ap_name "AP-Name" --evaluate

  # List available APs
  python predictor_lstm.py --list
"""

import os
import sys
import json
import argparse
import warnings
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
TARGET_COLUMN = 'signal_score'

FEATURES = [
    'signal_score', 'signal_strength', 'signal_db', 'snr',
    'cpu_utilization', 'mem_usage', 'client_count', 'health',
    'speed', 'maxspeed'
]

# Paths
DATA_PATH = 'meme_clean.parquet'
RESULTS_DIR = 'results/lstm'
PLOTS_DIR = 'results/lstm/plots'

# Similarity matching config
N_SIMILAR_DAYS = 10       # Number of similar days to use
HOUR_WINDOW = 2           # ± hours around target hour for pattern matching
MIN_HISTORY_DAYS = 7      # Minimum history required

# Signal integrity thresholds
INTEGRITY_THRESHOLDS = [
    (0.95, 'Excellent++'),
    (0.90, 'Excellent+'),
    (0.80, 'Excellent'),
    (0.70, 'Good'),
    (0.50, 'Fair'),
    (0.00, 'Poor'),
]


def score_to_integrity(score):
    """Convert signal score to integrity label."""
    for threshold, label in INTEGRITY_THRESHOLDS:
        if score >= threshold:
            return label
    return 'Poor'


def load_and_preprocess(data_path=DATA_PATH):
    """
    Load parquet data and preprocess for similarity matching.

    Returns:
        hourly_df: DataFrame with hourly data + time features
    """
    print(f"[INFO] Loading data from {data_path}...")
    df = pd.read_parquet(data_path)
    print(f"[INFO] Original shape: {df.shape}")

    # Drop NaN
    df = df.dropna()
    print(f"[INFO] After dropna: {df.shape}")

    # Convert timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Sort
    df_sorted = df.sort_values(['associated_device_name', 'timestamp'])

    # Select required columns
    required_columns = ['associated_device_name', 'timestamp'] + FEATURES
    model_df = df_sorted[required_columns].copy()

    # Forward fill per AP
    model_df = model_df.groupby('associated_device_name', group_keys=False).apply(
        lambda x: x.ffill().bfill()
    ).reset_index(drop=True)

    # Hourly resampling
    hourly_df = (
        model_df.set_index('timestamp')
        .groupby('associated_device_name')
        .resample('1H')
        .mean(numeric_only=True)
        .reset_index()
    )

    # Add time features
    hourly_df['hour'] = hourly_df['timestamp'].dt.hour
    hourly_df['day_of_week'] = hourly_df['timestamp'].dt.dayofweek  # 0=Mon, 6=Sun
    hourly_df['day_of_year'] = hourly_df['timestamp'].dt.dayofyear
    hourly_df['date'] = hourly_df['timestamp'].dt.date

    print(f"[INFO] Hourly resampled shape: {hourly_df.shape}")
    return hourly_df


def find_similar_days(ap_df, target_datetime, n_similar=N_SIMILAR_DAYS):
    """
    Find the most similar historical days for a target datetime.

    Similarity scoring:
      1. Same day-of-week (primary): +50 points
      2. Same hour pattern match: +30 points
      3. Proximity in time (recency bias): +20 points

    Args:
        ap_df: DataFrame for a single AP with hourly data
        target_datetime: datetime to predict for
        n_similar: number of similar days to return

    Returns:
        List of (date, similarity_score, daily_data) tuples
    """
    target_dow = target_datetime.dayofweek  # 0=Mon
    target_hour = target_datetime.hour
    target_date = target_datetime.date()

    # Get all unique dates for this AP
    ap_dates = sorted(ap_df['date'].unique())

    # Filter out future dates and the target date itself
    historical_dates = [d for d in ap_dates if d < target_date]

    scored_dates = []

    for date in historical_dates:
        day_data = ap_df[ap_df['date'] == date]
        if len(day_data) == 0:
            continue

        day_dow = pd.Timestamp(date).dayofweek
        score = 0

        # 1. Same day-of-week (strongest signal for WiFi patterns)
        if day_dow == target_dow:
            score += 50
        elif abs(day_dow - target_dow) == 1 or abs(day_dow - target_dow) == 6:
            score += 20  # Adjacent day
        else:
            score += 5

        # 2. Hour pattern similarity around target hour
        target_hour_data = day_data[
            (day_data['hour'] >= target_hour - HOUR_WINDOW) &
            (day_data['hour'] <= target_hour + HOUR_WINDOW)
        ]
        if len(target_hour_data) > 0:
            # Higher score if we have data for the target hours
            score += min(30, len(target_hour_data) * 10)

        # 3. Recency bias (more recent = more relevant)
        days_ago = (target_date - date).days
        if days_ago <= 7:
            score += 20
        elif days_ago <= 30:
            score += 10
        elif days_ago <= 90:
            score += 5

        scored_dates.append((date, score, day_data))

    # Sort by similarity score (descending)
    scored_dates.sort(key=lambda x: x[1], reverse=True)

    return scored_dates[:n_similar]


def predict_for_ap(ap_name, hourly_df, target_datetime):
    """
    Predict signal_score for an AP at a target datetime using
    similar day matching.

    Args:
        ap_name: name of the access point
        hourly_df: preprocessed hourly DataFrame
        target_datetime: datetime to predict for

    Returns:
        dict with prediction results
    """
    # Filter AP data
    ap_df = hourly_df[hourly_df['associated_device_name'] == ap_name].copy()

    if len(ap_df) == 0:
        return {
            'error': f'No data found for AP: {ap_name}',
            'success': False
        }

    # Find similar days
    similar_days = find_similar_days(ap_df, target_datetime)

    if len(similar_days) == 0:
        return {
            'error': f'No historical data available for prediction',
            'success': False
        }

    target_hour = target_datetime.hour

    # Collect signal scores from similar days at the target hour
    similar_scores = []
    similar_details = []

    for date, sim_score, day_data in similar_days:
        # Get data at the target hour
        hour_data = day_data[day_data['hour'] == target_hour]

        if len(hour_data) > 0:
            score = hour_data[TARGET_COLUMN].iloc[0]
            similar_scores.append(score)
            similar_details.append({
                'date': str(date),
                'similarity_score': sim_score,
                'signal_score': round(float(score), 4),
                'day_of_week': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][
                    pd.Timestamp(date).dayofweek
                ],
            })

    if len(similar_scores) == 0:
        return {
            'error': f'No matching hour data found in similar days',
            'success': False
        }

    # Calculate statistics
    scores_array = np.array(similar_scores)
    mean_score = float(np.mean(scores_array))
    median_score = float(np.median(scores_array))
    std_score = float(np.std(scores_array))
    min_score = float(np.min(scores_array))
    max_score = float(np.max(scores_array))

    # 95% confidence interval
    if len(scores_array) > 1:
        ci_lower = float(np.percentile(scores_array, 2.5))
        ci_upper = float(np.percentile(scores_array, 97.5))
    else:
        ci_lower = mean_score - 0.1
        ci_upper = mean_score + 0.1

    # Also predict the next few hours for context
    future_predictions = []
    for offset in range(5):  # Next 5 hours
        future_dt = target_datetime + timedelta(hours=offset)
        future_hour = future_dt.hour

        future_scores = []
        for date, sim_score, day_data in similar_days:
            hour_data = day_data[day_data['hour'] == future_hour]
            if len(hour_data) > 0:
                future_scores.append(hour_data[TARGET_COLUMN].iloc[0])

        if future_scores:
            future_scores_arr = np.array(future_scores)
            future_predictions.append({
                'hour_offset': offset,
                'timestamp': future_dt.strftime('%Y-%m-%d %H:00:00'),
                'predicted_signal_score': round(float(np.median(future_scores_arr)), 4),
                'confidence_lower': round(float(np.percentile(future_scores_arr, 25)), 4),
                'confidence_upper': round(float(np.percentile(future_scores_arr, 75)), 4),
                'integrity_label': score_to_integrity(float(np.median(future_scores_arr))),
            })

    result = {
        'success': True,
        'ap_name': ap_name,
        'target_datetime': target_datetime.strftime('%Y-%m-%d %H:00:00'),
        'target_hour': target_hour,
        'target_day_of_week': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][
            target_datetime.dayofweek
        ],
        'n_similar_days_used': len(similar_scores),
        'prediction': {
            'mean': round(mean_score, 4),
            'median': round(median_score, 4),
            'std': round(std_score, 4),
            'min': round(min_score, 4),
            'max': round(max_score, 4),
            'ci_95_lower': round(ci_lower, 4),
            'ci_95_upper': round(ci_upper, 4),
            'integrity_label': score_to_integrity(median_score),
        },
        'similar_days': similar_details,
        'hourly_forecast': future_predictions,
    }

    return result


def evaluate_accuracy(ap_name, hourly_df):
    """
    Evaluate prediction accuracy by simulating predictions for
    past dates and comparing with actual values.

    Uses leave-one-out: for each historical date, predict using
    all other dates as "similar days".
    """
    ap_df = hourly_df[hourly_df['associated_device_name'] == ap_name].copy()
    ap_dates = sorted(ap_df['date'].unique())

    if len(ap_dates) < MIN_HISTORY_DAYS + 1:
        print(f"[WARN] Not enough history for {ap_name} "
              f"(need {MIN_HISTORY_DAYS + 1} days, got {len(ap_dates)})")
        return None

    print(f"[INFO] Evaluating {ap_name} over {len(ap_dates)} days...")

    errors = []
    predictions_vs_actual = []

    # Test on the last 30% of dates
    test_dates = ap_dates[-max(len(ap_dates) // 3, 5):]

    for date in test_dates:
        day_data = ap_df[ap_df['date'] == date]
        if len(day_data) == 0:
            continue

        for _, row in day_data.iterrows():
            target_dt = row['timestamp']
            actual_score = row[TARGET_COLUMN]

            # Temporarily remove this date from history
            # (find_similar_days already filters out target date)
            result = predict_for_ap(ap_name, hourly_df, target_dt)

            if result['success']:
                predicted = result['prediction']['median']
                error = abs(predicted - actual_score)
                errors.append(error)
                predictions_vs_actual.append({
                    'timestamp': target_dt.strftime('%Y-%m-%d %H:00:00'),
                    'actual': round(float(actual_score), 4),
                    'predicted': round(predicted, 4),
                    'error': round(error, 4),
                })

    if len(errors) == 0:
        print("[WARN] No predictions could be evaluated")
        return None

    errors_arr = np.array(errors)
    metrics = {
        'ap_name': ap_name,
        'n_predictions': len(errors),
        'n_test_dates': len(test_dates),
        'mae': round(float(np.mean(errors_arr)), 4),
        'rmse': round(float(np.sqrt(np.mean(errors_arr ** 2))), 4),
        'median_error': round(float(np.median(errors_arr)), 4),
        'p90_error': round(float(np.percentile(errors_arr, 90)), 4),
        'max_error': round(float(np.max(errors_arr)), 4),
    }

    # Plot
    os.makedirs(PLOTS_DIR, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Error distribution
    axes[0].hist(errors, bins=30, alpha=0.7, edgecolor='black')
    axes[0].axvline(metrics['mae'], color='red', linestyle='--',
                    label=f"MAE = {metrics['mae']:.4f}")
    axes[0].set_title(f'Prediction Error Distribution - {ap_name}')
    axes[0].set_xlabel('Absolute Error')
    axes[0].set_ylabel('Frequency')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Predicted vs Actual scatter
    pv = predictions_vs_actual
    axes[1].scatter([p['actual'] for p in pv], [p['predicted'] for p in pv],
                    alpha=0.5, s=20)
    axes[1].plot([0, 1], [0, 1], 'r--', label='Perfect Prediction')
    axes[1].set_title(f'Predicted vs Actual - {ap_name}')
    axes[1].set_xlabel('Actual Signal Score')
    axes[1].set_ylabel('Predicted Signal Score')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, f'{ap_name}_evaluation.png'), dpi=150)
    plt.close()

    print(f"\n[RESULTS] Evaluation for {ap_name}:")
    print(f"  Predictions: {metrics['n_predictions']}")
    print(f"  MAE:         {metrics['mae']:.4f}")
    print(f"  RMSE:        {metrics['rmse']:.4f}")
    print(f"  Median Err:  {metrics['median_error']:.4f}")
    print(f"  P90 Error:   {metrics['p90_error']:.4f}")
    print(f"  Max Error:   {metrics['max_error']:.4f}")

    return metrics


def list_aps(hourly_df):
    """List available APs with data statistics."""
    ap_stats = hourly_df.groupby('associated_device_name').agg(
        total_hours=('timestamp', 'count'),
        first_seen=('timestamp', 'min'),
        last_seen=('timestamp', 'max'),
        unique_dates=('date', 'nunique'),
        avg_signal_score=(TARGET_COLUMN, 'mean'),
    ).reset_index()

    ap_stats = ap_stats.sort_values('total_hours', ascending=False)

    print(f"\n{'AP Name':<50s} {'Hours':>6s} {'Days':>5s} {'Avg Score':>10s} {'Date Range':<30s}")
    print("-" * 110)
    for _, row in ap_stats.iterrows():
        date_range = f"{row['first_seen'].strftime('%m/%d')} - {row['last_seen'].strftime('%m/%d')}"
        print(f"{row['associated_device_name']:<50s} "
              f"{int(row['total_hours']):>6d} "
              f"{int(row['unique_dates']):>5d} "
              f"{row['avg_signal_score']:>8.3f}   "
              f"{date_range:<30s}")
    print("-" * 110)
    print(f"Total APs: {len(ap_stats)}")

    return ap_stats


def main():
    parser = argparse.ArgumentParser(
        description='Predictor5_0 → Similar Day Matching Predictor\n'
                    'Predicts signal_score using historical pattern matching.\n'
                    'No real-time data required!'
    )
    parser.add_argument(
        '--ap_name', type=str, default=None,
        help='AP name to predict for'
    )
    parser.add_argument(
        '--target', type=str, default=None,
        help='Target datetime (e.g., "2026-05-28 14:00:00"). Default: now'
    )
    parser.add_argument(
        '--hours', type=int, default=None,
        help='Predict next N hours from target time'
    )
    parser.add_argument(
        '--evaluate', action='store_true',
        help='Evaluate prediction accuracy for an AP'
    )
    parser.add_argument(
        '--list', action='store_true',
        help='List available APs'
    )
    parser.add_argument(
        '--data', type=str, default=DATA_PATH,
        help=f'Path to parquet data file (default: {DATA_PATH})'
    )
    parser.add_argument(
        '--output', type=str, default=None,
        help='Save prediction results to JSON file'
    )

    args = parser.parse_args()

    # Load data
    hourly_df = load_and_preprocess(args.data)

    # List mode
    if args.list:
        list_aps(hourly_df)
        return

    # Evaluate mode
    if args.evaluate:
        if not args.ap_name:
            print("[ERROR] --ap_name is required for evaluation")
            sys.exit(1)
        metrics = evaluate_accuracy(args.ap_name, hourly_df)
        if metrics:
            if args.output:
                os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)
                with open(args.output, 'w') as f:
                    json.dump(metrics, f, indent=2)
                print(f"[INFO] Results saved to {args.output}")
        return

    # Predict mode
    if not args.ap_name:
        print("[ERROR] --ap_name is required for prediction")
        sys.exit(1)

    # Determine target datetime
    if args.target:
        target_dt = pd.to_datetime(args.target)
    else:
        target_dt = datetime.now()

    # Single prediction
    if not args.hours:
        result = predict_for_ap(args.ap_name, hourly_df, target_dt)

        if not result['success']:
            print(f"[ERROR] {result['error']}")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"Prediction for AP: {result['ap_name']}")
        print(f"Target: {result['target_datetime']} ({result['target_day_of_week']})")
        print(f"Based on {result['n_similar_days_used']} similar historical days")
        print(f"{'='*60}")

        pred = result['prediction']
        print(f"\n📊 Signal Score Prediction:")
        print(f"  Median:     {pred['median']:.4f}")
        print(f"  Mean:       {pred['mean']:.4f}")
        print(f"  Std Dev:    {pred['std']:.4f}")
        print(f"  Range:      [{pred['min']:.4f}, {pred['max']:.4f}]")
        print(f"  95% CI:     [{pred['ci_95_lower']:.4f}, {pred['ci_95_upper']:.4f}]")
        print(f"  Integrity:  {pred['integrity_label']}")

        print(f"\n📋 Similar Days Used:")
        print(f"{'Date':<15s} {'Day':<5s} {'Score':<10s} {'Similarity':<12s}")
        print("-" * 45)
        for sd in result['similar_days']:
            print(f"{sd['date']:<15s} {sd['day_of_week']:<5s} "
                  f"{sd['signal_score']:<10.4f} {sd['similarity_score']:<12d}")

        if result['hourly_forecast']:
            print(f"\n🔮 Hourly Forecast:")
            print(f"{'Hour':<6s} {'Timestamp':<20s} {'Score':<10s} {'Range':<18s} {'Label':<15s}")
            print("-" * 70)
            for f in result['hourly_forecast']:
                print(f"+{f['hour_offset']:<5d} {f['timestamp']:<20s} "
                      f"{f['predicted_signal_score']:<10.4f} "
                      f"[{f['confidence_lower']:.4f}, {f['confidence_upper']:.4f}]  "
                      f"{f['integrity_label']:<15s}")

        print(f"\n{'='*60}")

        # Save to file if requested
        if args.output:
            os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"[INFO] Results saved to {args.output}")

    else:
        # Predict next N hours
        print(f"\n[INFO] Predicting next {args.hours} hours for {args.ap_name}")
        print(f"[INFO] Starting from: {target_dt.strftime('%Y-%m-%d %H:00:%S')}")
        print()

        all_predictions = []
        for h in range(args.hours):
            dt = target_dt + timedelta(hours=h)
            result = predict_for_ap(args.ap_name, hourly_df, dt)

            if result['success']:
                all_predictions.append({
                    'timestamp': dt.strftime('%Y-%m-%d %H:00:00'),
                    'day_of_week': result['target_day_of_week'],
                    'predicted_median': result['prediction']['median'],
                    'predicted_mean': result['prediction']['mean'],
                    'ci_lower': result['prediction']['ci_95_lower'],
                    'ci_upper': result['prediction']['ci_95_upper'],
                    'integrity_label': result['prediction']['integrity_label'],
                    'n_similar_days': result['n_similar_days_used'],
                })

        if all_predictions:
            print(f"{'Hour':<6s} {'Timestamp':<20s} {'Day':<5s} {'Median':<10s} "
                  f"{'95% CI':<22s} {'Label':<15s} {'Days':<6s}")
            print("-" * 85)
            for p in all_predictions:
                ci = f"[{p['ci_lower']:.4f}, {p['ci_upper']:.4f}]"
                print(f"{p['timestamp'][11:13]:>2s}h   {p['timestamp']:<20s} "
                      f"{p['day_of_week']:<5s} {p['predicted_median']:<10.4f} "
                      f"{ci:<22s} {p['integrity_label']:<15s} {p['n_similar_days']:<6d}")
            print("-" * 85)

            # Plot
            os.makedirs(PLOTS_DIR, exist_ok=True)
            timestamps = [p['timestamp'] for p in all_predictions]
            medians = [p['predicted_median'] for p in all_predictions]
            ci_lowers = [p['ci_lower'] for p in all_predictions]
            ci_uppers = [p['ci_upper'] for p in all_predictions]

            fig, ax = plt.subplots(figsize=(14, 5))
            x = range(len(all_predictions))
            ax.plot(x, medians, 'b-', linewidth=2, label='Median Prediction')
            ax.fill_between(x, ci_lowers, ci_uppers, alpha=0.2, color='blue',
                            label='95% Confidence Interval')
            ax.set_title(f'Signal Score Forecast - {args.ap_name}')
            ax.set_xlabel('Hour')
            ax.set_ylabel('Signal Score')
            ax.set_xticks(x)
            ax.set_xticklabels([t[11:16] for t in timestamps], rotation=45)
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(os.path.join(PLOTS_DIR, f'{args.ap_name}_forecast.png'), dpi=150)
            plt.close()
            print(f"\n[INFO] Forecast plot saved to {PLOTS_DIR}/{args.ap_name}_forecast.png")

            # Save to file
            if args.output:
                output_data = {
                    'ap_name': args.ap_name,
                    'start_time': target_dt.strftime('%Y-%m-%d %H:00:00'),
                    'forecast_hours': args.hours,
                    'predictions': all_predictions,
                }
                os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)
                with open(args.output, 'w') as f:
                    json.dump(output_data, f, indent=2)
                print(f"[INFO] Results saved to {args.output}")


if __name__ == '__main__':
    main()
