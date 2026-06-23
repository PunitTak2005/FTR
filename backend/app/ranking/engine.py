import math
from sqlalchemy.orm import Session
from ..models import User, Transaction, UserMetrics, DuplicateRequest
import datetime

def calculate_balance_score(balance: float) -> float:
    """
    40% of the total score.
    Uses log-like exponential saturation: 100 * (1 - e^(-balance / 5000))
    This ensures that higher balances score higher, but prevents extreme wealth from 
    completely dominating the metrics, maintaining ranking fairness.
    """
    if balance <= 0:
        return 0.0
    return 100.0 * (1.0 - math.exp(-balance / 5000.0))


def calculate_activity_score(txn_count: int) -> float:
    """
    20% of the total score.
    Gives 5 points per valid transaction, capped at 100 (reached at 20 transactions).
    """
    return min(100.0, txn_count * 5.0)


def calculate_consistency_score(txns: list) -> float:
    """
    30% of the total score.
    Calculates consistency based on intervals between consecutive transactions.
    Uses Coefficient of Variation (CV = standard deviation / mean).
    Consistency Score = 100 / (1 + CV)
    Perfect spacing gives CV = 0 -> Score = 100.
    """
    if len(txns) < 2:
        return 0.0

    # Calculate intervals in seconds
    intervals = []
    for i in range(1, len(txns)):
        diff = (txns[i].created_at - txns[i-1].created_at).total_seconds()
        intervals.append(max(0.1, diff))  # Avoid absolute zero difference

    mean_interval = sum(intervals) / len(intervals)

    # Penalize if mean interval is less than 5 seconds (scripted behavior)
    if mean_interval < 5.0:
        return 0.0

    # Calculate standard deviation
    variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
    std_dev = math.sqrt(variance)

    cv = std_dev / mean_interval
    return 100.0 / (1.0 + cv)


def calculate_trust_score(txns: list, duplicate_requests: list) -> float:
    """
    10% of the total score.
    Starts at 100 and applies penalties for suspicious/abuse patterns:
    - Transaction Spike Penalty: -15 for each transaction > 50,000
    - Repeated Duplicate Attempt Penalty: -10 for each additional submission on a request_id
    - Rapid Successive Txns: -20 for each transaction interval < 5 seconds
    - Rate Spike (Spam): -30 if user exceeds 10 transactions in any 60-second sliding window
    
    Reward:
    - Safe Active User: +10 if user has zero penalties and has >= 5 transactions (capped at 100).
    """
    trust_score = 100.0
    penalties = 0.0

    # 1. Transaction Spike Penalty (amount > 50,000)
    spike_count = sum(1 for t in txns if t.amount > 50000.0)
    penalties += spike_count * 15.0

    # 2. Repeated Duplicate Attempt Penalty (attempts > 1)
    dup_attempts = sum(max(0, d.attempts - 1) for d in duplicate_requests)
    penalties += dup_attempts * 10.0

    # Sort transactions by creation time for sequential checking
    sorted_txns = sorted(txns, key=lambda t: t.created_at)

    # 3. Rapid Successive Txns (interval < 5s)
    rapid_intervals = 0
    intervals = []
    for i in range(1, len(sorted_txns)):
        diff = (sorted_txns[i].created_at - sorted_txns[i-1].created_at).total_seconds()
        intervals.append(diff)
        if diff < 5.0:
            rapid_intervals += 1
    penalties += rapid_intervals * 20.0

    # 4. Rate Spike (Spam: > 10 txns in any 60s sliding window)
    window_spam = False
    for i in range(len(sorted_txns)):
        t_start = sorted_txns[i].created_at
        count = 1
        for j in range(i + 1, len(sorted_txns)):
            if (sorted_txns[j].created_at - t_start).total_seconds() <= 60.0:
                count += 1
            else:
                break
        if count > 10:
            window_spam = True
            break
    
    if window_spam:
        penalties += 30.0

    trust_score = max(0.0, trust_score - penalties)

    # Reward consistent, safe behavior
    if penalties == 0.0 and len(txns) >= 5:
        trust_score = min(100.0, trust_score + 10.0)

    return trust_score


def recalculate_user_metrics(db: Session, user_id: str) -> UserMetrics:
    """
    Fetches the latest database state for a user, computes scores, and updates/saves UserMetrics.
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise ValueError("User not found")

    txns = db.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.created_at.asc()).all()
    dup_reqs = db.query(DuplicateRequest).filter(DuplicateRequest.user_id == user_id).all()

    balance_score = calculate_balance_score(user.balance)
    activity_score = calculate_activity_score(len(txns))
    consistency_score = calculate_consistency_score(txns)
    trust_score = calculate_trust_score(txns, dup_reqs)

    # Ranking score formula weights:
    # 40% balance, 30% consistency, 20% activity, 10% trust
    ranking_score = (
        0.40 * balance_score +
        0.30 * consistency_score +
        0.20 * activity_score +
        0.10 * trust_score
    )

    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
    if not metrics:
        metrics = UserMetrics(user_id=user_id)
        db.add(metrics)

    metrics.activity_score = round(activity_score, 2)
    metrics.consistency_score = round(consistency_score, 2)
    metrics.trust_score = round(trust_score, 2)
    metrics.ranking_score = round(ranking_score, 2)
    metrics.updated_at = datetime.datetime.utcnow()

    db.flush()  # Sync changes to session
    return metrics
