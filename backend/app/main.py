import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .database import engine, Base, get_db
from .models import User, Transaction, UserMetrics, DuplicateRequest
from .schemas import TransactionCreate, TransactionResponse, UserSummaryResponse, LeaderboardResponse, LeaderboardEntry
from .services import transaction_service

# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Fair Transaction Ranking System API")
app.state.limiter = limiter

# Allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Rate Limit Exceeded Handler
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"success": False, "error": f"Too many requests: {exc.detail}"}
    )

# Custom Request Validation Error Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if errors:
        first_error = errors[0]
        # Clean field location formatting
        loc_str = " -> ".join(str(l) for l in first_error.get("loc", []))
        msg = first_error.get("msg", "invalid input")
        error_message = f"Validation Error in {loc_str}: {msg}"
    else:
        error_message = "Validation Error"
    return JSONResponse(
        status_code=400,
        content={"success": False, "error": error_message}
    )

# Custom Value Error Handler
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"success": False, "error": str(exc)}
    )

# Database Table Initialization on Startup
@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)

@app.get("/")
def read_root():
    return {
        "success": True,
        "message": "Fair Transaction Ranking System API is active",
        "docs": "/docs"
    }

@app.post("/transaction", response_model=TransactionResponse)
@limiter.limit("30/minute")  # Moderate rate limiting for demo abuse prevention
def create_transaction(
    request: Request,
    txn_in: TransactionCreate,
    db: Session = Depends(get_db)
):
    """
    Creates a transaction for a user, enforcing idempotency and race condition prevention.
    """
    res = transaction_service.process_transaction(
        db=db,
        request_id=txn_in.request_id,
        user_id=txn_in.user_id,
        amount=txn_in.amount,
        txn_type=txn_in.type
    )
    return res

@app.get("/summary/{userId}", response_model=UserSummaryResponse)
def get_user_summary(
    userId: str,
    db: Session = Depends(get_db)
):
    """
    Returns user financial and scoring summary.
    """
    user = db.query(User).filter(User.user_id == userId).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "User not found"}
        )

    # Compute aggregates
    credits_sum = db.query(func.sum(Transaction.amount)).filter(
        Transaction.user_id == userId,
        Transaction.type == "credit"
    ).scalar() or 0.0

    debits_sum = db.query(func.sum(Transaction.amount)).filter(
        Transaction.user_id == userId,
        Transaction.type == "debit"
    ).scalar() or 0.0

    txn_count = db.query(func.count(Transaction.id)).filter(
        Transaction.user_id == userId
    ).scalar() or 0

    ranking_score = 0.0
    if user.metrics:
        ranking_score = user.metrics.ranking_score

    return {
        "user_id": user.user_id,
        "balance": round(user.balance, 2),
        "total_transactions": txn_count,
        "total_credits": round(credits_sum, 2),
        "total_debits": round(debits_sum, 2),
        "ranking_score": round(ranking_score, 2)
    }

@app.get("/ranking", response_model=LeaderboardResponse)
def get_leaderboard(
    db: Session = Depends(get_db)
):
    """
    Retrieves the leaderboard ordered by fairness-based ranking score.
    """
    # Join metrics with user to retrieve current balances
    results = db.query(UserMetrics, User).join(
        User, UserMetrics.user_id == User.user_id
    ).order_by(
        UserMetrics.ranking_score.desc(),
        User.balance.desc()
    ).limit(50).all()

    leaderboard = []
    for index, (metrics, user) in enumerate(results, start=1):
        leaderboard.append(
            LeaderboardEntry(
                rank=index,
                user_id=user.user_id,
                balance=round(user.balance, 2),
                ranking_score=round(metrics.ranking_score, 2)
            )
        )

    return {
        "success": True,
        "leaderboard": leaderboard
    }

# Explicitly override HTTPExceptions to return JSON in the expected style
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # If detail is already a dict, return it directly
    if isinstance(exc.detail, dict):
        content = exc.detail
    else:
        content = {"success": False, "error": exc.detail}
    return JSONResponse(
        status_code=exc.status_code,
        content=content
    )
