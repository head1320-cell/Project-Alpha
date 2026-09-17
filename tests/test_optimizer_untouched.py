"""AD — ★최적화기를 건드리지 않았다는 사실을 못 박는다★.

로드맵은 *"계좌별 제약을 `Constraints` 로 옮긴다"* 고 적었지만 이번 작업은 **관측만**
한다(사용자 결정, 2026-09-13). CLAUDE.md §3 은 최적화기 의미·`constrained_solve`·
배분 결정 경로 변경을 ★별도 승인 사항★ 으로 못 박았다.

의도는 문서에 적히지만 ★코드가 조용히 흘러가는 것은 문서가 막지 못한다★ — 그래서
골든으로 고정한다. 이 테스트가 빨개지면 둘 중 하나다: 승인받은 변경을 했거나(골든을
함께 고친다), 승인 없이 경계를 넘었거나(되돌린다).
"""
from __future__ import annotations

import dataclasses
import hashlib
import pathlib

from src.engine.constrained_opt import Constraints

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_OPTIMIZER = _ROOT / "src" / "engine" / "constrained_opt.py"

#: AD 착수 시점(커밋 8e3e1b8)의 해시. ★수치가 아니라 경계다.★
_GOLDEN_SHA256 = "97a3b73e31fdc3e52956b36bc1b458c2287f7009406a5a561b3ef168fd63c401"

#: `Constraints` 의 필드 집합. 계좌 제약이 섞여 들어오면 달라진다.
_GOLDEN_FIELDS = frozenset({
    "max_weight_pct", "min_weight_pct", "group_caps_pct", "turnover_cap_pct",
    "beta_min", "beta_max", "cash_min_pct", "cash_max_pct",
    "gross_max_pct", "net_min_pct", "net_max_pct",
})


def test_the_optimizer_source_is_unchanged():
    """★파일 전체 골든★ — 한 줄이라도 바뀌면 실패한다."""
    actual = hashlib.sha256(_OPTIMIZER.read_bytes()).hexdigest()
    assert actual == _GOLDEN_SHA256, (
        "constrained_opt.py 가 바뀌었다 — CLAUDE.md §3 의 별도 승인 사항이다. "
        "승인받은 변경이라면 이 골든을 함께 갱신할 것."
    )


def test_the_constraints_fields_are_unchanged():
    """해시보다 의미에 가까운 검사 — 계좌 필드가 섞여 들어오면 잡힌다."""
    actual = frozenset(f.name for f in dataclasses.fields(Constraints))
    assert actual == _GOLDEN_FIELDS, (
        f"Constraints 의 필드가 바뀌었다: 추가 {sorted(actual - _GOLDEN_FIELDS)} · "
        f"삭제 {sorted(_GOLDEN_FIELDS - actual)}")


def test_no_account_vocabulary_leaked_into_the_optimizer():
    """★어휘가 새는 것도 경계 침범이다★ — 필드명이 아니어도 개념이 들어오면 잡는다."""
    src = _OPTIMIZER.read_text(encoding="utf-8")
    for word in ("account_policy", "InvestorProfile", "irp", "pension_savings",
                 "risky_asset", "account_type"):
        assert word not in src, f"최적화기에 계좌 어휘 {word!r} 가 들어왔다"


def test_the_account_layer_does_not_import_the_optimizer():
    """반대 방향도 막는다 — 판정 계층이 최적화기를 부르면 '관측만' 이 아니게 된다."""
    import ast

    for rel in ("src/domain/account_policy.py", "src/engine/risky_share.py",
                "src/api/account_policy_routes.py"):
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for name in names:
            assert "constrained_opt" not in name, f"{rel} 이 최적화기를 import 한다"


def test_the_golden_would_catch_a_change():
    """★테스트의 테스트★ — 해시가 실제로 내용에 반응하는지."""
    original = _OPTIMIZER.read_bytes()
    mutated = original + b"\n# mutation\n"
    assert hashlib.sha256(mutated).hexdigest() != _GOLDEN_SHA256
