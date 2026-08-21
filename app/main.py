"""엔트리포인트 (로컬용).

  python -m app.main status         지금 상태 진단 (왜 알림이 안 왔나)
  python -m app.main probe worknet  소스 연결 진단 (키가 왜 거부되나)
  python -m app.main daily          수집 + 발송 (서버 없이 도는 배치 모드)
  python -m app.main ingest         수집만 1회
  python -m app.main digest         다이제스트만 1회
  python -m app.main dryrun         발송 없이 결과만 출력
  python -m app.main webhook on     .env 의 PUBLIC_BASE_URL 로 웹훅 등록
  python -m app.main webhook <URL>  주소를 직접 지정해 등록
  python -m app.main webhook off    웹훅 해제 (롱폴링으로 복귀)
  python -m app.main webhook        봇/웹훅 현재 상태 확인
  python -m app.main run            봇 + 스케줄러 (상주형 로컬 운영)

운영은 Vercel 이 맡는다: 크론과 웹훅 모두 server.py 의 WSGI 앱이 받는다
(/api/cron, /api/telegram). `run` 은 웹훅이 걸려 있지 않을 때만 쓰는 예전 방식이다.
"""
from __future__ import annotations

import logging
import sys

from . import bot, db, digest, matcher, telegram
from .config import cfg

# 윈도우 콘솔은 기본 코드페이지가 cp949 라 로그의 한글이 깨진다.
# 로그로 원인을 읽어야 하는 도구에서 이건 치명적이라 여기서 UTF-8 로 고정한다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# httpx 는 요청 URL 전체를 INFO 로 찍는다 — 쿼리스트링에 API 키가 들어있어서
# 그대로 두면 로그/터미널에 비밀값이 남는다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger("main")


def _daily_job():
    """수집 → 발송. 순서가 중요하다."""
    try:
        digest.ingest()
        digest.run_digest()
    except Exception:
        log.exception("일간 작업 실패")


def status() -> None:
    """지금 상태를 한 화면에. "알림이 왜 안 왔지" 를 여기서 판정한다.

    발송 0건인 날은 DB 에 흔적이 안 남아서, 크론이 돌았는지 아닌지를
    last_cron 기록 없이는 구분할 수 없다.
    """
    import json as _json

    db.init_db()
    raw = db.kv_get("last_cron")
    print("=== 마지막 크론 실행 ===")
    if not raw:
        print("  기록 없음")
        print("  (실행기록 기능을 넣은 뒤로 아직 한 번도 안 돌았다는 뜻입니다)")
    else:
        r = _json.loads(raw)
        print("  시각   : %s UTC" % r.get("at"))
        if r.get("ok"):
            print("  결과   : 성공 - 신규 %s건 / %s명 발송"
                  % (r.get("new_jobs"), r.get("sent")))
        else:
            print("  결과   : 실패 - %s: %s" % (r.get("error"), r.get("detail")))

    with db.conn() as c:
        row = c.execute(
            "SELECT count(*) AS n,"
            "       max(fetched_at AT TIME ZONE 'Asia/Seoul') AS last_fetch"
            "  FROM jobs").fetchone()
        d = c.execute(
            "SELECT count(*) AS n,"
            "       max(sent_at AT TIME ZONE 'Asia/Seoul') AS last_sent"
            "  FROM deliveries").fetchone()
    print("\n=== DB ===")
    print("  jobs       : %s건 (마지막 신규 수집 %s KST)" % (row["n"], row["last_fetch"]))
    print("  deliveries : %s건 (마지막 발송 %s KST)" % (d["n"], d["last_sent"]))

    print("\n=== 지금 보낼 게 있나 ===")
    for f in db.active_filters():
        cand = db.unsent_jobs_for(f["user_id"])
        hits = matcher.select_for(cand, f)
        print("  chat %s: 후보 %d건 -> 매칭 %d건%s"
              % (f["chat_id"], len(cand), len(hits),
                 "  (0건이면 알림이 안 가는 게 정상입니다)" if not hits else ""))

    print("\n발송 예정: 매일 08:00~08:59 KST (vercel.json 의 0 23 * * * UTC)")


def webhook(arg: str) -> None:
    """웹훅 등록/해제/조회. 배포 후 딱 한 번 등록하면 된다."""
    if not arg:
        info = telegram.webhook_info()
        url = info.get("url") or "(없음 - 롱폴링 모드)"
        try:
            me = telegram._call("getMe", {})
            print(f"봇           : @{me.get('username')}")
        except Exception as e:  # 토큰이 틀려도 나머지 정보는 보여준다
            print(f"봇           : (확인 실패: {e})")
        print(f"웹훅 URL     : {url}")
        print(f"대기 업데이트: {info.get('pending_update_count', 0)}")
        if info.get("last_error_message"):
            print(f"최근 오류    : {info['last_error_message']}")
        return

    # `webhook on` 은 .env 의 PUBLIC_BASE_URL 을 쓴다. 배포 주소를 저장소에
    # 적어두지 않으려고 이렇게 했다 - 공개 저장소라 URL 이 코드에 없다.
    if arg.lower() == "on":
        if not cfg.public_base_url:
            sys.exit("PUBLIC_BASE_URL 이 .env 에 없습니다.\n"
                     "  예) PUBLIC_BASE_URL=https://내배포주소.vercel.app\n"
                     "  또는 주소를 직접: python -m app.main webhook <URL>")
        arg = cfg.public_base_url.rstrip("/") + "/api/telegram"

    if arg.lower() in ("off", "delete", "none"):
        telegram.delete_webhook()
        print("웹훅을 해제했습니다. 이제 롱폴링(run)을 쓸 수 있습니다.")
        return

    if not cfg.telegram_webhook_secret:
        sys.exit("TELEGRAM_WEBHOOK_SECRET 이 없습니다.\n"
                 "  로컬 .env 와 Vercel 환경변수에 '같은 값'을 넣어야 합니다.\n"
                 "  둘이 다르면 텔레그램 요청이 전부 401 로 거부됩니다.")
    if not arg.startswith("https://"):
        sys.exit("웹훅 URL 은 https 여야 합니다: " + arg)

    telegram.set_webhook(arg, cfg.telegram_webhook_secret)
    print(f"웹훅 등록 완료: {arg}")
    print("이제 롱폴링(run)은 409 로 거부됩니다. 해제하려면 'webhook off'.")


def run():
    if not cfg.telegram_token:
        sys.exit("TELEGRAM_BOT_TOKEN 이 없습니다. .env 를 확인하세요.")

    # 웹훅이 걸린 채로 폴링하면 텔레그램이 409 를 계속 뱉는다. 원인을 로그에서
    # 찾기 어려운 실패라 먼저 걸러준다.
    if (telegram.webhook_info().get("url") or ""):
        sys.exit("웹훅이 등록돼 있어 롱폴링을 쓸 수 없습니다.\n"
                 "  Vercel 배포본이 이미 명령을 처리 중입니다.\n"
                 "  굳이 로컬로 돌리려면 먼저: python -m app.main webhook off")

    from apscheduler.schedulers.background import BackgroundScheduler

    db.init_db()
    sched = BackgroundScheduler(timezone=cfg.timezone)
    # 수집은 발송 30분 전에. 워크넷 응답이 느릴 때를 위한 여유.
    # 분에서 30을 빼면 음수가 될 수 있으므로 시를 빌려온다. max(0, ...) 로 자르면
    # DIGEST_MINUTE 가 30 미만일 때(기본값 0 포함) 수집과 발송이 같은 분에 돌아
    # 다이제스트가 수집 끝나기 전 DB 를 읽는다.
    ingest_hour, ingest_minute = divmod(
        (cfg.digest_hour * 60 + cfg.digest_minute - 30) % (24 * 60), 60)
    sched.add_job(digest.ingest, "cron",
                  hour=ingest_hour, minute=ingest_minute,
                  id="ingest")
    sched.add_job(digest.run_digest, "cron",
                  hour=cfg.digest_hour, minute=cfg.digest_minute,
                  id="digest")
    sched.start()
    log.info("스케줄러 기동: 수집 %02d:%02d → 발송 %02d:%02d (%s)",
             ingest_hour, ingest_minute,
             cfg.digest_hour, cfg.digest_minute, cfg.timezone)

    try:
        bot.poll_forever()
    except KeyboardInterrupt:
        log.info("종료")
    finally:
        sched.shutdown(wait=False)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    # webhook 은 DB 를 건드리지 않는다. DATABASE_URL 이 아직 없을 때도
    # 상태를 확인할 수 있어야 해서 init_db 앞에 둔다.
    if cmd == "webhook":
        webhook(sys.argv[2] if len(sys.argv) > 2 else "")
        return

    if cmd == "status":
        status()
        return

    if cmd == "probe":
        # DB 가 필요 없다. 키만 있으면 되므로 init_db 앞에 둔다.
        from . import probe
        sys.exit(probe.main(sys.argv[2] if len(sys.argv) > 2 else ""))

    db.init_db()
    if cmd == "run":
        run()
    elif cmd == "daily":
        # 수집 -> 발송을 한 번에. 서버리스의 /api/cron 과 동일한 일을 하며,
        # HTTP 서버 없이 스케줄러만 있으면 되는 환경(GitHub Actions, cron)용.
        # 순서가 중요하다: 발송이 수집 결과를 읽는다.
        new_jobs = digest.ingest()
        sent = digest.run_digest()
        print(f"신규 {new_jobs}건 / {sent}명 발송")
    elif cmd == "ingest":
        print(f"신규 {digest.ingest()}건")
    elif cmd == "digest":
        print(f"{digest.run_digest()}명에게 발송")
    elif cmd == "dryrun":
        digest.ingest()
        digest.run_digest(dry_run=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
