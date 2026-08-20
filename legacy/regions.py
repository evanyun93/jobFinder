"""대상 지역 화이트리스트 — 서울 + 판교 생활권.

여기 없는 지역의 공고는 수집 단계에서 버린다. DB에 안 쌓이고, 매칭도 안 하고,
다이제스트에도 안 나온다.

범위를 바꾸려면 AREAS 만 고치면 된다. 키가 다이제스트에 표시되는 그룹명이고,
값은 공고의 근무지역 문자열에 부분일치시킬 패턴들이다.

근무지역 문자열 예시:
  워크넷  "경기 성남시", "서울 강남구"
  사람인  "서울 > 관악구,서울 > 광진구"
"""
from .sources.base import normalize

AREAS: dict[str, tuple[str, ...]] = {
    "서울": ("서울",),
    "판교·분당": ("판교", "분당", "성남"),
    "수지·기흥": ("수지", "기흥"),          # 신분당선으로 판교 연결
    "과천·평촌": ("과천", "평촌", "안양"),
    "서울 인접": ("하남", "광명", "구리", "남양주"),
}

# 지역명이지만 대상에서 빼야 하는 것들.
# 예: "용인시 처인구"는 기흥/수지와 달리 판교 생활권이 아니다.
EXCLUDE = ("처인",)

_NORM_AREAS = {label: tuple(normalize(p) for p in pats) for label, pats in AREAS.items()}
_NORM_EXCLUDE = tuple(normalize(p) for p in EXCLUDE)


def area_of(region_text: str) -> str | None:
    """근무지역 문자열이 대상 지역이면 그룹명을, 아니면 None 을 돌려준다."""
    t = normalize(region_text)
    if not t:
        return None
    if any(x in t for x in _NORM_EXCLUDE):
        return None
    for label, patterns in _NORM_AREAS.items():
        if any(p in t for p in patterns):
            return label
    return None


def is_covered(region_text: str) -> bool:
    return area_of(region_text) is not None


def all_labels() -> list[str]:
    return list(AREAS.keys())


def describe() -> str:
    """봇 안내문에 넣을 지역 목록."""
    return " / ".join(AREAS.keys())
