"""엔트리포인트.

  python -m app.main run       봇 + 스케줄러 (운영)
  python -m app.main ingest    수집만 1회
  python -m app.main digest    다이제스트만 1회
  python -m app.main dryrun    발송 없이 결과만 출력
  python -m app.main probe jobkorea   피드 XML 구조 확인 (필드 매핑용)
"""
import logging
import sys

from apscheduler.schedulers.background import BackgroundScheduler

from . import bot, db, digest, probe as probe_mod
from .config import cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("main")


def _daily_job():
    """수집 → 발송. 순서가 중요하다."""
    try:
        digest.ingest()
        digest.run_digest()
    except Exception:
        log.exception("일간 작업 실패")


def run():
    if not cfg.telegram_token:
        sys.exit("TELEGRAM_BOT_TOKEN 이 없습니다. .env 를 확인하세요.")
    db.init_db()

    sched = BackgroundScheduler(timezone=cfg.timezone)
    # 수집은 발송 30분 전에. 워크넷 응답이 느릴 때를 위한 여유.
    sched.add_job(digest.ingest, "cron",
                  hour=cfg.digest_hour, minute=max(0, cfg.digest_minute - 30),
                  id="ingest")
    sched.add_job(digest.run_digest, "cron",
                  hour=cfg.digest_hour, minute=cfg.digest_minute,
                  id="digest")
    sched.start()
    log.info("스케줄러 기동: 매일 %02d:%02d (%s)",
             cfg.digest_hour, cfg.digest_minute, cfg.timezone)

    try:
        bot.poll_forever()
    except KeyboardInterrupt:
        log.info("종료")
    finally:
        sched.shutdown(wait=False)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    db.init_db()
    if cmd == "run":
        run()
    elif cmd == "ingest":
        print(f"신규 {digest.ingest()}건")
    elif cmd == "digest":
        print(f"{digest.run_digest()}명에게 발송")
    elif cmd == "probe":
        name = sys.argv[2] if len(sys.argv) > 2 else "jobkorea"
        sys.exit(probe_mod.probe(name))
    elif cmd == "dryrun":
        digest.ingest()
        digest.run_digest(dry_run=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
