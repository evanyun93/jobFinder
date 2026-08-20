"""사람인 오픈API 어댑터.

엔드포인트: https://oapi.saramin.co.kr/job-search
발급: https://oapi.saramin.co.kr/join (이용신청 → 승인 → access-key)
쿼터: 일 500회

라이선스 메모: 사람인 약관은 "API를 사용한 서비스의 재판매 또는 이용요금
발생"과 "이용자로부터 이용에 대한 대가를 제공받는 행위"를 금지한다.
이 서비스는 무료라서 문제없다. 나중에 과금을 붙일 생각이 생기면 이 파일을
먼저 지우거나 사람인과 제휴 계약(api@saramin.co.kr)을 맺을 것.
"""
import logging

import httpx

from .base import Job

log = logging.getLogger(__name__)

ENDPOINT = "https://oapi.saramin.co.kr/job-search"
PAGE_SIZE = 100


class SaraminSource:
    name = "saramin"

    def __init__(self, access_key: str, timeout: float = 20.0):
        self.access_key = access_key
        self.timeout = timeout

    def fetch_recent(self, max_pages: int = 5) -> list[Job]:
        jobs: list[Job] = []
        with httpx.Client(timeout=self.timeout) as client:
            for page in range(max_pages):
                params = {
                    "access-key": self.access_key,
                    "count": PAGE_SIZE,
                    "start": page,
                    "sort": "pd",  # 등록일 최신순
                    "fields": "posting-date,expiration-date,keyword-code,count",
                }
                try:
                    resp = client.get(ENDPOINT, params=params,
                                      headers={"Accept": "application/json"})
                    resp.raise_for_status()
                    batch = self._parse(resp.json())
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    log.warning("saramin page %s 실패: %s", page, e)
                    break

                if not batch:
                    break
                jobs.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
        log.info("saramin %d건 수집", len(jobs))
        return jobs

    def _parse(self, payload: dict) -> list[Job]:
        items = (payload.get("jobs") or {}).get("job") or []
        out = []
        for it in items:
            pos = it.get("position") or {}
            source_id = str(it.get("id") or "")
            title = (pos.get("title") or "").strip()
            if not source_id or not title:
                continue
            out.append(Job(
                source=self.name,
                source_id=source_id,
                title=title,
                company=((it.get("company") or {}).get("detail") or {}).get("name", ""),
                url=it.get("url", ""),
                region=(pos.get("location") or {}).get("name", ""),
                salary=(it.get("salary") or {}).get("name", ""),
                career=(pos.get("experience-level") or {}).get("name", ""),
                education=(pos.get("required-education-level") or {}).get("name", ""),
                posted_at=it.get("posting-date", ""),
                closes_at=it.get("expiration-date", ""),
                extra={
                    "industry": (pos.get("industry") or {}).get("name", ""),
                    "keyword": it.get("keyword", ""),
                },
            ))
        return out
