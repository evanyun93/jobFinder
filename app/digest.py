"""수집(ingest)과 아침 다이제스트(digest)."""
from __future__ import annotations

import logging
from collections import OrderedDict

from . import db, matcher, regions, telegram
from .config import cfg
from .sources import build_sources
from .sources.base import SourceConfigError
from .telegram import esc

log = logging.getLogger(__name__)


def ingest() -> int:
    """모든 소스에서 최근 공고를 긁어 DB 에 넣는다. 하루 1회.

    사용자 수와 무관하게 호출량이 고정된다 — 여기가 이 구조의 핵심.
    대상 지역(서울·판교권) 밖 공고는 저장 전에 버린다."""
    sources = build_sources()
    if not sources:
        log.error("활성화된 소스가 없습니다. .env 의 API 키를 확인하세요.")
        return 0

    total_new = 0
    for src in sources:
        try:
            fetched = src.fetch_recent(max_pages=cfg.ingest_max_pages)
            in_area = [j for j in fetched if regions.is_covered(j.region)]
            log.info("%s: 수집 %d건 → 대상지역 %d건 (%.0f%%)",
                     src.name, len(fetched), len(in_area),
                     100 * len(in_area) / len(fetched) if fetched else 0)
            if fetched and not in_area:
                log.warning("%s: 대상지역 공고가 0건입니다. "
                            "regions.AREAS 패턴이 이 소스의 근무지역 표기와 "
                            "맞는지 확인하세요.", src.name)
            total_new += db.upsert_jobs(in_area)
        except SourceConfigError as e:  # 사람이 고쳐야 하는 문제. 트레이스백은 노이즈다.
            log.error("소스 %s 사용 불가: %s", src.name, e)
        except Exception as e:  # 한 소스가 죽어도 나머지는 돈다
            log.exception("소스 %s 수집 실패: %s", src.name, e)

    log.info("수집 완료: 신규 %d건", total_new)
    return total_new


def build_digest_text(flt: dict, hits: list, limit: int) -> str:
    shown = hits[:limit]

    grouped: OrderedDict[str, list] = OrderedDict()
    for j in shown:
        grouped.setdefault(j["area"] or "기타", []).append(j)

    lines = [f"☀️ <b>오늘의 채용공고 {len(hits)}건</b>"]
    if flt["keywords"]:
        lines.append(f"<i>키워드: {esc(', '.join(flt['keywords']))}</i>")

    for area, items in grouped.items():
        lines.append("")
        lines.append(f"📍 <b>{esc(area)}</b>")
        for j in items:
            title = esc(j["title"])
            title = f'<a href="{esc(j["url"])}">{title}</a>' if j["url"] else f"<b>{title}</b>"
            lines.append(f"▪️ {title}")

            meta = [x for x in (j["company"], j["region"]) if x]
            if meta:
                lines.append(f"   {esc(' · '.join(meta))}")

            tail = [x for x in (j["career"], j["salary"]) if x]
            if tail:
                lines.append(f"   <code>{esc(' | '.join(tail))}</code>")
            if j["closes_at"]:
                lines.append(f"   마감 {esc(j['closes_at'])}")

    if len(hits) > limit:
        lines.append("")
        lines.append(f"…외 {len(hits) - limit}건. /more 로 더 보기")
    return "\n".join(lines).strip()


def run_digest(only_chat_id: str | None = None, dry_run: bool = False) -> int:
    """필터가 걸린 사용자들에게 신규 공고를 보낸다."""
    filters = db.active_filters()
    if only_chat_id:
        filters = [f for f in filters if f["chat_id"] == str(only_chat_id)]

    sent_count = 0
    for flt in filters:
        if not flt["keywords"]:
            continue  # 설정 안 한 사용자에게는 보내지 않는다

        candidates = db.unsent_jobs_for(flt["user_id"])
        hits = matcher.select_for(candidates, flt)
        if not hits:
            continue

        text = build_digest_text(flt, hits, cfg.max_items_per_message)
        if dry_run:
            print(f"--- chat {flt['chat_id']} ---\n{text}\n")
        else:
            telegram.send_message(flt["chat_id"], text)
            # 보낸 것만 원장에 남긴다. 잘린 나머지는 내일 다시 후보가 된다.
            db.mark_delivered(
                flt["user_id"],
                [j["dedup_key"] for j in hits[:cfg.max_items_per_message]],
            )
        sent_count += 1

    log.info("다이제스트 발송: %d명", sent_count)
    return sent_count
