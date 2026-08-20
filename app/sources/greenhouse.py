"""Greenhouse 채용보드 공개 API 어댑터.

엔드포인트: https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
인증: 없음. 기업이 자사 채용페이지를 임베드하라고 공개하는 공식 Job Board API 다.
      승인·키·쿼터 협의가 필요 없어서 지금 당장 돌릴 수 있는 유일한 소스.

스크래핑이 아니다: HTML 을 긁는 게 아니라 Greenhouse 가 문서화한 JSON 을 읽는다.
보드 토큰은 각 기업 채용페이지 URL(boards.greenhouse.io/<토큰>)에 그대로 드러나 있다.

한계: 그 기업이 Greenhouse 를 쓸 때만 잡힌다. 워크넷·사람인처럼 전체를 훑지 못하니
보조 소스로 쓰고, 회사 목록(GREENHOUSE_BOARDS)을 직접 관리해야 한다.
"""
from __future__ import annotations

import html
import logging
import re

import httpx

from .base import Job

log = logging.getLogger(__name__)

BOARD_API = "https://boards-api.greenhouse.io/v1/boards/{board}"

# 지역 게이트(regions.py)는 한글 지명에 부분일치시킨다. Greenhouse 는 근무지를
# "Seoul, Korea", "Pangyo" 처럼 영문으로 주므로 여기서 한글로 옮겨준다.
# 판정 권한은 regions.py 에 그대로 두고, 이 어댑터는 표기만 맞춘다.
_LOC_MAP = (
    ("pangyo", "판교"),
    ("bundang", "분당"),
    ("seongnam", "성남"),
    ("gwacheon", "과천"),
    ("anyang", "안양"),
    ("yongin", "용인"),
    ("suji", "수지"),
    ("giheung", "기흥"),
    ("hanam", "하남"),
    ("gwangmyeong", "광명"),
    ("seoul", "서울"),
)

_TAG = re.compile(r"<[^>]+>")


def _plain(content: str, limit: int = 4000) -> str:
    """공고 본문 HTML 을 키워드 매칭용 평문으로. 길이는 잘라서 DB 를 아낀다."""
    if not content:
        return ""
    text = _TAG.sub(" ", html.unescape(content))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _region(location: str) -> str:
    """영문 근무지를 지역 게이트가 읽는 한글 표기로 바꾼다."""
    low = (location or "").lower()
    hits = [ko for en, ko in _LOC_MAP if en in low]
    if not hits:
        return location or ""
    # "Seoul; Pangyo" 처럼 여러 곳이 붙는 경우가 있어 전부 남긴다.
    return " ".join(dict.fromkeys(hits))


class GreenhouseSource:
    name = "greenhouse"

    def __init__(self, boards, timeout: float = 20.0):
        self.boards = [b.strip() for b in boards if b and b.strip()]
        self.timeout = timeout

    def fetch_recent(self, max_pages: int = 1) -> list[Job]:
        """보드별로 한 번씩 호출한다. 이 API 는 전체 목록을 한 응답에 준다.

        max_pages 는 인터페이스를 맞추려고 받기만 하고 쓰지 않는다.
        """
        jobs: list[Job] = []
        with httpx.Client(timeout=self.timeout) as client:
            for board in self.boards:
                try:
                    company = self._company_name(client, board)
                    resp = client.get(BOARD_API.format(board=board) + "/jobs",
                                      params={"content": "true"})
                    resp.raise_for_status()
                    batch = self._parse(board, company, resp.json())
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    # 한 회사가 보드를 닫아도 나머지는 계속 돈다.
                    log.warning("greenhouse %s 실패: %s", board, e)
                    continue
                log.debug("greenhouse %s: %d건", board, len(batch))
                jobs.extend(batch)
        log.info("greenhouse %d개 보드에서 %d건 수집", len(self.boards), len(jobs))
        return jobs

    def _company_name(self, client, board: str) -> str:
        try:
            r = client.get(BOARD_API.format(board=board))
            r.raise_for_status()
            return (r.json().get("name") or board).strip()
        except (httpx.HTTPError, ValueError):
            return board

    def _parse(self, board: str, company: str, payload: dict) -> list[Job]:
        out = []
        for it in payload.get("jobs") or []:
            source_id = str(it.get("id") or "")
            title = (it.get("title") or "").strip()
            if not source_id or not title:
                continue
            location = ((it.get("location") or {}).get("name") or "").strip()
            out.append(Job(
                source=self.name,
                source_id="{}:{}".format(board, source_id),
                title=title,
                company=company,
                url=it.get("absolute_url", ""),
                region=_region(location),
                posted_at=(it.get("updated_at") or "")[:10],
                extra={
                    "board": board,
                    "location_raw": location,
                    "description": _plain(it.get("content") or ""),
                },
            ))
        return out
