"""골든 비교 — ★"판정 불가" 를 "무해" 로 부르지 않는다★
==============================================================================
사건: `docs/HISTORY.md` 2026-08-28 · 감사 `docs/specs/2026-08-26-data-extraction-audit.md`

## 이 파일이 막는 것

`t3_geometry` 산출의 한 필드(`mdd_pct` −23.16 ↔ −23.17)가 **소스 변경 없이**
저장된 기준선과 달랐다. 조사 결과:

    · 기준선 이후 계산 사슬을 건드린 커밋 0건(21커밋 전부 무편집)
    · 기준선 시점 커밋을 오늘 실행 → 오늘 HEAD 와 바이트 동일
    · 같은 설정 4연속 → md5 동일(완전 결정론)
    · ★`OPENBLAS_CORETYPE` 만 바꾸면 그 한 필드가 뒤집힌다★

numpy 가 싣는 OpenBLAS 는 `DYNAMIC_ARCH=1` 이라 **호스트 CPU 를 보고 런타임에
마이크로커널을 고른다**. 즉 ★"골든 바이트 동일" 은 코드의 성질이 아니다.★

그런데 `diff` 는 "달랐다" 만 말한다. 불변 증거에 필요한 것은 **무엇이 · 얼마나 ·
그것이 부동소수 잡음일 수 있는가** 이고, 그 판정을 하는 도구가 없었다.

## ★세 판정★

    identical   구조·값 모두 동일                      → 종료 0
    last_place  인쇄된 마지막 자리 1단위 이내 차이뿐   → 종료 ★2★
    material    그보다 크거나 구조가 다름              → 종료 1

`last_place` 는 **"잡음이다" 가 아니다**. 리포트가 값을 반올림해 저장하므로
1e-12 의 진짜 변화도 반올림 경계에서는 마지막 자리를 뒤집는다. 그래서 종료코드를
0 과 분리하고 **지문 대조를 요구**한다 — 그것이 이 판정이 말할 수 있는 전부다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
import scripts.golden_compare as gc  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def _run(*args):
    """CLI 로 실제 실행 — ★종료코드는 함수 반환값이 아니라 프로세스가 낸다★"""
    return subprocess.run([sys.executable, "scripts/golden_compare.py", *args],
                          cwd=_ROOT, capture_output=True, text=True)


# ══════════════════════════════════════════════════════════════════════════
# G1 동일
# ══════════════════════════════════════════════════════════════════════════
def test_identical_reports_are_identical(tmp_path):
    obj = {"arms": {"A": {"mdd_pct": -23.16, "name": "A"}}, "n": 3}
    a = _write(tmp_path, "a.json", obj)
    b = _write(tmp_path, "b.json", obj)
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.IDENTICAL
    assert res["diffs"] == []
    assert _run(a, b).returncode == gc.EXIT_IDENTICAL == 0


# ══════════════════════════════════════════════════════════════════════════
# G2 ★핵심 — 이번 사건 그 자체★
# ══════════════════════════════════════════════════════════════════════════
def test_the_observed_drift_is_last_place_not_identical(tmp_path):
    """−23.16 vs −23.17. ★종료 0 이 되면 이 도구는 존재 이유가 없다★"""
    a = _write(tmp_path, "a.json", {"arms": {"A": {"mdd_pct": -23.16}}})
    b = _write(tmp_path, "b.json", {"arms": {"A": {"mdd_pct": -23.17}}})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.LAST_PLACE
    assert len(res["diffs"]) == 1
    assert res["diffs"][0]["path"] == "arms.A.mdd_pct"

    proc = _run(a, b)
    assert proc.returncode == gc.EXIT_LAST_PLACE == 2, "잡음 판정이 성공으로 샜다"


def test_last_place_hands_over_the_fingerprint_to_compare(tmp_path):
    """★G10★ 출력이 **대조에 쓸 수 있는 지문 자체**를 줘야 한다.

    ★문구가 아니라 **쓸 수 있는 데이터**를 검사한다★ — "무해라고 쓰지 마라" 를
    문자열 포함으로 검사하면, 무해함을 **부정하는** 좋은 문장까지 막는다(실제로
    그렇게 잘못 썼다). 필요한 성질은 "읽는 사람이 기계를 대조할 수 있는가" 다.
    """
    a = _write(tmp_path, "a.json", {"x": -23.16})
    b = _write(tmp_path, "b.json", {"x": -23.17})
    out = _run(a, b).stdout
    assert "지문" in out, "지문 대조를 요구하지 않는다"

    last = [ln for ln in out.splitlines() if ln.strip()][-1]
    fp = json.loads(last)          # ★마지막 줄이 그대로 지문이어야 한다★
    assert fp["numpy"] and fp["cpu"]["model"], "대조할 수 있는 지문이 아니다"


def test_an_identical_run_does_not_shout_about_fingerprints(tmp_path):
    """★짝★ 지문 요구가 **항상** 붙으면 그 요구는 신호가 아니라 배경소음이다."""
    obj = {"x": -23.16}
    a = _write(tmp_path, "a.json", obj)
    b = _write(tmp_path, "b.json", obj)
    assert "지문" not in _run(a, b).stdout


# ══════════════════════════════════════════════════════════════════════════
# G3 ★짝★ 실제 차이를 잡음으로 부르지 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_a_real_change_is_material(tmp_path):
    a = _write(tmp_path, "a.json", {"arms": {"A": {"mdd_pct": -23.16}}})
    b = _write(tmp_path, "b.json", {"arms": {"A": {"mdd_pct": -24.20}}})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert _run(a, b).returncode == gc.EXIT_MATERIAL == 1


# ══════════════════════════════════════════════════════════════════════════
# G4 ★핵심 짝 — 허용오차가 **자릿수를 따라간다**★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("a_val,b_val,expected", [
    (0.001, 0.002, "last_place"),      # 마지막 자리 1단위
    (0.0010, 0.0030, "material"),      # 같은 절대차 0.002 인데 자릿수가 다르다
    (-23.16, -23.17, "last_place"),
    (-23.16, -23.18, "material"),      # 2단위
    (1000.0, 1000.1, "last_place"),
    (1000.0, 1000.3, "material"),
])
def test_the_tolerance_follows_the_printed_precision(tmp_path, a_val, b_val, expected):
    """★절대값 고정 허용오차는 틀렸다★

    `0.001` 규모의 값에서 절대 `0.01` 을 허용하면 **10배 변화가 "잡음"** 이 된다.
    허용오차는 그 값이 **몇 자리로 인쇄됐는가**를 따라야 한다.
    """
    a = _write(tmp_path, "a.json", {"x": a_val})
    b = _write(tmp_path, "b.json", {"x": b_val})
    assert gc.compare_files(a, b)["verdict"] == expected


# ══════════════════════════════════════════════════════════════════════════
# G5·G6 구조 차이는 수치 허용오차를 타지 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_an_added_key_is_material_even_when_every_shared_value_matches(tmp_path):
    a = _write(tmp_path, "a.json", {"x": 1.0})
    b = _write(tmp_path, "b.json", {"x": 1.0, "y": 2.0})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert any(d["kind"] == gc.KIND_ADDED and d["path"] == "y" for d in res["diffs"])


def test_a_removed_key_is_material(tmp_path):
    a = _write(tmp_path, "a.json", {"x": 1.0, "y": 2.0})
    b = _write(tmp_path, "b.json", {"x": 1.0})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert any(d["kind"] == gc.KIND_REMOVED for d in res["diffs"])


def test_a_type_change_is_material_not_a_numeric_diff(tmp_path):
    """`1` → `"1"` 은 값이 "같아" 보여도 다른 사실이다."""
    a = _write(tmp_path, "a.json", {"x": 1})
    b = _write(tmp_path, "b.json", {"x": "1"})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert any(d["kind"] == gc.KIND_TYPE for d in res["diffs"])


def test_a_length_change_in_a_list_is_material(tmp_path):
    a = _write(tmp_path, "a.json", {"xs": [1.0, 2.0]})
    b = _write(tmp_path, "b.json", {"xs": [1.0, 2.0, 3.0]})
    assert gc.compare_files(a, b)["verdict"] == gc.MATERIAL


# ══════════════════════════════════════════════════════════════════════════
# G7 중첩 — ★얕게 훑으면 깊은 차이를 놓친다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_deeply_nested_difference_is_found_with_its_path(tmp_path):
    mk = lambda v: {"arms": {"A-level": {"cells": [{"c": 10.0, "m": {"mdd_pct": v}}]}}}  # noqa: E731
    a = _write(tmp_path, "a.json", mk(-23.16))
    b = _write(tmp_path, "b.json", mk(-25.90))
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert res["diffs"][0]["path"] == "arms.A-level.cells[0].m.mdd_pct"


def test_nested_equal_structures_report_nothing(tmp_path):
    """★짝★ 없으면 위 테스트가 "항상 차이 있음" 구현으로도 통과한다."""
    mk = lambda: {"a": {"b": [{"c": [1.0, {"d": "x"}]}]}}  # noqa: E731
    a = _write(tmp_path, "a.json", mk())
    b = _write(tmp_path, "b.json", mk())
    assert gc.compare_files(a, b)["verdict"] == gc.IDENTICAL


# ══════════════════════════════════════════════════════════════════════════
# G8 비수치는 허용오차를 타지 않는다
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("a_val,b_val", [
    ("synthetic_mechanism", "real_forecast"),
    (None, 0.0),
    (0.0, None),
    (True, False),
    (True, 1),
])
def test_non_numeric_differences_never_count_as_rounding_noise(tmp_path, a_val, b_val):
    a = _write(tmp_path, "a.json", {"x": a_val})
    b = _write(tmp_path, "b.json", {"x": b_val})
    assert gc.compare_files(a, b)["verdict"] == gc.MATERIAL


def test_a_numeric_looking_string_is_still_a_string(tmp_path):
    """★변이 M6 이 살아남아 발견한 구멍★

    문자열을 float 로 강제 비교하면 `"2026.1"` 과 `"2026.11"` 같은 **판본·라벨**이
    허용오차에 삼켜진다. 문자열에는 반올림이 없다 — 다르면 다른 것이다.
    """
    for a_val, b_val in (("1.000", "1.001"), ("2026.1", "2026.11"), ("0", "0.001")):
        a = _write(tmp_path, "a.json", {"version": a_val})
        b = _write(tmp_path, "b.json", {"version": b_val})
        assert gc.compare_files(a, b)["verdict"] == gc.MATERIAL, (a_val, b_val)


def test_mixed_precision_uses_the_stricter_side(tmp_path):
    """★변이 M8 이 살아남아 발견한 구멍★

    `1.0` 과 `1.05` 는 **인쇄 자릿수부터 다르다**. 느슨한 쪽(0.1)을 쓰면 그
    자릿수 변화까지 잡음으로 흡수된다 — 자릿수가 달라진 것 자체가 리포트가
    달라졌다는 신호다. 그래서 더 엄격한 쪽(0.01)을 쓴다.
    """
    a = _write(tmp_path, "a.json", {"x": 1.0})
    b = _write(tmp_path, "b.json", {"x": 1.05})
    assert gc.compare_files(a, b)["verdict"] == gc.MATERIAL

    # ★짝★ 자릿수가 같으면 여전히 last_place 다(항상-material 배제).
    c = _write(tmp_path, "c.json", {"x": 1.00})
    d = _write(tmp_path, "d.json", {"x": 1.01})
    assert gc.compare_files(c, d)["verdict"] == gc.LAST_PLACE


def test_none_equal_to_none_is_identical(tmp_path):
    """★짝★ `None` 을 무조건 material 로 만들면 안 된다."""
    a = _write(tmp_path, "a.json", {"x": None, "y": "s", "z": True})
    b = _write(tmp_path, "b.json", {"x": None, "y": "s", "z": True})
    assert gc.compare_files(a, b)["verdict"] == gc.IDENTICAL


# ══════════════════════════════════════════════════════════════════════════
# G11 ★설정 차이 — "코드가 바뀐 것" 과 "다른 실험" 을 가른다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_setup_difference_is_surfaced_separately(tmp_path):
    """도구를 만들자마자 실제로 걸린 사례다.

    저장된 `t3_bl_ep` 기준선은 `--conf 25`, 재생성은 기본값(conf≈1.111)이었고
    40개 필드가 전부 크게 달랐다. ★`conf` 한 줄이 40줄에 묻히면 회귀로 오독된다.★
    """
    # ★문서 순서상 `conf` 를 **뒤에** 둔다★ 앞에 두면 별도 구획이 없어도 우연히
    # 먼저 나와, 순서 검사가 통과해 버린다(변이 M12 가 그렇게 살아남았다).
    a = _write(tmp_path, "a.json", {"arms": {"A": {"w_l1_mean": 0.6279, "conf": 25.0}}})
    b = _write(tmp_path, "b.json", {"arms": {"A": {"w_l1_mean": 0.0662, "conf": 1.111}}})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert [d["path"] for d in res["setup_diffs"]] == ["arms.A.conf"]

    out = _run(a, b).stdout
    assert out.index("conf") < out.index("w_l1_mean"), "설정 차이가 값 차이에 묻혔다"


def test_a_pure_value_difference_is_not_called_a_setup_difference(tmp_path):
    """★짝★ 없으면 "전부 설정 차이" 구현으로도 통과한다."""
    a = _write(tmp_path, "a.json", {"arms": {"A": {"conf": 25.0, "mdd_pct": -23.16}}})
    b = _write(tmp_path, "b.json", {"arms": {"A": {"conf": 25.0, "mdd_pct": -25.90}}})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL
    assert res["setup_diffs"] == []
    assert "설정이 다릅니다" not in _run(a, b).stdout


def test_the_setup_list_only_changes_emphasis_never_the_verdict(tmp_path, monkeypatch):
    """★손 목록에 가드의 이빨을 걸지 않는다★

    `RUN_DEFINING` 을 비워도 판정은 `material`, 종료코드는 1 이어야 한다 —
    목록은 **무엇을 먼저 보여줄지**만 정한다.
    """
    monkeypatch.setattr(gc, "RUN_DEFINING", frozenset())
    a = _write(tmp_path, "a.json", {"conf": 25.0})
    b = _write(tmp_path, "b.json", {"conf": 1.111})
    res = gc.compare_files(a, b)
    assert res["verdict"] == gc.MATERIAL and res["setup_diffs"] == []


# ══════════════════════════════════════════════════════════════════════════
# G9 ★지문 — 기계에 관한 것이지 자격증명이 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_fingerprint_names_the_machine(monkeypatch):
    monkeypatch.setenv("OPENBLAS_CORETYPE", "NEHALEM")
    fp = gc.fingerprint()
    assert fp["numpy"] and fp["python"]
    assert fp["openblas_coretype"] == "NEHALEM"
    assert "cpu" in fp


def test_the_fingerprint_never_carries_secrets(monkeypatch):
    """★안전 계약★ 지문이 리포트·이슈로 나가므로 키가 실리면 그대로 샌다."""
    monkeypatch.setenv("KIS_APP_SECRET", "SECRET-VALUE-SHOULD-NOT-APPEAR")
    monkeypatch.setenv("DART_API_KEY", "ANOTHER-SECRET-VALUE")
    monkeypatch.setenv("BOK_API_KEY", "THIRD-SECRET-VALUE")
    blob = json.dumps(gc.fingerprint(), ensure_ascii=False)
    for leaked in ("SECRET-VALUE-SHOULD-NOT-APPEAR", "ANOTHER-SECRET-VALUE",
                   "THIRD-SECRET-VALUE"):
        assert leaked not in blob, "지문이 비밀을 실어 날랐다"
    assert "KIS_APP_SECRET" not in blob and "DART_API_KEY" not in blob


def test_the_fingerprint_cli_prints_json():
    proc = _run("--fingerprint")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["python"]


# ══════════════════════════════════════════════════════════════════════════
# 사용 오류도 조용하지 않다
# ══════════════════════════════════════════════════════════════════════════
def test_a_missing_file_fails_loudly(tmp_path):
    a = _write(tmp_path, "a.json", {"x": 1.0})
    proc = _run(a, str(tmp_path / "nope.json"))
    assert proc.returncode == gc.EXIT_MATERIAL
    assert "nope.json" in (proc.stdout + proc.stderr)
