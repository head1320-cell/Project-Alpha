"""KIS 마스터파일 테일 파싱 + 플래그 캐시 단위 테스트.

공식 스펙 필드 테이블(KOSPI 227B / KOSDAQ 221B)로 합성 .mst 라인을 만들어
관리종목·시장경고·거래정지·투자주의환기·시가총액·업종코드 추출을 검증.
네트워크·실파일 불필요 (실파일 정합은 사용자 환경 collect-master sanity로 확인).
"""
import pytest

from src.data import stock_master as sm
from src.kis_master_parser import (
    KOSDAQ_TAIL_FIELDS,
    KOSPI_TAIL_FIELDS,
    TAIL_LEN_BY_MARKET,
    parse_krx_master,
)


# ─── 합성 .mst 라인 빌더 (스펙 테이블 → 고정폭 바이트) ────────────────────────
def build_line(market: str, code: str, name: str, **overrides) -> bytes:
    fields = KOSPI_TAIL_FIELDS if market == "KOSPI" else KOSDAQ_TAIL_FIELDS
    part1 = code.encode("euc-kr").ljust(9) + f"KR7{code}003".encode().ljust(12) \
        + name.encode("euc-kr").ljust(40)
    defaults = {"그룹코드": "ST", "시장경고": "00", "시가총액규모": "1"}
    tail = ""
    for fname, w in fields:
        v = str(overrides.get(fname, defaults.get(fname, "")))
        tail += v[:w].rjust(w) if v.isdigit() else v[:w].ljust(w)
    return part1 + tail.encode("ascii")


def parse_one(line: bytes, market: str) -> dict:
    out = parse_krx_master(line + b"\n", market)
    assert len(out) == 1
    return out[0]


# ─── 스펙 회귀 가드 ───────────────────────────────────────────────────────────
def test_tail_lengths_match_official_spec():
    """공식 스펙: KOSPI 테일 227자, KOSDAQ 221자 (개행 제외)."""
    assert TAIL_LEN_BY_MARKET == {"KOSPI": 227, "KOSDAQ": 221}
    assert len(KOSPI_TAIL_FIELDS) == 70
    assert len(KOSDAQ_TAIL_FIELDS) == 64


# ─── 테일 파싱 ────────────────────────────────────────────────────────────────
def test_parse_normal_kospi_stock():
    s = parse_one(build_line("KOSPI", "005930", "삼성전자",
                             지수업종대분류="0013", 시가총액="4000000"), "KOSPI")
    assert (s["ticker"], s["name"], s["market"]) == ("005930", "삼성전자", "KOSPI")
    assert s["group_code"] == "ST" and not s["is_managed"] and not s["is_halted"]
    assert s["alert_code"] == "00"
    assert s["sector_code"] == "0013"
    assert s["market_cap_억"] == 4_000_000


def test_parse_flags_managed_halted_alert():
    s = parse_one(build_line("KOSPI", "000001", "관리테스트",
                             관리종목="Y", 거래정지="Y", 정리매매="Y", 시장경고="02"), "KOSPI")
    assert s["is_managed"] and s["is_halted"] and s["is_clearing"]
    assert s["alert_code"] == "02"


def test_parse_kosdaq_caution_flag():
    """투자주의환기는 코스닥 전용 필드."""
    s = parse_one(build_line("KOSDAQ", "247540", "코스닥주", 투자주의환기="Y",
                             시가총액="15000"), "KOSDAQ")
    assert s["market"] == "KOSDAQ" and s["is_caution"]
    assert s["market_cap_억"] == 15_000
    s2 = parse_one(build_line("KOSPI", "005930", "유가주"), "KOSPI")
    assert s2["is_caution"] is False  # KOSPI 테일엔 없음 → False


def test_parse_etf_group_code():
    s = parse_one(build_line("KOSPI", "069500", "KODEX200", 그룹코드="EF"), "KOSPI")
    assert s["group_code"] == "EF"


def test_short_line_falls_back_to_three_fields():
    """테일 없는 짧은 행 → 기존 3필드 동작 보존 (테일 키 없음)."""
    line = b"000660".ljust(9) + b"KR7000660001".ljust(12) \
        + "SK하이닉스".encode("euc-kr").ljust(40)
    s = parse_one(line, "KOSPI")
    assert (s["ticker"], s["name"]) == ("000660", "SK하이닉스")
    assert "sector_code" not in s and "is_managed" not in s


def test_blank_mcap_is_none():
    s = parse_one(build_line("KOSPI", "000002", "시총없음", 시가총액=""), "KOSPI")
    assert s["market_cap_억"] is None


# ─── 플래그 캐시 저장/로드 + 관리·감리 리스트 ─────────────────────────────────
@pytest.fixture
def tmp_flags_path(tmp_path, monkeypatch):
    p = tmp_path / "master_flags_cache.json"
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(p))
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)
    yield p
    sm._MASTER_FLAGS = None
    sm.MANAGED_CODES[:] = []
    sm.SUPERVISED_CODES[:] = []


def test_flags_roundtrip_and_status_lists(tmp_flags_path):
    symbols = parse_krx_master(
        build_line("KOSPI", "005930", "삼성전자", 시가총액="4000000") + b"\n"
        + build_line("KOSPI", "000001", "관리주", 관리종목="Y") + b"\n"
        + build_line("KOSPI", "000002", "경고주", 시장경고="03") + b"\n",
        "KOSPI",
    ) + parse_krx_master(build_line("KOSDAQ", "000003", "환기주", 투자주의환기="Y") + b"\n", "KOSDAQ")

    assert sm.save_master_flags(symbols) == 4
    flags = sm.load_master_flags()
    assert flags["005930"]["market_cap_억"] == 4_000_000

    sm._refresh_status_lists()
    assert sm.MANAGED_CODES == ["000001"]                      # 관리종목
    assert set(sm.SUPERVISED_CODES) == {"000002", "000003"}    # 시장경고 + 투자주의환기


def test_status_lists_empty_without_cache(tmp_flags_path):
    """캐시 파일 없음 → 빈 리스트 (현행 no-op 불변)."""
    sm._refresh_status_lists()
    assert sm.MANAGED_CODES == [] and sm.SUPERVISED_CODES == []
