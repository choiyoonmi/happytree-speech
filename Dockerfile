FROM python:3.11-slim

# ffmpeg: 오디오 변환용 / libssl·libasound: Azure Speech SDK 필수 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates libssl-dev libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
