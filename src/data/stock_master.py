"""
Stock Master — Screener V3 중앙 종목 마스터 & 데이터 품질
==========================================================================
모든 종목코드 ↔ 종목명 매핑의 단일 진실 공급원(Single Source of Truth).

★ 우선순위 ★
  1. DART corpCode.xml (실데이터 — DART_API_KEY 설정 시 전체 상장사)
  2. 내장 마스터 (실제 KOSPI 주요 종목 — 키 없어도 작동)
  3. fallback ("종목 {code}")

★ "Unknown Corp" 박멸 ★
  기존 KOSPI200 = 실제 50개 + 가짜 150개(100000~) → 이름 없음.
  내장 마스터로 실제 종목명 공급, 가짜 코드는 마스터 종목으로 대체.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 내장 종목 마스터 — 실제 KOSPI 시가총액 상위 종목 (코드: 종목명)
# ═══════════════════════════════════════════════════════════════════════════════

STOCK_MASTER: dict[str, str] = {
    # 시총 상위
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "005490": "POSCO홀딩스",
    "035420": "NAVER", "051910": "LG화학", "006400": "삼성SDI",
    "000270": "기아", "068270": "셀트리온", "035720": "카카오",
    "105560": "KB금융", "055550": "신한지주", "012330": "현대모비스",
    "028260": "삼성물산", "066570": "LG전자", "003670": "포스코퓨처엠",
    "096770": "SK이노베이션", "017670": "SK텔레콤", "316140": "우리금융지주",
    "086790": "하나금융지주", "323410": "카카오뱅크", "138040": "메리츠금융지주",
    "000810": "삼성화재", "010130": "고려아연", "009150": "삼성전기",
    "032830": "삼성생명", "015760": "한국전력", "034730": "SK",
    "018260": "삼성에스디에스", "011200": "HMM", "010950": "S-Oil",
    "030200": "KT", "024110": "기업은행", "402340": "SK스퀘어",
    "267260": "HD현대일렉트릭", "047050": "포스코인터내셔널", "009830": "한화솔루션",
    "086280": "현대글로비스", "036570": "엔씨소프트", "078930": "GS",
    "033780": "KT&G", "003550": "LG", "259960": "크래프톤",
    "352820": "하이브", "377300": "카카오페이", "326030": "SK바이오팜",
    "302440": "SK바이오사이언스", "021240": "코웨이",
    # 추가 대형주
    "271560": "오리온", "000100": "유한양행", "128940": "한미약품",
    "069500": "KODEX 200", "005935": "삼성전자우", "012450": "한화에어로스페이스",
    "042700": "한미반도체", "064350": "현대로템", "010140": "삼성중공업",
    "329180": "HD현대중공업", "267250": "HD현대", "011070": "LG이노텍",
    "036460": "한국가스공사", "047810": "한국항공우주", "008770": "호텔신라",
    "139480": "이마트", "071050": "한국금융지주", "138930": "BNK금융지주",
    "175330": "JB금융지주", "029780": "삼성카드", "001570": "금양",
    "002790": "아모레퍼시픽홀딩스", "090430": "아모레퍼시픽", "051900": "LG생활건강",
    "097950": "CJ제일제당", "000120": "CJ대한통운", "180640": "한진칼",
    "003490": "대한항공", "020560": "아시아나항공", "241560": "두산밥캣",
    "034020": "두산에너빌리티", "042660": "한화오션", "010620": "현대미포조선",
    "161390": "한국타이어앤테크놀로지", "073240": "금호타이어",
    "004020": "현대제철", "001230": "동국제강", "058430": "포스코스틸리온",
    "022100": "포스코DX", "047040": "대우건설", "000720": "현대건설",
    "006360": "GS건설", "028050": "삼성엔지니어링", "375500": "DL이앤씨",
    "009540": "HD한국조선해양", "010060": "OCI홀딩스", "298050": "효성첨단소재",
    "011170": "롯데케미칼", "285130": "SK케미칼", "120110": "코오롱인더",
    "069960": "현대백화점", "023530": "롯데쇼핑", "004170": "신세계",
    "057050": "현대홈쇼핑", "035250": "강원랜드", "079160": "CJ CGV",
    "041510": "에스엠", "122870": "와이지엔터테인먼트", "035900": "JYP Ent.",
    # KOSDAQ 대형
    "247540": "에코프로비엠", "086520": "에코프로", "091990": "셀트리온헬스케어",
    "066970": "엘앤에프", "263750": "펄어비스",
    "293490": "카카오게임즈", "196170": "알테오젠", "112040": "위메이드",
    "058470": "리노공업", "240810": "원익IPS", "095660": "네오위즈",
    "067310": "하나마이크론", "121600": "나노신소재", "078340": "컴투스",
    "036930": "주성엔지니어링", "098460": "고영", "140860": "파크시스템스",
    "357780": "솔브레인", "131970": "테스나", "319660": "피에스케이",
}

# 섹터 매핑 (주요 종목)
STOCK_SECTOR: dict[str, str] = {
    "005930": "반도체", "000660": "반도체", "042700": "반도체", "011070": "반도체",
    "247540": "2차전지", "086520": "2차전지", "373220": "2차전지", "006400": "2차전지",
    "051910": "화학", "011170": "화학", "285130": "화학",
    "035420": "인터넷", "035720": "인터넷", "323410": "인터넷",
    "005380": "자동차", "000270": "자동차", "012330": "자동차",
    "105560": "금융", "055550": "금융", "086790": "금융", "316140": "금융",
    "207940": "바이오", "068270": "바이오", "196170": "바이오", "128940": "바이오",
    "005490": "철강", "004020": "철강", "001230": "철강",
    "017670": "통신", "030200": "통신",
    "036570": "게임", "259960": "게임", "263750": "게임", "293490": "게임",
}


# 주요 ETF 종목명 (ETF는 DART corpCode에 없음 → 별도 매핑). 지수·레버리지/인버스·섹터·채권·원자재.
ETF_NAMES: dict[str, str] = {
    "069500": "KODEX 200", "102110": "TIGER 200", "148020": "KBSTAR 200",
    "278530": "KODEX 200TR", "069660": "KOSEF 200", "226490": "KODEX 코스피",
    "122630": "KODEX 레버리지", "252670": "KODEX 200선물인버스2X", "114800": "KODEX 인버스",
    "251340": "KODEX 코스닥150선물인버스", "229200": "KODEX 코스닥150", "233740": "KODEX 코스닥150레버리지",
    "091160": "KODEX 반도체", "091230": "TIGER 반도체", "117460": "KODEX 에너지화학",
    "305720": "KODEX 2차전지산업", "305540": "TIGER 2차전지테마", "364980": "TIGER KRX2차전지K-뉴딜",
    "091170": "KODEX 은행", "102780": "KODEX 삼성그룹", "266370": "KODEX IT",
    "117680": "KODEX 철강", "091180": "KODEX 자동차", "140710": "KODEX 운송",
    "244580": "KODEX 바이오", "261070": "TIGER 코스닥150바이오테크", "143860": "TIGER 헬스케어",
    "227540": "TIGER 200 헬스케어", "139660": "TIGER 200 IT", "139270": "TIGER 200 중공업",
    "139290": "TIGER 200 경기소비재", "139250": "TIGER 200 에너지화학",
    "273130": "KODEX 종합채권액티브", "153130": "KODEX 단기채권", "214980": "KODEX 단기채권PLUS",
    "132030": "KODEX 골드선물(H)", "130680": "TIGER 원유선물Enhanced(H)",
    "278540": "KODEX MSCI Korea TR", "195930": "TIGER 선진국MSCI World", "143850": "TIGER 미국S&P500선물(H)",
}


def get_stock_name(stock_code: str) -> str | None:
    """
    종목코드 → 종목명. 우선순위:
    1) 내장 마스터  2) ETF 매핑  3) DART corpCode (실데이터)  4) None
    """
    code = (stock_code or "").replace(".KS", "").replace(".KQ", "").strip()
    # 내장 마스터 우선 (빠름)
    if code in STOCK_MASTER:
        return STOCK_MASTER[code]
    # KIS 마스터(collect-master) — ETF·전종목 실명 (가장 포괄적)
    nm = master_name(code)
    if nm:
        return nm
    if code in ETF_NAMES:
        return ETF_NAMES[code]
    # DART corpCode 역매핑 시도
    name = _dart_name(code)
    if name:
        return name
    return None


_DART_NAME_CACHE: dict | None = None

def _dart_name(stock_code: str) -> str | None:
    """DART corpCode.xml 역매핑 (코드→이름). 키 없으면 None."""
    global _DART_NAME_CACHE
    if _DART_NAME_CACHE is None:
        _DART_NAME_CACHE = {}
        try:
            import json
            import os
            cache_path = os.path.join(os.path.dirname(__file__), "corp_name_cache.json")
            if os.path.exists(cache_path):
                with open(cache_path) as f:
                    _DART_NAME_CACHE = json.load(f)
        except Exception:
            pass
    return _DART_NAME_CACHE.get(stock_code)


def get_stock_sector(stock_code: str) -> str | None:
    """종목코드 → 섹터 (알려진 경우)."""
    code = (stock_code or "").replace(".KS", "").replace(".KQ", "").strip()
    return STOCK_SECTOR.get(code)


def resolve_name(stock_code: str, fallback: bool = True) -> str:
    """종목명 해소 (항상 문자열 반환). Unknown Corp 박멸용."""
    name = get_stock_name(stock_code)
    if name:
        return name
    return f"종목 {stock_code}" if fallback else ""


# 실제 종목코드 리스트 (가짜 코드 대체용)
REAL_KOSPI_TICKERS = list(STOCK_MASTER.keys())


def search_stocks(q: str, limit: int = 20) -> list[dict]:
    """종목명/코드 부분일치 검색 → [{code, name}]. 검색엔진식 자동완성용.
    소스: DART corpCode 이름 캐시(전체 상장사) + 내장 마스터. 키 없으면 내장만."""
    q = (q or "").strip()
    if not q:
        return []
    _dart_name("__warm__")  # _DART_NAME_CACHE 로드 보장
    names: dict[str, str] = {}
    names.update(_DART_NAME_CACHE or {})
    names.update(ETF_NAMES)     # ETF (DART에 없음)
    # KIS 마스터(collect-master) 전종목 실명 — ETF·코스닥 포함 가장 포괄적
    try:
        for c, f in load_master_flags().items():
            if f.get("name"):
                names[c] = f["name"]
    except Exception:
        pass
    names.update(STOCK_MASTER)  # 내장 마스터 최우선(정확한 이름)
    ql = q.lower()
    scored: list[tuple] = []
    for code, name in names.items():
        nl = (name or "").lower()
        if code.startswith(q):
            score = 0           # 코드 시작 일치
        elif nl.startswith(ql):
            score = 1           # 이름 시작 일치
        elif ql in nl:
            score = 2           # 이름 부분 일치
        elif q in code:
            score = 3           # 코드 부분 일치
        else:
            continue
        scored.append((score, len(name or ""), code, name))
    scored.sort()
    return [{"code": c, "name": n} for _, _, c, n in scored[:limit]]


def build_corp_name_cache_from_dart() -> int:
    """
    DART corpCode.xml에서 {종목코드: 종목명} 캐시 생성.
    DART_API_KEY 설정 시 호출 → corp_name_cache.json 저장.
    Returns: 매핑된 종목 수.
    """
    import json
    import os
    api_key = os.getenv("DART_API_KEY", "")
    if not api_key:
        return 0
    try:
        import io
        import xml.etree.ElementTree as ET
        import zipfile

        import requests
        resp = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                            params={"crtfc_key": api_key}, timeout=30)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        root = ET.fromstring(zf.read(zf.namelist()[0]))
        mapping = {}
        for corp in root.iter("list"):
            stock = (corp.findtext("stock_code") or "").strip()
            name = (corp.findtext("corp_name") or "").strip()
            if stock and len(stock) == 6 and name:
                mapping[stock] = name
        cache_path = os.path.join(os.path.dirname(__file__), "corp_name_cache.json")
        with open(cache_path, "w") as f:
            json.dump(mapping, f, ensure_ascii=False)
        global _DART_NAME_CACHE
        _DART_NAME_CACHE = mapping
        logger.info(f"DART 종목명 캐시 생성: {len(mapping)}개")
        return len(mapping)
    except Exception as e:
        logger.warning(f"DART 종목명 캐시 실패: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# 데이터 품질 검증기 (Data Quality Validation)
# ═══════════════════════════════════════════════════════════════════════════════

# 필드별 합리적 범위 (이상치 탐지)
SANITY_RANGES: dict[str, tuple] = {
    "per":              (-1000, 1000),
    "pbr":              (0, 100),
    "roe_pct":          (-200, 200),
    "roa_pct":          (-100, 100),
    "debt_ratio_pct":   (0, 2000),
    "dividend_yield_pct": (0, 30),
    "operating_margin": (-200, 100),
    "net_margin":       (-200, 100),
    "gross_margin":     (-50, 100),
    "current_ratio":    (0, 2000),
    "altman_z":         (-10, 30),
    "gp_to_assets":     (-1, 5),
    "rsi_14":           (0, 100),
    "market_cap_억":    (0, 100_000_000),
}


def validate_item(item) -> dict:
    """
    단일 종목의 데이터 품질 검사.
    Returns: {"issues": [...], "score": 0~100, "missing": [...]}
    """
    issues, missing = [], []

    # 종목명 검증
    name = getattr(item, "corp_name", None)
    if not name or name == "Unknown Corp":
        issues.append("종목명 누락/미해소")

    # 범위 검증
    for field, (lo, hi) in SANITY_RANGES.items():
        val = getattr(item, field, None)
        if val is None:
            continue
        try:
            v = float(val)
            if v < lo or v > hi:
                issues.append(f"{field} 이상치: {v} (범위 {lo}~{hi})")
        except (ValueError, TypeError):
            issues.append(f"{field} 타입 오류: {val!r}")

    # 핵심 필드 결측 검사
    core_fields = ["per", "pbr", "roe_pct", "market_cap_억"]
    for f in core_fields:
        if getattr(item, f, None) is None:
            missing.append(f)

    # 논리 검증 (예: PBR>0인데 PER<0 가능하나, 둘 다 음수면 의심)
    per = getattr(item, "per", None)
    pbr = getattr(item, "pbr", None)
    if per is not None and pbr is not None:
        try:
            if float(pbr) < 0:
                issues.append("PBR 음수 (자본잠식 가능)")
        except (ValueError, TypeError):
            pass

    # 품질 점수 (이슈/결측 차감)
    score = max(0, 100 - len(issues) * 15 - len(missing) * 10)

    return {"issues": issues, "missing": missing, "score": score}


def validate_dataset(items: list) -> dict:
    """
    종목 리스트 전체의 데이터 품질 리포트.
    Returns: 요약 통계 + 문제 종목 목록.
    """
    if not items:
        return {"n_items": 0, "avg_score": 0, "issues_total": 0,
                "unknown_names": 0, "problem_items": [], "health": "no_data"}

    total_score, total_issues, unknown = 0, 0, 0
    problem_items = []

    for it in items:
        result = validate_item(it)
        total_score += result["score"]
        total_issues += len(result["issues"])
        name = getattr(it, "corp_name", None)
        if not name or name == "Unknown Corp":
            unknown += 1
        if result["issues"] or result["missing"]:
            problem_items.append({
                "stock_code": getattr(it, "stock_code", "?"),
                "corp_name": name or "?",
                "score": result["score"],
                "issues": result["issues"][:3],
                "missing": result["missing"],
            })

    n = len(items)
    avg_score = round(total_score / n, 1)
    health = ("excellent" if avg_score >= 90 else "good" if avg_score >= 75
              else "fair" if avg_score >= 60 else "poor")

    return {
        "n_items": n,
        "avg_score": avg_score,
        "issues_total": total_issues,
        "unknown_names": unknown,
        "unknown_pct": round(unknown / n * 100, 1),
        "problem_items": sorted(problem_items, key=lambda x: x["score"])[:20],
        "health": health,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# KIS 마스터파일 플래그 — 관리/감리(시장경고·투자주의환기)/거래정지/시총/업종
#   kis_master_parser.collect_master_files()가 save_master_flags()로 적재.
#   universe_select._status_codes()가 MANAGED_CODES/SUPERVISED_CODES를 소비(seam).
#   캐시 파일 없으면 빈 값 = 현행 no-op 동작 불변.
# ═══════════════════════════════════════════════════════════════════════════════

def _master_flags_path() -> str:
    import os
    return os.path.join(os.path.dirname(__file__), "master_flags_cache.json")


_MASTER_FLAGS: dict | None = None  # {"005930": {...}} (지연 로드)

# 관리 취급 = 관리종목 + 거래정지 + 정리매매 (매매 불가/위험 — 백테스트 안전 우선)
# 감리(투자주의) 취급 = 시장경고(01주의/02경고/03위험) + 투자주의환기(코스닥)
MANAGED_CODES: list[str] = []
SUPERVISED_CODES: list[str] = []


def save_master_flags(symbols: list[dict]) -> int:
    """파서 산출물(심볼 dict 리스트) → master_flags_cache.json. 저장 종목 수 반환."""
    import json
    from datetime import datetime
    stocks = {}
    for s in symbols:
        code = s.get("ticker")
        if not code:
            continue
        stocks[code] = {
            "name": s.get("name"),
            "market": s.get("market"),
            "isin": s.get("isin", ""),
            "group_code": s.get("group_code", ""),
            "is_etf": bool(s.get("is_etf")),
            "is_kospi200": bool(s.get("is_kospi200")),
            "is_kosdaq150": bool(s.get("is_kosdaq150")),
            "cap_size": s.get("cap_size", ""),
            "sector_code": s.get("sector_code", ""),
            "sector_mid": s.get("sector_mid", ""),
            "sector_sub": s.get("sector_sub", ""),
            "is_managed": bool(s.get("is_managed")),
            "alert_code": s.get("alert_code", "00"),
            "is_halted": bool(s.get("is_halted")),
            "is_clearing": bool(s.get("is_clearing")),
            "is_caution": bool(s.get("is_caution")),
            "market_cap_억": s.get("market_cap_억"),
        }
    payload = {
        "generated_at": datetime.now().isoformat(),
        "source": "kis_master",
        "stocks": stocks,
    }
    with open(_master_flags_path(), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    logger.info(f"master flags cached: {len(stocks)} symbols")
    return len(stocks)


def load_master_flags() -> dict:
    """캐시 파일 → {코드: 플래그 dict}. 없으면 {} (현행 동작 불변)."""
    global _MASTER_FLAGS
    if _MASTER_FLAGS is None:
        import json
        import os
        _MASTER_FLAGS = {}
        path = _master_flags_path()
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    _MASTER_FLAGS = json.load(f).get("stocks", {}) or {}
        except Exception as e:
            logger.warning(f"master flags cache load failed: {e}")
    return _MASTER_FLAGS


def master_name(stock_code: str) -> str | None:
    """KIS 마스터 플래그 캐시의 종목명 (collect-master 적재 시 — ETF·전종목 실명)."""
    f = load_master_flags().get((stock_code or "").strip())
    return (f or {}).get("name") if f else None


def build_master_universe(kind: str) -> list[str]:
    """KIS 마스터(collect-master 적재) 기반 유니버스 코드 목록. 미적재 시 []."""
    flags = load_master_flags()
    if not flags:
        return []
    items = list(flags.items())

    def mkt(f):
        return (f.get("market") or "").upper()

    def grp(f):
        return f.get("group_code") or ""

    def mcap(f):
        return f.get("market_cap_억") or 0

    def _topn(market: str, n: int) -> list[str]:
        rows = [(c, f) for c, f in items if mkt(f) == market and grp(f) == "ST"]
        rows.sort(key=lambda x: mcap(x[1]), reverse=True)
        return [c for c, _ in rows[:n]]

    if kind in ("etf",):
        return [c for c, f in items if f.get("is_etf") or grp(f) in ("EF", "EN")]
    if kind == "kospi":
        return [c for c, f in items if mkt(f) == "KOSPI" and grp(f) == "ST"]
    if kind == "kosdaq":
        return [c for c, f in items if mkt(f) == "KOSDAQ" and grp(f) == "ST"]
    if kind in ("all", "all_listed"):
        return [c for c, f in items if grp(f) == "ST"]
    if kind == "kospi200":
        flagged = [c for c, f in items if f.get("is_kospi200")]
        return flagged if 150 <= len(flagged) <= 260 else _topn("KOSPI", 200)
    if kind == "kosdaq150":
        flagged = [c for c, f in items if f.get("is_kosdaq150")]
        return flagged if 100 <= len(flagged) <= 200 else _topn("KOSDAQ", 150)
    return []


def _refresh_status_lists() -> None:
    """플래그 → MANAGED_CODES/SUPERVISED_CODES 모듈 변수 갱신 (리스트 제자리 교체)."""
    flags = load_master_flags()
    managed = [c for c, f in flags.items()
               if f.get("is_managed") or f.get("is_halted") or f.get("is_clearing")]
    supervised = [c for c, f in flags.items()
                  if (f.get("alert_code") or "00") != "00" or f.get("is_caution")]
    MANAGED_CODES[:] = managed
    SUPERVISED_CODES[:] = supervised


def reload_master_flags() -> int:
    """캐시 재로드 + 상태 리스트 갱신 + universe_select 캐시 무효화. 종목 수 반환."""
    global _MASTER_FLAGS
    _MASTER_FLAGS = None
    flags = load_master_flags()
    _refresh_status_lists()
    try:
        from src.engine.universe_select import _status_codes, load_universe_frame
        _status_codes.cache_clear()
        load_universe_frame.cache_clear()
    except Exception:
        pass
    return len(flags)


# import 시 1회 로드 — 캐시 파일이 있으면 관리/감리 자동 활성 (없으면 no-op)
try:
    _refresh_status_lists()
except Exception:
    pass
