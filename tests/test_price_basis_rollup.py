"""`price_quality.basis_rollup` — ★라벨을 세는 순수 함수★

## 무엇을 답하나

로드맵 0단계의 넷 중 **"가격 정의 상태"**. 백테스트가 실제로 로드한 프레임마다
`ohlcv_loader._tag` 가 붙여 둔 두 라벨(`adj_status`·`price_basis`)을 모아
한 문장으로 만든다.

## ★규칙을 새로 만들지 않는다★

판정은 `price_usage()` 와 **같은 전부-아니면-전무 계약**이다 — 모든 티커가
`adjusted` 이고 **그리고** 정의가 섞이지 않았을 때만 깨끗하다. 새 등급도 새
임계값도 만들지 않는다. 이 함수가 하는 일은 **세는 것**뿐이고, DB 를 보지 않는다.

## ★이 파일이 지키는 세 가지★

  · **미상은 통과가 아니다** — 라벨이 없거나 `unknown` 이면 `ok` 를 내지 않는다
  · **미상 ≠ 행 없음** — `missing`(행이 없다는 *판단*)과 `unlabeled`(라벨 자체가
    없다)는 다른 칸이다. 섞으면 DB 가 죽었을 때 "행이 없다" 는 하지 않은 진술이 된다
  · **이름을 낸다** — 개수만으로는 어느 종목을 고쳐야 하는지 알 수 없다
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.price_quality import (  # noqa: E402
    BASIS_MIXED,
    BASIS_UNIFORM_ADJUSTED,
    BASIS_UNIFORM_RAW,
    BASIS_UNKNOWN,
    ROLLUP_UNLABELED,
    STATE_ADJUSTED,
    STATE_CHAIN_BROKEN,
    STATE_MISSING,
    STATE_RAW,
    basis_rollup,
)


def _clean(n: int) -> tuple[dict, dict]:
    """전부 깨끗한 n 종목."""
    ts = [f"{i:06d}" for i in range(n)]
    return ({t: BASIS_UNIFORM_ADJUSTED for t in ts},
            {t: STATE_ADJUSTED for t in ts})


# ═══════════════════════════════════════════════════════════════════════════
# ⑤ 전부 깨끗하면 ok
# ═══════════════════════════════════════════════════════════════════════════

def test_all_uniform_adjusted_is_ok():
    b, a = _clean(4)
    out = basis_rollup(b, a)
    assert out["state"] == "ok", out
    assert out["reason"] is None, out
    assert out["uniform_adjusted_pct"] == 100.0, out
    assert out["tickers"] == 4, out
    assert out["basis"][BASIS_UNIFORM_ADJUSTED] == 4, out


def test_the_unit_is_declared():
    """★세는 단위를 밝힌다★ 봉도 행도 아니고 티커다."""
    b, a = _clean(2)
    assert basis_rollup(b, a)["unit"] == "ticker"


def test_the_label_source_is_declared():
    """★`attrs` 는 권위가 아니라 힌트다★ 어디서 온 라벨인지 페이로드가 말한다."""
    b, a = _clean(2)
    assert basis_rollup(b, a)["source"] == "loader_attrs"


# ═══════════════════════════════════════════════════════════════════════════
# ⑥⑦ 알려진 결함 하나면 degraded — ★이름과 함께★
# ═══════════════════════════════════════════════════════════════════════════

def test_one_mixed_ticker_degrades_and_is_named():
    b, a = _clean(3)
    b["000001"] = BASIS_MIXED
    out = basis_rollup(b, a)
    assert out["state"] == "degraded", out
    assert out["mixed_tickers"] == ["000001"], out
    assert "000001" in (out["reason"] or ""), out["reason"]
    assert out["basis"][BASIS_MIXED] == 1, out


def test_one_raw_ticker_degrades_and_is_named():
    b, a = _clean(3)
    b["000002"] = BASIS_UNIFORM_RAW
    a["000002"] = STATE_RAW
    out = basis_rollup(b, a)
    assert out["state"] == "degraded", out
    assert out["unadjusted_tickers"] == ["000002"], out
    assert "000002" in (out["reason"] or ""), out["reason"]


def test_a_broken_chain_is_not_adjusted():
    """★`chain_broken` 은 `adjusted` 가 아니다★ 일부만 조정된 계열이다."""
    b, a = _clean(2)
    a["000001"] = STATE_CHAIN_BROKEN
    out = basis_rollup(b, a)
    assert out["state"] == "degraded", out
    assert "000001" in out["unadjusted_tickers"], out


def test_a_missing_ticker_degrades():
    b, a = _clean(2)
    a["000001"] = STATE_MISSING
    out = basis_rollup(b, a)
    assert out["state"] == "degraded", out
    assert out["adj_status"][STATE_MISSING] == 1, out


# ═══════════════════════════════════════════════════════════════════════════
# ⑧⑩ ★미상은 통과가 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_unknown_labels_never_produce_ok():
    """★짝★ — 결함이 하나도 관측되지 않아도, 못 잰 것이 있으면 `ok` 가 아니다."""
    b, a = _clean(3)
    b["000001"] = BASIS_UNKNOWN
    out = basis_rollup(b, a)
    assert out["state"] == "unknown", out
    assert out["reason"], "미상인데 사유가 없다"


def test_an_unlabeled_frame_is_not_ok_either():
    """라벨 자체가 없는 프레임(태깅 실패·`attrs` 유실)도 `ok` 를 막는다."""
    b, a = _clean(3)
    b["000001"] = None
    a["000001"] = None
    out = basis_rollup(b, a)
    assert out["state"] == "unknown", out
    assert out["unlabeled_tickers"] == ["000001"], out


def test_unlabeled_is_not_counted_as_missing():
    """★미상 ≠ 행 없음★ — `missing` 은 '행이 없다' 는 **판단**이다.

    둘을 한 칸에 세면, DB 를 못 읽은 실행이 "이 종목들은 데이터가 없습니다" 라는
    하지 않은 진술로 둔갑한다.
    """
    b, a = _clean(2)
    b["000001"] = None
    a["000001"] = None
    out = basis_rollup(b, a)
    assert out["adj_status"][ROLLUP_UNLABELED] == 1, out
    assert out["adj_status"][STATE_MISSING] == 0, out


def test_unknown_stays_in_the_denominator():
    """★분모에서 빼면 비율이 좋아 보인다★"""
    b, a = _clean(4)
    b["000000"] = BASIS_UNKNOWN
    b["000001"] = BASIS_UNKNOWN
    out = basis_rollup(b, a)
    assert out["tickers"] == 4, out
    assert out["uniform_adjusted_pct"] == 50.0, out


def test_a_known_defect_outranks_an_unmeasured_one():
    """섞여 있으면 `degraded` — ★관측된 결함이 미상보다 강한 진술이다★"""
    b, a = _clean(3)
    b["000000"] = BASIS_MIXED
    b["000001"] = BASIS_UNKNOWN
    out = basis_rollup(b, a)
    assert out["state"] == "degraded", out
    assert "000000" in (out["reason"] or ""), out["reason"]
    # ★강등이지 삭제가 아니다★ 미상도 사유에 남는다.
    assert out["basis"][BASIS_UNKNOWN] == 1, out


# ═══════════════════════════════════════════════════════════════════════════
# ⑨ 안 잰 것 ≠ 재서 0
# ═══════════════════════════════════════════════════════════════════════════

def test_no_frames_is_none_not_zeroes():
    """★프레임이 하나도 없으면 `None`★ — 0 으로 채우면 '재봤더니 전부 0' 이 된다."""
    assert basis_rollup({}, {}) is None


# ═══════════════════════════════════════════════════════════════════════════
# 표본과 개수 — ★이름은 표본이고 개수는 정확하다★
# ═══════════════════════════════════════════════════════════════════════════

def test_names_are_a_capped_sample_but_counts_are_exact():
    ts = [f"{i:06d}" for i in range(12)]
    b = {t: BASIS_MIXED for t in ts}
    a = dict.fromkeys(ts, STATE_ADJUSTED)
    out = basis_rollup(b, a)
    assert out["basis"][BASIS_MIXED] == 12, "개수가 잘렸다"
    assert len(out["mixed_tickers"]) == 5, out["mixed_tickers"]
    assert out["mixed_tickers"] == sorted(out["mixed_tickers"]), "표본이 결정론적이지 않다"


def test_the_sample_helper_itself_sorts():
    """★변이를 재보고 알게 된 것★ — 결정론이 **두 곳**에서 보장된다.

    처음에 이 자리에는 "입력 dict 순서를 뒤집어도 같은 표본" 이라는 테스트가
    있었다. 그런데 `_sample` 의 정렬을 **빼는 변이가 살아남았다** — `basis_rollup`
    이 이미 `sorted(set(...))` 로 티커를 순회하므로 표본이 그 순서로 만들어져
    정렬이 no-op 이었기 때문이다.

    ★적용됐다고 겨냥이 맞은 것은 아니다★ 그래서 실제 가드를 직접 건다. 둘 중
    하나만 빼면 여전히 통과하는 것이 **사실**이고(중복 보장), 이 테스트는 그중
    `_sample` 쪽을 못 박는다. 위 순회 정렬이 언젠가 사라져도 표본은 결정론적이다.
    """
    from src.data.price_quality import _sample
    assert _sample(["000009", "000001", "000005"]) == ["000001", "000005", "000009"]


def test_the_sample_is_deterministic_end_to_end():
    """같은 입력 → 같은 표본. ★가장 작은 다섯을 순서대로★"""
    ts = [f"{i:06d}" for i in range(12)]
    b = {t: BASIS_MIXED for t in reversed(ts)}
    a = dict.fromkeys(ts, STATE_ADJUSTED)
    assert basis_rollup(b, a)["mixed_tickers"] == ts[:5]


# ═══════════════════════════════════════════════════════════════════════════
# ★순수 함수★ — DB 를 보지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_it_never_touches_the_database(monkeypatch):
    """롤업이 DB 를 열면 백테스트마다 티커 수만큼 왕복이 는다."""
    import src.data.price_quality as PQ

    def _boom(*a, **k):
        raise AssertionError("basis_rollup 이 DB 를 열었다 — 순수 함수여야 한다")

    monkeypatch.setattr(PQ, "_engine", _boom)
    monkeypatch.setattr(PQ, "_fetch", _boom)
    b, a = _clean(3)
    assert basis_rollup(b, a)["state"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# ★실행해 보고 발견한 것★ — 조회 실패가 "행이 없다" 로 둔갑하고 있었다
#
# 목업 백테스트를 실제로 돌려 응답을 눈으로 보니 진단이 이렇게 나왔다:
#
#     수정주가 아님(91종목) — 000100, 000270, … · 라벨 없음(91종목) — …
#
# **같은 91종목이 양쪽에 있었다.** `adj_status_of()` 가 커버리지 리포트를 얻지
# 못했을 때 `missing`("`daily_prices` 에 행이 하나도 없습니다" 라는 **판단**)을
# 돌려줬기 때문이다. DB 가 없는 실행에서 그것은 하지 않은 진술이고, 화면에는
# "이 91종목은 수정주가가 아닙니다" 라는 **거짓 주장**으로 나갔다.
#
# ★미상 ≠ 0 · 미검증 ≠ 검증 · 미적재 ≠ 제공자 미지원★ 과 같은 부류다.
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unavailable_report_is_not_a_missing_row_claim(monkeypatch):
    """`adj_status_of` 는 조회 실패를 `missing` 으로 적지 않는다."""
    import src.data.price_quality as PQ
    monkeypatch.setattr(PQ, "adj_close_coverage",
                        lambda *a, **k: {"available": False, "reason": "DB 없음"})
    assert PQ.adj_status_of("005930") is None


def test_a_real_absence_is_still_missing(monkeypatch):
    """★짝★ 리포트를 얻었는데 그 티커가 없으면 그것은 진짜 `missing` 이다."""
    import src.data.price_quality as PQ
    monkeypatch.setattr(PQ, "adj_close_coverage",
                        lambda *a, **k: {"available": True, "by_ticker": {}})
    assert PQ.adj_status_of("005930") == STATE_MISSING


def test_an_unreadable_run_is_unknown_not_degraded():
    """DB 를 못 읽은 실행 전체는 `unknown` 이다 — ★결함을 관측한 것이 아니다.★"""
    ts = [f"{i:06d}" for i in range(3)]
    out = basis_rollup(dict.fromkeys(ts, None), dict.fromkeys(ts, None))
    assert out["state"] == "unknown", out
    assert out["adj_status"][STATE_MISSING] == 0, "조회 실패가 '행 없음' 으로 세어졌다"
    assert out["adj_status"][ROLLUP_UNLABELED] == 3, out
    assert out["unadjusted_tickers"] == [], "미상이 '수정주가 아님' 으로 주장됐다"
