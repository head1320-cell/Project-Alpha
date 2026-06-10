"""
Database Module — SQLAlchemy 2.x ORM
=====================================
PostgreSQL-first with SQLite fallback for development/testing.

Features:
  - Declarative ORM models (User, Portfolio, TradeLog, RiskSnapshot, ModelMonitorRun)
  - bcrypt password hashing (upgrade-on-login for legacy plaintext)
  - Session management via scoped_session
  - Automatic schema creation + default admin bootstrap
  - Retries on connection failure

Connection resolution order:
  1. `DATABASE_URL` env var (e.g. postgresql://user:pass@host:5432/db)
  2. Docker service hostname "db" (postgres inside compose)
  3. Localhost fallback
  4. SQLite file (last resort — enables unit tests without PG)
"""

import os
import time
from contextlib import contextmanager

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    func,
    text,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# Connection Resolution
# ═══════════════════════════════════════════════════════════════════════════════

def _build_database_url() -> str:
    """Resolve the database URL with sensible fallbacks."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    pg_host = os.getenv("PG_HOST", "db")
    pg_port = os.getenv("PG_PORT", "5432")
    pg_user = os.getenv("PG_USER", "ficc_user")
    pg_pass = os.getenv("PG_PASSWORD", "ficc_password")
    pg_db   = os.getenv("PG_DATABASE", "ficc_risk")

    return f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"


def _build_sqlite_fallback_url() -> str:
    """SQLite path used only when PostgreSQL unreachable (dev/test)."""
    path = os.getenv("SQLITE_PATH", "risk_system.db")
    return f"sqlite:///{path}"


DATABASE_URL = _build_database_url()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "frm123!")

# ═══════════════════════════════════════════════════════════════════════════════
# Engine + Session Setup
# ═══════════════════════════════════════════════════════════════════════════════

Base = declarative_base()
_engine = None
_SessionLocal = None
_connected_url: str = ""


def _create_engine_with_fallback(url: str, retries: int = 2):
    """Try connecting to the requested URL with retries; fall back to SQLite."""
    if url.startswith("postgresql"):
        for attempt in range(retries):
            try:
                engine = create_engine(
                    url, pool_pre_ping=True, pool_size=5, max_overflow=10,
                    pool_recycle=3600, echo=False,
                )
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
                return engine, SessionLocal, url
            except OperationalError as e:
                print(f"[DB] PostgreSQL connection attempt {attempt + 1} failed: {e}")
                time.sleep(1)

        sqlite_url = _build_sqlite_fallback_url()
        print(f"[DB] PostgreSQL unavailable — falling back to SQLite at {sqlite_url}")
        engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        return engine, SessionLocal, sqlite_url

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, SessionLocal, url


def get_engine():
    global _engine, _SessionLocal, _connected_url
    if _engine is None:
        _engine, _SessionLocal, _connected_url = _create_engine_with_fallback(DATABASE_URL)
    return _engine


def get_session_factory():
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    SessionFactory = get_session_factory()
    session: Session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_connected_url() -> str:
    if _connected_url:
        return _connected_url
    get_engine()
    return _connected_url


def is_postgres() -> bool:
    return get_connected_url().startswith("postgresql")


# ═══════════════════════════════════════════════════════════════════════════════
# ORM Models
# ═══════════════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    username = Column(String(64), primary_key=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="analyst", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    portfolios = relationship("Portfolio", back_populates="user",
                               cascade="all, delete-orphan")
    trades = relationship("TradeLog", back_populates="user",
                           cascade="all, delete-orphan")


class Portfolio(Base):
    __tablename__ = "portfolios"

    username = Column(String(64), ForeignKey("users.username", ondelete="CASCADE"),
                       primary_key=True)
    ticker = Column(String(32), nullable=False)
    investment_amount = Column(Float, nullable=False)
    beta = Column(Float, default=1.0, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())

    user = relationship("User", back_populates="portfolios")


class TradeLog(Base):
    __tablename__ = "trade_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), ForeignKey("users.username", ondelete="CASCADE"),
                       index=True, nullable=False)
    ticker = Column(String(32), nullable=False)
    qty = Column(Integer, nullable=False)
    side = Column(String(8), nullable=False)
    status = Column(String(32), nullable=False)
    executed_at = Column(DateTime(timezone=True),
                          server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="trades")

    __table_args__ = (
        Index("ix_trade_log_user_time", "username", "executed_at"),
    )


class RiskSnapshot(Base):
    """Historical VaR calculations for backtesting continuity."""
    __tablename__ = "risk_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), index=True)
    ticker = Column(String(32), index=True)
    snapshot_time = Column(DateTime(timezone=True),
                            server_default=func.now(), nullable=False)
    confidence_level = Column(Float, nullable=False)
    var_amount = Column(Float, nullable=False)
    es_amount = Column(Float)
    method = Column(String(32))
    portfolio_value = Column(Float)
    extra = Column(JSON)


class ModelMonitorRun(Base):
    """Persist AI model monitoring runs for historical comparison."""
    __tablename__ = "model_monitor_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(32), index=True, nullable=False)
    run_time = Column(DateTime(timezone=True), server_default=func.now(),
                       nullable=False)
    status = Column(String(16))
    rmse = Column(Float)
    mae = Column(Float)
    directional_accuracy = Column(Float)
    max_psi = Column(Float)
    rmse_decay_pct = Column(Float)
    n_flags = Column(Integer)
    report = Column(JSON)

    __table_args__ = (
        Index("ix_monitor_ticker_time", "ticker", "run_time"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Password Hashing
# ═══════════════════════════════════════════════════════════════════════════════

def hash_password(plain: str) -> str:
    """bcrypt hash a plaintext password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, stored: str) -> bool:
    """Verify password, supporting bcrypt hashes and legacy plaintext."""
    if not stored:
        return False
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    return plain == stored


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Initialisation
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    """Create all tables and bootstrap the default admin account. Idempotent."""
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as s:
        admin = s.query(User).filter_by(username="admin").first()
        if admin is None:
            s.add(User(
                username="admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                role="admin",
            ))
            s.flush()
            s.add(Portfolio(
                username="admin", ticker="005930.KS",
                investment_amount=100_000_000, beta=1.2,
            ))

    print(f"[DB] Initialized at: {get_connected_url()}")


def drop_all_tables():
    """Destroy all tables — test/reset only."""
    engine = get_engine()
    Base.metadata.drop_all(engine)


def reset_session():
    """Reset engine + session — used for tests that toggle DATABASE_URL."""
    global _engine, _SessionLocal, _connected_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _connected_url = ""


# ═══════════════════════════════════════════════════════════════════════════════
# User / Auth Functions
# ═══════════════════════════════════════════════════════════════════════════════

def verify_user(username: str, password: str) -> bool:
    """Verify credentials. Upgrades legacy plaintext to bcrypt on success."""
    with session_scope() as s:
        user = s.query(User).filter_by(username=username).first()
        if user is None:
            return False

        if not verify_password(password, user.password_hash):
            return False

        if not user.password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            user.password_hash = hash_password(password)

        return True


def create_user(username: str, password: str, role: str = "analyst") -> bool:
    """Create a new user. Returns False if username already exists."""
    with session_scope() as s:
        existing = s.query(User).filter_by(username=username).first()
        if existing:
            return False
        s.add(User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        ))
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Functions
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_portfolio(username: str) -> dict:
    """Fetch user's portfolio, defaulting to admin profile if missing."""
    with session_scope() as s:
        p = s.query(Portfolio).filter_by(username=username).first()
        if p:
            return {
                "ticker": p.ticker,
                "investment_amount": p.investment_amount,
                "beta": p.beta,
            }
    return {"ticker": "005930.KS", "investment_amount": 100_000_000, "beta": 1.2}


def update_user_portfolio(
    username: str, ticker: str, amount: float, beta: float = 1.2,
) -> None:
    """Upsert portfolio for a user."""
    with session_scope() as s:
        p = s.query(Portfolio).filter_by(username=username).first()
        if p:
            p.ticker = ticker
            p.investment_amount = amount
            p.beta = beta
        else:
            user = s.query(User).filter_by(username=username).first()
            if not user:
                s.add(User(
                    username=username,
                    password_hash=hash_password("temp"),
                    role="analyst",
                ))
                s.flush()
            s.add(Portfolio(
                username=username, ticker=ticker,
                investment_amount=amount, beta=beta,
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Trade Log Functions
# ═══════════════════════════════════════════════════════════════════════════════

def log_trade(username: str, ticker: str, qty: int, side: str, status: str) -> None:
    """Record a trade execution."""
    with session_scope() as s:
        user = s.query(User).filter_by(username=username).first()
        if not user:
            s.add(User(
                username=username,
                password_hash=hash_password("temp"),
                role="analyst",
            ))
            s.flush()
        s.add(TradeLog(
            username=username, ticker=ticker, qty=qty,
            side=side, status=status,
        ))


def get_trade_history(username: str, limit: int = 50) -> list[dict]:
    """Fetch recent trades for a user."""
    with session_scope() as s:
        trades = (
            s.query(TradeLog)
            .filter_by(username=username)
            .order_by(TradeLog.executed_at.desc())
            .limit(limit)
            .all()
        )
        return [{
            "ticker": t.ticker,
            "qty": t.qty,
            "side": t.side,
            "status": t.status,
            "time": t.executed_at.isoformat() if t.executed_at else None,
        } for t in trades]


# ═══════════════════════════════════════════════════════════════════════════════
# Risk Snapshots
# ═══════════════════════════════════════════════════════════════════════════════

def save_risk_snapshot(
    username: str | None,
    ticker: str,
    method: str,
    var_amount: float,
    confidence_level: float = 0.99,
    es_amount: float | None = None,
    portfolio_value: float | None = None,
    extra: dict | None = None,
) -> int:
    """Persist a risk calculation. Returns the snapshot ID."""
    with session_scope() as s:
        snap = RiskSnapshot(
            username=username, ticker=ticker, method=method,
            var_amount=var_amount, confidence_level=confidence_level,
            es_amount=es_amount, portfolio_value=portfolio_value,
            extra=extra,
        )
        s.add(snap)
        s.flush()
        return snap.id


def get_risk_snapshots(
    ticker: str | None = None, limit: int = 100,
) -> list[dict]:
    """Retrieve historical risk snapshots."""
    with session_scope() as s:
        q = s.query(RiskSnapshot)
        if ticker:
            q = q.filter_by(ticker=ticker)
        snapshots = q.order_by(RiskSnapshot.snapshot_time.desc()).limit(limit).all()
        return [{
            "id": sn.id, "username": sn.username, "ticker": sn.ticker,
            "method": sn.method, "var_amount": sn.var_amount,
            "es_amount": sn.es_amount,
            "confidence_level": sn.confidence_level,
            "portfolio_value": sn.portfolio_value,
            "snapshot_time": sn.snapshot_time.isoformat() if sn.snapshot_time else None,
            "extra": sn.extra,
        } for sn in snapshots]


# ═══════════════════════════════════════════════════════════════════════════════
# Model Monitor Runs
# ═══════════════════════════════════════════════════════════════════════════════

def save_monitor_run(
    ticker: str,
    status: str,
    rmse: float,
    mae: float,
    directional_accuracy: float,
    max_psi: float,
    rmse_decay_pct: float,
    n_flags: int,
    report: dict,
) -> int:
    """Persist an AI monitoring run for historical tracking."""
    with session_scope() as s:
        run = ModelMonitorRun(
            ticker=ticker, status=status, rmse=rmse, mae=mae,
            directional_accuracy=directional_accuracy,
            max_psi=max_psi, rmse_decay_pct=rmse_decay_pct,
            n_flags=n_flags, report=report,
        )
        s.add(run)
        s.flush()
        return run.id


def get_monitor_history(ticker: str | None = None, limit: int = 30) -> list[dict]:
    """Fetch historical monitor runs for trend display."""
    with session_scope() as s:
        q = s.query(ModelMonitorRun)
        if ticker:
            q = q.filter_by(ticker=ticker)
        runs = q.order_by(ModelMonitorRun.run_time.desc()).limit(limit).all()
        return [{
            "id": r.id, "ticker": r.ticker, "status": r.status,
            "rmse": r.rmse, "mae": r.mae,
            "directional_accuracy": r.directional_accuracy,
            "max_psi": r.max_psi, "rmse_decay_pct": r.rmse_decay_pct,
            "n_flags": r.n_flags,
            "run_time": r.run_time.isoformat() if r.run_time else None,
        } for r in runs]


if __name__ == "__main__":
    init_db()
