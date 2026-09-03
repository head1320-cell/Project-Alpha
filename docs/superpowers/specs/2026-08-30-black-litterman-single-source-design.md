# BL 단일 출처 + 사후 공분산 진단 — 설계 (P2′, 2026-08-30)

> 상위: `docs/specs/2026-08-30-macro-to-portfolio-architecture-review.md` §6 P2
> ★원래 P2 는 "Σ_post 를 최적화기에 연결" 이었다. 측정이 그 계획을 바꿨다.★

## 0. 측정이 P2 를 P2′ 로 바꿨다

원 설계의 근거는 **"뷰 불확실성이 포지션 크기를 줄인다"** 였다. 실측하니 틀렸다:

| 검증 | 결과 |
|---|---|
| `_opt` 은 long-only·합=1 | ★줄어들 것이 없다★ — 비중은 항상 1로 정규화된다 |
| max-Sharpe 의 Σ 균등배수 불변성 | `‖w(Σ) − w(1.05Σ)‖ = 7.5e-7` ≈ 0. `Σ_post = Σ+M` 에서 `M ⪯ τΣ = 0.05Σ` 라 효과는 M 의 **비균등 부분**뿐 |
| 방향 (시드 30개) | 시장에서 **멀어짐 18 · 가까워짐 12** — ★일정하지 않다★ |
| 크기 | `max|Δw| = 0.70 %p` |
| 무거래 반밴드 (`dynamic_band` 실측) | **1.00 ~ 4.19 %p** |

★Σ_post 를 연결해도 이 저장소의 리밸런싱 규칙상 거래가 한 건도 발생하지 않는다.★
CLAUDE.md §5 "측정 가능한 투자 가치 없이 복잡도를 올리지 말라" 에 걸린다.

## 1. 그런데 파다가 13배 큰 결함을 찾았다

★BL 구현이 두 벌이고, 독스트링이 "동일 공식" 이라고 **틀리게** 적고 있다.★

| | `allocation_studio` | `risk_allocations.s_black_litterman` |
|---|---|---|
| Ω 신뢰도 스케일링 | ★있음★ `× (100−conf)/max(conf,1)` | ★없음★ |
| Ω 바닥 | `max(diag, 1e-10)` | 없음 |
| Ω ridge | `1e-10` | `1e-8` |

둘 다 프로덕션이다 — `s_black_litterman` 은 사용자가 고르는 전략
`("black_litterman", "블랙-리터만", …)` 로 등록돼 있다.

**실측 divergence** (시드 30개, 동일 뷰):

| 차이 원인 | `max|Δw|` | 밴드(최소 1.00%p) 대비 |
|---|---|---|
| ridge `1e-10` vs `1e-8` | **0.0001 %p** | 무의미 — P1 에서 본 CPU 흔들림(6e-7)과 같은 자릿수 |
| ★신뢰도 스케일링 유무★ | ★**9.07 %p**★ | ★밴드의 9배★ |

★같은 뷰를 넣어도 두 경로가 9%p 다른 비중을 낸다.★ P2 본체(0.70%p)보다 13배 크다.
P1 에서 고친 것과 **정확히 같은 형태**의 결함이다.

## 2. 설계 — `src/engine/black_litterman.py` (신규)

`allocation_studio → risk_allocations` 단방향 의존이므로(역방향 0건) 두 모듈이
함께 import 할 **새 공유 모듈**이 맞다. 순환 없음.

```python
TAU_DEFAULT = 0.05 · RIDGE_DEFAULT = 1e-10 · OMEGA_FLOOR = 1e-10

bl_omega(P, sigma, *, tau, confidences=None, ridge, floor) -> ndarray
bl_posterior_mean(pi, sigma, P, Q, omega, *, tau) -> ndarray
bl_posterior_cov(sigma, P, omega, *, tau)  -> ndarray      # ★진단 전용★
bl_solve(...) -> {mean, posterior_cov, omega, convention}
```

`confidences=None` 이면 스케일링 없음 → `s_black_litterman` 의 현행 동작.
`confidences` 를 주면 `(100−conf)/max(conf,1)` → `allocation_studio` 의 현행 동작.
★두 동작을 **선언된 인자**로 가른다★ — 지금은 복사본이 우연히 갈라져 있다.

**`convention` 블록** (P1 패턴): `tau` · `ridge` · `omega_floor` ·
`confidence_scaling: bool` · 그리고 ★`posterior_cov_used_in_optimizer: False`★ 와
그 사유(위 §0 측정치). ★의도적으로 연결하지 않았다는 사실을 관측 가능하게 만든다★
— 안 그러면 누군가 "빠뜨렸네" 하고 측정 없이 연결한다.

## 3. 이전은 값을 바꾸지 않는다 — ridge 하나만 빼고

`allocation_studio.bl_posterior` 는 얇은 위임으로 남긴다(공개 표면 유지, P1 의
`_sharpe` 와 같은 패턴). `s_black_litterman` 은 `confidences=None` 으로 위임한다.

★유일한 변경★ ridge 를 `1e-10` 으로 통일한다 — `risk_allocations` 의 `1e-8` 에서
바뀌지만 실측 `max|Δw| = 7.5e-7` 이라 **P1 에서 관측한 CPU 흔들림과 같은
자릿수**다. 그 자리에서 비트 동일을 고집하는 것은 의미가 없다. 바뀐다는 사실과
그 크기를 테스트로 못 박고 공개한다. 바닥 `max(diag, 1e-10)` 은 **유지**한다 —
분산이 0 인 뷰에서 `Ω⁻¹` 가 터지는 것을 막는 수치 가드다(CLAUDE.md 수치 안전).

## 4. 테스트와 변이

| 계약 | 짝 |
|---|---|
| 신뢰도 스케일링이 9%p 차이를 낸다 | 스케일링 없으면 그 차이가 사라진다 |
| `Ω→0` 이면 사후가 **뷰**에 수렴 | `Ω→∞` 면 **사전**에 수렴 |
| `Σ ⪯ Σ_post ⪯ (1+τ)Σ` | τ=0 이면 `Σ_post = Σ` |
| ridge 통일 변화 ≤ 1e-6 | — |
| ★`Σ_post` 가 최적화기에 안 들어간다★ (정적 검사) | `convention` 이 그 사실을 신고 |
| 두 호출부 값 불변 | — |

변이: 신뢰도 스케일링 제거 · `Σ_post` 를 최적화기에 연결 · `M` 을 버려
`Σ_post=Σ` · τ 무시 · 바닥 제거 · `convention` 미신고 · Ω 역행렬 부호 반전.

## 5. 하지 않는 것

- ★`Σ_post` 를 최적화기에 연결하지 않는다★ — 측정된 이유(§0)와 함께 기록한다.
  나중에 연결하려면 **밴드보다 큰 효과**를 먼저 보여야 한다.
- Entropy Pooling 경로 · 새 최적화기 · 배분 정책 변경.
- 투자 주장 없음. 증거 등급 E0 그대로.
