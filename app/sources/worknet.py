"""워크넷 채용정보 오픈API 어댑터.

엔드포인트: http://openapi.work.go.kr/opi/opi/opia/wantedApi.do
인증키: openapi.work.go.kr '채용정보' 활용신청 → UUID 형식 authKey (data.go.kr 의 serviceKey 아님)
쿼터: 일 1000회. 페이지당 100건이면 하루 10만건까지 커버 가능.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from .base import Job, SourceConfigError

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
                msg = err.text.strip()
                code_el = root.find(".//messageCd")
                code = (code_el.text or "").strip() if code_el is not None else ""
                if code == "002":
                    raise SourceConfigError(
                        "워크넷 인증키가 거부됐습니다 ({}).\n"
                        "  .env 의 WORKNET_AUTH_KEY 를 확인하세요. 이 어댑터가 쓰는 키는\n"
                        "  워크넷 오픈API(openapi.work.go.kr) 가 발급하는 UUID 형식이며,\n"
                        "  공공데이터포털(data.go.kr) 의 serviceKey 와는 다른 값입니다.\n"
                        "  발급 직후라면 승인 반영까지 시간이 걸릴 수 있습니다.".format(msg))
                raise RuntimeError("워크넷 API 오류: {}{}".format(
                    msg, " (코드 {})".format(code) if code else ""))

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
