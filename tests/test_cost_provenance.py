"""AZ · ★문이 정한 수수료를 문이 밝힌다★ — 비용 요율의 **런타임** 출처
==============================================================================
대상: `src/domain/cost_provenance.py` · 증거 파일
`docs/specs/cost-rate-evidence.json` · 표면 `kis_backtest_engine._cost_model_block`

## 무엇이 없었나 (실측 2026-09-22)

같은 전략·같은 데이터인데 왕복 비용이 갈린다:

    15bp 진영(screener·메인엔진·graph·legacy)      round_trip = 40.0bp
    1.5bp 진영(stage11·stage12·realism·multi)      round_trip = 13.0bp

차이를 만드는 것은 ★어느 문으로 들어왔는가★ 뿐이다. 요청이 값을 안 실으면
**문이 수수료를 정하는데**, 응답은 그 사실을 말하지 않았다 — CLAUDE.md §4 의
침묵 폴백 정의(*"라벨이 붙고 · 관측·테스트 가능할 때만 허용"*)에 걸린다.

## ★이미 있는 것과 다른 축이다★

`engine/cost_model_registry`(AK2)는 **정적** 축이다 — *"이 자리의 기본값은
무엇이고 어디 박혀 있나"*. 이 모듈은 **런타임** 축이다 — *"이 **실행**의 요율을
요청이 줬나 문이 채웠나"*. 두 모듈은 서로를 임포트하지 않는다(AST 로 건다).

## 이 파일이 지키는 것

- ★출처(누가 정했나) ⟂ 근거(재봤나)★ — 한 칸에 넣지 않는다
- ★미상 ≠ 기본값★ — 안 이은 문은 `unknown` 이지 `door_default` 가 아니다
- ★관측 ≠ 계약 요율★ — 체결을 100번 본다고 증권사 요율을 알게 되지는 않는다
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from src.domain.cost_provenance import (
    BASIS_NEVER_MEASURED,
    BASIS_OBSERVED,
    EVIDENCE_PATH,
    RATE_DOOR_DEFAULT,
    RATE_REQUEST,
    RATE_UNKNOWN,
    UNIFY_GRADES,
    load_rate_evidence,
    rate_provenance,
)

_MODULE = pathlib.Path("src/domain/cost_provenance.py")


class _Policy:
    """`CostPolicy` 의 최소 대역 — 이 모듈은 값을 읽기만 한다."""

    def __init__(self, commission_bps=15.0, slippage_bps=5.0):
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps


# ── ★출처 — 누가 이 요율을 정했나★ ───────────────────────────────────────

def test_an_explicit_request_field_is_credited_to_the_request():
    out = rate_provenance(door="screener", explicit={"commission_rate"},
                          policy=_Policy())
    assert out["commission"]["origin"] == RATE_REQUEST


def test_an_omitted_request_field_is_credited_to_the_door():
    """변이 b·c — ★요청과 문을 바꿔 부르면 죽는다★ (짝)."""
    out = rate_provenance(door="screener", explicit=set(), policy=_Policy())
    assert out["commission"]["origin"] == RATE_DOOR_DEFAULT
    assert out["commission"]["door"] == "screener"


def test_an_unwired_door_is_unknown_not_defaulted():
    """변이 d — ★미상 ≠ 기본값★

    문을 안 이었으면 *"요청이 안 줬다"* 를 **알 수 없다**. 낙관적으로
    `door_default` 라고 부르면 안 이은 것과 안 준 것이 한 칸에 합쳐진다.
    """
    out = rate_provenance(door=None, explicit=None, policy=_Policy())
    assert out["commission"]["origin"] == RATE_UNKNOWN
    assert out["commission"]["door"] is None
    assert out["commission"]["reason"]


def test_the_slippage_axis_is_reported_too():
    out = rate_provenance(door="stage11", explicit={"slippage_rate"},
                          policy=_Policy())
    assert out["slippage"]["origin"] == RATE_REQUEST
    assert out["commission"]["origin"] == RATE_DOOR_DEFAULT


def test_every_entry_carries_a_reason():
    """★사유 없는 미상·사유 없는 라벨은 금지★ (CLAUDE.md §4)."""
    for kwargs in ({"door": "screener", "explicit": {"commission_rate"}},
                   {"door": "screener", "explicit": set()},
                   {"door": None, "explicit": None}):
        out = rate_provenance(policy=_Policy(), **kwargs)
        for part in ("commission", "slippage"):
            assert out[part]["reason"], (kwargs, part)


# ── ★근거 — 그 요율을 재본 적이 있나 (다른 축)★ ──────────────────────────

def test_the_basis_is_never_measured_while_the_evidence_file_is_empty():
    """변이 e — ★안 잰 것을 `observed` 라 부르면 죽는다★"""
    out = rate_provenance(door="screener", explicit=set(), policy=_Policy())
    assert out["commission"]["basis"] == BASIS_NEVER_MEASURED


def test_the_two_axes_are_separate_keys():
    """변이 a — ★출처 ⟂ 근거★ 한 칸에 넣으면 다음 사람이 못 가른다."""
    out = rate_provenance(door="screener", explicit=set(), policy=_Policy())
    entry = out["commission"]
    assert entry["origin"] != entry["basis"]
    assert {"origin", "basis"} <= set(entry)


def test_the_basis_vocabulary_is_closed():
    assert BASIS_NEVER_MEASURED != BASIS_OBSERVED
    out = rate_provenance(door="screener", explicit=set(), policy=_Policy())
    for part in ("commission", "slippage"):
        assert out[part]["basis"] in (BASIS_NEVER_MEASURED, BASIS_OBSERVED)


def test_the_note_says_the_doors_disagree():
    """변이 k — ★저장소가 아는 것보다 덜 말하면 죽는다★

    40bp 와 13bp 로 갈린다는 것은 실측이다. 그것을 안 말하면 읽는 사람은
    이 라벨이 왜 있는지 모른다.
    """
    out = rate_provenance(door="screener", explicit=set(), policy=_Policy())
    note = out["note"]
    assert "40" in note and "13" in note


# ── ★증거 파일 — 실측이 착지할 자리★ ────────────────────────────────────

def test_the_evidence_file_exists_and_is_valid_json():
    doc = json.loads(pathlib.Path(EVIDENCE_PATH).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)


def test_the_evidence_file_is_empty_and_says_why():
    """★비어 있는 것이 결함이 아니라 정직한 현재 상태다★ (AS 선례)."""
    doc = json.loads(pathlib.Path(EVIDENCE_PATH).read_text(encoding="utf-8"))
    assert doc.get("observed") == {}
    assert len(doc.get("why_empty", "")) > 60
    assert "live_fills" in doc["why_empty"]


def test_observation_alone_cannot_unify_the_rate():
    """변이 f — ★관측 ≠ 계약 요율★

    체결을 100번 본다고 증권사 수수료표를 알게 되지는 않는다. AS 가 `rt_cd`
    에서 세운 논리와 같다 — 적용선은 관측 등급보다 **위**에 있어야 한다.
    """
    doc = json.loads(pathlib.Path(EVIDENCE_PATH).read_text(encoding="utf-8"))
    floor = doc["min_grade_to_unify"]
    assert floor in UNIFY_GRADES
    assert UNIFY_GRADES.index(floor) > UNIFY_GRADES.index("C1")


def test_the_loader_folds_a_broken_file_into_an_empty_table():
    """★깨진 파일이 예외로 번지지 않는다★ — 대신 빈 표 + 사유."""
    observed, floor = load_rate_evidence()
    assert isinstance(observed, dict)
    assert floor in UNIFY_GRADES


# ── ★다른 축과 섞지 않는다★ ─────────────────────────────────────────────

def test_the_module_does_not_import_the_static_registry():
    """변이 l — ★정적 축(AK)과 런타임 축은 다른 것이다★

    `cost_model_registry` 는 *"이 자리의 기본값이 무엇인가"* 를 답한다.
    임포트하면 두 축이 한 모듈에서 섞이고, 그러면 다음 사람이 어느 쪽을
    고쳐야 하는지 모른다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # ★모듈 경로만 보면 샌다★ — 처음 쓴 이 테스트는 `module` 만 봤고
            #   `from src.engine import cost_model_registry` 를 통째로
            #   놓쳤다(변이가 살아남아 알려 줬다). 이름까지 본다.
            parts = {getattr(node, "module", None) or ""}
            parts |= {a.name for a in node.names}
            for part in parts:
                assert "cost_model_registry" not in part, part


def test_the_module_imports_no_database_or_network():
    """계층 경계(CLAUDE.md §3) — 앞 프로그램들과 같은 가드."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("requests", "sqlalchemy", "httpx", "urllib"):
        assert banned not in imported, banned


@pytest.mark.parametrize("name", [
    "RATE_REQUEST", "RATE_DOOR_DEFAULT", "RATE_UNKNOWN",
    "BASIS_NEVER_MEASURED", "BASIS_OBSERVED", "UNIFY_GRADES", "EVIDENCE_PATH",
])
def test_the_public_names_exist(name):
    import src.domain.cost_provenance as mod

    assert hasattr(mod, name)


# ── ★표면 — `cost_model` 블록이 출처를 낸다★ ─────────────────────────────

def _run_cfg(**over):
    """최소 백테스트 설정. ★비용 값은 기본 그대로★ — 이 프로그램은 안 바꾼다."""
    from src.kis_backtest_engine import BacktestConfig

    kw = dict(symbols=["000000"], strategy_name="GoldenCross",
              strategy_params={}, start_date="2023-06-01", end_date="2023-09-01")
    kw.update(over)
    return BacktestConfig(**kw)


def test_the_config_carries_the_door_observation_with_defaults():
    """★관측용 칸은 기본값을 갖고 맨 뒤에 온다★ — 위치인자 생성을 안 깬다."""
    cfg = _run_cfg()
    assert cfg.cost_door is None
    assert cfg.cost_explicit_fields is None


def test_the_engine_block_reports_the_provenance():
    """변이 j — ★키가 늘기만 한다★"""
    from src.kis_backtest_engine import BacktestEngine

    eng = BacktestEngine(_run_cfg(cost_door="screener",
                                  cost_explicit_fields=frozenset()))
    block = eng._cost_model_block()
    assert "rate_provenance" in block
    # 기존 키는 하나도 안 사라진다.
    for old in ("policy", "version", "round_trip_bps", "n_unmeasured_trades"):
        assert old in block, old


def test_an_unwired_run_says_unknown_not_default():
    """변이 d — ★안 이은 경로는 미상이다★"""
    from src.kis_backtest_engine import BacktestEngine

    block = BacktestEngine(_run_cfg())._cost_model_block()
    assert block["rate_provenance"]["commission"]["origin"] == RATE_UNKNOWN


def test_a_wired_run_distinguishes_request_from_door():
    """★짝★ — 배선이 실제로 판정을 움직인다."""
    from src.kis_backtest_engine import BacktestEngine

    gave = BacktestEngine(_run_cfg(
        cost_door="screener",
        cost_explicit_fields=frozenset({"commission_rate"}),
    ))._cost_model_block()["rate_provenance"]["commission"]
    omitted = BacktestEngine(_run_cfg(
        cost_door="screener", cost_explicit_fields=frozenset(),
    ))._cost_model_block()["rate_provenance"]["commission"]
    assert gave["origin"] == RATE_REQUEST
    assert omitted["origin"] == RATE_DOOR_DEFAULT
    assert gave["reason"] != omitted["reason"]


#: ★AZ 이전의 값을 기계로 떠내 체크인한 것★ — *"이 값이 옳다"* 가 아니라
#: *"이 프로그램이 값을 안 바꿨다"* 의 증명이다. 요율을 재서 고치는 것은
#: 별개의 일이고, 그때는 이 상수도 함께 움직인다(증거 파일이 근거를 갖는다).
GOLDEN_DEFAULT_COMMISSION_BPS = 15.0
GOLDEN_DEFAULT_SLIPPAGE_BPS = 5.0
GOLDEN_DEFAULT_ROUND_TRIP_BPS = 40.0


def test_the_cost_values_are_untouched():
    """변이 i — ★동작 보존이 이 프로그램의 계약이다★

    ★처음 쓴 이 테스트는 두 인스턴스를 **서로** 비교했고, 그래서 기본값을
    통째로 바꾸는 변이가 살아남았다★ — 둘 다 같이 바뀌면 상대 비교는 통과한다.
    체크인된 상수로 절대값을 못 박는다.
    """
    from src.kis_backtest_engine import BacktestEngine

    plain = BacktestEngine(_run_cfg())._cost_model_block()
    wired = BacktestEngine(_run_cfg(
        cost_door="screener", cost_explicit_fields=frozenset(),
    ))._cost_model_block()
    # ⑴ 배선이 값을 안 움직인다(상대).
    for k in ("policy", "version", "round_trip_bps"):
        assert plain[k] == wired[k], k
    # ⑵ ★그리고 그 값이 AZ 이전 그대로다★(절대).
    assert plain["policy"]["commission_bps"] == GOLDEN_DEFAULT_COMMISSION_BPS
    assert plain["policy"]["slippage_bps"] == GOLDEN_DEFAULT_SLIPPAGE_BPS
    assert plain["round_trip_bps"] == GOLDEN_DEFAULT_ROUND_TRIP_BPS


# ── ★수집기 — 관측을 계약 요율로 만들지 않는다★ ─────────────────────────

def _collector():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "collect_cost_rates", "scripts/collect_cost_rates.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_collector_says_it_saw_nothing_rather_than_zero():
    """변이 g — ★미상 ≠ 0★

    *"0건 성공"* 은 *"확인했더니 문제가 없었다"* 로 읽힌다. 이 환경에는
    `live_fills` 테이블 자체가 없으므로 **사유와 함께 빈손**이어야 한다.
    """
    mod = _collector()
    rows, skipped = mod._read_fills(10)
    assert rows == []
    assert skipped and "live_fills" in skipped
    report = mod._report(skipped, None)
    assert "skipped" in report
    assert "observed" not in report


def test_the_collector_grade_is_below_the_unify_floor():
    """변이 f — ★수집기가 아무리 돌아도 통일할 수는 없다★"""
    mod = _collector()
    _observed, floor = load_rate_evidence()
    assert UNIFY_GRADES.index(mod.OBSERVED_GRADE) < UNIFY_GRADES.index(floor)


def test_the_merge_never_overwrites_the_curated_fields():
    """★사람이 적은 것을 덮지 않는다★ (AS 의 규율)."""
    mod = _collector()
    doc = {"observed": {"commission": {
        "bps": 12.3, "grade": "C2", "evidence_source": "수수료표 3쪽",
        "account_kind": "live", "probed_at": "2026-01-01",
        "first_seen": "2025-01-01", "n_fills": 1}}}
    out = mod._merge(doc, {"n_fills": 99, "bps_median": 7.0,
                           "first_seen": "2026-09-22"})
    got = out["observed"]["commission"]
    assert got["bps"] == 12.3 and got["grade"] == "C2"
    assert got["evidence_source"] == "수수료표 3쪽"
    # 변이 h — ★`first_seen` 은 UPDATE 하지 않는다★
    assert got["first_seen"] == "2025-01-01"
    # 관측은 갱신된다(짝).
    assert got["n_fills"] == 99


def test_the_fold_uses_the_median_and_keeps_the_spread():
    """★평균은 최소수수료가 걸린 소액 체결 하나에 끌려간다★"""
    mod = _collector()
    rows = [{"value": 1_000_000, "commission": 1_500, "at": "2026-01-02"},
            {"value": 1_000_000, "commission": 1_500, "at": "2026-01-03"},
            {"value": 10_000, "commission": 1_000, "at": "2026-01-01"}]
    folded, skipped = mod._fold(rows)
    assert skipped is None
    assert folded["bps_median"] == 15.0          # 중앙값은 안 끌린다
    assert folded["bps_max"] > folded["bps_median"]   # 퍼진 정도가 보인다
    assert folded["first_seen"] == "2026-01-01"


def test_the_fold_reports_unmeasurable_rather_than_zero():
    """변이 g 의 짝 — 체결이 있어도 값이 0 이면 ★미상★ 이다."""
    mod = _collector()
    folded, skipped = mod._fold([{"value": 0, "commission": 500, "at": "x"}])
    assert folded is None
    assert skipped
