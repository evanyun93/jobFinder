"""잡코리아 채용정보 XML 어댑터.

다른 두 소스와 다른 점: 엔드포인트가 고정이 아니다.
잡코리아는 승인 후 요청한 IP를 등록하고 **고유 호출 링크**를 발급하며,
XML 태그 구조는 그때 가이드로 함께 전달된다. 그래서 이 어댑터는
엔드포인트와 필드 매핑을 둘 다 설정으로 받는다.

신청: https://www.jobkorea.co.kr/service/api  (문의 api@jobkorea.co.kr)
  - 공공기관·학교 우선 제공. 개인/일반기업은 내부 검토 후 거절될 수 있다.
  - 업데이트 주기 2시간, 조건 설정 시 최대 500건.

발급받은 뒤 할 일:
  1) .env 에 JOBKOREA_FEED_URL 을 넣는다
  2) `python -m app.main probe jobkorea` 로 실제 태그 이름을 확인한다
  3) 아래 DEFAULT_FIELD_MAP 이 안 맞으면 .env 의 JOBKOREA_FIELD_MAP 에
     JSON 으로 덮어쓴다. 예:
     JOBKOREA_FIELD_MAP={"title":"GI_Title","company":"GI_CoNm"}
"""
import json
import logging
import xml.etree.ElementTree as ET

import httpx

from .base import Job

log = logging.getLogger(__name__)

# 실제 태그 이름을 모르므로 후보를 여러 개 두고 먼저 걸리는 걸 쓴다.
# probe 로 확인한 뒤 정확한 이름 하나로 좁히는 게 좋다.
DEFAULT_FIELD_MAP: dict[str, list[str]] = {
    "source_id": ["GI_No", "GINo", "No", "JobNo", "Id", "id"],
    "title":     ["Title", "GI_Title", "JobTitle", "Subject", "title"],
    "company":   ["Company", "GI_CoNm", "CoNm", "CompanyName", "Corp", "company"],
    "url":       ["Url", "GI_Url", "Link", "JobUrl", "DetailUrl", "url"],
    "region":    ["Local", "Region", "Area", "WorkArea", "Location", "local"],
    "salary":    ["Salary", "Sal", "Pay", "salary"],
    "career":    ["Career", "Exp", "Experience", "career"],
    "education": ["Edu", "Education", "School", "edu"],
    "posted_at": ["RegDate", "StartDate", "OpenDate", "regDate"],
    "closes_at": ["EndDate", "CloseDate", "Deadline", "endDate"],
}


def _index_children(node: ET.Element) -> dict[str, str]:
    """자식 태그를 {소문자태그명: 텍스트} 로 평탄화. 네임스페이스는 떼어낸다."""
    out: dict[str, str] = {}
    for child in node.iter():
        if child is node:
            continue
        tag = child.tag.split("}")[-1].lower()
        text = (child.text or "").strip()
        if text and tag not in out:
            out[tag] = text
    return out


def _pick(flat: dict[str, str], candidates: list[str] | str) -> str:
    if isinstance(candidates, str):
        candidates = [candidates]
    for c in candidates:
        v = flat.get(c.lower())
        if v:
            return v
    return ""


def find_record_element(root: ET.Element) -> str | None:
    """반복되는 레코드 태그를 찾는다.

    기준은 (등장 횟수, 깊이) 순. 깊이를 타이브레이크로 쓰는 이유:
    레코드가 1건뿐인 응답에서는 <list> 와 <job> 의 등장 횟수가 똑같이 1이라
    횟수만 보면 감싸는 컨테이너를 레코드로 착각한다. 더 깊은 쪽이 레코드다.
    """
    stats: dict[str, list[int]] = {}   # tag -> [count, max_depth]

    def walk(node: ET.Element, depth: int) -> None:
        for child in node:
            if len(list(child)) > 0:
                tag = child.tag.split("}")[-1]
                cur = stats.setdefault(tag, [0, depth])
                cur[0] += 1
                cur[1] = max(cur[1], depth)
            walk(child, depth + 1)

    walk(root, 1)
    if not stats:
        return None
    return max(stats.items(), key=lambda kv: (kv[1][0], kv[1][1]))[0]


class JobkoreaSource:
    name = "jobkorea"

    def __init__(self, feed_url: str, field_map: dict | None = None,
                 timeout: float = 20.0):
        self.feed_url = feed_url
        self.field_map = {**DEFAULT_FIELD_MAP, **(field_map or {})}
        self.timeout = timeout

    def fetch_raw(self) -> str:
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as c:
            resp = c.get(self.feed_url)
            resp.raise_for_status()
            return resp.text

    def fetch_recent(self, max_pages: int = 1) -> list[Job]:
        # 잡코리아 피드는 페이지네이션 없이 한 번에 최대 500건을 내려준다.
        try:
            jobs = self._parse(self.fetch_raw())
        except (httpx.HTTPError, ET.ParseError) as e:
            log.warning("jobkorea 수집 실패: %s", e)
            return []
        log.info("jobkorea %d건 수집", len(jobs))
        return jobs

    def _parse(self, xml_text: str) -> list[Job]:
        root = ET.fromstring(xml_text)

        for tag in (".//errMsg", ".//error", ".//ErrorMessage"):
            err = root.find(tag)
            if err is not None and (err.text or "").strip():
                raise RuntimeError(f"잡코리아 API 오류: {err.text.strip()}")

        record_tag = find_record_element(root)
        if not record_tag:
            log.warning("jobkorea: 레코드 태그를 못 찾았습니다. "
                        "`python -m app.main probe jobkorea` 로 구조를 확인하세요.")
            return []

        out = []
        unmapped_warned = False
        for node in root.iter():
            if node.tag.split("}")[-1] != record_tag:
                continue
            flat = _index_children(node)

            title = _pick(flat, self.field_map["title"])
            company = _pick(flat, self.field_map["company"])
            if not title:
                if not unmapped_warned:
                    log.warning(
                        "jobkorea: 제목 필드를 못 찾았습니다. 실제 태그: %s → "
                        ".env 의 JOBKOREA_FIELD_MAP 을 설정하세요.",
                        ", ".join(sorted(flat)[:15]),
                    )
                    unmapped_warned = True
                continue

            source_id = _pick(flat, self.field_map["source_id"])
            if not source_id:
                # 번호 필드가 없으면 URL 을, 그것도 없으면 제목+회사로 대체
                source_id = _pick(flat, self.field_map["url"]) or f"{company}|{title}"

            out.append(Job(
                source=self.name,
                source_id=source_id,
                title=title,
                company=company,
                url=_pick(flat, self.field_map["url"]),
                region=_pick(flat, self.field_map["region"]),
                salary=_pick(flat, self.field_map["salary"]),
                career=_pick(flat, self.field_map["career"]),
                education=_pick(flat, self.field_map["education"]),
                posted_at=_pick(flat, self.field_map["posted_at"]),
                closes_at=_pick(flat, self.field_map["closes_at"]),
            ))
        return out


def parse_field_map(raw: str) -> dict:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("JOBKOREA_FIELD_MAP 이 올바른 JSON 이 아닙니다: %s", e)
        return {}
