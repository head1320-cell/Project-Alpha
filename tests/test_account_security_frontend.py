"""BS1 — 화면이 미리 보이는 비밀번호 규칙이 서버 규칙과 갈라지지 않는다.

판정은 서버(`src/domain/password_policy.py`)가 하지만, 화면(`frontend/src/features/settings/passwordRules.ts`)이
다른 목록을 들고 있으면 "화면은 초록인데 서버가 거절" 이 생긴다. 수와 목록을 소스에서 읽어 맞춰 본다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.domain import password_policy as pp

_TS = Path(__file__).resolve().parents[1] / "frontend/src/features/settings/passwordRules.ts"


def _ts() -> str:
    return _TS.read_text(encoding="utf-8")


def test_known_defaults_are_the_same_list():
    m = re.search(r"KNOWN_DEFAULTS\s*=\s*(\[[^\]]*\])", _ts())
    assert m, "passwordRules.ts 에 KNOWN_DEFAULTS 가 없다"
    assert json.loads(m.group(1)) == list(pp.KNOWN_DEFAULTS)


def test_length_limits_are_the_same():
    src = _ts()
    assert re.search(rf"MIN_LENGTH\s*=\s*{pp.MIN_LENGTH}\b", src)
    assert re.search(rf"MAX_BYTES\s*=\s*{pp.MAX_BYTES}\b", src)


def test_a_drifted_list_would_be_caught(monkeypatch):
    """짝 — 목록이 달라지면 위 비교가 실패한다(항상-통과 배제)."""
    monkeypatch.setattr(pp, "KNOWN_DEFAULTS", ("frm123!", "temp"))
    m = re.search(r"KNOWN_DEFAULTS\s*=\s*(\[[^\]]*\])", _ts())
    assert json.loads(m.group(1)) != list(pp.KNOWN_DEFAULTS)
