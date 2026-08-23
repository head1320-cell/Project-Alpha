"""
Screener Presets — Milestone 4
==========================================================================
거장 전략 + 국면 최적화 프리셋을 FilterGroup(AST) 형태로 정의.

카테고리:
  · master  — 투자 거장 전략 (그레이엄, 그린블라트, 버핏, 린치)
  · regime  — 매크로 국면별 최적화
  · theme   — 테마 (딥밸류, 고배당, 퀄리티)

각 프리셋은 M1 FilterGroup 구조를 그대로 사용 → run-advanced로 즉시 실행.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# Preset Definitions (FilterGroup AST)
# ═══════════════════════════════════════════════════════════════════════════════

SCREENER_PRESETS: dict[str, dict] = {
    # ─── 거장 전략 ─────────────────────────────────────────────────
    "graham_value": {
        "name": "그레이엄 가치주",
        "master": "벤저민 그레이엄",
        "category": "master",
        "icon": "🎩",
        "description": "안전마진 중시 — 저PBR·저PER·낮은 부채. 가치투자의 아버지가 정립한 방어적 종목 선별.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "pbr", "op": "lt", "value": 1.5},
                {"field": "per", "op": "lt", "value": 15},
                {"field": "debt_ratio_pct", "op": "lt", "value": 100},
            ],
            "groups": [],
        },
    },
    "magic_formula": {
        "name": "마법공식",
        "master": "조엘 그린블라트",
        "category": "master",
        "icon": "✨",
        "description": "높은 자본수익률 + 저평가의 결합. ROE 상위 + 괴리율(이익수익률 대용) 상위를 교집합.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "roe_pct", "rank_mode": "top_pct", "rank_value": 30},
                {"field": "gap_score", "rank_mode": "top_pct", "rank_value": 30},
            ],
            "groups": [],
        },
    },
    "buffett_quality": {
        "name": "버핏 퀄리티",
        "master": "워런 버핏",
        "category": "master",
        "icon": "🏰",
        "description": "경제적 해자 — 높은 ROE, 낮은 부채, 잉여현금흐름 흑자. 장기 우량 기업 선별.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "roe_pct", "op": "gte", "value": 15},
                {"field": "debt_ratio_pct", "op": "lt", "value": 50},
                {"field": "fcf_억", "op": "gt", "value": 0},
            ],
            "groups": [],
        },
    },
    "lynch_garp": {
        "name": "린치 GARP",
        "master": "피터 린치",
        "category": "master",
        "icon": "📈",
        "description": "성장 대비 합리적 가격 — 적정 PER에 높은 수익성. 성장과 가치의 균형.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "per", "op": "between", "value": 5, "value2": 20},
                {"field": "roe_pct", "rank_mode": "top_pct", "rank_value": 40},
            ],
            "groups": [],
        },
    },

    # ─── 국면 최적화 ─────────────────────────────────────────────────
    "goldilocks_growth": {
        "name": "골디락스 성장주",
        "master": "국면 최적화",
        "category": "regime",
        "icon": "🌤️",
        "description": "성장↑·물가↓ 환경 최적 — 높은 ROE·종합점수. 위험자산 선호 국면용.",
        "use_macro": True,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "roe_pct", "rank_mode": "top_pct", "rank_value": 30},
                {"field": "composite_score", "op": "gte", "value": 60},
            ],
            "groups": [],
        },
    },
    "stagflation_defense": {
        "name": "스태그플레이션 방어",
        "master": "국면 최적화",
        "category": "regime",
        "icon": "🛡️",
        "description": "성장↓·물가↑ 환경 방어 — 고배당·저부채·현금흐름 흑자. 위기 방어 국면용.",
        "use_macro": True,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "dividend_yield_pct", "rank_mode": "top_pct", "rank_value": 30},
                {"field": "debt_ratio_pct", "op": "lt", "value": 100},
                {"field": "fcf_억", "op": "gt", "value": 0},
            ],
            "groups": [],
        },
    },

    # ─── 테마 ─────────────────────────────────────────────────────
    "deep_value": {
        "name": "딥 밸류",
        "master": "테마",
        "category": "theme",
        "icon": "💎",
        "description": "극단적 저평가 — PBR<1, 저PER, 큰 괴리율. 역발상 가치 종목.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "pbr", "op": "lt", "value": 1.0},
                {"field": "per", "op": "lt", "value": 8},
                {"field": "gap_pct", "op": "lt", "value": -20},
            ],
            "groups": [],
        },
    },
    "dividend_aristocrat": {
        "name": "배당 귀족주",
        "master": "테마",
        "category": "theme",
        "icon": "👑",
        "description": "고배당 + 재무 안정 — 배당수익률 상위·낮은 부채·현금흐름 흑자.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "dividend_yield_pct", "rank_mode": "top_pct", "rank_value": 20},
                {"field": "debt_ratio_pct", "op": "lt", "value": 100},
                {"field": "fcf_억", "op": "gt", "value": 0},
            ],
            "groups": [],
        },
    },
    "quality_compounder": {
        "name": "퀄리티 컴파운더",
        "master": "테마",
        "category": "theme",
        "icon": "⚙️",
        "description": "지속 복리 성장 — 높은 ROE·ROA, 낮은 부채, 종합점수 상위.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "roe_pct", "op": "gte", "value": 12},
                {"field": "roa_pct", "op": "gte", "value": 6},
                {"field": "composite_score", "rank_mode": "top_pct", "rank_value": 40},
            ],
            "groups": [],
        },
    },
    # ─── V3 고급 전략 (신규 kind 활용) ─────────────────────────────
    "v3_contrarian_insider": {
        "name": "역발상 내부자 매수",
        "master": "행동재무 (V3)",
        "category": "v3_advanced",
        "icon": "🧠",
        "description": "내부자는 사들이는데 개인이 투매하는 종목 — 정보 비대칭 역발상. 저부채 필터로 안정성 확보.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"kind": "behavioral", "field": "__b__", "behavior_signal": "insider_buy_retail_sell"},
                {"field": "debt_ratio_pct", "op": "lt", "value": 150},
            ],
            "groups": [],
        },
    },
    "v3_historical_value": {
        "name": "역사적 저평가 반등",
        "master": "Mean Reversion (V3)",
        "category": "v3_advanced",
        "icon": "📉",
        "description": "PER이 자기 과거 평균 대비 저평가(-1σ↓) + 선행 EPS 추정 상향. 시계열 Z-Score 기반.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"kind": "z_score", "field": "__z__", "z_field": "per", "z_window": 20, "op": "lt", "value": -1.0},
                {"kind": "estimate", "field": "__e__", "estimate_field": "fwd_eps_1m_chg", "op": "gt", "value": 0},
            ],
            "groups": [],
        },
    },
    "v3_quality_sentiment": {
        "name": "우량주 + 긍정 센티먼트",
        "master": "AI 센티먼트 (V3)",
        "category": "v3_advanced",
        "icon": "💬",
        "description": "고ROE 우량주 중 뉴스 센티먼트가 긍정인 종목. 정성적 맥락 필터 결합.",
        "use_macro": False,
        "filter_ast": {
            "logic": "AND",
            "conditions": [
                {"field": "roe_pct", "rank_mode": "top_pct", "rank_value": 30},
                {"kind": "sentiment", "field": "__s__", "sentiment_source": "news_score", "op": "gt", "value": 0.2},
            ],
            "groups": [],
        },
    },
    # ─── 학술 논문 팩터 전략 (Fundamental Factor Library) ──────────
    "ffl_magic_formula": {
        "name": "마법공식 (정량)",
        "master": "Joel Greenblatt",
        "category": "factor_academic",
        "icon": "✨",
        "description": "이익수익률(Earnings Yield) + 자본수익률(ROIC) 결합. 좋은 기업을 싼 가격에.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "earnings_yield", "op": "gt", "value": 8},
            {"field": "roic", "op": "gt", "value": 12},
        ], "groups": []},
    },
    "ffl_novy_marx": {
        "name": "노비-마르크스 퀄리티",
        "master": "Novy-Marx (2013)",
        "category": "factor_academic",
        "icon": "💎",
        "description": "GP/A(매출총이익/자산)가 높은 진짜 우량주. 'The Other Side of Value'의 핵심 팩터.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "gp_to_assets", "op": "gt", "value": 0.33},
            {"field": "debt_to_equity", "op": "lt", "value": 1.5},
        ], "groups": []},
    },
    "ffl_piotroski": {
        "name": "피오트로스키 F-Score",
        "master": "Piotroski (2000)",
        "category": "factor_academic",
        "icon": "🎯",
        "description": "재무건전성 9점 만점 중 7점 이상 + 저PBR. 가치주 중 재무 우량 종목 선별.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "piotroski_f", "op": "gte", "value": 7},
            {"field": "pbr", "op": "lt", "value": 1.5},
        ], "groups": []},
    },
    "ffl_acquirers_multiple": {
        "name": "인수자의 배수",
        "master": "Tobias Carlisle (2014)",
        "category": "factor_academic",
        "icon": "🏦",
        "description": "EV/EBIT가 낮은 저평가주. 사모펀드가 기업 인수 시 보는 핵심 지표.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "acquirers_multiple", "op": "lt", "value": 8},
            {"field": "altman_z", "op": "gt", "value": 2.5},
        ], "groups": []},
    },
    "ffl_qmj": {
        "name": "퀄리티 마이너스 정크 (QMJ)",
        "master": "Asness / AQR (2019)",
        "category": "factor_academic",
        "icon": "👑",
        "description": "수익성·성장·안전·배당을 종합한 고품질 종목. AQR의 대표 퀄리티 전략.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "qmj_score", "op": "gt", "value": 65},
            {"field": "gp_to_assets", "op": "gt", "value": 0.25},
        ], "groups": []},
    },
    "ffl_shareholder_yield": {
        "name": "주주환원 수익률",
        "master": "Meb Faber (2013)",
        "category": "factor_academic",
        "icon": "💰",
        "description": "배당 + 자사주매입 수익률이 높은 주주친화 기업. 'Shareholder Yield'.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "shareholder_yield", "op": "gt", "value": 4},
            {"field": "fcf_yield", "op": "gt", "value": 5},
        ], "groups": []},
    },
    "ffl_garp": {
        "name": "GARP (성장+가치)",
        "master": "Peter Lynch",
        "category": "factor_academic",
        "icon": "📈",
        "description": "합리적 가격의 성장주 — PEG 낮고 EPS 성장 견조. 린치의 대표 전략.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "eps_growth_yoy", "op": "gt", "value": 15},
            {"field": "roe_pct", "op": "gt", "value": 12},
            {"field": "per", "op": "lt", "value": 25},
        ], "groups": []},
    },
    "ffl_fortress_quality": {
        "name": "철벽 우량주",
        "master": "복합 (안전+수익)",
        "category": "factor_academic",
        "icon": "🛡️",
        "description": "Altman 안전 + 분식 무위험(Beneish) + 높은 이자보상배율. 재무 리스크 최소.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "altman_z", "op": "gt", "value": 3.0},
            {"field": "beneish_m", "op": "lt", "value": -2.22},
            {"field": "current_ratio", "op": "gt", "value": 150},
        ], "groups": []},
    },
    "ffl_high_quality_compounder": {
        "name": "고퀄리티 컴파운더",
        "master": "복합 (퀄리티+성장)",
        "category": "factor_academic",
        "icon": "🚀",
        "description": "높은 ROIC + 매출 성장 + 낮은 발생액(이익의 질). 장기 복리 성장 후보.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "roic", "op": "gt", "value": 15},
            {"field": "revenue_growth_yoy", "op": "gt", "value": 10},
            {"field": "accruals", "op": "lt", "value": 5},
        ], "groups": []},
    },
    "ffl_deep_value": {
        "name": "딥 밸류",
        "master": "복합 (저평가 다중)",
        "category": "factor_academic",
        "icon": "🔍",
        "description": "EV/EBITDA·PSR·PBR 모두 낮은 극저평가주. 다중 밸류 지표 교집합.",
        "use_macro": False,
        "filter_ast": {"logic": "AND", "conditions": [
            {"field": "ev_ebitda", "op": "lt", "value": 7},
            {"field": "psr", "op": "lt", "value": 1.0},
            {"field": "pbr", "op": "lt", "value": 1.0},
        ], "groups": []},
    },
}



CATEGORY_LABELS = {
    "master": "투자 거장",
    "regime": "국면 최적화",
    "theme":  "테마 전략",
}


def list_presets() -> dict:
    """프리셋 카탈로그 (카테고리별 그룹)."""
    by_cat: dict[str, list] = {}
    for pid, p in SCREENER_PRESETS.items():
        item = {
            "id": pid,
            "name": p["name"],
            "master": p["master"],
            "category": p["category"],
            "icon": p["icon"],
            "description": p["description"],
            "use_macro": p.get("use_macro", False),
            "condition_count": _count_conditions(p["filter_ast"]),
        }
        by_cat.setdefault(p["category"], []).append(item)

    return {
        "categories": [
            {"id": cat, "label": CATEGORY_LABELS.get(cat, cat), "presets": items}
            for cat, items in by_cat.items()
        ],
        "total": len(SCREENER_PRESETS),
    }


def get_preset(preset_id: str) -> dict | None:
    return SCREENER_PRESETS.get(preset_id)


def _count_conditions(ast: dict) -> int:
    n = len(ast.get("conditions", []))
    for g in ast.get("groups", []):
        n += _count_conditions(g)
    return n
