import os
import time
import datetime
import pytest
import concurrent.futures
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import User, Transaction, UserMetrics, DuplicateRequest
from backend.app.services.transaction_service import process_transaction
from backend.app.ranking.engine import recalculate_user_metrics

DB_FILE = "test_suite.db"

@pytest.fixture(name="db_session")
def fixture_db_session():
    # Clean up existing database files
    for suffix in ["", "-wal", "-shm"]:
        path = f"{DB_FILE}{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    engine = create_engine(
        f"sqlite:///{DB_FILE}",
        connect_args={"check_same_thread": False}
    )

    # Enable WAL mode and foreign keys for SQLite
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        for suffix in ["", "-wal", "-shm"]:
            path = f"{DB_FILE}{suffix}"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_validation_errors(client):
    # Test amount <= 0
    resp = client.post("/transaction", json={
        "request_id": "req-1",
        "user_id": "user1",
        "amount": 0,
        "type": "credit"
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "Amount must be greater than 0" in resp.json()["error"]

    # Test amount > 100,000
    resp = client.post("/transaction", json={
        "request_id": "req-2",
        "user_id": "user1",
        "amount": 100001,
        "type": "credit"
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "Amount cannot exceed 100000" in resp.json()["error"]

    # Test invalid type
    resp = client.post("/transaction", json={
        "request_id": "req-3",
        "user_id": "user1",
        "amount": 250,
        "type": "transfer"
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "Type must be either: credit or debit" in resp.json()["error"]

    # Test missing fields
    resp = client.post("/transaction", json={
        "user_id": "user1",
        "amount": 250,
        "type": "credit"
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "Validation Error" in resp.json()["error"]


def test_transaction_flows(client, db_session):
    # Credit transaction
    resp = client.post("/transaction", json={
        "request_id": "req-credit-1",
        "user_id": "user-a",
        "amount": 500,
        "type": "credit"
    })
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["new_balance"] == 500.0
    assert res_data["transaction_id"].startswith("txn_")

    # Debit transaction
    resp = client.post("/transaction", json={
        "request_id": "req-debit-1",
        "user_id": "user-a",
        "amount": 200,
        "type": "debit"
    })
    assert resp.status_code == 200
    assert resp.json()["new_balance"] == 300.0

    # Overdraft attempt
    resp = client.post("/transaction", json={
        "request_id": "req-debit-2",
        "user_id": "user-a",
        "amount": 400,
        "type": "debit"
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "Insufficient balance" in resp.json()["error"]


def test_duplicate_prevention_and_penalties(client, db_session):
    # Process original transaction
    payload = {
        "request_id": "req-uniq-1",
        "user_id": "user-b",
        "amount": 100,
        "type": "credit"
    }
    resp1 = client.post("/transaction", json=payload)
    assert resp1.status_code == 200
    val1 = resp1.json()

    # Re-submit duplicate
    resp2 = client.post("/transaction", json=payload)
    assert resp2.status_code == 200
    val2 = resp2.json()

    # Verify duplicate prevention matches response and prevents double-processing
    assert val1["transaction_id"] == val2["transaction_id"]
    assert val1["new_balance"] == val2["new_balance"]

    user = db_session.query(User).filter(User.user_id == "user-b").first()
    assert user.balance == 100.0  # Balance was NOT processed twice

    # Re-submit duplicate again
    client.post("/transaction", json=payload)

    # Verify trust score penalty for duplicate attempts
    metrics = db_session.query(UserMetrics).filter(UserMetrics.user_id == "user-b").first()
    assert metrics is not None
    # Starting trust: 100
    # Duplicate attempts: 2 repeats. Penalty: 2 * 10 = 20.
    # Expected trust: 80.0
    assert metrics.trust_score == 80.0


def test_ranking_calculations(client, db_session):
    # Setup a user with regular transactions spaced out to check metrics
    user_id = "user-ranking"
    
    # 1st transaction
    client.post("/transaction", json={
        "request_id": "rank-1",
        "user_id": user_id,
        "amount": 1000,
        "type": "credit"
    })
    
    # Check initial summary
    resp = client.get(f"/summary/{user_id}")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["balance"] == 1000.0
    assert summary["total_transactions"] == 1
    # Consistency is 0 when transaction count < 2
    
    # We manually modify transactions timestamps in DB to simulate safe spaced consistency
    txns = db_session.query(Transaction).filter(Transaction.user_id == user_id).all()
    # First txn at baseline
    t0 = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
    txns[0].created_at = t0
    db_session.commit()

    # 2nd transaction (simulated 10 minutes later)
    client.post("/transaction", json={
        "request_id": "rank-2",
        "user_id": user_id,
        "amount": 1000,
        "type": "credit"
    })
    txns2 = db_session.query(Transaction).filter(Transaction.user_id == user_id).order_by(Transaction.created_at.asc()).all()
    txns2[1].created_at = t0 + datetime.timedelta(minutes=10)
    db_session.commit()

    # Recalculate
    recalculate_user_metrics(db_session, user_id)
    db_session.commit()

    metrics = db_session.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
    assert metrics.activity_score == 10.0  # 2 txns * 5 = 10
    assert metrics.consistency_score > 0.0  # spacing is set up


def test_concurrency_race_condition(db_session):
    # Test direct concurrency on transaction_service.process_transaction
    # We spin up 10 threads to concurrently execute $100 credits for the same user.
    user_id = "user-concurrent"
    num_threads = 10
    amount = 100.0
    
    # Pre-populate user
    user = User(user_id=user_id, balance=0.0)
    db_session.add(user)
    db_session.commit()

    def worker(i):
        # We need a new session per thread to simulate actual server threads
        engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            req_id = f"req-concurrent-{i}"
            res = process_transaction(db, req_id, user_id, amount, "credit")
            return res
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Refresh primary session
    db_session.expire_all()
    user = db_session.query(User).filter(User.user_id == user_id).first()
    
    # Total deposits must equal num_threads * amount (1000.0)
    # Row-level lock ensures no updates were lost!
    assert user.balance == 1000.0
    
    txns_count = db_session.query(Transaction).filter(Transaction.user_id == user_id).count()
    assert txns_count == 10
