"""환경설정. 모든 비밀값은 .env 로만 주입한다."""
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "y")


@dataclass
class Config:
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "jobalert.db"))

    # 워크넷(공공데이터포털). 자동승인, 일 1000회.
    worknet_key: str = field(default_factory=lambda: os.getenv("WORKNET_AUTH_KEY", ""))
    worknet_enabled: bool = field(default_factory=lambda: _bool("WORKNET_ENABLED", True))

    # 사람인 오픈API. 일 500회.
    # 약관상 "API를 사용한 서비스의 재판매 또는 이용요금 발생 금지",
    # "이용자로부터 이용에 대한 대가를 제공받는 행위 금지".
    # 이 서비스는 무료이므로 사용 가능하다. 나중에 과금을 붙이려면 이 소스를
    # 먼저 빼거나 사람인과 별도 제휴 계약(api@saramin.co.kr)을 맺어야 한다.
    saramin_key: str = field(default_factory=lambda: os.getenv("SARAMIN_ACCESS_KEY", ""))
    saramin_enabled: bool = field(default_factory=lambda: _bool("SARAMIN_ENABLED", True))

    # 잡코리아. 승인 후 IP 등록 → 고유 호출 링크 발급 방식이라 URL 이 사람마다 다르다.
    # 공공기관·학교 우선 제공이라 개인 신청은 거절될 수 있다.
    jobkorea_url: str = field(default_factory=lambda: os.getenv("JOBKOREA_FEED_URL", ""))
    jobkorea_field_map: str = field(default_factory=lambda: os.getenv("JOBKOREA_FIELD_MAP", ""))
    jobkorea_enabled: bool = field(default_factory=lambda: _bool("JOBKOREA_ENABLED", True))

    digest_hour: int = field(default_factory=lambda: int(os.getenv("DIGEST_HOUR", "8")))
    digest_minute: int = field(default_factory=lambda: int(os.getenv("DIGEST_MINUTE", "0")))
    timezone: str = field(default_factory=lambda: os.getenv("TZ_NAME", "Asia/Seoul"))

    max_items_per_message: int = 12
    # 지역을 서울·판교권으로 좁혔으므로 넉넉히 훑어야 대상 공고가 충분히 걸린다.
    ingest_max_pages: int = field(default_factory=lambda: int(os.getenv("INGEST_MAX_PAGES", "30")))

    def enabled_sources(self) -> list[str]:
        out = []
        if self.worknet_enabled and self.worknet_key:
            out.append("worknet")
        if self.saramin_enabled and self.saramin_key:
            out.append("saramin")
        if self.jobkorea_enabled and self.jobkorea_url:
            out.append("jobkorea")
        return out


cfg = Config()
