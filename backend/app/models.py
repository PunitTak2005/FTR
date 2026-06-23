import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, index=True, nullable=False)
    balance = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    # Relationships
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    metrics = relationship("UserMetrics", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String, unique=True, index=True, nullable=False)
    request_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, ForeignKey("users.user_id", ondelete="CASCADE"), index=True, nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # "credit" or "debit"
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="transactions")


class UserMetrics(Base):
    __tablename__ = "user_metrics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    activity_score = Column(Float, default=0.0, nullable=False)
    consistency_score = Column(Float, default=0.0, nullable=False)
    trust_score = Column(Float, default=100.0, nullable=False)
    ranking_score = Column(Float, default=0.0, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="metrics")


class DuplicateRequest(Base):
    __tablename__ = "duplicate_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, nullable=False)
    first_processed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    response_snapshot = Column(String, nullable=True)  # JSON serialized response body or None if in-progress
    attempts = Column(Integer, default=1, nullable=False)  # Track retries for abuse analysis
