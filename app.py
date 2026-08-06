import os
import io
import json
import base64

import httpx
from fastapi import FastAPI, UploadFile, Form, HTTPException, File
from fastapi.middleware.cors import CORSMiddleware
from pydub import AudioSegment

AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus")

app = FastAPI(title="HappyTree Pronunciation Assessment")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 내부용 소규모 도구라 전체 허용. 필요하면 특정 도메인으로 좁히세요.
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "azure_key_set": bool(AZURE_KEY)}


@app.post("/api/assess")
async def assess(text: str = Form(...), audio: UploadFile = File(...)):
    if not AZURE_KEY:
        raise HTTPException(500, "서버에 AZURE_SPEECH_KEY 환경변수가 설정되어 있지 않아요.")

    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "오디오 파일이 비어있어요.")

    # Azure REST API는 16kHz mono 16bit PCM WAV를 요구함 -> 브라우저가 보낸 webm/opus를 변환
    try:
        seg = AudioSegment.from_file(io.BytesIO(raw))
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        wav_bytes = buf.getvalue()
    except Exception as e:
        raise HTTPException(400, f"오디오 변환에 실패했어요: {e}")

    pa_config = {
        "ReferenceText": text,
        "GradingSystem": "HundredMark",
        "Granularity": "Word",
        "EnableMiscue": True,
    }
    pa_header = base64.b64encode(json.dumps(pa_config).encode("utf-8")).decode("utf-8")

    url = f"https://{AZURE_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    params = {"language": "en-US", "format": "detailed"}
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        "Accept": "application/json",
        "Pronunciation-Assessment": pa_header,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, params=params, headers=headers, content=wav_bytes)
    except httpx.RequestError as e:
        raise HTTPException(502, f"Azure 요청 실패: {e}")

    if resp.status_code != 200:
        raise HTTPException(502, f"Azure 오류 ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    nbest_list = data.get("NBest") or []
    nbest = nbest_list[0] if nbest_list else {}
    pa = nbest.get("PronunciationAssessment", {})
    words = [
        {
            "word": w.get("Word"),
            "accuracyScore": (w.get("PronunciationAssessment") or {}).get("AccuracyScore"),
            "errorType": (w.get("PronunciationAssessment") or {}).get("ErrorType"),
        }
        for w in nbest.get("Words", [])
    ]

    return {
        "recognizedText": data.get("DisplayText", ""),
        "accuracyScore": pa.get("AccuracyScore"),
        "fluencyScore": pa.get("FluencyScore"),
        "completenessScore": pa.get("CompletenessScore"),
        "pronScore": pa.get("PronScore"),
        "words": words,
    }
