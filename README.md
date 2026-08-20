# 채용공고 알리미

**서울 + 판교 생활권**의 신규 채용공고를 조건에 맞춰 매일 아침 텔레그램으로 보내주는 봇.
무료 개인용.

운영은 **Vercel 서버리스**에서 돕니다 (아래 배포 절차). 로컬 PC 는 꺼져 있어도 됩니다.

| 문서 | 내용 |
|---|---|
| [FEATURES.md](FEATURES.md) | **기능설명서** — 명령어, 매칭 규칙, 소스 현황, 한계 |
| [DESIGN.md](DESIGN.md) | **설계문서** — 왜 이렇게 만들었는지, 데이터 모델, 보안 경계 |
| [PORTING.md](PORTING.md) | **이전 대비** — Vercel 이 막혔을 때 어디로 어떻게 옮기나 |

## 5분 셋업 (로컬 확인용)

```bash
pip install -r requirements.txt
cp .env.example .env      # 토큰, DATABASE_URL, 시크릿 채우기
python -m app.main dryrun # 발송 없이 결과 확인
```

## Vercel 배포

서버리스에는 상주 프로세스도 영구 디스크도 없습니다. 그래서 세 가지가 바뀝니다:
APScheduler → **Vercel Cron**, 롱폴링 → **웹훅**, SQLite → **Supabase Postgres**.

**현재 배포:** https://<배포주소>
(`jobfinder.vercel.app` 은 다른 사람이 선점한 무관한 앱입니다. 헷갈리지 마세요.)

```bash
vercel link                              # 프로젝트 연결
vercel env add DATABASE_URL production   # Supabase Transaction pooler(6543) URL
vercel env add TELEGRAM_BOT_TOKEN production
vercel env add TELEGRAM_WEBHOOK_SECRET production
vercel env add CRON_SECRET production
vercel env add WORKNET_AUTH_KEY production      # 선택
vercel --prod

# 배포 후 딱 한 번, 웹훅 등록
python -m app.main webhook https://<배포주소>/api/telegram
python -m app.main webhook                      # 상태 확인
```

### 왜 `api/*.py` 가 아니라 `server.py` 하나인가

Vercel 의 Python 빌더는 `api/` 안의 파일을 함수 하나씩 만드는 예전 방식 대신
**앱 하나**를 요구합니다. `api/cron.py` + `api/telegram.py` 로 올리면
`No python entrypoint found in default locations` 로 빌드가 깨집니다.
그래서 `server.py` 의 WSGI 앱이 두 경로를 직접 라우팅하고,
`pyproject.toml` 의 `[tool.vercel] entrypoint` 로 그걸 지정합니다.

`app/main.py` 는 `.vercelignore` 로 배포에서 뺍니다. `app/` 이 저쪽 관례상
예약된 이름이라, 올리면 빌더가 `app/main.py` 를 ASGI 앱으로 착각합니다.

`pyproject.toml` 에는 `[project]` 테이블이 반드시 있어야 합니다 — 이 파일이
생기는 순간 Vercel 이 uv 프로젝트 모드로 바뀌고, `[tool.vercel]` 만 있으면
`No 'project' table found` 로 실패합니다.

### 확인 방법

```bash
curl https://<배포주소>/            # {"ok": true, ...}
curl https://<배포주소>/api/cron    # 401 (정상 - 시크릿 없음)
vercel crons ls                                         # /api/cron  0 23 * * *
```

`DATABASE_URL` 은 반드시 **Transaction pooler(포트 6543)** 를 쓰세요. 서버리스는 호출마다
새 커넥션을 열기 때문에 직접 접속(5432)으로는 금방 한도에 걸립니다.

### 크론 시각은 UTC 입니다

`vercel.json` 의 `"0 23 * * *"` 는 **UTC 23:00 = 한국 오전 8시**입니다. 여기서
`"0 8 * * *"` 로 적으면 오후 5시에 옵니다.

Hobby 플랜은 크론이 **하루 1회**로 제한되고 실행 시각에 **±59분 오차**가 있습니다
(8:00~8:59 사이 도착). 그래서 수집과 발송을 한 번의 호출에서 연달아 처리합니다 —
"발송 전에 수집이 끝나 있어야 한다"가 원래 의도였으므로 오히려 정확해졌습니다.
분 단위 정시 발송이 필요하면 Pro 로 올리고 크론을 둘로 나누면 됩니다.

### 엔드포인트는 공개 주소입니다

`/api/cron` 과 `/api/telegram` 은 누구나 호출할 수 있는 URL 입니다. 그래서
크론은 `Authorization: Bearer $CRON_SECRET` 을, 웹훅은 텔레그램이 보내는
`X-Telegram-Bot-Api-Secret-Token` 헤더를 매 요청에서 검사합니다. 시크릿이
설정돼 있지 않으면 **요청을 통과시키지 않습니다**(fail closed). 로컬 `.env` 와
Vercel 환경변수에 같은 값이 들어가야 합니다.

Supabase 쪽도 `public` 테이블 전체에 RLS 를 켜고 정책을 하나도 두지 않았습니다.
anon 키는 공개값이라, 그대로 두면 누구나 `users.chat_id` 와 키워드를 읽습니다.
앱은 `postgres` 롤로 직접 접속하므로 RLS 를 우회합니다.

### 웹훅과 롱폴링은 함께 못 씁니다

웹훅이 걸려 있으면 `getUpdates` 가 409 로 거절됩니다. `python -m app.main run` 은
이 경우 실행 전에 막아둡니다. 로컬 상주 모드로 되돌리려면
`python -m app.main webhook off`.

키 발급 세 곳:

| | 어디서 | 승인 | 쿼터 |
|---|---|---|---|
| 텔레그램 토큰 | 텔레그램 `@BotFather` → `/newbot` | 즉시 | — |
| 워크넷 인증키 | `openapi.work.go.kr` → 채용정보 활용신청 (UUID 형식) | 자동 | 일 1000회 |
| 사람인 access-key | https://oapi.saramin.co.kr/join | 신청→승인 | 일 500회 |
| 잡코리아 호출링크 | https://www.jobkorea.co.kr/service/api | 심사 (아래 참고) | 2시간 주기, 최대 500건 |

워크넷만으로도 돌아갑니다. IT 직군은 사람인 커버리지가 훨씬 두꺼우니 사람인을 먼저 붙이세요.

잡코리아는 **공공기관·학교 대상** 서비스라 개인은 내부 검토를 거칩니다. 승인되면 키가 아니라
계정별 **고유 호출 링크**를 받으므로 `.env` 의 `JOBKOREA_API_URL` 에 URL 을 통째로 넣습니다.
등록한 IP 에서만 호출되니 가정용 회선처럼 IP 가 바뀌면 재등록이 필요합니다. 또 근무지역이
`AreaCode` 코드값으로 오기 때문에, 승인 가이드의 코드표를 `app/sources/jobkorea.py` 의
`AREA_CODES` 에 채워야 지역 게이트를 통과합니다 (안 채우면 로그가 미매핑 코드를 찍어줍니다).

> 인크루트는 붙이지 않았습니다. 공식 오픈API 가 없고 `robots.txt` 가 `User-agent: *` 를
> 전면 차단하고 있어, 어댑터를 만들면 아래 ⚠️ 항목에 정확히 해당합니다.

### 잡코리아는 기대치를 낮추세요

잡코리아 API는 **공공기관·학교 우선 제공**이고, 기업·개인 사업자는 내부 검토를
거쳐 거절될 수 있다고 명시돼 있습니다. 신청서에 이용기관, 관리 업체, 서버 정보,
오픈일, 사용목적을 적어야 하고 "사이트가 오픈되지 않은 경우"는 제공이 어렵다고
합니다. 개인 텔레그램 봇으로는 통과가 쉽지 않습니다. 신청 자체는 무료이니
넣어보되, 안 될 걸 전제로 나머지를 굴리는 게 맞습니다.

승인되면 **IP를 등록하고 고유 호출 링크**를 받습니다. 즉 엔드포인트가 사람마다
다르고 XML 태그 구조도 그때 가이드로 옵니다. 그래서 어댑터가 필드 매핑을
설정으로 받고, 구조를 알아내는 도구를 같이 제공합니다:

```bash
python -m app.main probe jobkorea
```

실제 응답을 받아 레코드 태그와 전 필드를 찍어주고, 기본 매핑이 뭘 잡고 뭘
놓쳤는지 ✓/✗ 로 보여준 뒤 `.env` 에 넣을 `JOBKOREA_FIELD_MAP` 값까지 만들어
줍니다. 잡코리아의 근무지역 표기가 `regions.py` 패턴에 걸리는지도 함께 확인합니다.

기본 태그 추측이 맞으면 설정 없이 바로 돌아가고, 틀리면 probe 가 알려준 대로
한 줄 넣으면 됩니다.

## 대상 지역

```
서울  /  판교·분당  /  수지·기흥  /  과천·평촌  /  서울 인접
```

이 범위 밖 공고는 **수집 단계에서 버립니다.** DB에 쌓이지도, 매칭되지도 않아요.
`app/regions.py` 의 `AREAS` 하나만 고치면 범위가 바뀝니다.

```python
AREAS = {
    "서울":      ("서울",),
    "판교·분당":  ("판교", "분당", "성남"),
    "수지·기흥":  ("수지", "기흥"),      # 신분당선으로 판교 연결
    "과천·평촌":  ("과천", "평촌", "안양"),
    "서울 인접":  ("하남", "광명", "구리", "남양주"),
}
EXCLUDE = ("처인",)   # 용인시 처인구는 판교 생활권이 아니다
```

`EXCLUDE` 가 필요한 이유: "용인"으로 매칭하면 처인구까지 딸려옵니다. 같은 시(市)라도
생활권이 갈리는 곳이 있어서 예외 목록을 따로 뒀습니다.

## 사용자 입장

```
/start
/keywords 백엔드, PostgreSQL, GIS, 공간정보
/regions 판교, 강남     ← 위 범위 안에서 더 좁히기 (생략 시 전체)
/exclude 인턴, 아르바이트, 파견
/preview                ← 지금 바로 결과 확인
```

받는 메시지는 지역별로 묶여서 옵니다:

```
☀️ 오늘의 채용공고 3건
키워드: 백엔드, GIS, 공간정보

📍 판교·분당
▪️ 백엔드 개발자 (PostgreSQL/PostGIS)
   (주)공간정보 · 경기 성남시 분당구
   경력 5년 이상 | 6,000만원

📍 서울
▪️ GIS 공간DB 엔지니어
   국토정보 · 서울 중구
```

## 구조

```
소스 어댑터 ──▶ 지역 게이트 ──▶ jobs 테이블 ──▶ 매처 ──▶ 텔레그램
  (하루 1회)    (서울·판교권)      (dedup)      (사용자별)
```

핵심 설계 하나: **수집과 매칭을 분리했습니다.** 사용자별로 API를 때리지 않고
하루 한 번 넓게 긁어 DB에 쌓은 뒤 로컬에서 매칭합니다. 사용자가 1명이든
1,000명이든 API 호출량이 고정이라 일 500회 쿼터로 충분합니다.

중복 제거는 `정규화(회사명) + 정규화(직무명)` 해시. 워크넷과 사람인에 같은 공고가
올라와도 한 번만 갑니다. `deliveries` 원장이 재발송을 막습니다.

| 파일 | 역할 |
|---|---|
| `app/regions.py` | **대상 지역 정의 — 범위 바꾸려면 여기만** |
| `app/sources/base.py` | `Job` 모델 + 어댑터 인터페이스 |
| `app/sources/greenhouse.py` | Greenhouse 공개 채용보드 (키 불필요) |
| `app/sources/worknet.py` | 워크넷 오픈API |
| `app/sources/saramin.py` | 사람인 오픈API |
| `app/sources/jobkorea.py` | 잡코리아 채용정보 API (발급 URL + 지역 코드표) |
| `app/matcher.py` | 키워드/제외/지역 매칭 + 랭킹 |
| `app/digest.py` | 수집 + 아침 다이제스트 |
| `app/bot.py` | 명령 처리 (`handle_command`) |
| `app/db.py` | Postgres 스토리지 |
| `server.py` | **Vercel 진입점 (WSGI)** — `/api/cron`, `/api/telegram` 라우팅 |
| `pyproject.toml` | 의존성 + Vercel 진입점 선언 (`server:app`) |
| `legacy/` | 구버전 보관. 배포 제외. `legacy/README.md` 참고 |

## ⚠️ 크롤링 어댑터는 넣지 않습니다

잡코리아가 사람인을 상대로 낸 소송에서 대법원(2017다224395)은 무단 크롤링을
부정경쟁행위이자 데이터베이스제작자 권리 침해로 보고 총 4억 5천만원 배상을
확정했습니다. "10%만 선별해 재구성했다"는 항변도 받아들여지지 않았고요.
개인용이라도 굳이 밟을 지뢰가 아닙니다. 공식 API 어댑터만 붙입니다.

## 튜닝

로그에 `worknet: 수집 3000건 → 대상지역 420건 (14%)` 이 찍힙니다.
대상 비율이 낮으면 `INGEST_MAX_PAGES` 를 올리세요. 반대로 대상 공고가 넘치면
낮춰서 쿼터를 아끼면 됩니다.

두 API 모두 서버측 지역 필터 파라미터가 있습니다(워크넷 `region`,
사람인 `loc_cd`). 각 코드표를 확인해 어댑터에 넣으면 페이지 낭비가 줄지만,
지역 판정의 최종 권한은 `regions.py` 에 있으니 코드가 틀려도 잘못된 공고가
새어나가진 않습니다.

## 다음 단계

- [x] Greenhouse 어댑터 — 키·승인 없이 도는 유일한 소스. 현재 주력입니다
- [x] SQLite → PostgreSQL (Supabase). "표준 SQL 만 썼다"는 건 사실이 아니었고
      `AUTOINCREMENT`, `datetime('now')`, `INSERT OR IGNORE`, `?`,
      `GROUP BY dedup_key` 를 전부 고쳐야 했습니다 — 자세한 건 `app/db.py` 상단
- [x] 롱폴링 → 웹훅 (`server.py`)
- [ ] Lever/Ashby 어댑터 — Greenhouse 와 같은 방식
- [ ] **제외어에 영문 추가.** 지금 제외 목록이 한글뿐이라
      "Machine Learning Engineer Intern" 이 `인턴` 필터를 그냥 통과합니다
- [ ] 임베딩 기반 유사도 매칭 (지금은 부분문자열이라 "BE" ≠ "백엔드")
- [ ] 잡코리아 어댑터 이중화 정리 (`legacy/README.md` 참고)
