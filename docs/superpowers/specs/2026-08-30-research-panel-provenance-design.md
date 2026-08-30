# 연구 패널의 출처와 증거 등급 — 설계 (M9, 2026-08-30)

> 사용자가 "M6~M9 를 하라" 고 지시했으나 M6~M9 는 저장소에 정의된 적이 없었다
> (감사 `7313371` §0 정정 #2). 사용자가 원문을 제시해 대조한 결과 **M6·M8 은
> 이번 세션에 이미 착지**했고(A1·A2 = `375db5e` · A4 = `80f4b5a`), **M7 은 그
> 전제가 측정으로 반증**됐다. 남은 것이 M9 다.
>
> 지시: "개발 취지에 맞게 실데이터가 들어올 때 정상적으로 모델이 작동하게 만들어"

## 0. 무엇이 문제였나

`regime_control.run(..., panel_is_synthetic: bool = True)` 이 등급을 정했다.
★호출자가 주는 검증되지 않은 불리언★ 이라, 합성 패널에 `False` 를 넘기면 그대로
`E3` 가 찍혔다 — **하지 않은 검증을 주장하는 경로**다.
`regime_signal_gate` 는 아예 `"E0"` 하드코딩이라 실데이터가 들어와도 계속 E0 라고
말했을 것이다. `source_registry.EVIDENCE_GRADES` 가 이미 있는데 두 하네스 다
쓰지 않았다.

## 1. 등급은 출처에서 **파생**한다

`src/engine/research_panel.py`

```python
@dataclass(frozen=True)
class Panel:
    names; returns; dates; points; provenance
```

`evidence_grade(provenance) -> (등급 | None, 사유)` — 규칙 셋:

| 규칙 | 뜻 |
|---|---|
| ★**미상은 등급이 아니다**★ | 출처를 모르면 `None` + 사유. 모르는 것에 E3 를 찍으면 그것이 과대주장이다 |
| ★**약한 고리가 지배한다**★ | 실가격 + 합성 국면 = E0. 한쪽이 합성이면 실증거가 아니다 |
| ★**주입하면 강등된다**★ | 반합성은 검정력을 재는 **도구**이지 증거가 아니다. `scale=1`(항등)도 강등한다 — 반합성 실험의 일부라는 사실을 리포트가 말해야 한다 |

그리고 `price_basis != adj_close` 면 E3 가 아니다 — ★원주가 ≠ 수정주가★.
`vintage.revision_bias == managed` 일 때만 `E4`. 지금 KRX·ECOS 는
`BLOCKED_BY_SOURCE` 라 도달 불가이고, 그 사실이 사유에 적힌다.

★`panel_is_synthetic` 인자를 삭제했다.★

## 2. 실 공급자 — 없으면 거부한다

`real_panel(codes, months, as_of)` → `(Panel | None, 사유들)`
가격 `daily_prices.adj_close` · 국면 `regime_transitions.regime_path()` ·
빈티지 `regime_axes.axis_revision_status()`.

- ★`adj_close` 가 없을 때 `close` 로 조용히 갈아타지 않는다★ — 그 종목을 사유와
  함께 빼고, 전부 없으면 `None`. `coverage` 에 요청·사용·탈락을 남긴다.
- 가격 월과 국면 월이 **겹치는 구간만** 쓴다. 없는 달을 중립으로 메우지 않는다.
- ★개발 모드에서도 합성으로 대체하지 않는다★ — `mock_allowed()` 는 **호출자가**
  합성으로 갈아탈 수 있는가를 정하지(→ `panel_for`), 실 공급자가 몰래 합성을
  내도 되는가를 정하지 않는다. 두 개념을 섞으면 개발에서 통과한 경로가 운영에서
  다르게 동작한다.

`panel_for(real=…)` 가 하네스의 단일 진입점이고, ★운영(`mock_allowed()` False)
에서는 합성 연구 패널을 거부★한다. mock 게이트가 여기서 하중이 된다.

## 3. 반합성 양성 통제

`inject_regime_drift(panel, scale)` —
`r'_{t,i} = r_{t,i} + (scale − 1)·(μ̂_{regime(t),i} − μ̂_i)`

- `scale = 1` 항등 · `scale = 0` 음성 통제 · `scale > 1` 양성 통제
- ★전체 수준을 건드리지 않는다★ — 국면 간 **차이**만 배율한다. 전체평균 중심화를
  빼면 scale=0 에서 국면별 평균이 여전히 같아져 음성 통제 테스트는 통과하는데
  **전체 수익 수준이 밀린다**(변이 Q9 가 그렇게 살아남았다). 그러면 척도를 올릴 때
  관문이 국면 정보가 아니라 드리프트를 보고 반응한다.
- ★실 공분산·꼬리·자기상관은 그대로★ — 주입은 월 단위 **수준 이동**이라 각 달
  안의 일별 편차가 변하지 않는다.
- ★원본을 변형하지 않는다★ — 같은 패널로 여러 척도를 돌리므로.

합성 쪽 `t3_transmission.scaled_profiles` 와 **같은 계약**이라
`research_power.power_curve` 가 양쪽에서 그대로 돈다.

## 4. 하네스 배선

두 하네스가 `Panel` 을 받고 등급을 `provenance` 에서 파생한다. `--real --codes
--as-of` CLI 를 더했고, 실데이터가 없으면 ★종료코드 2 로 거부★한다(빈 결과보다
나쁜 것은 지어낸 결과다). `measure_power`/`power_trial` 의 척도는 합성이면
`scaled_profiles`, 실이면 `inject_regime_drift` 로 라우팅된다.

★합성 경로는 비트 동일★ — 동결 해시와 두 하네스의 실측 출력이 M9 전후로 한 자리도
다르지 않다.

## 5. 하지 않은 것

- ★실데이터 실행 자체★ — 배포 후. 이것은 **준비**다. 증거 등급을 올리는 주장,
  예측 스킬·경제적 알파 주장은 하나도 하지 않는다.
- M7 측정 · 새 국면 모델 · `MacroState` 추상 · 프론티어 5종.
- `E1`·`E2`·`E5` — 이 경로에 해당 출처가 없다. 필요해지면 그때 더한다.
