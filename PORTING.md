# 이전 대비 문서

Vercel 이 막히거나, 요금제가 바뀌거나, 그냥 마음에 안 들 때 옮기는 방법.

**결론부터: 옮기기 쉽게 만들어놨다.** 호스팅에 묶인 건 설정 파일 세 개뿐이고,
실제 코드는 표준 Python + 표준 WSGI 라 어디서든 그대로 돈다.

---

## 1. 무엇이 종속인가

| 파일 | 종속 내용 | 다른 곳에서 |
|---|---|---|
| `vercel.json` | 크론 스케줄, maxDuration | 무시됨 — 그냥 두면 된다 |
| `pyproject.toml` 의 `[tool.vercel]` | 진입점 선언 | 무시됨 — 다른 키는 표준 |
| `.vercelignore` | 배포 제외 목록 | 무시됨 |

**코드는 종속이 없다.** [server.py](server.py) 는 순수 WSGI 앱이라
gunicorn / uwsgi / waitress / wsgiref 어디서든 돈다 (표준 `wsgiref` 로 검증함).
DB 는 이미 외부(Supabase)라 호스팅과 무관하다.

> 이 이식성은 저절로 얻어진 게 아니다. 표준 WSGI 서버로 테스트했을 때
> 인증 실패 응답에서 **커넥션이 끊기는 버그**가 나왔다. 조기 반환 시 요청
> 본문을 안 읽고 나가는 게 원인인데, Vercel 은 요청을 통째로 버퍼링해줘서
> 가려져 있었다. `_drain()` 으로 고쳤다. 옮긴 뒤에 발견했으면 훨씬 아팠을 버그다.

---

## 2. 먼저 이해할 것: 필요한 게 둘로 나뉜다

이걸 알면 선택지가 확 넓어진다.

| | 무엇이 필요한가 | 없으면 |
|---|---|---|
| **① 아침 다이제스트** | 하루 한 번 파이썬을 돌릴 스케줄러 | 서비스의 존재 이유가 사라짐 |
| **② 봇 명령** (`/keywords` 등) | HTTPS 주소(웹훅) **또는** 상주 프로세스(롱폴링) | 설정 변경 불가. 알림은 계속 옴 |

**①은 웹 서버가 전혀 필요 없다.** `python -m app.main daily` 한 줄이면 끝난다.
그래서 GitHub Actions 같은 "서버 없는" 곳으로도 피신할 수 있다.

②만 HTTPS 주소가 필요하다. 급하면 ①만 먼저 살리고 ②는 나중에 붙여도 된다.

---

## 3. 선택지 (2026년 8월 기준)

| 대상 | 비용 | ① 다이제스트 | ② 봇 명령 | 주의점 |
|---|---|---|---|---|
| **GitHub Actions** | 무료 (공개 저장소) | ✅ | ❌ | 60일 무커밋 시 자동 정지 |
| **Oracle Cloud 무료 VM** | 영구 무료 | ✅ | ✅ | 가입 심사가 까다로움 |
| **Google Cloud Run** | 무료 한도 넉넉 | ✅ (Cloud Scheduler) | ✅ | 설정 단계가 많음 |
| **Koyeb** | 무료 티어 | ✅ | ✅ | 무료 인스턴스 1개 |
| **Render** | 무료 티어 | △ | ✅ | 15분 후 슬립, 콜드스타트 ~30초 |
| ~~Railway~~ / ~~Fly.io~~ | ❌ | | | 2026 기준 트라이얼 크레딧으로 전환, 진짜 무료 아님 |

**추천 순서**

1. **급하면 GitHub Actions** — 30분이면 끝나고 알림이 계속 온다
2. **제대로 옮기려면 Oracle 무료 VM** — 상주 모드로 돌리면 Vercel 이전과 완전히 동일
3. **컨테이너가 편하면 Cloud Run / Koyeb** — `Dockerfile` 이 이미 있다

DB(Supabase)는 **어느 경우에도 그대로 둔다.** 건드릴 필요가 없다.

---

## 4. 시나리오 A — GitHub Actions (가장 빠른 대피)

서버가 없다. 스케줄에 맞춰 컨테이너 하나 띄워 수집+발송하고 끝난다.

워크플로 파일은 이미 만들어져 있다: [.github/workflows/daily-digest.yml](.github/workflows/daily-digest.yml)

```bash
# 1. 저장소를 GitHub 에 올린다 (.gitignore 가 .env 를 막아준다)
git init && git add -A && git commit -m "initial"
gh repo create jobfinder --private --source=. --push

# 2. secret 등록
gh secret set DATABASE_URL        # Supabase Transaction pooler URL
gh secret set TELEGRAM_BOT_TOKEN

# 3. Actions 탭에서 워크플로 Enable, 수동 실행으로 확인
gh workflow run "매일 채용공고 다이제스트"
```

### 함정 세 개

**60일 무커밋이면 GitHub 이 스케줄을 자동으로 끈다.** 메일은 오지만 놓치기
쉽다. 커밋만 타이머를 리셋하고 이슈나 PR은 안 된다. 두 달에 한 번 아무 커밋이나
하거나, keepalive 액션을 붙여야 한다.

**정시를 보장하지 않는다.** 혼잡하면 15분 이상 밀린다. Vercel Hobby의 ±59분보다는
낫지만 정각은 아니다.

**봇 명령이 안 된다.** 키워드를 바꾸려면 로컬에서
`python -m app.main webhook off` 후 `run` 을 잠깐 돌리거나, DB를 직접 수정한다.

---

## 5. 시나리오 B — 컨테이너 호스트 (Cloud Run, Koyeb, Render)

[Dockerfile](Dockerfile) 이 이미 있다. 봇 명령까지 전부 살아난다.

```bash
docker build -t jobfinder .
docker run -p 8080:8080 --env-file .env jobfinder
curl localhost:8080/          # {"ok": true, ...}
```

배포 후 할 일 두 가지:

**1) 크론을 새로 건다.** 호스트의 스케줄러가 `/api/cron` 을 때리게 한다.
Vercel 과 달리 인증 헤더를 직접 넣어줘야 한다.

```bash
curl -X POST https://<새주소>/api/cron \
     -H "Authorization: Bearer $CRON_SECRET"
```

스케줄러가 없는 호스트면 [cron-job.org](https://cron-job.org) 같은 무료 외부
핑거를 쓰면 된다. 헤더를 넣을 수 있는 곳이어야 한다.

**2) 웹훅을 새 주소로 옮긴다.**

```bash
python -m app.main webhook https://<새주소>/api/telegram
```

### 주의

- **크론 시각은 UTC.** 한국 오전 8시 = `0 23 * * *`
- **Render 무료 티어는 15분 후 잠든다.** 크론이 깨우긴 하지만 콜드스타트 ~30초가
  붙는다. 웹훅 응답도 첫 명령은 느리다
- **Cloud Run 은 리전을 서울(asia-northeast3)로.** DB가 서울이다

---

## 6. 시나리오 C — VM (Oracle 무료 등)

가장 단순하다. **서버리스 이전 방식 그대로** 돌린다.

```bash
git clone <저장소> && cd jobFinder
pip install -r requirements.txt
cp .env.example .env && vi .env      # DATABASE_URL, TELEGRAM_BOT_TOKEN

python -m app.main webhook off       # 웹훅 해제 (롱폴링과 공존 불가)
python -m app.main run               # 스케줄러 + 롱폴링
```

`run` 모드는 APScheduler 로 매일 발송하고 롱폴링으로 봇 명령을 받는다.
**HTTPS 주소도, 인증서도, 외부 크론도 필요 없다.** 이래서 이 모드를 지우지 않고
남겨뒀다.

systemd 로 상주시키려면:

```ini
[Unit]
Description=jobFinder
After=network-online.target

[Service]
WorkingDirectory=/home/ubuntu/jobFinder
ExecStart=/usr/bin/python3 -m app.main run
Restart=always
RestartSec=10
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
```

---

## 7. 이전 체크리스트

어느 시나리오든 공통이다.

- [ ] `DATABASE_URL` 을 새 환경에 등록 (**Transaction pooler, 6543**)
- [ ] `TELEGRAM_BOT_TOKEN` 등록
- [ ] `CRON_SECRET` 등록 — HTTP로 크론을 트리거하는 경우에만
- [ ] `TELEGRAM_WEBHOOK_SECRET` 등록 — 웹훅을 쓰는 경우에만
- [ ] 크론 시각이 **UTC 기준**인지 확인 (한국 8시 = `0 23 * * *`)
- [ ] 새 주소로 웹훅 재등록 또는 `webhook off`
- [ ] `python -m app.main webhook` 으로 상태 확인 (`최근 오류: 없음`)
- [ ] 다음날 아침 알림 도착 확인
- [ ] **확인된 뒤에** Vercel 프로젝트 삭제

마지막 항목이 중요하다. 새 곳이 확실히 돌기 전에 지우지 말 것. 둘 다 살아 있는
동안에는 **웹훅이 한쪽만 가리키므로** 봇 명령은 한 곳에서만 처리되지만,
**크론은 양쪽 다 돌 수 있다.** 다만 `deliveries` 원장이 공유되므로 중복 발송은
일어나지 않는다 — 늦게 도는 쪽이 "보낼 게 없음"으로 끝난다.

---

## 8. 검증 방법

옮긴 뒤 이 순서로 확인한다.

```bash
# 1. 앱이 살아있나
curl https://<새주소>/
# {"ok": true, "service": "jobfinder", ...}

# 2. 인증이 막고 있나 (401 이 정상)
curl https://<새주소>/api/cron

# 3. 크론이 실제로 도나
curl https://<새주소>/api/cron -H "Authorization: Bearer $CRON_SECRET"
# {"new_jobs": N, "sent": M}

# 4. 웹훅이 새 주소를 보나
python -m app.main webhook

# 5. 텔레그램에서 /my 를 쳐본다
```

3번에서 `new_jobs: 0` 이 나와도 정상이다. 이미 수집된 공고는 중복으로 안 들어간다.
`sent: 0` 도 마찬가지 — 매칭된 공고가 전부 원장에 있으면 재발송하지 않는다.

서버 없이 도는 배치 모드는 이렇게 확인한다.

```bash
python -m app.main dryrun    # 수집하고 결과만 출력, 발송 안 함
python -m app.main daily     # 진짜 수집 + 발송
```

---

## 9. 자주 겪을 문제

| 증상 | 원인 | 해결 |
|---|---|---|
| `invalid connection option "pgbouncer"` | Supabase가 붙여준 Prisma 전용 파라미터 | URL 끝의 `?pgbouncer=true` 삭제 |
| 며칠 뒤 커넥션 고갈 | Direct connection(5432) 사용 | Transaction pooler(6543)로 교체 |
| `prepared statement ... already exists` | psycopg 자동 prepare | `prepare_threshold=None` (이미 적용됨) |
| 봇 명령 무응답, 409 오류 | 웹훅과 롱폴링 동시 사용 | 한쪽만. `webhook off` 또는 `run` 중지 |
| 알림이 오후에 옴 | 크론을 KST로 적음 | UTC로 환산 (8시 → `0 23 * * *`) |
| 소스가 조용히 0건 | 빈 환경변수 주입 | `_str()` 이 방어하지만, 값 확인 |
| 수집이 타임아웃 | 기본 타임아웃 30초 < 실측 11.6초+ | gunicorn `--timeout 120` (이미 적용됨) |

---

## 참고

- [GitHub Actions 스케줄 제약](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) — 60일 자동 정지, 지연
- [Vercel Cron 요금·제약](https://vercel.com/docs/cron-jobs/usage-and-pricing) — Hobby 하루 1회, ±59분
- [Supabase 연결 방식](https://supabase.com/docs/guides/database/connecting-to-postgres) — pooler vs direct
