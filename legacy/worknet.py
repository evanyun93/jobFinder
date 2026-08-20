"""워크넷 채용정보 오픈API 어댑터.

엔드포인트: http://openapi.work.go.kr/opi/opi/opia/wantedApi.do
인증키: 공공데이터포털 '한국고용정보원_워크넷 채용정보 채용목록 및 상세정보' 활용신청 (자동승인)
쿼터: 일 1000회. 페이지당 100건이면 하루 10만건까지 커버 가능.
"""
import logging
import xml.etree.ElementTree as ET

import httpx

from .base import Job

log = logging.getLogger(__name__)

ENDPOINT = "http://openapi.work.go.kr/opi/opi/opia/wantedApi.do"
PAGE_SIZE = 100


def _text(node: ET.Element, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


class WorknetSource:
    name = "worknet"

    def __init__(self, auth_key: str, timeout: float = 20.0):
        self.auth_key = auth_key
        self.timeout = timeout

    def fetch_recent(self, max_pages: int = 20) -> list[Job]:
        jobs: list[Job] = []
        with httpx.Client(timeout=self.timeout) as client:
            for page in range(1, max_pages + 1):
                params = {
                    "authKey": self.auth_key,
                    "callTp": "L",          # L = 목록
                    "returnType": "XML",
                    "startPage": page,
                    "display": PAGE_SIZE,
                    "sortOrderBy": "DESC",  # 최신순
                }
                try:
                    resp = client.get(ENDPOINT, params=params)
                    resp.raise_for_status()
                    batch = self._parse(resp.text)
                except (httpx.HTTPError, ET.ParseError) as e:
                    log.warning("worknet page %s 실패: %s", page, e)
                    break

                if not batch:
                    break
                jobs.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
        log.info("worknet %d건 수집", len(jobs))
        return jobs

    def _parse(self, xml_text: str) -> list[Job]:
        root = ET.fromstring(xml_text)

        # 인증 실패 등은 에러 노드로 온다. 조용히 넘기면 "왜 알림이 안 오지"로 이어진다.
        # 주의: ElementTree 의 Element 는 자식이 없으면 falsy 라서 `a or b` 로 쓰면 안 된다.
        for tag in (".//errMsg", ".//message", ".//error"):
            err = root.find(tag)
            if err is not None and (err.text or "").strip():
                raise RuntimeError(f"워크넷 API 오류: {err.text.strip()}")

        out = []
        for w in root.findall(".//wanted"):
            source_id = _text(w, "wantedAuthNo")
            title = _text(w, "title")
            if not source_id or not title:
                continue
            out.append(Job(
                source=self.name,
                source_id=source_id,
                title=title,
                company=_text(w, "company"),
                url=_text(w, "wantedInfoUrl") or _text(w, "wantedMobileInfoUrl"),
                region=_text(w, "region"),
                salary=_text(w, "sal") or _text(w, "salTpNm"),
                career=_text(w, "career"),
                education=_text(w, "minEdubg"),
                posted_at=_text(w, "regDt"),
                closes_at=_text(w, "closeDt"),
                extra={"provider": _text(w, "infoSvc")},
            ))
        return out
