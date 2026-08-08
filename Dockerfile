FROM python:3.11-slim

# ffmpeg: 오디오 변환용 / libssl·libasound: Azure Speech SDK 필수 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates libssl-dev libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# worker는 반드시 1개 유지 (파일 잠금이 프로세스 내에서만 동작).
# 동시 처리는 워커 내부 스레드풀이 담당하며 10~20명 동시 녹음에 충분합니다.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000", \
     "--workers", "1", "--timeout-keep-alive", "65"]
