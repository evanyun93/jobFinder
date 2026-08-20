"""피드 구조 탐색기.

`python -m app.main probe jobkorea` 로 실행한다.
실제 응답을 받아 태그 구조와 첫 레코드의 값들을 찍어주고,
DEFAULT_FIELD_MAP 이 뭘 잡고 뭘 놓쳤는지 보여준다.

잡코리아처럼 스키마를 미리 알 수 없는 피드를 붙일 때 쓴다.
"""
import xml.etree.ElementTree as ET

from .config import cfg
from .sources.jobkorea import (
    DEFAULT_FIELD_MAP,
    JobkoreaSource,
    _index_children,
    _pick,
    find_record_element,
    parse_field_map,
)


def probe_jobkorea() -> int:
    if not cfg.jobkorea_url:
        print("JOBKOREA_FEED_URL 이 .env 에 없습니다.")
        print("잡코리아 승인 후 발급받은 고유 호출 링크를 넣으세요.")
        return 1

    src = JobkoreaSource(cfg.jobkorea_url, parse_field_map(cfg.jobkorea_field_map))

    print(f"요청: {cfg.jobkorea_url}\n")
    try:
        raw = src.fetch_raw()
    except Exception as e:
        print(f"요청 실패: {e}")
        print("\n승인 시 등록한 IP 에서 실행 중인지 확인하세요. "
              "잡코리아는 IP 화이트리스트로 접근을 제한합니다.")
        return 1

    print("=" * 60)
    print("원본 응답 앞부분")
    print("=" * 60)
    print(raw[:1200])
    print("...\n")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"XML 파싱 실패: {e}")
        print("응답이 XML 이 아닐 수 있습니다. 위 원본을 확인하세요.")
        return 1

    record_tag = find_record_element(root)
    records = [n for n in root.iter() if n.tag.split("}")[-1] == record_tag]
    print("=" * 60)
    print(f"루트 태그: <{root.tag.split('}')[-1]}>")
    print(f"레코드 태그: <{record_tag}>  ({len(records)}건)")
    print("=" * 60)

    if not records:
        print("레코드가 없습니다. 조건 파라미터를 확인하세요.")
        return 1

    flat = _index_children(records[0])
    print("\n첫 레코드의 모든 필드:\n")
    for tag, val in sorted(flat.items()):
        shown = val if len(val) <= 60 else val[:60] + "…"
        print(f"  {tag:22} = {shown}")

    print("\n" + "=" * 60)
    print("현재 매핑 결과 (✓ 성공 / ✗ 실패)")
    print("=" * 60)
    missing = []
    for field, candidates in DEFAULT_FIELD_MAP.items():
        val = _pick(flat, src.field_map[field])
        if val:
            hit = next(c for c in (src.field_map[field] if isinstance(src.field_map[field], list)
                                   else [src.field_map[field]]) if flat.get(c.lower()))
            print(f"  ✓ {field:12} ← <{hit}>")
        else:
            print(f"  ✗ {field:12} 매칭 실패")
            missing.append(field)

    if missing:
        print("\n실패한 필드는 위 '첫 레코드의 모든 필드' 목록에서 해당 태그를 찾아")
        print(".env 에 아래 형식으로 넣으세요 (한 줄, 따옴표 없이):\n")
        guess = ", ".join(f'"{f}": "실제태그명"' for f in missing)
        print(f"  JOBKOREA_FIELD_MAP={{{guess}}}")
    else:
        print("\n모든 필드가 매핑됐습니다. 그대로 쓰시면 됩니다.")

    print("\n" + "=" * 60)
    print("지역 게이트 확인")
    print("=" * 60)
    from . import regions
    sample = [_pick(_index_children(r), src.field_map["region"]) for r in records[:20]]
    covered = [s for s in sample if regions.is_covered(s)]
    print(f"  샘플 {len(sample)}건 중 대상지역 {len(covered)}건")
    for s in sample[:8]:
        print(f"    {s or '(빈값)':30} → {regions.area_of(s) or '✗ 제외'}")
    if sample and not covered:
        print("\n  대상지역이 0건입니다. 잡코리아의 근무지역 표기가")
        print("  regions.AREAS 패턴과 다를 수 있으니 위 값들을 보고 조정하세요.")
    return 0


def probe(source_name: str) -> int:
    if source_name == "jobkorea":
        return probe_jobkorea()
    print(f"probe 를 지원하지 않는 소스입니다: {source_name}")
    print("사용 가능: jobkorea")
    return 1
