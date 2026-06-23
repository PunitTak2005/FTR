from pydantic import BaseModel, Field, validator
from typing import List, Optional

class TransactionCreate(BaseModel):
    request_id: str = Field(..., min_length=1, description="Unique idempotency key for the transaction")
    user_id: str = Field(..., min_length=1, description="ID of the user initiating the transaction")
    amount: float = Field(..., description="Amount of the transaction (must be > 0 and <= 100000)")
    type: str = Field(..., description="Type of transaction: credit or debit")

    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        if v > 100000:
            raise ValueError("Amount cannot exceed 100000")
        return v

    @validator("type")
    def validate_type(cls, v):
        if v not in ("credit", "debit"):
            raise ValueError("Type must be either: credit or debit")
        return v


class TransactionResponse(BaseModel):
    success: bool
    transaction_id: str
    new_balance: float


class UserSummaryResponse(BaseModel):
    user_id: str
    balance: float
    total_transactions: int
    total_credits: float
    total_debits: float
    ranking_score: float


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    balance: float
    ranking_score: float


class LeaderboardResponse(BaseModel):
    success: bool
    leaderboard: List[LeaderboardEntry]
