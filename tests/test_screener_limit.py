"""스크리너 결과 상한 — 전종목(all_listed ~2,900) 유니버스를 다 돌려주도록 상한 확대."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src.api.screener_routes import AdvancedRunRequest  # noqa: E402

_AST = {"logic": "AND", "conditions": [], "groups": []}


def test_limit_accepts_full_universe():
    # 전종목(~2,900) 대응 — 1000 초과도 허용
    assert AdvancedRunRequest(universe="all_listed", filter_ast=_AST, limit=3000).limit == 3000


def test_limit_rejects_over_cap():
    with pytest.raises(ValidationError):
        AdvancedRunRequest(universe="all_listed", filter_ast=_AST, limit=5000)
