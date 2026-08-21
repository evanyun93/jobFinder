"""Vercel 진입점 (WSGI).

Vercel 의 Python 빌더는 `api/*.py` 를 함수 하나씩 만드는 예전 방식 대신
**앱 하나**를 요구한다. 그래서 두 엔드포인트를 여기서 라우팅한다:

    POST /api/telegram   텔레그램 웹훅 (봇 명령)
    GET  /api/cron       하루 1회 수집 + 발송 (Vercel Cron)

프레임워크를 쓰지 않는 이유: 라우트가 둘뿐이라 WSGI 원형이면 충분하고,
의존성이 줄면 콜드스타트도 짧아진다.

두 URL 모두 공개 주소다. 크론은 Authorization: Bearer $CRON_SECRET 을,
웹훅은 텔레그램이 보내는 X-Telegram-Bot-Api-Secret-Token 을 매 요청 확인한다.
시크릿이 설정돼 있지 않으면 통과시키지 않는다(fail closed).
"""
from __future__ import annotations

import hmac
import json
import logging

from app import bot, db, digest, telegram
from app.config import cfg

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s [%(name)s] %(message)s")
# httpx 는 요청 URL 전체를 INFO 로 찍는다. 쿼리스트링에 API 키가 들어 있어서
# 그대로 두면 Vercel 로그에 비밀값이 남는다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger("server")

MAX_BODY = 1 << 20  # 텔레그램 업데이트는 훨씬 작다. 방어적 상한.

# WSGI 는 "코드 + 사유문구" 형태의 상태줄을 요구한다. Vercel 은 사유가 비어도
# 받아줬지만 표준 서버(gunicorn, wsgiref)는 그렇지 않다.
_REASON = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
           404: "Not Found", 405: "Method Not Allowed",
           500: "Internal Server Error"}


def _drain(environ) -> None:
    """요청 본문을 읽어서 버린다.

    인증 실패로 조기 반환할 때 본문을 남겨두면, keep-alive 커넥션에 읽히지
    않은 바이트가 남아 다음 요청과 뒤섞인다. 표준 WSGI 서버는 이때 커넥션을
    강제로 끊어버려서, 클라이언트는 응답 대신 connection reset 을 받는다.
    Vercel 은 요청을 통째로 버퍼링해줘서 이 버그가 가려져 있었다.
    """
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return
    if 0 < length <= MAX_BODY:
        try:
            environ["wsgi.input"].read(length)
        except Exception:
            pass


def _json(start_response, status: int, body: dict):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    start_response(f"{status} {_REASON.get(status, 'Unknown')}", [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(payload))),
    ])
    return [payload]


def _cron(environ, start_response):
    _drain(environ)  # POST 로 불릴 수도 있다. 본문은 쓰지 않지만 비워둬야 한다.
    # 스케줄러는 CRON_SECRET 을 Authorization: Bearer 로 보낸다.
    # (Vercel Cron 은 자동으로, 다른 호스트에서는 curl -H 로 직접)
    if not cfg.cron_secret:
        return _json(start_response, 401, {
            "error": "unauthorized",
            "hint": "환경변수에 CRON_SECRET 을 설정하세요."})
    got = environ.get("HTTP_AUTHORIZATION", "")
    if not hmac.compare_digest(got, "Bearer " + cfg.cron_secret):
        return _json(start_response, 401, {"error": "unauthorized"})

    try:
        db.init_db()
        new_jobs = digest.ingest()
        sent = digest.run_digest()
    except Exception as e:
        log.exception("일간 작업 실패")
        _record_run({"ok": False, "error": type(e).__name__, "detail": str(e)[:200]})
        # 500 을 돌려줘야 Vercel 대시보드에 실패로 남는다. 조용히 200 을 주면
        # 몇 주 뒤에야 "왜 알림이 안 오지"로 알아차리게 된다.
        return _json(start_response, 500,
                     {"error": type(e).__name__, "detail": str(e)[:500]})

    log.info("완료: 신규 %d건 / %d명 발송", new_jobs, sent)
    _record_run({"ok": True, "new_jobs": new_jobs, "sent": sent})
    return _json(start_response, 200, {"new_jobs": new_jobs, "sent": sent})


def _record_run(result: dict) -> None:
    """크론이 돌았다는 사실을 DB 에 남긴다.

    발송 0건인 날은 DB 에 아무 흔적이 안 남는다 - 새 공고가 없으면 jobs 에도
    (ON CONFLICT DO NOTHING 이라) 새 행이 안 생기고 deliveries 도 그대로다.
    그래서 "알림이 안 왔다"가 정상 동작인지 크론이 안 돈 건지 구분할 수가 없었다.
    Hobby 플랜은 런타임 로그도 금방 사라져서 사후 확인이 불가능하다.

    기록 실패가 크론 자체를 실패시키면 안 되므로 예외는 삼킨다.
    """
    import datetime
    result["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    try:
        db.kv_set("last_cron", json.dumps(result, ensure_ascii=False))
    except Exception:
        log.warning("크론 실행 기록 실패 (본 작업에는 영향 없음)", exc_info=True)


def _telegram(environ, start_response):
    if not cfg.telegram_webhook_secret:
        log.error("TELEGRAM_WEBHOOK_SECRET 이 없어 요청을 거부했습니다.")
        _drain(environ)
        return _json(start_response, 401, {"error": "webhook secret not configured"})
    got = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
    if not hmac.compare_digest(got, cfg.telegram_webhook_secret):
        log.warning("secret 불일치 요청 거부")
        _drain(environ)
        return _json(start_response, 401, {"error": "bad secret"})

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY:
        _drain(environ)
        return _json(start_response, 400, {"error": "bad length"})

    chat_id = ""
    try:
        update = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if chat_id and text.startswith("/"):
            bot.handle_command(chat_id, text)
    except Exception:
        log.exception("업데이트 처리 실패")
        if chat_id:
            telegram.send_message(
                chat_id, "처리 중 오류가 났습니다. 잠시 후 다시 시도해주세요.")

    # 무슨 일이 있어도 200. 200 이 아니면 텔레그램이 같은 업데이트를 계속
    # 재전송해서, 버그 하나가 무한 재시도 루프가 된다.
    return _json(start_response, 200, {"ok": True})


def app(environ, start_response):
    path = environ.get("PATH_INFO", "") or "/"
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if path.rstrip("/") == "/api/cron":
        if method not in ("GET", "POST"):
            return _json(start_response, 405, {"error": "method not allowed"})
        return _cron(environ, start_response)

    if path.rstrip("/") == "/api/telegram":
        if method == "GET":
            # 브라우저로 열었을 때 배포 여부만 확인. 비밀값은 노출하지 않는다.
            return _json(start_response, 200,
                         {"ok": True, "hint": "POST only (Telegram webhook)"})
        if method != "POST":
            return _json(start_response, 405, {"error": "method not allowed"})
        return _telegram(environ, start_response)

    if path == "/":
        return _json(start_response, 200,
                     {"ok": True, "service": "jobfinder",
                      "endpoints": ["/api/cron", "/api/telegram"]})

    return _json(start_response, 404, {"error": "not found", "path": path})


# Vercel 의 일부 감지 경로가 `application` 이라는 이름을 찾는다.
application = app
