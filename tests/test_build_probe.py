"""AM2 — 빌드 식별자를 **실제로 측정**한다 (부작용을 한 곳에 가둔다).

## 왜 이 파일이 생겼나

`code_version()` 은 `GIT_SHA or APP_VERSION or "dev"` 였고 두 환경변수는
**어디에도 설정돼 있지 않았다**. 그래서 701행이 전부 `"dev"` 였다.
★`"dev"` 는 폴백이 아니라 침묵 폴백이었다★ — 의미가 라벨되지 않았고, 동등
품질로 위장했고(비교에서 서로 일치했고), 관측할 수 없었다. `CLAUDE.md` 가
금지하는 네 조건에 전부 걸린다.

## 이 모듈이 지키는 규율

· 부작용(subprocess)은 여기에만 있다 — 어휘(`src/domain/build_identity.py`)는 순수하다.
· `run` 을 주입할 수 있어 ★테스트가 subprocess 없이 전 분기를 돈다★.
· 실패는 전부 **사유를 동반한다**. 사유 없는 미상은 금지다.
· 환경변수는 **매번 새로 읽고** git 측정만 캐시한다 — 프로세스당 subprocess 2회.
"""
from __future__ import annotations

import subprocess

import pytest

from src.domain.build_identity import (
    METHOD_INJECTED,
    METHOD_MEASURED,
    METHOD_UNKNOWN,
    TREE_CLEAN,
    TREE_DIRTY,
    TREE_UNKNOWN,
    is_version,
)
from src.engine.build_probe import (
    current_identity,
    probe_git,
    reset_probe_cache,
)

_SHA = "9f8e7d6c5b4a39281706"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """★이 파일은 주입 없는 상태를 기본으로 본다★"""
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    reset_probe_cache()
    yield
    reset_probe_cache()


def _runner(*, sha=_SHA, sha_rc=0, status="", status_rc=0, calls=None):
    def run(args):
        if calls is not None:
            calls.append(args)
        if "rev-parse" in args:
            return sha_rc, (sha or "")
        if "status" in args:
            return status_rc, status
        raise AssertionError(f"예상치 못한 호출: {args}")
    return run


# ═══════════════════════════════════════════════════════════════════════════
# probe_git — 분기 전수
# ═══════════════════════════════════════════════════════════════════════════

def test_a_clean_checkout_measures_a_sha_and_says_it_is_clean():
    sha, dirty, reason = probe_git(run=_runner(status=""))
    assert sha == _SHA
    assert dirty is False
    assert reason is None


def test_uncommitted_changes_are_measured_as_dirty():
    sha, dirty, reason = probe_git(run=_runner(status=" M src/x.py\n?? y\n"))
    assert sha == _SHA
    assert dirty is True


def test_the_probe_runs_git_against_the_repository_root_not_the_cwd():
    """★작업 디렉터리에 의존하지 않는다★ 스크립트가 어디서 돌든 같아야 한다."""
    calls: list[list[str]] = []
    probe_git(run=_runner(calls=calls))
    assert calls, "git 을 부르지도 않았다"
    for args in calls:
        assert args[0] == "git"
        assert args[1] == "-C" and args[2].endswith("Project-Alpha")


def test_no_git_repository_is_unknown_with_a_reason():
    """`.dockerignore` 가 `.git` 을 빼므로 **컨테이너의 정상 상태**다."""
    sha, dirty, reason = probe_git(run=_runner(sha_rc=128, sha=""))
    assert sha is None and dirty is None
    assert reason and "git" in reason


def test_a_missing_git_binary_is_unknown_with_a_reason():
    def run(args):
        raise FileNotFoundError("git")
    sha, dirty, reason = probe_git(run=run)
    assert sha is None and dirty is None
    assert reason


def test_a_timeout_is_unknown_with_a_reason():
    def run(args):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1.0)
    sha, dirty, reason = probe_git(run=run)
    assert sha is None
    assert reason


def test_a_readable_sha_with_an_unreadable_status_keeps_the_sha_but_not_the_tree():
    """★부분 측정을 전부 버리지 않는다★ — 커밋은 알고 트리는 모른다."""
    sha, dirty, reason = probe_git(run=_runner(status_rc=1, status="boom"))
    assert sha == _SHA
    assert dirty is None, "모르는 것을 깨끗하다고 말하지 않는다"
    assert reason


@pytest.mark.parametrize("run", [
    _runner(sha_rc=128, sha=""),
    _runner(status_rc=1),
    lambda args: (_ for _ in ()).throw(FileNotFoundError("git")),
])
def test_every_failure_branch_carries_a_reason(run):
    """★사유 없는 미상은 금지★ (CLAUDE.md §4)"""
    _, _, reason = probe_git(run=run)
    assert reason and reason.strip()


def test_the_probe_never_invents_a_version():
    """★`"dev"` 를 만들지 않는다★"""
    for run in (_runner(sha_rc=128, sha=""), _runner(sha="")):
        sha, _, _ = probe_git(run=run)
        assert sha is None or is_version(sha)
        assert sha != "dev"


def test_an_empty_sha_output_is_not_a_sha():
    sha, _, reason = probe_git(run=_runner(sha="   \n"))
    assert sha is None
    assert reason


# ═══════════════════════════════════════════════════════════════════════════
# current_identity — 환경은 매번, 측정은 한 번
# ═══════════════════════════════════════════════════════════════════════════

def test_the_measurement_is_cached_but_the_environment_is_not(monkeypatch):
    """★subprocess 는 프로세스당 한 번, 환경변수는 매번★

    캐시가 환경까지 얼리면 배포 중 주입이 반영되지 않고, 환경까지 매번 재면
    요청마다 git 을 두 번 부른다.
    """
    calls: list[list[str]] = []
    run = _runner(calls=calls)
    assert current_identity(run=run).method == METHOD_MEASURED
    n_after_first = len(calls)
    current_identity(run=run)
    assert len(calls) == n_after_first, "두 번째 호출이 git 을 다시 불렀다"

    monkeypatch.setenv("GIT_SHA", "injected-1")
    ident = current_identity(run=run)
    assert ident.value == "injected-1", "환경 변화가 즉시 보여야 한다"
    assert len(calls) == n_after_first, "환경만 바뀌었는데 git 을 다시 불렀다"


def test_refresh_re_measures():
    calls: list[list[str]] = []
    run = _runner(calls=calls)
    current_identity(run=run)
    n = len(calls)
    current_identity(run=run, refresh=True)
    assert len(calls) > n


def test_the_identity_labels_that_the_tree_was_read_at_process_start():
    """★캐시의 한계를 라벨한다★ 라벨하지 않으면 침묵 폴백이다."""
    ident = current_identity(run=_runner())
    assert ident.tree == TREE_CLEAN
    assert ident.reason and "프로세스" in ident.reason


def test_a_dirty_tree_is_reported_dirty():
    ident = current_identity(run=_runner(status=" M a.py\n"))
    assert ident.tree == TREE_DIRTY


def test_without_git_and_without_injection_the_identity_is_none_not_dev():
    """★이 프로그램의 전부★ — 컨테이너에서 조용한 `"dev"` 가 나오지 않는다."""
    ident = current_identity(run=_runner(sha_rc=128, sha=""))
    assert ident.value is None
    assert ident.method == METHOD_UNKNOWN
    assert ident.tree == TREE_UNKNOWN
    assert ident.reason


def test_injection_wins_and_a_matching_measurement_promotes_the_tree(monkeypatch):
    monkeypatch.setenv("GIT_SHA", _SHA)
    ident = current_identity(run=_runner())
    assert ident.method == METHOD_INJECTED
    assert ident.tree == TREE_CLEAN


def test_injection_that_contradicts_the_measurement_is_recorded(monkeypatch):
    """★조용히 삼키지 않는다★ 배포 이미지가 다른 커밋이라는 사건을 놓치지 않는다."""
    monkeypatch.setenv("GIT_SHA", "deadbeef")
    ident = current_identity(run=_runner())
    assert ident.value == "deadbeef"
    assert ident.tree == TREE_UNKNOWN
    assert ident.reason and _SHA in ident.reason


def test_the_real_probe_runs_without_a_fake_runner():
    """★진짜로 돌려 본다★ 가짜 러너만 보면 기본 러너가 깨진 것을 못 잡는다."""
    reset_probe_cache()
    sha, dirty, reason = probe_git()
    assert (sha is None) == (not is_version(sha))
    if sha is None:
        assert reason
    else:
        assert dirty in (True, False, None)


# ═══════════════════════════════════════════════════════════════════════════
# research_context 와의 배선
# ═══════════════════════════════════════════════════════════════════════════

def test_code_version_is_the_identity_value():
    from src.engine.research_context import code_version
    assert code_version() == current_identity().value


def test_code_version_never_returns_dev(monkeypatch):
    """★단일 출처가 `"dev"` 를 만들지 않는다★ (교정 전 코드에서 red)"""
    from src.engine.research_context import code_version
    monkeypatch.setenv("GIT_SHA", "dev")
    monkeypatch.setenv("APP_VERSION", "dev")
    reset_probe_cache()
    assert code_version() != "dev"


def test_describe_declares_how_the_version_was_known():
    from src.engine.research_context import describe, now
    d = describe(now())
    assert d["code_version_method"] in ("measured", "injected", "declared",
                                        "unknown")
    assert d["code_tree"] in (TREE_CLEAN, TREE_DIRTY, TREE_UNKNOWN)


def test_the_tree_state_is_part_of_the_fingerprint(monkeypatch):
    """★같은 SHA 라도 트리가 다르면 다른 실행이다★"""
    import src.engine.research_context as rc
    from src.domain.build_identity import BuildIdentity

    base = BuildIdentity(value=_SHA, method=METHOD_MEASURED, tree=TREE_CLEAN)
    monkeypatch.setattr(rc, "current_identity", lambda **kw: base)
    clean = rc.fingerprint(rc.now(as_of="2025-06-30"))

    dirty = BuildIdentity(value=_SHA, method=METHOD_MEASURED, tree=TREE_DIRTY)
    monkeypatch.setattr(rc, "current_identity", lambda **kw: dirty)
    assert rc.fingerprint(rc.now(as_of="2025-06-30")) != clean
