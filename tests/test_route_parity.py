"""라우트 파리티 — 파일을 옮겨도 **URL 은 하나도 바뀌지 않는다**.

★이 테스트는 `timing_routes.py` 분리 **전에** 통과해야 한다★
그래야 이동 전/후를 실제로 비교한 것이 된다. 이동한 뒤에 스냅샷을 뜨면 "지금 상태" 를 기록할
뿐이고, 그 사이에 사라진 라우트는 영원히 안 보인다.

라우트 이동은 **한 글자만 어긋나도 삭제와 구별되지 않는다** — 프론트는 404 를 받고, 저장된
룰셋은 열리지 않고, 어느 쪽도 예외를 던지지 않는다. 그래서 개수가 아니라 **{메서드, 경로} 집합**
전체를 고정한다(CLAUDE.md: 개수는 세지 말고 레지스트리를 읽을 것).
"""
from src.app_factory import create_app

#: 이 경로들은 프론트엔드 클라이언트·E2E·저장된 룰셋이 직접 참조한다. 모듈을 어디로 옮기든
#: 이 목록은 그대로여야 한다. `timing_routes.py` 분리의 유일한 성공 조건이기도 하다.
TIMING_PATHS: tuple[tuple[str, str], ...] = (
    ("GET", "/api/v1/allocation/timing-factors"),
    ("GET", "/api/v1/allocation/timing-factors/{factor_id}/history"),
    ("POST", "/api/v1/allocation/timing-rules"),
    ("GET", "/api/v1/allocation/timing-rules"),
    ("GET", "/api/v1/allocation/timing-rules/{set_id}/versions"),
    ("DELETE", "/api/v1/allocation/timing-rules/{set_id}"),
    ("POST", "/api/v1/allocation/timing/three-way"),
    ("POST", "/api/v1/allocation/timing/simulate"),
    ("POST", "/api/v1/allocation/timing"),
)


def _route_set(app) -> set[tuple[str, str]]:
    """{(메서드, 경로)} — HEAD/OPTIONS 같은 자동 생성 메서드는 뺀다."""
    out: set[tuple[str, str]] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            out.add((m, path))
    return out


def test_every_timing_path_is_registered():
    """★분리 전후로 이 8개가 그대로 있어야 한다★ 하나라도 빠지면 프론트가 404 를 받는다."""
    routes = _route_set(create_app())
    missing = [p for p in TIMING_PATHS if p not in routes]
    assert missing == [], f"등록되지 않은 타이밍 경로: {missing}"


def test_timing_paths_are_registered_exactly_once():
    """두 라우터가 같은 경로를 등록하면 뒤엣것이 그림자가 된다 — 조용히.

    분리 도중 원본에서 지우지 않고 새 모듈에 추가하면 정확히 이 상태가 된다.
    """
    app = create_app()
    for method, path in TIMING_PATHS:
        n = sum(1 for r in app.routes
                if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or set()))
        assert n == 1, f"{method} {path} 가 {n}번 등록됐다(중복 등록은 그림자 라우트를 만든다)"


#: "/timing" 을 포함하지만 **이 분리와 무관한** 기존 경로.
#: `/api/v1/macro/timing` 은 매크로 탭의 마켓타이밍 패널(`macro_routes`)이고 AAS 타이밍
#: 룰셋과는 다른 개념이다. 이름이 겹친다는 이유로 옮기면 안 되므로 사유와 함께 남긴다.
_UNRELATED_TIMING_PATHS = {"/api/v1/macro/timing"}


def test_the_allocation_prefix_is_unchanged():
    """타이밍 라우트가 다른 프리픽스로 옮겨가지 않았는지 — URL 변경은 파괴적 변경이다."""
    routes = _route_set(create_app())
    stray = [p for _m, p in routes
             if "/timing" in p
             and not p.startswith("/api/v1/allocation/")
             and p not in _UNRELATED_TIMING_PATHS]
    assert stray == [], f"허용되지 않은 프리픽스의 타이밍 경로: {stray}"


def test_the_whole_route_surface_is_large_and_healthy():
    """전체 표면이 통째로 사라지지 않았는지 — 라우터 하나가 import 에러로 빠지면
    `app_factory` 는 로그만 남기고 계속 진행하므로, 조용히 수십 개가 없어질 수 있다."""
    routes = _route_set(create_app())
    assert len(routes) > 200, f"라우트가 {len(routes)}개뿐 — 라우터 등록이 실패했을 수 있다"
