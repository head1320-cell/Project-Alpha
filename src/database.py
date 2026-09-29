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
import secrets
import time
from contextlib import contextmanager

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.exc import NoSuchModuleError, OperationalError
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
#: ★기본 비밀번호를 바꾸지 않는다★ — 말없이 바꾸면 배포가 조용히 잠기고,
#: `tests/test_api.py` 가 이 값을 고정하고 있다. 대신 **쓰이고 있다는 사실을
#: 관측 가능하게** 만든다(`admin_password_state()` → `GET /api/v1/auth/me`).
#: 인증(P-1)이 켜진 뒤로 이 값은 **돈 라우트의 열쇠**다 — 운영에서는 반드시 설정할 것.
DEFAULT_ADMIN_PASSWORD = "frm123!"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)



# ═══════════════════════════════════════════════════════════════════════════════
# Engine + Session Setup
# ═══════════════════════════════════════════════════════════════════════════════

Base = declarative_base()
_engine = None
_SessionLocal = None
_connected_url: str = ""


def _create_engine_with_fallback(url: str, retries: int = 2):
    """Try connecting to the requested URL with retries; fall back to SQLite.

    ★드라이버 부재도 "PostgreSQL unavailable" 이다 (R0, 실측으로 확인)★
    예전에는 `OperationalError` 만 잡았다. 그런데 `psycopg2` 가 설치돼 있지 않으면
    `create_engine()` 이 `ModuleNotFoundError` 를 던지므로 폴백이 **전혀 걸리지 않고**
    호출자에게 그대로 터졌다 — 개발/CI 컨테이너에서 가장 흔한 형태의 "DB 없음"이
    하필 폴백을 비껴가고 있었다. 드라이버 부재는 재시도해도 달라지지 않으므로
    기다리지 않고 곧장 SQLite 로 내려간다.
    """
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
            except (ModuleNotFoundError, ImportError, NoSuchModuleError) as e:
                print(f"[DB] PostgreSQL driver unavailable ({e}) — SQLite 로 폴백합니다")
                break                                    # 재시도해도 모듈은 생기지 않는다
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


#: 동기 엔진의 다른 이름. ★18곳이 이 이름을 임포트하는데 정의가 없었다★ —
#: `stage11`·`stage12`·`stage13`(실거래) 라우트와 `dag_runner`·`graph_runner` 가
#: 전부 `try/except` 안에서 임포트해 `ImportError` 가 **HTTP 500 으로 조용히**
#: 바뀌었고, 그래서 그 엔드포인트들이 통째로 죽어 있었다.
#: 비동기 엔진은 `database_async` 가 맡으므로 "sync" 를 굳이 붙인 이름이 따로
#: 필요했던 것이고, 여기가 그 자리다. `tests/test_database_public_names.py` 가
#: 이제 **임포트되는 모든 이름이 실재하는지** 전수로 지킨다.
def get_sync_engine():
    """동기 SQLAlchemy 엔진 — `get_engine()` 과 같은 객체."""
    return get_engine()


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
    security = relationship("UserSecurity", back_populates="user", uselist=False,
                            cascade="all, delete-orphan")


class UserSecurity(Base):
    """계정 보안 상태 (BS1) — ★`users` 를 고치지 않고 옆에 둔다★.

    `users` 에 열을 더하면 운영 DB 에 `ALTER` 가 필요하고, 실패하면 ORM 조회 전체가 깨진다
    (`schema_add_columns` 주석의 함정). 새 테이블은 `create_all` 이 만든다. 행이 없으면
    기본값(토큰 판 0 · 바꿀 차례 아님)이다 — 예전 계정이 그대로 로그인된다.
    """
    __tablename__ = "user_security"

    username = Column(String(64), ForeignKey("users.username", ondelete="CASCADE"),
                      primary_key=True)
    #: 토큰에 실리는 판(`tv`). 비밀번호를 바꾸거나 초기화하면 1 오른다 → 옛 토큰이 죽는다.
    token_version = Column(Integer, default=0, nullable=False)
    #: 관리자가 발급·초기화한 임시 비밀번호 — 바꾸기 전에는 보호 라우트가 열리지 않는다.
    must_change_password = Column(Boolean, default=False, nullable=False)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="security")


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


def _unusable_hash() -> str:
    """★아무도 모르는 비밀번호의 해시★ — 로그인 이외의 길로 생긴 계정이 알려진 값으로 열리지 않게.

    예전에는 `hash_password("temp")` 였다 — 코드를 읽은 누구나 그 계정으로 로그인할 수 있었다(BS1).
    이 계정을 쓰려면 관리자가 설정에서 비밀번호를 초기화한다.
    """
    return hash_password(secrets.token_urlsafe(32))


# ═══════════════════════════════════════════════════════════════════════════════
# Account Security (BS1) — 비밀번호 바꾸기 · 관리자 발급 · 옛 토큰 폐기
# ═══════════════════════════════════════════════════════════════════════════════

#: 발급·초기화 때 만드는 임시 비밀번호 길이(`token_urlsafe` 바이트 수 → 약 16자).
_TEMP_PASSWORD_BYTES = 12


def _security_row(s, username: str) -> "UserSecurity":
    row = s.get(UserSecurity, username)
    if row is None:
        row = UserSecurity(username=username, token_version=0, must_change_password=False)
        s.add(row)
        s.flush()
    return row


def account_state(username: str) -> dict | None:
    """토큰을 믿기 전에 보는 계정 상태. 계정이 없으면 `None`(삭제된 계정의 토큰은 죽는다).

    반환: `{role, token_version, must_change_password, password_changed_at}`.
    ★DB 에 닿지 못하면 예외가 그대로 올라간다★ — 호출자(`auth.get_current_principal`)가 503 으로 말한다.
    """
    with session_scope() as s:
        user = s.get(User, username)
        if user is None:
            return None
        sec = s.get(UserSecurity, username)
        return {
            "role": user.role,
            "token_version": int(sec.token_version) if sec else 0,
            "must_change_password": bool(sec.must_change_password) if sec else False,
            "password_changed_at": sec.password_changed_at.isoformat()
            if sec and sec.password_changed_at else None,
        }


def set_password(username: str, new_plain: str, *, must_change: bool) -> int | None:
    """해시를 바꾸고 토큰 판을 올린다. 새 판을 돌려준다. 계정이 없으면 `None`."""
    import datetime as _dt
    with session_scope() as s:
        user = s.get(User, username)
        if user is None:
            return None
        user.password_hash = hash_password(new_plain)
        sec = _security_row(s, username)
        sec.token_version = int(sec.token_version or 0) + 1
        sec.must_change_password = must_change
        sec.password_changed_at = _dt.datetime.now(_dt.timezone.utc)
        return int(sec.token_version)


def issue_account(username: str, role: str) -> str | None:
    """관리자 발급 — 임시 비밀번호를 만들어 **돌려주기만** 한다(저장은 해시). 이미 있으면 `None`."""
    temp = secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)
    with session_scope() as s:
        if s.get(User, username) is not None:
            return None
        s.add(User(username=username, password_hash=hash_password(temp), role=role))
        s.flush()
        s.add(UserSecurity(username=username, token_version=0, must_change_password=True))
    return temp


def reset_account_password(username: str) -> str | None:
    """관리자 초기화 — 새 임시 비밀번호 · 바꿀 차례 · 옛 토큰 폐기. 계정이 없으면 `None`."""
    temp = secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)
    return temp if set_password(username, temp, must_change=True) is not None else None


def list_accounts() -> list[dict]:
    """관리자 목록 — ★해시·비밀번호를 싣지 않는다★."""
    with session_scope() as s:
        out = []
        for u in s.query(User).order_by(User.username).all():
            sec = s.get(UserSecurity, u.username)
            out.append({
                "username": u.username,
                "role": u.role,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "must_change_password": bool(sec.must_change_password) if sec else False,
                "password_changed_at": sec.password_changed_at.isoformat()
                if sec and sec.password_changed_at else None,
            })
        return out


#: 해시 → 기본값을 받는가. bcrypt 비교는 비싸다(rounds 12) — 해시가 바뀌면 새로 잰다.
_DEFAULT_CHECK: dict[str, bool] = {}


def _admin_accepts_default() -> bool | None:
    with session_scope() as s:
        admin = s.get(User, "admin")
        stored = admin.password_hash if admin else None
    if stored is None:
        return None
    if stored not in _DEFAULT_CHECK:
        _DEFAULT_CHECK.clear()
        _DEFAULT_CHECK[stored] = verify_password(DEFAULT_ADMIN_PASSWORD, stored)
    return _DEFAULT_CHECK[stored]


def admin_password_state() -> str:
    """`configured` | `default` | `unknown` — ★admin 계정이 **지금** 기본 비밀번호를 받는가★.

    예전에는 환경변수 `ADMIN_PASSWORD` 가 있는지만 봤다. 그런데 그 값은 admin 행을 **처음 만들 때만**
    쓰인다 — 나중에 설정해도 계정은 여전히 기본값을 받는데 "configured" 라고 말했고, 설정 화면에서
    바꿔도 "default" 라고 말했다(BS1 감사). 이제 DB 의 해시를 직접 본다.
    """
    try:
        accepts = _admin_accepts_default()
    except Exception:  # noqa: BLE001 — 모름은 모름이라고 말한다
        return "unknown"
    if accepts is None:
        return "unknown"
    return "default" if accepts else "configured"


def admin_password_reason() -> str | None:
    """상태의 이유. `configured` 이면 `None`."""
    state = admin_password_state()
    if state == "configured":
        return None
    if state == "unknown":
        return "admin 계정을 찾지 못했거나 DB 에 닿지 못했어요 — 기본 비밀번호인지 모릅니다."
    if os.getenv("ADMIN_PASSWORD", "").strip():
        return ("ADMIN_PASSWORD 가 설정돼 있지만 admin 계정은 아직 기본 비밀번호를 받아요 — "
                "환경변수는 계정을 처음 만들 때만 쓰여요. 설정 화면에서 바꾸세요.")
    return "admin 계정이 기본 비밀번호를 받아요 — 설정 화면에서 바꾸세요."


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
                    password_hash=_unusable_hash(),
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
                password_hash=_unusable_hash(),
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
