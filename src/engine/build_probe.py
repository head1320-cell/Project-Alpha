"""빌드 식별자 측정 — ★부작용을 한 곳에 가둔다★ (AM2)
==============================================================================
어휘 `src/domain/build_identity.py`(순수) · 소비 `src/engine/research_context.py`
· 레지스트리 `src/engine/version_registry.py`

## 왜 이 모듈이 생겼나

`code_version()` 은 `GIT_SHA or APP_VERSION or "dev"` 였다. 그런데 두 환경변수가
**어디에도 설정돼 있지 않아서**(Dockerfile·compose·Makefile·CI·`.env.example`
전부 0건) 실측 701행이 전부 `"dev"` 다. ★그것은 폴백이 아니라 침묵 폴백이었다★
— `CLAUDE.md` §4 의 네 조건 중 셋을 어긴다: 라벨이 없고, 동등 품질로 위장하고
(비교에서 서로 일치하고), 관측할 수 없다.

## 무엇을 하는가

1. **측정한다** — `git rev-parse HEAD` 로 커밋을, `git status --porcelain` 로
   트리 상태를 읽는다. ★SHA 는 커밋을 식별하지 트리를 식별하지 않으므로★
   둘을 함께 읽지 않으면 "이 실행 = 커밋 abc" 라는 하지 않은 주장을 하게 된다.
2. **못 재면 못 쟀다고 말한다** — `None` + **사유**. `"dev"` 를 만들지 않는다.
3. **주입을 우선한다** — 컨테이너에는 `.git` 이 없어(`.dockerignore`) 주입이
   유일한 진실이다. 다만 측정이 가능하면 대조하고, 어긋나면 사유에 남긴다.

## ★캐시의 경계★

**git 측정만** 프로세스당 1회 캐시하고 **환경변수는 매번 새로 읽는다.**

· 환경까지 얼리면 배포 중 주입이 반영되지 않는다.
· 환경까지 매번 재면 요청마다 subprocess 를 두 번 띄운다.

트리 상태는 프로세스가 사는 동안 바뀔 수 있다(개발 중 파일을 고치면). TTL 로
다시 재지 않는다 — ★정교함을 위한 정교함 금지★ — 대신 **"프로세스 시작 시점
기준" 이라고 사유에 라벨한다.** 라벨하지 않으면 그것이 곧 침묵 폴백이다.
"""
from __future__ import annotations

import logging
import os
import pathlib
import subprocess
from collections.abc import Callable
from dataclasses import replace

from src.domain.build_identity import (
    KIND_CODE,
    TREE_CLEAN,
    TREE_DIRTY,
    BuildIdentity,
    identity_from,
    is_version,
)

logger = logging.getLogger(__name__)

#: `src/engine/build_probe.py` → 저장소 루트. ★작업 디렉터리에 의존하지 않는다★
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: git 이 느려도 요청을 붙잡지 않는다. 못 재면 미상이지 대기가 아니다.
TIMEOUT_SEC = 5.0

#: 측정의 유효 범위. ★라벨하지 않으면 침묵 폴백★
CACHE_NOTE = ("git 측정은 **프로세스 시작 시점 기준**입니다 — 이후 작업 트리가 "
              "바뀌어도 이 값은 갱신되지 않습니다.")

#: `(sha, dirty, reason)` 프로세스 로컬 캐시. `uvicorn --workers 1` 전제와 같은 결.
_cache: tuple[str | None, bool | None, str | None] | None = None

Runner = Callable[[list[str]], tuple[int, str]]


def _default_run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True,  # noqa: S603
                       timeout=TIMEOUT_SEC, check=False)
    return p.returncode, p.stdout


def probe_git(*, run: Runner | None = None
              ) -> tuple[str | None, bool | None, str | None]:
    """`(sha, dirty, reason)`. ★실패는 전부 사유를 동반한다★

    · `sha is None` — 커밋을 모른다(저장소가 아니거나 git 이 없다).
    · `dirty is None` — 트리가 깨끗한지 **모른다**. 깨끗하다는 뜻이 아니다.

    `run` 을 주입하면 subprocess 없이 전 분기를 돌 수 있다.
    """
    runner = run or _default_run
    root = str(REPO_ROOT)

    try:
        rc, out = runner(["git", "-C", root, "rev-parse", "HEAD"])
    except FileNotFoundError:
        return None, None, ("git 실행 파일을 찾지 못했습니다 — 빌드 식별자를 "
                            "측정할 수 없습니다.")
    except subprocess.TimeoutExpired:
        return None, None, (f"git 호출이 {TIMEOUT_SEC}초 안에 끝나지 않았습니다 "
                            "— 빌드 식별자를 측정할 수 없습니다.")
    except OSError as e:  # noqa: BLE001
        return None, None, f"git 을 실행하지 못했습니다 — {type(e).__name__}: {e}"

    sha = (out or "").strip()
    if rc != 0 or not is_version(sha):
        return None, None, (
            f"git 저장소를 읽지 못했습니다(`{root}`, rc={rc}) — 컨테이너에서는 "
            "`.dockerignore` 가 `.git` 을 제외하므로 정상입니다. 빌드 시각에 "
            "`GIT_SHA` 를 주입하십시오.")

    # ★커밋은 알고 트리는 모를 수 있다★ 부분 측정을 통째로 버리지 않는다.
    try:
        rc2, out2 = runner(["git", "-C", root, "status", "--porcelain"])
    except (OSError, subprocess.TimeoutExpired) as e:  # noqa: BLE001
        return sha, None, (f"작업 트리 상태를 읽지 못했습니다 — "
                           f"{type(e).__name__}. 깨끗한지 **모릅니다**.")
    if rc2 != 0:
        return sha, None, (f"작업 트리 상태를 읽지 못했습니다(rc={rc2}) — "
                           "깨끗한지 **모릅니다**.")
    return sha, bool((out2 or "").strip()), None


def reset_probe_cache() -> None:
    """측정 캐시를 비운다. 테스트와 `refresh=True` 가 쓴다."""
    global _cache
    _cache = None


def _measured(*, run: Runner | None, refresh: bool
              ) -> tuple[str | None, bool | None, str | None]:
    global _cache
    if refresh or _cache is None:
        _cache = probe_git(run=run)
    return _cache


def current_identity(*, run: Runner | None = None, refresh: bool = False,
                     kind: str = KIND_CODE) -> BuildIdentity:
    """지금 도는 코드의 식별자. ★환경은 매번, 측정은 한 번★"""
    sha, dirty, reason = _measured(run=run, refresh=refresh)
    ident = identity_from(env_sha=os.getenv("GIT_SHA"),
                          env_app=os.getenv("APP_VERSION"),
                          measured_sha=sha, measured_dirty=dirty,
                          probe_reason=reason, kind=kind)
    if ident.tree in (TREE_CLEAN, TREE_DIRTY):
        # ★캐시의 한계를 라벨한다★ 값이 옳아도 유효 범위를 말하지 않으면
        # 그것이 곧 조용한 주장이다.
        joined = f"{ident.reason} · {CACHE_NOTE}" if ident.reason else CACHE_NOTE
        ident = replace(ident, reason=joined)
    return ident
