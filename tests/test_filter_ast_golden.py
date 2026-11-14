"""AW0 · ★골든 스냅샷 — 구조를 건드리기 전에 현 상태를 못 박는다★
==============================================================================
대상: `src/engine/filter_ast.py` 의 `FIELD_CATALOG` · `FIELD_BY_ID` ·
`fields_catalog()`

## 왜 이 파일이 먼저인가

CLAUDE.md §6 은 스크리너 3-레이어와 `filter_ast.FIELD_BY_ID` 를 ★리팩터링
대상이 아니라고★ 못 박는다. AW 는 맨손 리터럴 12개를 스토어로 옮기는데,
그것은 **구조 변경**이다. 그래서 옮기기 **전에** 관측 가능한 모양을 떠내
두고, 옮긴 뒤에도 이 파일이 그대로 통과하는 것으로 ★아무것도 변하지 않았다★
를 증명한다.

## ★값을 손으로 적지 않았다★

아래 `GOLDEN` 은 변경 전 상태에서 **기계로 떠낸** 것이다. 손으로 적으면
적는 사람이 본 것을 적게 되고, 그것은 스냅샷이 아니라 소망이다.

## ★이 파일이 재지 않는 것★

- **필드가 옳은지 재지 않는다.** `per` 의 상한이 50 인 것이 맞는지는 다른
  질문이고, 여기서는 ★그 값이 **변하지 않았는지**★만 본다.
- **새 칸을 막지 않는다.** `origin`·`literature` 처럼 **늘어나는** 것은
  허용이고, 기존 일곱 칸의 값이 바뀌거나 키·순서가 달라지는 것이 금지다.
"""
from __future__ import annotations

import src.engine.filter_ast as fa

#: ★AW0 에서 뽑은 실측값★ — 손으로 적은 것이 아니라 당시 상태를 떠낸 것이다.
_ATTRS = ('id', 'label', 'category', 'unit', 'higher_better', 'typical_min', 'typical_max')

GOLDEN: tuple[tuple, ...] = (
    ('per', 'PER', 'valuation', '배', False, 0, 50),
    ('pbr', 'PBR', 'valuation', '배', False, 0, 10),
    ('gap_pct', '괴리율', 'valuation', '%', False, -80, 80),
    ('intrinsic_value', '적정가', 'valuation', '원', True, 0, 1000000),
    ('roe_pct', 'ROE', 'profitability', '%', True, -10, 40),
    ('roa_pct', 'ROA', 'profitability', '%', True, -10, 25),
    ('dividend_yield_pct', '배당수익률', 'dividend', '%', True, 0, 10),
    ('debt_ratio_pct', '부채비율', 'stability', '%', False, 0, 300),
    ('fcf_억', '잉여현금흐름', 'stability', '억', True, -5000, 50000),
    ('market_cap_억', '시가총액', 'size', '억', True, 0, 5000000),
    ('composite_score', '종합 점수', 'score', '점', True, 0, 100),
    ('gap_score', '저평가 점수', 'score', '점', True, 0, 100),
    ('roe_score', '수익성 점수', 'score', '점', True, 0, 100),
    ('stability_score', '안정성 점수', 'score', '점', True, 0, 100),
    ('operating_margin', '영업이익률', 'quality', '%', True, -10, 35),
    ('net_margin', '순이익률', 'quality', '%', True, -10, 30),
    ('gross_margin', '매출총이익률', 'quality', '%', True, 0, 70),
    ('gp_to_assets', 'GP/A', 'quality', '', True, 0, 1.2),
    ('roic', 'ROIC', 'quality', '%', True, -10, 40),
    ('asset_turnover', '자산회전율', 'quality', '회', True, 0, 3),
    ('equity_multiplier', '재무레버리지', 'quality', '배', False, 1, 5),
    ('fcf_margin', 'FCF 마진', 'quality', '%', True, -10, 30),
    ('ev_ebitda', 'EV/EBITDA', 'valuation', '배', False, 0, 30),
    ('ev_sales', 'EV/Sales', 'valuation', '배', False, 0, 10),
    ('ev_fcf', 'EV/FCF', 'valuation', '배', False, 0, 50),
    ('psr', 'PSR', 'valuation', '배', False, 0, 10),
    ('pcr', 'PCR', 'valuation', '배', False, 0, 30),
    ('peg', 'PEG', 'valuation', '배', False, 0, 5),
    ('fcf_yield', 'FCF 수익률', 'valuation', '%', True, -5, 20),
    ('earnings_yield', '이익수익률', 'valuation', '%', True, -5, 25),
    ('acquirers_multiple', "Acquirer's Multiple", 'valuation', '배', False, 0, 30),
    ('shareholder_yield', '주주환원수익률', 'valuation', '%', True, -5, 15),
    ('revenue_growth_yoy', '매출성장률(YoY)', 'growth', '%', True, -30, 50),
    ('op_growth_yoy', '영업이익성장률(YoY)', 'growth', '%', True, -50, 80),
    ('eps_growth_yoy', 'EPS성장률(YoY)', 'growth', '%', True, -50, 80),
    ('revenue_cagr_3y', '매출 CAGR(3년)', 'growth', '%', True, -20, 40),
    ('eps_cagr_3y', 'EPS CAGR(3년)', 'growth', '%', True, -20, 50),
    ('price_momentum_12_1', '12-1 모멘텀', 'growth', '%', True, -40, 60),
    ('pead_score', 'PEAD 점수', 'growth', '', True, -3, 3),
    ('altman_z', 'Altman Z-Score', 'safety', '', True, 0, 8),
    ('beneish_m', 'Beneish M-Score', 'safety', '', False, -4, 0),
    ('current_ratio', '유동비율', 'safety', '%', True, 0, 400),
    ('quick_ratio', '당좌비율', 'safety', '%', True, 0, 300),
    ('interest_coverage', '이자보상배율', 'safety', '배', True, -5, 30),
    ('accruals', '발생액 비율', 'safety', '%', False, -20, 20),
    ('debt_to_equity', '부채자본비율', 'safety', '배', False, 0, 3),
    ('piotroski_f', 'F-Score', 'composite', '점', True, 0, 9),
    ('qmj_score', 'QMJ 점수', 'composite', '점', True, 0, 100),
    ('magic_formula_rank', 'Magic Formula 순위', 'composite', '위', False, 1, 200),
    ('roe', 'ROE', 'quality', '%', True, -10, 40),
    ('roa', 'ROA', 'quality', '%', True, -5, 25),
    ('roe_dupont', 'ROE(듀폰)', 'quality', '%', True, -10, 40),
    ('ebitda_margin', 'EBITDA 마진', 'quality', '%', True, -5, 45),
    ('ocf_to_ni', '이익의 질', 'quality', '배', True, 0, 3),
    ('cash_conversion', '현금전환율', 'quality', '배', True, 0, 2),
    ('rnd_intensity', 'R&D 집약도', 'quality', '%', True, 0, 15),
    ('sga_to_revenue', '판관비율', 'quality', '%', False, 0, 35),
    ('capex_intensity', '설비투자 집약도', 'quality', '%', False, 0, 20),
    ('ev_ic', 'EV/투하자본', 'valuation', '배', False, 0, 20),
    ('dividend_yield', '배당수익률', 'valuation', '%', True, 0, 12),
    ('payout_ratio', '배당성향', 'valuation', '%', True, 0, 100),
    ('bps', 'BPS', 'valuation', '원', True, 0, 500000),
    ('book_to_market', '장부/시장', 'valuation', '배', True, 0, 3),
    ('ncav_to_mcap', 'NCAV/시총', 'valuation', '배', True, -1, 2),
    ('revenue_qoq', '매출성장률(QoQ)', 'growth', '%', True, -30, 40),
    ('growth_acceleration', '성장 가속도', 'growth', '%p', True, -30, 30),
    ('sustainable_growth', '지속가능성장률', 'growth', '%', True, -10, 35),
    ('fcf_growth', 'FCF 성장률', 'growth', '%', True, -40, 60),
    ('net_debt_to_ebitda', '순부채/EBITDA', 'safety', '배', False, -2, 8),
    ('cash_ratio', '현금비율', 'safety', '%', True, 0, 150),
    ('equity_ratio', '자기자본비율', 'safety', '%', True, 0, 90),
    ('sloan_accruals', 'Sloan 발생액', 'safety', '%', False, -20, 20),
    ('debt_to_assets', '부채/자산', 'safety', '배', False, 0, 1),
    ('graham_number', '그레이엄 넘버', 'composite', '원', True, 0, 500000),
    ('greenblatt_score', 'Greenblatt 점수', 'composite', '점', True, 0, 100),
    ('value_composite', '가치 종합점수', 'composite', '점', True, 0, 100),
    ('return_1m', '1개월 수익률', 'momentum', '%', True, -30, 30),
    ('return_3m', '3개월 수익률', 'momentum', '%', True, -40, 40),
    ('return_6m', '6개월 수익률', 'momentum', '%', True, -50, 60),
    ('return_12m', '12개월 수익률', 'momentum', '%', True, -50, 80),
    ('momentum_12_1', '12-1 모멘텀', 'momentum', '%', True, -40, 60),
    ('momentum_6_1', '6-1 모멘텀', 'momentum', '%', True, -40, 50),
    ('volatility_20d', '20일 변동성', 'volatility', '%', False, 5, 80),
    ('volatility_60d', '60일 변동성', 'volatility', '%', False, 5, 70),
    ('beta_1y', '베타(1년)', 'volatility', '', False, 0, 2.5),
    ('max_drawdown_1y', '최대낙폭(1년)', 'volatility', '%', False, 0, 70),
    ('downside_vol', '하방변동성', 'volatility', '%', False, 3, 50),
    ('skewness', '수익률 왜도', 'volatility', '', True, -2, 2),
    ('price_to_52w_high', '52주 고가 대비', 'technical', '%', True, 30, 100),
    ('price_to_52w_low', '52주 저가 대비', 'technical', '%', True, 100, 400),
    ('dist_ma20', '20일선 이격도', 'technical', '%', True, -20, 20),
    ('dist_ma60', '60일선 이격도', 'technical', '%', True, -25, 25),
    ('dist_ma120', '120일선 이격도', 'technical', '%', True, -30, 30),
    ('rsi_14', 'RSI(14)', 'technical', '', True, 0, 100),
    ('ma_alignment', '이평 정배열', 'technical', '점', True, 0, 3),
    ('volume_trend_20d', '거래량 추세', 'volume', '%', True, -50, 100),
    ('turnover_rate', '거래회전율', 'volume', '%', True, 0, 15),
    ('amount_20d_avg', '20일 평균거래대금', 'volume', '억', True, 0, 5000),
    ('volume_spike', '거래량 급증', 'volume', '배', True, 0, 5),
    ('price_volume_corr', '가격-거래량 상관', 'volume', '', True, -1, 1),
    ('foreign_net_5d', '외국인 5일 순매수', 'supply', '억', True, -500, 500),
    ('foreign_net_20d', '외국인 20일 순매수', 'supply', '억', True, -2000, 2000),
    ('inst_net_5d', '기관 5일 순매수', 'supply', '억', True, -500, 500),
    ('inst_net_20d', '기관 20일 순매수', 'supply', '억', True, -2000, 2000),
    ('retail_net_5d', '개인 5일 순매수', 'supply', '억', False, -500, 500),
    ('retail_net_20d', '개인 20일 순매수', 'supply', '억', False, -2000, 2000),
    ('insider_net_20d', '내부자 20일 순매수', 'supply', '억', True, -300, 300),
    ('dps', '주당배당금', 'dividend', '원', True, 0, 5000),
    ('treasury_ratio', '자사주보유비율', 'dividend', '%', True, 0, 20),
    ('foreign_ownership', '외국인지분율', 'ownership', '%', True, 0, 60),
    ('div_count', '배당횟수', 'dividend', '회', True, 0, 4),
    ('div_at_record', '배당시점배당수익률', 'dividend', '%', True, 0, 8),
    ('div_total_growth', '배당금총액증가율', 'dividend', '%', True, -30, 50),
    ('fcf_payout', 'FCF배당성향', 'dividend', '%', True, 0, 100),
    ('treasury_cancel_cnt', '자사주소각횟수', 'dividend', '회', True, 0, 3),
    ('treasury_cancel_ratio', '자사주소각비율', 'dividend', '%', True, 0, 10),
    ('employees', '직원수', 'business', '명', True, 50, 50000),
    ('emp_growth', '직원수증가율', 'business', '%', True, -20, 30),
    ('male_emp', '남자직원수', 'business', '명', True, 30, 35000),
    ('female_emp', '여자직원수', 'business', '명', True, 10, 20000),
    ('female_ratio', '여자직원비율', 'business', '%', True, 5, 70),
    ('avg_salary', '평균급여', 'business', '백만원', True, 30, 150),
    ('avg_salary_growth', '평균급여증가율', 'business', '%', True, -10, 25),
    ('salary_total', '직원급여총액', 'business', '억', True, 50, 50000),
    ('rev_per_emp', '1인당매출액', 'business', '백만원', True, 100, 3000),
    ('op_per_emp', '1인당영업이익', 'business', '백만원', True, -100, 500),
    ('executives', '임원수', 'business', '명', True, 3, 20),
    ('exec_avg_salary', '임원평균급여', 'business', '백만원', True, 100, 2000),
    ('exec_salary_growth', '임원급여총액증가율', 'business', '%', True, -20, 40),
    ('order_backlog', '수주잔고', 'business', '억', True, 0, 100000),
    ('order_backlog_growth', '수주잔고증가율', 'business', '%', True, -40, 60),
    ('major_holder', '대주주지분율', 'business', '%', True, 5, 75),
    ('minority_cnt', '소액주주수', 'business', '명', True, 1000, 800000),
    ('minority_ratio', '소액주주지분율', 'business', '%', True, 10, 80),
    ('pref_shares', '우선주발행', 'business', '만주', True, 0, 5000),
    ('insider_buy', '장내매수', 'business', '주', True, 0, 1000000),
    ('insider_sell', '장내매도', 'business', '주', False, 0, 1000000),
    ('tangible_ratio', '유형자산비중', 'financials', '%', True, 10, 80),
    ('intangible_ratio', '무형자산비중', 'financials', '%', True, 0, 30),
    ('net_fin_asset', '시총대비순금융자산비율', 'financials', '%', True, -50, 60),
    ('capex_amt', '자본지출(CAPEX)', 'financials', '억', False, 0, 100000),
    ('cogs_ratio', '매출원가율', 'fundamental', '%', False, 30, 95),
    ('gp_growth', '매출총이익성장율', 'fundamental', '%', True, -30, 50),
    ('inv_growth', '재고자산증가율', 'fundamental', '%', False, -30, 50),
    ('recv_growth', '매출채권증가율', 'fundamental', '%', False, -30, 50),
    ('payable_growth', '매입채무증가율', 'fundamental', '%', True, -30, 50),
    ('recv_turnover', '매출채권회전율', 'fundamental', '회', True, 2, 20),
    ('inv_turnover', '재고자산회전율', 'fundamental', '회', True, 2, 30),
    ('ccc', '현금회전일수', 'fundamental', '일', False, -30, 200),
    ('por', 'POR', 'valuation', '배', False, 1, 50),
    ('bps_growth', '주당순자산증가율', 'valuation', '%', True, -20, 40),
    ('return_1y', '주가변동률1년', 'stock', '%', True, -50, 80),
    ('investor_return', '투자자주가수익률', 'stock', '%', True, -50, 80),
    ('total_return', '총수익률', 'stock', '%', True, -50, 85),
    ('amount_growth', '거래대금증가율', 'stock', '%', True, -50, 100),
    ('earnings_recency', '실적발표일', 'ir', '일', False, 0, 180),
    ('ir_count', '기업설명회횟수', 'ir', '회', True, 0, 12),
)


def _current() -> tuple[tuple, ...]:
    return tuple(tuple(getattr(m, n) for n in _ATTRS)
                 for m in fa.FIELD_BY_ID.values())


def test_the_existing_attributes_are_still_there():
    """★새 칸은 늘어도 되지만 기존 칸은 사라질 수 없다★"""
    from dataclasses import fields as dfields

    names = [f.name for f in dfields(fa.FieldMeta)]
    assert names[:len(_ATTRS)] == list(_ATTRS), (
        "기존 칸의 **순서**가 바뀌면 위치인자 생성 17곳이 조용히 어긋난다")


def test_the_field_ids_and_their_order_are_unchanged():
    """★키와 순서★ — 리터럴을 스토어로 옮겨도 여기가 흔들리면 안 된다."""
    assert [row[0] for row in _current()] == [row[0] for row in GOLDEN]


def test_every_field_keeps_every_value():
    """★일곱 속성값 전부★ — 옮기다 오타 하나 나도 여기서 죽는다."""
    assert _current() == GOLDEN


def test_the_catalog_and_the_index_agree():
    """★두 읽기 경로가 갈라지지 않는다★

    `source_registry` 가 `_BY_KEY` 를 `_SPECS` 에서 파생시키는 이유를 적어
    두었다 — 따로 만들면 한쪽만 고쳐도 아무 테스트가 깨지지 않는다.
    """
    assert [f.id for f in fa.FIELD_CATALOG] == list(fa.FIELD_BY_ID)
    for f in fa.FIELD_CATALOG:
        assert fa.FIELD_BY_ID[f.id] is f


def test_the_api_catalog_keeps_its_categories_and_members():
    """`fields_catalog()` 는 `GET` 스크리너 카탈로그로 나간다(asdict 직렬화)."""
    cats = {c["id"]: [f["id"] for f in c["fields"]]
            for c in fa.fields_catalog()["categories"]}
    expected: dict[str, list[str]] = {}
    for row in GOLDEN:
        expected.setdefault(row[2], []).append(row[0])
    assert cats == expected


def test_the_snapshot_is_not_vacuous():
    """★스냅샷의 스냅샷★ — 비어 있으면 위 넷이 전부 공짜로 통과한다."""
    assert len(GOLDEN) > 100
    assert len(_ATTRS) == 7
