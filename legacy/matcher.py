"""사용자 필터 매칭.

매칭 규칙 (MVP):
  지역   - 하나라도 걸리면 통과 (OR). 비어 있으면 지역 조건 없음.
  키워드 - 하나라도 걸리면 통과 (OR). 비어 있으면 아무것도 보내지 않는다.
           (키워드 없는 사용자에게 전국 공고를 다 쏘면 즉시 차단당한다)
  제외   - 하나라도 걸리면 탈락. 제외가 항상 이긴다.
"""
import sqlite3
from typing import Any

from .sources.base import normalize


def matches(job: sqlite3.Row, flt: dict[str, Any]) -> bool:
    haystack = job["haystack"] or ""
    region_text = normalize(job["region"] or "")

    for ex in flt["excludes"]:
        if normalize(ex) and normalize(ex) in haystack:
            return False

    regions = [normalize(r) for r in flt["regions"] if normalize(r)]
    if regions:
        # 사용자가 "판교"라고 쓰든 "판교·분당"(그룹명)이라고 쓰든 걸리게 한다.
        area_text = normalize(job["area"] or "")
        target = f"{region_text} {area_text}"
        if not any(r in target for r in regions):
            return False

    keywords = [normalize(k) for k in flt["keywords"] if normalize(k)]
    if not keywords:
        return False
    return any(k in haystack for k in keywords)


def score(job: sqlite3.Row, flt: dict[str, Any]) -> int:
    """키워드가 여러 개 걸릴수록 위로. 제목에 걸리면 가산점."""
    haystack = job["haystack"] or ""
    title = normalize(job["title"] or "")
    s = 0
    for k in flt["keywords"]:
        nk = normalize(k)
        if not nk:
            continue
        if nk in title:
            s += 3
        elif nk in haystack:
            s += 1
    return s


def select_for(jobs: list[sqlite3.Row], flt: dict[str, Any]) -> list[sqlite3.Row]:
    hits = [j for j in jobs if matches(j, flt)]
    hits.sort(key=lambda j: score(j, flt), reverse=True)
    return hits
