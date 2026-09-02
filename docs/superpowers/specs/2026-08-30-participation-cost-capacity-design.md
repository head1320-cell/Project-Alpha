# 참여율 비용과 전략 용량 — 설계 (P3, 2026-08-30)

> 상위: `docs/specs/2026-08-30-macro-to-portfolio-architecture-review.md` §6 P3
> ★P2 는 측정이 막았다. P3 는 측정이 밀어붙인다.★

## 0. 왜 P3 는 P2 와 다른가

| | P2(Σ_post) | **P3(참여율 비용)** |
|---|---|---|
| 주 통계에 미치는 영향 | 비중 0.70%p → ★거래 0건★ | ★`sharpe_diff` 0.202 → 0.167 (1000억)★ |
| 방향 | 일정하지 않음(30시드 18/12) | ★일정 — 회전율에 비례★ |
| 판정 | NO-GO(P2′ 로 축소) | **GO** |

★핵심은 편향이다.★ 충격 비용은 회전율에 비례하는데 `regime-on` 은 `regime-off`
보다 **4.3배 더 거래한다**(8.5151% vs 1.9823%, 실측). 정액 비용은 얼마나 많이
거래하든 **같은 요율**을 매기므로, 현재 백테스트는 국면 전략을 **체계적으로
유리하게** 평가한다. ④ 관문이 재려는 것이 바로 그 우위이므로 이는 관문의 편향이다.

실측(Almgren-Chriss √법칙, ADV 500억·σ 1.8%·α 0.7 — 기존 `market_impact` 기본값):

| 포트폴리오 | `regime-on` | `regime-off` | 차이 | 초과드래그 차이 |
|---|---|---|---|---|
| 10억 | 5.2bp | 2.5bp | 2.7bp | — |
| 100억 | 16.4bp | 7.9bp | **8.5bp** | 0.149 %p/yr |
| 1000억 | 52.0bp | 25.1bp | **26.9bp** | 0.472 %p/yr |
| 1조 | 164bp | 79bp | 85bp | — |

## 1. 모델은 이미 있다 — 안 쓰고 있을 뿐이다

`src/engine/market_impact.py`(342줄)에 Almgren-Chriss √법칙이 **이미 구현돼
있고** `realism_engine` 이 `enable_market_impact=True` 로 쓴다. 특히
`MarketImpactModel.turnover_based_impact(turnover_pct, portfolio_equity,
avg_adv_krw, avg_volatility, weighted_alpha)` 는 `walk_forward` 가 필요로 하는
**바로 그 형태**다.

★그런데 연구 관문이 쓰는 `allocation_backtest.walk_forward` 는 그것을 부르지
않는다★ — `cost = cost_bps/1e4` 정액뿐이다. P1(지표 두 벌)·P2′(BL 두 벌)와 같은
형태의 **불일치**다: 저장소가 이미 가진 모델을 하중 경로가 안 쓴다.

## 2. 설계

### 2-1. 규모 가정 — ★가정하지 않고 측정한다★ (사용자 결정)

`walk_forward` 의 `equity` 는 1.0 에서 시작하는 **단위 정규화**라 KRW notional 이
없다. 참여율에는 규모가 필요하다. 임의의 기본값을 고르면 ★그 하나의 가정이 주
통계를 5~17% 움직인다★ — 정당화할 근거가 없다.

그래서 규모를 **쓸어서 측정값으로 바꾼다**(M7 이 개월 축에 한 것과 같은 규율).
답하는 질문은 ★"이 매크로 전략은 얼마까지 태울 수 있는가" — 전략 **용량**★ 이고,
그것이 이 플랫폼이 답해야 할 경제적 질문이다.

### 2-2. `market_impact.ImpactAssumptions` (신규, frozen dataclass)

```python
portfolio_krw: float          # ★기본값 없음 — 반드시 선언해야 한다★
adv_krw: float = 50e9 · volatility: float = 0.018 · alpha: float = 0.7
as_convention() -> dict       # P1·P2′ 패턴: 가정이 산출과 함께 다닌다
```

`portfolio_krw` 에 기본값을 두지 않는 것이 계약이다 — 충격 비용을 쓰려면 규모를
**말해야** 한다.

### 2-3. `walk_forward(..., impact: ImpactAssumptions | None = None)`

```
turnover = 0.5·Σ|Δw|
bps = cost_bps + (impact_bps(turnover, portfolio_krw × equity) if impact else 0)
equity *= (1 − turnover × bps/1e4)
```

★`portfolio_krw × equity`★ — notional 이 성과에 따라 커지고 작아진다. 수익이 나면
충격도 커진다(용량 곡선의 핵심).

★기본 `None` 이면 비트 동일★(사용자 결정) — A3·M7 의 기록이 보존된다.
요약에 `impact` 블록(가정 + 실현 충격 통계)을 싣고, `None` 이면 **사유와 함께**
비었음을 적는다(침묵 폴백 금지).

### 2-4. `scripts/regime_control.py --capacity 1e9,1e10,1e11,1e12`

규모마다 **전체 관문**(팔 + 순환이동 널 + SPA)을 돌려 `sharpe_diff` 와 판정을
낸다. 규모당 ≈3분이라 4규모 ≈ 12분. 산출:

```
capacity_curve: [{portfolio_krw, sharpe_diff, verdict, spa_p, impact_bps_on/off}]
capacity_limit: {value|None, bracket, reason}   # sharpe_diff ≤ 0 이 되는 첫 규모
```

`capacity_limit` 은 ★미도달이면 `None` + 사유★ — 탐색 범위를 답이라고 적지 않는다
(A1 `mde_from_curve` 와 같은 계약).

## 3. 테스트와 변이

| 계약 | 짝 |
|---|---|
| 규모가 커지면 충격이 커진다 | ★√법칙 — 4배 규모면 2배 충격★ |
| 회전율이 높은 팔이 더 많이 낸다 | 회전 0 이면 충격 0 |
| `impact=None` 이면 비트 동일 | `impact` 주면 달라진다 |
| notional 이 `portfolio_krw × equity` 로 따라간다 | 고정이면 용량 곡선이 틀린다 |
| `portfolio_krw` 없이 못 쓴다 | 기본값으로 조용히 돌지 않는다 |
| 가정이 `convention` 으로 실린다 | `None` 이면 사유가 실린다 |
| `capacity_limit` 미도달 = `None` + 사유 | 탐색 최대값을 답으로 쓰지 않는다 |

변이: 충격을 정액으로 · √ 를 선형으로 · notional 을 고정으로 · `impact=None` 인데
충격 적용 · 회전율 무시 · 가정 미신고 · `capacity_limit` 을 탐색 최대값으로 ·
`turnover_based_impact` 대신 인라인 재구현.

## 4. 하지 않는 것

- ★종목별 ADV★ — 연구 패널은 합성 6자산이라 종목 ADV 가 없다. 포트폴리오 수준
  평균 ADV 를 쓴다(`realism_engine` 과 같은 관례). 실데이터 경로(M9)에서
  종목별로 갈 수 있으나 그것은 별도 결정이다.
- ★영구/일시 임팩트 분해★ · cross-impact — `market_impact` 에 있지만 이 관문은
  총비용만 필요하다. 복잡도를 사지 않는다.
- 증권거래세 비대칭 — ★long-only 전량투자 리밸런싱에서는 매수 notional = 매도
  notional 이라 대칭/비대칭이 **총비용을 바꾸지 않는다**★(검토했고 접었다).
- 기본값 ON · 배분 결정 경로 변경 · 투자 주장. 증거 등급 E0 그대로.
