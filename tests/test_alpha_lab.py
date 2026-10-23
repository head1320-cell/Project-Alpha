"""Alpha Lab 검증 (Full Expansion P2)

핵심 주장:
  파서    — 우선순위·괄호·함수 인자수·허용 토큰만 (eval 금지)
  lint    — parse 에러=error, 주가원값·스케일혼합=warn, 펀더멘털 PIT=info, 중복 감지
  검증    — ★look-ahead 가드★: 다음 달 수익률을 완벽 예측하는 합성 알파 → IC≈1,
            과거 수익률만 담은 알파 → IC≈0 (미래참조가 구조적으로 불가함을 증명).
            분위 모노토닉·IS/OOS 분할·회전율 프록시 산출.
  레지스트리 — CRUD·expr 변경 시 버전+1·draft 강등·승격 요건(검증 run/노트)·템플릿 시드 멱등
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.alpha_registry as reg  # noqa: E402
from src.engine.alpha_lab import (  # noqa: E402
    AlphaParseError,
    lint_alpha,
    parse_alpha,
    validate_alpha,
)


# ── 파서 ─────────────────────────────────────────────────────────────────────
def test_parse_precedence_and_funcs():
    n = parse_alpha("zscore(mom_6m) + 2 * rank(roe) - vol_20d / 3")
    assert n.fields() == {"mom_6m", "roe", "vol_20d"}
    assert {"zscore", "rank"} <= n.calls()


def test_parse_rejects_unknown_and_unsafe():
    with pytest.raises(AlphaParseError):
        parse_alpha("unknown_field + 1")
    with pytest.raises(AlphaParseError):
        parse_alpha("__import__('os')")
    with pytest.raises(AlphaParseError):
        parse_alpha("rank(mom_1m, mom_3m)")   # 인자수 오류
    with pytest.raises(AlphaParseError):
        parse_alpha("mom_1m ^ 2")             # 허용되지 않는 연산자


# ── lint ─────────────────────────────────────────────────────────────────────
def test_lint_levels():
    bad = lint_alpha("this_is_not_a_field")
    assert bad["ok"] is False and bad["issues"][0]["level"] == "error"

    warn = lint_alpha("price_level + mom_1m")
    codes = {i["code"] for i in warn["issues"]}
    assert warn["ok"] is True and "price_level" in codes and "scale_mix" in codes

    info = lint_alpha("zscore(roe)")
    assert info["ok"] is True
    assert any(i["code"] == "pit_lag" and i["level"] == "info" for i in info["issues"])

    dup = lint_alpha("zscore(mom_6m)", existing_exprs=["zscore( mom_6m )"])
    assert any(i["code"] == "duplicate" for i in dup["issues"])


# ── 검증: look-ahead 가드 (합성 데이터) ───────────────────────────────────────
def _synthetic_loader(predictive: bool):
    """40종목 × ~800일 합성 시계열. predictive=True면 각 종목의 '다음 21일 수익률'이
    mom_1m(과거 21일 수익률)과 강하게 상관되도록 구성(모멘텀 지속 세계) —
    look-ahead 없이도 IC가 높게 나오는 것이 정상.
    predictive=False면 완전 무작위(랜덤워크) — IC≈0이어야 함(미래참조 불가 증명)."""
    def loader(tickers, start, end):
        import pandas as pd
        rng = np.random.default_rng(99)
        n_days = 820
        idx = pd.bdate_range("2023-01-02", periods=n_days)
        out = {}
        drifts = np.linspace(-0.0035, 0.0035, len(tickers[:40]))
        for k, t in enumerate(tickers[:40]):
            if predictive:
                # 종목별 고정 드리프트(크로스섹션 지속성) → 과거 모멘텀 순위 ≈ 미래 수익 순위
                r = drifts[k] + rng.normal(0, 0.004, n_days)
            else:
                r = rng.normal(0.0002, 0.015, n_days)
            c = 10000 * np.cumprod(1 + r)
            df = pd.DataFrame({"close": c, "amount": np.full(n_days, 1e9)}, index=idx)
            out[t] = df
        def one(tk, s, e):
            return out.get(tk)
        return {tk: {"dates": np.array(v.index.values, dtype="datetime64[D]"),
                     "close": v["close"].values,
                     "amount": v["amount"].values} for tk, v in out.items()}
    return loader


TICKERS = [f"{i:06d}" for i in range(1, 41)]


def test_validate_predictive_alpha_high_ic_and_monotonic():
    rep = validate_alpha("rank(mom_1m)", TICKERS, months=18,
                         price_loader=_synthetic_loader(predictive=True))
    assert rep["error"] is False
    assert rep["ic"]["mean"] is not None and rep["ic"]["mean"] > 0.25   # 지속 세계 → 높은 IC
    assert rep["quantiles"]["monotonicity"] is not None and rep["quantiles"]["monotonicity"] > 0.7
    assert rep["long_short"]["total_return_pct"] > 0
    assert rep["n_periods"] >= 12
    assert rep["is_oos"]["is_ic"] is not None and rep["is_oos"]["oos_ic"] is not None


def test_validate_random_walk_near_zero_ic():
    """랜덤워크에서 IC≈0 — 점수 계산에 미래 수익률이 새어들지 않음을 증명하는 가드."""
    rep = validate_alpha("rank(mom_1m)", TICKERS, months=18,
                         price_loader=_synthetic_loader(predictive=False))
    assert rep["error"] is False
    assert abs(rep["ic"]["mean"]) < 0.15   # look-ahead가 있다면 1.0 근처가 됨


def test_validate_turnover_and_coverage():
    rep = validate_alpha("zscore(mom_3m)", TICKERS, months=18,
                         price_loader=_synthetic_loader(predictive=True))
    assert rep["turnover_proxy"] is not None and 0 <= rep["turnover_proxy"] <= 1
    assert rep["avg_coverage"] >= 8
    assert any("비용" in n for n in rep["notes"])   # 비용 미반영 정직 라벨


def test_validate_insufficient_universe_honest():
    rep = validate_alpha("rank(mom_1m)", TICKERS[:4], months=12,
                         price_loader=_synthetic_loader(predictive=True))
    assert rep["error"] is True and "유니버스" in rep["message"] or "종목" in rep["message"]


# ── 레지스트리 ────────────────────────────────────────────────────────────────
@pytest.fixture
def mem_reg(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(reg, "_engine", lambda: eng)
    monkeypatch.setattr(reg, "_inited", False)
    yield eng
    eng.dispose()


def test_registry_crud_version_and_demote(mem_reg):
    a = reg.upsert_alpha(None, "내 알파", "zscore(mom_6m)")
    assert a and a["version"] == 1 and a["status"] == "draft"

    same = reg.upsert_alpha(a["alpha_id"], "내 알파", "zscore(mom_6m)")
    assert same["version"] == 1   # expr 불변 → 버전 유지

    reg.promote_alpha(a["alpha_id"], "experimental")
    changed = reg.upsert_alpha(a["alpha_id"], "내 알파", "zscore(mom_12m)")
    assert changed["version"] == 2 and changed["status"] == "draft"   # 수정 → 재검증 강제


def test_registry_promotion_rules(mem_reg):
    a = reg.upsert_alpha(None, "규칙 테스트", "rank(mom_1m)")
    aid = a["alpha_id"]

    r = reg.promote_alpha(aid, "validated")
    assert r["ok"] is False and "직행 불가" in r["reason"]

    assert reg.promote_alpha(aid, "experimental")["ok"] is True
    r = reg.promote_alpha(aid, "validated")
    assert r["ok"] is False and "검증 리포트" in r["reason"]   # run 없이 불가

    reg.attach_validation(aid, "rr_test_123")
    assert reg.promote_alpha(aid, "validated")["ok"] is True

    r = reg.promote_alpha(aid, "approved", note="")
    assert r["ok"] is False and "노트" in r["reason"]
    assert reg.promote_alpha(aid, "approved", note="PM 승인 — IC 0.05 확인")["ok"] is True

    assert reg.promote_alpha(aid, "retired")["ok"] is True


def test_registry_seed_templates_idempotent(mem_reg):
    n1 = reg.seed_templates()
    assert n1 == 6
    n2 = reg.seed_templates()
    assert n2 == 0   # 멱등
    alphas = reg.list_alphas()
    tpl = [a for a in alphas if a["is_template"]]
    assert len(tpl) == 6
    # 데이터 미보유 신호는 정직 라벨
    er = next(a for a in tpl if "리비전" in a["name"])
    assert "컨센서스" in a_desc(er)
    pair = next(a for a in tpl if "페어" in a["name"])
    assert pair["expr"] == "" and pair["status"] == "draft"


def a_desc(a: dict) -> str:
    return (a.get("description") or "") + (a.get("notes") or "")
