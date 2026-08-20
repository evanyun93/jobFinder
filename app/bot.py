"""텔레그램 봇 명령 처리 (롱폴링).

웹훅 대신 롱폴링을 쓰는 이유: MVP 단계에서 공인 IP, TLS 인증서, 리버스 프록시
없이 아무 데서나 돌릴 수 있다. 사용자가 늘면 웹훅으로 바꾼다.
"""
from __future__ import annotations

import logging
import time

from . import db, digest, matcher, regions, telegram
from .config import cfg
from .telegram import esc

log = logging.getLogger(__name__)

HELP_TEMPLATE = """<b>채용공고 알리미</b>

<b>{areas}</b> 지역의 신규 공고를
매일 아침 조건에 맞춰 보내드립니다.

<b>설정</b>
/keywords 백엔드, PostgreSQL, GIS
  → 관심 키워드 (하나라도 맞으면 알림)
/regions 판교, 강남
  → 위 지역 안에서 더 좁히기 (비우면 전체)
/exclude 인턴, 아르바이트, 파견
  → 이 단어가 있으면 제외

<b>확인</b>
/my      현재 설정
/preview 지금 바로 미리보기
/more    오늘 잘린 나머지 공고
/stop    알림 중지

<i>공고는 각 사의 공식 API 로만 수집합니다. 무료입니다.</i>"""


def help_text() -> str:
    return HELP_TEMPLATE.format(areas=regions.describe())


def _parse_list(arg: str) -> list[str]:
    raw = arg.replace("\n", ",").split(",")
    return [t.strip() for t in raw if t.strip()][:20]


def _fmt_list(items: list[str]) -> str:
    return ", ".join(items) if items else "(없음)"


def handle_command(chat_id: str, text: str) -> None:
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        db.upsert_user(chat_id)
        telegram.send_message(chat_id, help_text())
        return

    if cmd == "/stop":
        db.deactivate_user(chat_id)
        telegram.send_message(chat_id, "알림을 중지했습니다. /start 로 다시 켤 수 있어요.")
        return

    db.upsert_user(chat_id)

    if cmd in ("/keywords", "/regions", "/exclude"):
        field = {"/keywords": "keywords", "/regions": "regions",
                 "/exclude": "excludes"}[cmd]
        if not arg:
            cur = db.get_filter(chat_id)
            msg = f"현재 값: {esc(_fmt_list(cur[field]))}\n\n"
            if cmd == "/regions":
                msg += (f"수집 대상 지역: <b>{esc(regions.describe())}</b>\n"
                        f"이 안에서 더 좁히려면 예) <code>/regions 판교, 강남</code>\n"
                        f"비우려면 <code>/regions -</code>")
            else:
                msg += f"예) <code>{cmd} 백엔드, PostgreSQL</code>"
            telegram.send_message(chat_id, msg)
            return
        values = [] if arg.strip() == "-" else _parse_list(arg)
        db.set_filter_field(chat_id, field, values)
        telegram.send_message(chat_id, f"저장했습니다 → {esc(_fmt_list(values))}")
        return

    if cmd == "/my":
        f = db.get_filter(chat_id)
        telegram.send_message(chat_id, (
            "<b>현재 설정</b>\n"
            f"키워드: {esc(_fmt_list(f['keywords']))}\n"
            f"지역: {esc(_fmt_list(f['regions']))}"
            f"  <i>(수집 범위: {esc(regions.describe())})</i>\n"
            f"제외: {esc(_fmt_list(f['excludes']))}\n"
            f"발송: 매일 {cfg.digest_hour:02d}:{cfg.digest_minute:02d}"
        ))
        return

    if cmd in ("/preview", "/more"):
        f = db.get_filter(chat_id)
        if not f["keywords"]:
            telegram.send_message(chat_id, "먼저 키워드를 설정해주세요.\n예) <code>/keywords 백엔드, GIS</code>")
            return
        hits = matcher.select_for(db.unsent_jobs_for(f["user_id"]), f)
        if not hits:
            telegram.send_message(chat_id, "조건에 맞는 새 공고가 없습니다.")
            return
        # /preview 는 원장에 남기지 않아 아침 다이제스트에 다시 나온다.
        telegram.send_message(chat_id, digest.build_digest_text(f, hits, cfg.max_items_per_message))
        if cmd == "/more":
            db.mark_delivered(f["user_id"], [j["dedup_key"] for j in hits[:cfg.max_items_per_message]])
        return

    telegram.send_message(chat_id, "모르는 명령입니다. /help 를 눌러보세요.")


def poll_forever(stop_flag=lambda: False) -> None:
    offset = int(db.kv_get("tg_offset", "0") or 0)
    log.info("봇 폴링 시작 (offset=%s)", offset)
    while not stop_flag():
        updates = telegram.get_updates(offset or None)
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            if not chat_id or not text.startswith("/"):
                continue
            try:
                handle_command(chat_id, text)
            except Exception:
                log.exception("명령 처리 실패: %s", text)
                telegram.send_message(chat_id, "처리 중 오류가 났습니다. 잠시 후 다시 시도해주세요.")
        if updates:
            db.kv_set("tg_offset", str(offset))
        else:
            time.sleep(1)
