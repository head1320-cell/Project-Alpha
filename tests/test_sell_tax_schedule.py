"""매도세는 ★거래일·시장·상품에 따라 다르다★ — `market_rules.sell_tax_bp_on` (2026-11-14)

## 왜 필요한가

`sell_tax_bp()` 는 18bp 고정이다 — 2024년 한 해의 값이다(코스피 0.03% + 농특세 0.15% · 코스닥 0.18%).
2023년은 20bp, 2025년은 15bp, 2026년은 다시 20bp 이고 ETF 는 매도세가 없다. 하루에 여러 번 사고파는 사람에게
매도세는 가장 큰 고정 비용이라, 2bp~5bp 의 차이가 손익분기 승률을 바꾼다.

## 이 파일이 거는 계약

① 구간의 경계가 맞다(전날과 당일이 다른 값).
② 값과 함께 구성(거래세·농특세) · 등급 · 출처 · 구간을 싣는다.
③ ★면제는 0 이라는 값이고 미상은 `None` 이다★ — 둘을 섞지 않는다.
④ 모르는 구간·시장·상품은 `None` + 사유다(가까운 값으로 채우지 않는다).
⑤ 증거 파일이 스스로 모순되지 않는다(구간 겹침 · 없는 출처 · 어휘 밖 등급).
⑥ 기존 `sell_tax_bp()` 는 그대로다(그 값을 읽는 엔진의 결과가 바뀌지 않는다).
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from src.data import market_rules as mr

# (거래일, 합계, 거래세, 농특세)
KOSPI = [
    ("2019-05-30", 25, 10, 15), ("2020-12-31", 25, 10, 15),
    ("2021-01-01", 23, 8, 15), ("2022-12-31", 23, 8, 15),
    ("2023-01-01", 20, 5, 15), ("2023-12-31", 20, 5, 15),
    ("2024-01-01", 18, 3, 15), ("2024-12-31", 18, 3, 15),
    ("2025-01-01", 15, 0, 15), ("2025-12-31", 15, 0, 15),
    ("2026-01-01", 20, 5, 15), ("2026-11-13", 20, 5, 15),
]
KOSDAQ = [
    ("2019-05-30", 25), ("2020-12-31", 25), ("2021-01-01", 23), ("2022-12-31", 23), ("2023-01-01", 20),
    ("2023-12-31", 20), ("2024-01-01", 18), ("2024-12-31", 18), ("2025-01-01", 15), ("2025-12-31", 15),
    ("2026-01-01", 20), ("2026-11-13", 20),
]


# ══ ① 경계 ════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("day,total,tx,rural", KOSPI)
def test_kospi_rate_on_each_side_of_every_change(day, total, tx, rural):
    out = mr.sell_tax_bp_on(day, "KOSPI")
    assert out["available"] is True and out["bp"] == total
    assert out["parts"] == {"transaction_tax_bp": tx, "rural_special_tax_bp": rural}


@pytest.mark.parametrize("day,total", KOSDAQ)
def test_kosdaq_rate_on_each_side_of_every_change(day, total):
    out = mr.sell_tax_bp_on(day, "KOSDAQ")
    assert out["bp"] == total
    assert out["parts"] == {"transaction_tax_bp": total, "rural_special_tax_bp": 0}, "코스닥에는 농특세가 없다"


def test_the_fixed_constant_is_only_right_for_one_year():
    """이 함수가 필요한 까닭 — 고정값 18bp 는 2024년에만 맞는다."""
    assert mr.sell_tax_bp() == 18.0
    by_year = {y: mr.sell_tax_bp_on(f"{y}-06-15", "KOSPI")["bp"] for y in (2020, 2022, 2023, 2024, 2025, 2026)}
    assert by_year == {2020: 25, 2022: 23, 2023: 20, 2024: 18, 2025: 15, 2026: 20}


# ══ ② 값과 함께 싣는 것 ═══════════════════════════════════════════════════════

def test_an_answer_carries_grade_period_and_sources():
    out = mr.sell_tax_bp_on("2024-03-04", "KOSPI")
    assert out["grade"] == "T1" and out["reason"] is None
    assert out["period"] == {"from": "2024-01-01", "to": "2024-12-31"}
    assert out["sources"] and all(s["url"].startswith("https://") and s["title"] for s in out["sources"])
    assert out["market"] == "KOSPI" and out["instrument"] == "stock"


def test_an_open_ended_period_says_so():
    assert mr.sell_tax_bp_on("2026-03-04", "KOSDAQ")["period"] == {"from": "2026-01-01", "to": None}


def test_a_note_about_weak_evidence_travels_with_the_value():
    """2026년 값은 입법예고 보도가 근거다 — 그 단서가 값과 함께 가야 쓰는 쪽이 '추정'이라고 적을 수 있다."""
    assert "원문" in mr.sell_tax_bp_on("2026-03-04", "KOSPI")["note"]


@pytest.mark.parametrize("form", ["2024-03-04", "20240304", date(2024, 3, 4), datetime(2024, 3, 4, 14, 30)])
def test_the_date_may_come_in_any_usual_form(form):
    assert mr.sell_tax_bp_on(form, "KOSPI")["bp"] == 18


@pytest.mark.parametrize("market", ["kospi", "Kospi", " KOSPI "])
def test_the_market_name_is_case_and_space_insensitive(market):
    assert mr.sell_tax_bp_on("2024-03-04", market)["bp"] == 18


# ══ ③ 면제는 값 · 미상은 None ═════════════════════════════════════════════════

@pytest.mark.parametrize("market", ["KOSPI", "KOSDAQ"])
def test_an_etf_is_exempt_and_that_is_a_value(market):
    out = mr.sell_tax_bp_on("2026-03-04", market, "etf")
    assert out["available"] is True and out["bp"] == 0 and out["reason"] is None
    assert out["parts"] == {"transaction_tax_bp": 0, "rural_special_tax_bp": 0}


def test_exempt_and_unknown_are_not_the_same_answer():
    etf, etn = mr.sell_tax_bp_on("2026-03-04", "KOSPI", "etf"), mr.sell_tax_bp_on("2026-03-04", "KOSPI", "etn")
    assert etf["bp"] == 0 and etn["bp"] is None
    assert etf["available"] is True and etn["available"] is False


# ══ ④ 모르면 None + 사유 ══════════════════════════════════════════════════════

@pytest.mark.parametrize("day,market,instrument,reason", [
    ("2019-05-29", "KOSPI", "stock", "outside_schedule"),      # 표가 시작하기 하루 전 — 직전 구간의 시작일을 모른다
    ("2010-01-04", "KOSDAQ", "stock", "outside_schedule"),
    ("2026-03-04", "KONEX", "stock", "outside_schedule"),      # 2026년 개정에서 코넥스가 유지되는지 확인하지 못했다
    ("2024-03-04", "KOSPI", "etn", "unknown_instrument"),
    ("2024-03-04", "KOSPI", "elw", "unknown_instrument"),
    ("2024-03-04", "K-OTC", "stock", "unknown_market"),
    ("2024-03-04", "NYSE", "stock", "unknown_market"),
])
def test_an_unknown_cell_is_none_with_a_reason(day, market, instrument, reason):
    out = mr.sell_tax_bp_on(day, market, instrument)
    assert out["available"] is False and out["bp"] is None and out["parts"] is None
    assert out["reason"] == reason and out["message"]


def test_konex_is_known_until_the_change_it_was_not_named_in():
    assert mr.sell_tax_bp_on("2025-12-31", "KONEX")["bp"] == 10
    assert mr.sell_tax_bp_on("2026-01-01", "KONEX")["bp"] is None


@pytest.mark.parametrize("bad", ["", "2024-13-40", "어제", None, 20240304])
def test_a_date_it_cannot_read_is_refused_not_guessed(bad):
    out = mr.sell_tax_bp_on(bad, "KOSPI")
    assert out["bp"] is None and out["reason"] == "bad_date"


# ══ ⑤ 증거 파일 ═══════════════════════════════════════════════════════════════

def _doc() -> dict:
    return json.loads(mr.SELL_TAX_EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_periods_of_one_market_and_instrument_never_overlap():
    rows: dict[tuple, list] = {}
    for r in _doc()["schedule"]:
        rows.setdefault((r["market"], r["instrument"]), []).append(r)
    assert len(rows) >= 5
    for key, rs in rows.items():
        rs.sort(key=lambda r: r["from"])
        for a, b in zip(rs, rs[1:]):
            assert a["to"] is not None and a["to"] < b["from"], f"{key}: {a['from']}~{a['to']} 과 {b['from']} 이 겹친다"


def test_every_row_points_at_sources_that_exist_and_a_grade_in_the_vocabulary():
    doc = _doc()
    for r in doc["schedule"]:
        assert r["sources"] and set(r["sources"]) <= set(doc["sources"]), r
        assert r["grade"] in doc["grades"] and r["grade"] != "T0", r
        assert r["transaction_tax_bp"] >= 0 and r["rural_special_tax_bp"] >= 0


def test_the_unknown_list_is_not_empty_and_each_entry_has_a_reason():
    """확인하지 못한 구간이 '없는 것처럼' 보이면 안 된다."""
    unknown = _doc()["unknown"]
    assert len(unknown) >= 3 and all(u["reason"].strip() for u in unknown)


def _override(tmp_path, monkeypatch, mutate) -> None:
    doc = _doc()
    mutate(doc)
    p = tmp_path / "tax.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SELL_TAX_EVIDENCE_PATH", str(p))


def test_a_row_below_the_grade_floor_is_not_applied(tmp_path, monkeypatch):
    """등급이 적용선에 못 미치면 값이 있어도 쓰지 않는다 — 낮은 확신이 조용히 사실이 되지 않게."""
    _override(tmp_path, monkeypatch, lambda d: d.update(min_grade_to_apply="T2"))
    out = mr.sell_tax_bp_on("2024-03-04", "KOSPI")
    assert out["bp"] is None and out["reason"] == "below_grade_floor" and out["grade"] == "T1"


def test_the_table_is_read_from_the_file_not_from_the_code(tmp_path, monkeypatch):
    """표의 값이 코드에 박혀 있으면 증거 파일은 장식이다."""
    def mutate(d):
        for r in d["schedule"]:
            if r["market"] == "KOSPI" and r["instrument"] == "stock" and r["from"] == "2024-01-01":
                r["transaction_tax_bp"] = 7
    _override(tmp_path, monkeypatch, mutate)
    assert mr.sell_tax_bp_on("2024-03-04", "KOSPI")["bp"] == 22
    assert mr.sell_tax_bp_on("2023-03-06", "KOSPI")["bp"] == 20


def test_a_missing_evidence_file_is_an_explicit_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("SELL_TAX_EVIDENCE_PATH", str(tmp_path / "nope.json"))
    out = mr.sell_tax_bp_on("2024-03-04", "KOSPI")
    assert out["bp"] is None and out["reason"] == "no_evidence_file"


# ══ ⑥ 기존 함수는 그대로 ══════════════════════════════════════════════════════

def test_the_old_function_and_its_override_are_unchanged(monkeypatch):
    assert mr.sell_tax_bp() == 18.0
    monkeypatch.setenv("KR_SELL_TAX_BP", "23")
    assert mr.sell_tax_bp() == 23.0
    assert mr.rules_snapshot()["sell_tax_bp"] == 23.0
    assert mr.sell_tax_bp_on("2024-03-04", "KOSPI")["bp"] == 18, "새 함수는 예전 환경변수에 끌려가지 않는다"
