"""잡코리아 채용정보 API 어댑터.

인증: 신청 → 내부 검토·승인 → IP 등록 후 '고유 호출 링크' 발급 (api@jobkorea.co.kr)
      https://www.jobkorea.co.kr/service/api

주의 하나: 다른 두 소스와 달리 엔드포인트가 고정이 아니다. 승인 시 계정마다
다른 URL 을 가이드와 함께 받으므로, 코드에 박지 않고 .env 의 JOBKOREA_API_URL
로 통째로 주입받는다. 업직종·지역·학력 같은 조건과 페이징도 그 URL 의
쿼리스트링에 이미 들어 있으니 여기서 파라미터를 덧붙이지 않는다.

또 하나: 호출 IP 가 등록된 IP 와 달라지면 거부된다. 가정용 회선처럼 IP 가
바뀌는 환경이면 재등록이 필요하다.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from .base import Job, SourceConfigError

log = logging.getLogger(__name__)

# 근무지역이 AreaCode(코드값)로만 오는 경우를 위한 변환표.
# 지역 게이트(regions.py)는 "서울", "판교" 같은 문자열에 부분일치시키므로
# 코드를 그대로 넘기면 전 건이 대상지역 밖으로 떨어진다.
#
# 코드표는 승인 시 함께 받는 가이드에 있다. 받는 즉시 여기를 채울 것.
# 비어 있어도 동작은 한다 — 아래 _region() 이 텍스트 지역 태그를 먼저 보고,
# 변환 못 한 코드는 로그에 모아서 찍어준다.
AREA_CODES: dict[str, str] = {
    # "I000": "서울",
    # "B000": "경기 성남시 분당구",
}

# 근무지역이 텍스트로 오는 경우 쓰이는 태그 후보들.
# 공식 샘플에는 AreaCode 만 있지만 실제 피드에 텍스트가 함께 오는 경우가 있어
# 먼저 훑는다. 있으면 코드표 없이도 바로 돈다.
_AREA_TEXT_TAGS = ("Area", "AreaName", "GI_Area", "Local", "LocalName")


def _text(node: ET.Element, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _first(node: ET.Element, tags) -> str:
    for tag in tags:
        v = _text(node, tag)
        if v:
            return v
    return ""


class JobkoreaSource:
    name = "jobkorea"

    def __init__(self, api_url: str, timeout: float = 20.0):
        self.api_url = api_url
        self.timeout = timeout
        self._unmapped_codes: set = set()

    def fetch_recent(self, max_pages: int = 1) -> list[Job]:
        """발급받은 링크를 그대로 한 번 호출한다.

        max_pages 는 받지만 쓰지 않는다. 이 API 는 조건 미설정 시 최대 100건,
        조건 설정 시 최대 500건을 한 응답에 담아 주고 페이징 파라미터는 발급
        URL 쪽에 있기 때문이다. 인터페이스를 맞추려고 인자만 유지한다.
        """
        self._unmapped_codes.clear()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.api_url)
            resp.raise_for_status()
            jobs = self._parse(resp.text)

        if self._unmapped_codes:
            log.warning(
                "jobkorea: AREA_CODES 에 없는 지역코드 %d종이 나왔습니다 -> %s. "
                "sources/jobkorea.py 의 AREA_CODES 를 승인 가이드의 코드표로 "
                "채우세요. 지금은 이 코드의 공고가 전부 대상지역 밖으로 떨어집니다.",
                len(self._unmapped_codes), ", ".join(sorted(self._unmapped_codes)[:20]))

        log.info("jobkorea %d건 수집", len(jobs))
        return jobs

    def _region(self, item: ET.Element) -> str:
        """지역 게이트가 읽을 수 있는 문자열을 만든다."""
        text = _first(item, _AREA_TEXT_TAGS)
        if text:
            return text

        code = _text(item, "AreaCode")
        if not code:
            return ""
        mapped = AREA_CODES.get(code)
        if mapped:
            return mapped
        self._unmapped_codes.add(code)
        return ""

    def _parse(self, xml_text: str) -> list[Job]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            # 승인 전이거나 IP 가 안 맞으면 XML 대신 HTML 오류/로그인 페이지가 온다.
            raise SourceConfigError(
                "잡코리아 응답이 XML 이 아닙니다 ({}).\n"
                "  .env 의 JOBKOREA_API_URL 이 승인 후 발급받은 고유 호출 링크인지,\n"
                "  그리고 지금 나가는 공인 IP 가 등록한 IP 와 같은지 확인하세요.\n"
                "  문의: api@jobkorea.co.kr".format(e))

        if root.tag != "DataList" and root.find(".//Items") is None:
            raise SourceConfigError(
                "잡코리아 응답에 DataList/Items 가 없습니다 (루트: {}).\n"
                "  발급 링크가 채용정보 API 가 맞는지 가이드와 대조하고,\n"
                "  로그인/오류 페이지가 온 것이라면 등록 IP 와 현재 공인 IP 가\n"
                "  같은지 확인하세요. 문의: api@jobkorea.co.kr".format(root.tag))

        out = []
        for item in root.findall(".//Items"):
            source_id = _text(item, "GI_No")
            title = _text(item, "GI_Subject")
            if not source_id or not title:
                continue

            # 급여는 비공개 플래그가 서 있으면 숫자가 의미 없다.
            pay = _text(item, "GI_Pay")
            if _text(item, "GI_Pay_Flag") in ("N", "0", "false"):
                pay = ""
            elif pay and _text(item, "GI_Pay_Term"):
                pay = "{} {}".format(_text(item, "GI_Pay_Term"), pay)

            career = _text(item, "GI_Career")
            years = _text(item, "GI_Career_Year_Cnt")
            if years and years != "0":
                career = "{} {}년".format(career, years).strip()

            out.append(Job(
                source=self.name,
                source_id=source_id,
                title=title,
                company=_text(item, "C_Name"),
                url=_text(item, "JK_URL"),
                region=self._region(item),
                salary=pay,
                career=career,
                education=_text(item, "GI_EDU_CutLine") or _text(item, "GI_Edu_Options"),
                posted_at=_text(item, "GI_W_Date"),
                closes_at=_text(item, "GI_End_Date") or _text(item, "GI_E_Date"),
                extra={
                    "keyword": _text(item, "GI_Keyword"),
                    "job_type": _text(item, "GI_Job_Type"),
                    "jikgub": _text(item, "Jikgub"),
                    "company_url": _text(item, "C_URL"),
                },
            ))
        return out
