import json
import time
import uuid
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from ..models import User, Transaction, UserMetrics, DuplicateRequest
from ..ranking.engine import recalculate_user_metrics

logger = logging.getLogger(__name__)

def process_transaction(db: Session, request_id: str, user_id: str, amount: float, txn_type: str) -> dict:
    """
    Processes a transaction with strong concurrency guarantees, duplicate prevention,
    and automatic score updates.
    
    1. Duplicate Prevention:
       - Uses the duplicate_requests table.
       - If request_id exists and has a response_snapshot, returns it.
       - If it exists but is pending (response_snapshot is None), polls for completion.
       - If it doesn't exist, inserts a pending record. If unique constraint fails, polls.
    
    2. Concurrency Control:
       - Uses .with_for_update() to lock the User row.
       - Implements a retry loop for SQLite lock contention (OperationalError).
    """
    max_retries = 3
    retry_delay = 0.1

    for attempt in range(max_retries):
        try:
            # Check if idempotency key exists
            existing_req = db.query(DuplicateRequest).filter(DuplicateRequest.request_id == request_id).first()
            
            if existing_req:
                if existing_req.response_snapshot:
                    # Increment duplicate attempt count (triggers trust score penalty)
                    existing_req.attempts += 1
                    db.commit()
                    
                    # Recalculate metrics to immediately apply penalty for duplicate request
                    try:
                        recalculate_user_metrics(db, user_id)
                        db.commit()
                    except Exception as e:
                        logger.error(f"Error recalculating user metrics after duplicate attempt: {e}")
                        db.rollback()
                        
                    return json.loads(existing_req.response_snapshot)
                else:
                    # Request is in-progress by another thread. Poll for completion.
                    poll_start = time.time()
                    while time.time() - poll_start < 3.0:
                        time.sleep(0.2)
                        # Refresh session
                        db.expire_all()
                        req_check = db.query(DuplicateRequest).filter(DuplicateRequest.request_id == request_id).first()
                        if req_check and req_check.response_snapshot:
                            req_check.attempts += 1
                            db.commit()
                            
                            try:
                                recalculate_user_metrics(db, user_id)
                                db.commit()
                            except Exception:
                                db.rollback()
                                
                            return json.loads(req_check.response_snapshot)
                    
                    raise ValueError("A transaction with this request_id is already in progress. Please try again.")

            # Request is new. Add a pending entry.
            pending_req = DuplicateRequest(request_id=request_id, user_id=user_id, response_snapshot=None)
            db.add(pending_req)
            db.flush()
            break  # Successfully inserted pending request record
            
        except IntegrityError:
            # Handled duplicate request race condition: another thread inserted it between check and insert.
            db.rollback()
            # Retry next loop iteration which will hit the existing_req block
            time.sleep(0.05)
        except OperationalError as oe:
            db.rollback()
            if attempt == max_retries - 1:
                raise oe
            time.sleep(retry_delay * (2 ** attempt))

    # Now we process the actual transaction
    for attempt in range(max_retries):
        try:
            # Lock user row. If user doesn't exist, create user first, then lock.
            user = db.query(User).filter(User.user_id == user_id).with_for_update().first()
            if not user:
                # Create user
                user = User(user_id=user_id, balance=0.0)
                db.add(user)
                db.flush()
                # Lock newly created user
                user = db.query(User).filter(User.user_id == user_id).with_for_update().first()

            # Execute transaction logic
            if txn_type == "credit":
                user.balance += amount
            elif txn_type == "debit":
                if user.balance < amount:
                    # Rollback the pending request as transaction failed
                    db.rollback()
                    raise ValueError("Insufficient balance")
                user.balance -= amount
            else:
                db.rollback()
                raise ValueError("Invalid transaction type")

            txn_id = f"txn_{uuid.uuid4().hex[:8]}"
            txn = Transaction(
                transaction_id=txn_id,
                request_id=request_id,
                user_id=user_id,
                amount=amount,
                type=txn_type
            )
            db.add(txn)
            db.flush()

            # Recalculate ranking metrics
            recalculate_user_metrics(db, user_id)

            # Format and save the response snapshot for idempotency
            response_data = {
                "success": True,
                "transaction_id": txn_id,
                "new_balance": round(user.balance, 2)
            }
            
            # Fetch pending request inside the transaction to save snapshot
            req_record = db.query(DuplicateRequest).filter(DuplicateRequest.request_id == request_id).first()
            if req_record:
                req_record.response_snapshot = json.dumps(response_data)
            
            db.commit()
            return response_data

        except OperationalError as oe:
            db.rollback()
            if attempt == max_retries - 1:
                # Clean up the pending duplicate request record on final failure so user can retry
                try:
                    db.query(DuplicateRequest).filter(DuplicateRequest.request_id == request_id).delete()
                    db.commit()
                except Exception:
                    db.rollback()
                raise oe
            time.sleep(retry_delay * (2 ** attempt))
        except Exception as e:
            db.rollback()
            # Clean up pending request on general failure
            try:
                db.query(DuplicateRequest).filter(DuplicateRequest.request_id == request_id).delete()
                db.commit()
            except Exception:
                db.rollback()
            raise e
