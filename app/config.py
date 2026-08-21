"""환경설정. 모든 비밀값은 .env 로만 주입한다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _str(key: str, default: str = "") -> str:
    """비어 있는 환경변수는 '설정 안 함'으로 본다.

    CI/호스팅 플랫폼은 등록되지 않은 secret 을 빈 문자열로 주입한다.
    os.getenv(key, default) 는 이때 default 가 아니라 '' 를 돌려주므로,
    GREENHOUSE_BOARDS 를 안 채운 GitHub Actions 에서 기본 보드 목록이 통째로
    날아가 유일하게 도는 소스가 조용히 꺼진다. 실제로 그럴 뻔했다.
    """
    v = os.getenv(key)
    return v.strip() if v and v.strip() else default


def _int(key: str, default: int) -> int:
    """빈 문자열이나 이상한 값이 와도 죽지 않는다. int('') 는 ValueError 다."""
    try:
        return int(_str(key, str(default)))
    except ValueError:
        return default


def _bool(key: str, default: bool = False) -> bool:
    return _str(key, str(default)).lower() in ("1", "true", "yes", "y")


@dataclass
class Config:
    telegram_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN"))

    # Supabase Postgres. 서버리스에서는 Transaction pooler(포트 6543)를 써야
    # 한다 - 직접 접속(5432)은 호출마다 새 커넥션을 열어 금방 한도에 걸린다.
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL"))

    # 웹훅 URL 은 공개 주소다. 이 값이 없으면 아무나 가짜 명령을 POST 할 수 있다.
    # 텔레그램이 매 요청에 X-Telegram-Bot-Api-Secret-Token 헤더로 되돌려준다.
    telegram_webhook_secret: str = field(
        default_factory=lambda: _str("TELEGRAM_WEBHOOK_SECRET"))
    # 크론 엔드포인트도 마찬가지. Vercel 이 Authorization: Bearer 로 보낸다.
    cron_secret: str = field(default_factory=lambda: _str("CRON_SECRET"))

    # 배포 주소. 비밀은 아니지만 저장소가 공개라 여기에 두지 않는다.
    # `python -m app.main webhook on` 이 이 값으로 웹훅을 건다.
    public_base_url: str = field(default_factory=lambda: _str("PUBLIC_BASE_URL"))

    # 워크넷(공공데이터포털). 자동승인, 일 1000회.
    worknet_key: str = field(default_factory=lambda: _str("WORKNET_AUTH_KEY"))
    worknet_enabled: bool = field(default_factory=lambda: _bool("WORKNET_ENABLED", True))

    # 사람인 오픈API. 일 500회.
    # 약관상 "API를 사용한 서비스의 재판매 또는 이용요금 발생 금지",
    # "이용자로부터 이용에 대한 대가를 제공받는 행위 금지".
    # 이 서비스는 무료이므로 사용 가능하다. 나중에 과금을 붙이려면 이 소스를
    # 먼저 빼거나 사람인과 별도 제휴 계약(api@saramin.co.kr)을 맺어야 한다.
    saramin_key: str = field(default_factory=lambda: _str("SARAMIN_ACCESS_KEY"))
    saramin_enabled: bool = field(default_factory=lambda: _bool("SARAMIN_ENABLED", True))

    # 잡코리아. 공공기관/학교 대상이라 개인은 내부 검토를 거친다.
    # 엔드포인트가 계정마다 다르게 발급되므로 키가 아니라 URL 을 통째로 받는다.
    jobkorea_url: str = field(default_factory=lambda: _str("JOBKOREA_API_URL"))
    jobkorea_enabled: bool = field(default_factory=lambda: _bool("JOBKOREA_ENABLED", False))

    # Greenhouse 공개 채용보드. 키·승인이 필요 없어 기본으로 켜둔다.
    # 보드 토큰은 기업 채용페이지 URL(boards.greenhouse.io/<토큰>)에 그대로 있다.
    greenhouse_boards: str = field(default_factory=lambda: _str(
        "GREENHOUSE_BOARDS", "krafton,moloco,sendbird,daangn,seoulrobotics,databricks"))
    greenhouse_enabled: bool = field(default_factory=lambda: _bool("GREENHOUSE_ENABLED", True))

    digest_hour: int = field(default_factory=lambda: _int("DIGEST_HOUR", 8))
    digest_minute: int = field(default_factory=lambda: _int("DIGEST_MINUTE", 0))
    timezone: str = field(default_factory=lambda: _str("TZ_NAME", "Asia/Seoul"))

    max_items_per_message: int = 12
    # 지역을 서울·판교권으로 좁혔으므로 넉넉히 훑어야 대상 공고가 충분히 걸린다.
    ingest_max_pages: int = field(default_factory=lambda: _int("INGEST_MAX_PAGES", 30))

    def enabled_sources(self) -> list[str]:
        out = []
        if self.worknet_enabled and self.worknet_key:
            out.append("worknet")
        if self.saramin_enabled and self.saramin_key:
            out.append("saramin")
        if self.jobkorea_enabled and self.jobkorea_url:
            out.append("jobkorea")
        if self.greenhouse_enabled and self.greenhouse_boards.strip():
            out.append("greenhouse")
        return out


cfg = Config()
