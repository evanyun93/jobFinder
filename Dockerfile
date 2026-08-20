# Vercel 밖으로 옮길 때 쓰는 컨테이너 이미지.
# Cloud Run, Koyeb, Render, Fly, 그냥 VM — Docker 를 받는 곳이면 어디든 돈다.
#
#   docker build -t jobfinder .
#   docker run -p 8080:8080 --env-file .env jobfinder
#
# 자세한 이전 절차는 PORTING.md 참고.

FROM python:3.12-slim

# 파이썬이 .pyc 를 남기지 않게 하고, 로그가 버퍼에 갇히지 않게 한다.
# 후자가 없으면 컨테이너 로그가 실시간으로 안 보여서 디버깅이 괴로워진다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# 의존성을 먼저 복사해야 소스만 바뀔 때 이 레이어가 캐시된다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY app/ ./app/
COPY server.py .

# 대부분의 호스트가 PORT 환경변수로 포트를 지정한다. 없으면 8080.
ENV PORT=8080
EXPOSE 8080

# 루트로 돌리지 않는다.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# --timeout 120: 수집이 10초 넘게 걸린다(실측 11.6초). 기본 30초로는 잘린다.
# --workers 2: 개인용이라 이 이상 필요 없다. 메모리 적은 무료 티어를 배려.
CMD exec gunicorn server:app \
      --bind "0.0.0.0:${PORT}" \
      --workers 2 \
      --timeout 120 \
      --access-logfile - \
      --error-logfile -
