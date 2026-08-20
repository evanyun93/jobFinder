"""소스 어댑터 인터페이스.

새 채용 소스를 붙일 때 이 파일만 보면 되도록 유지한다.
규칙 하나: 여기에 붙이는 소스는 반드시 공식 API 이거나 제공자가 배포를
허용한 피드여야 한다. HTML 스크래핑 어댑터는 이 저장소에 들어오지 않는다.
(잡코리아-사람인 판결: 대법원 2017다224395)
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import Protocol

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[\[\]()（）【】·・,\-_/|]+")


def normalize(text: str) -> str:
    t = (text or "").lower()
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


@dataclass
class Job:
    source: str
    source_id: str
    title: str
    company: str
    url: str = ""
    region: str = ""
    salary: str = ""
    career: str = ""
    education: str = ""
    posted_at: str = ""
    closes_at: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        """소스가 달라도 같은 공고면 같은 키가 나오게 한다.
        회사명+직무명 정규화 해시. 완벽하진 않지만 오탐보다 중복발송이 더 짜증난다."""
        basis = f"{normalize(self.company)}|{normalize(self.title)}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    def haystack(self) -> str:
        """키워드 매칭 대상 텍스트."""
        parts = [self.title, self.company, self.region, self.career,
                 self.education, self.extra.get("industry", "")]
        return normalize(" ".join(p for p in parts if p))


class JobSource(Protocol):
    name: str

    def fetch_recent(self, max_pages: int) -> list[Job]:
        """최근 등록 공고를 가져온다. 사용자별 필터는 여기서 하지 않는다.
        하루 한 번 넓게 긁어 DB에 쌓고, 매칭은 로컬에서 한다 — 사용자가 늘어도
        API 호출량이 늘지 않는 구조."""
        ...
