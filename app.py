import os
import io
import json
import base64
import uuid
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, Form, HTTPException, File, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydub import AudioSegment

AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus")
ADMIN_PASSCODE = os.environ.get("ADMIN_PASSCODE", "happytree")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "db.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

DEFAULT_DB = {"students": [], "assignments": [], "submissions": {}}


def load_db():
    if not DB_PATH.exists():
        return json.loads(json.dumps(DEFAULT_DB))
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
        for k, v in DEFAULT_DB.items():
            db.setdefault(k, v)
        return db
    except Exception:
        return json.loads(json.dumps(DEFAULT_DB))


def save_db(db):
    tmp = DB_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    tmp.replace(DB_PATH)


app = FastAPI(title="HappyTree Reading Homework")


@app.get("/api/health")
def health():
    db = load_db()
    return {
        "ok": True,
        "azure_key_set": bool(AZURE_KEY),
        "students": len(db["students"]),
        "assignments": len(db["assignments"]),
    }


# ---------- auth ----------
@app.post("/api/login/student")
def login_student(payload: dict = Body(...)):
    db = load_db()
    sid = str(payload.get("id", "")).strip()
    pw = str(payload.get("pw", "")).strip()
    for s in db["students"]:
        if s["id"] == sid and s["pw"] == pw:
            return {"ok": True, "student": s}
    raise HTTPException(401, "아이디 또는 비밀번호가 일치하지 않아요.")


@app.post("/api/login/admin")
def login_admin(payload: dict = Body(...)):
    if str(payload.get("pw", "")) != ADMIN_PASSCODE:
        raise HTTPException(401, "비밀번호가 올바르지 않아요.")
    return {"ok": True}


# ---------- students ----------
@app.get("/api/students")
def get_students():
    return load_db()["students"]


@app.post("/api/students")
def add_student(payload: dict = Body(...)):
    with _lock:
        db = load_db()
        sid = str(payload.get("id", "")).strip()
        if not sid:
            sid = "ht" + uuid.uuid4().hex[:4]
        if any(s["id"] == sid for s in db["students"]):
            raise HTTPException(400, "이미 사용 중인 아이디예요.")
        student = {
            "id": sid,
            "pw": str(payload.get("pw", "")).strip() or uuid.uuid4().hex[:4],
            "name": str(payload.get("name", "")).strip(),
            "className": str(payload.get("className", "")).strip(),
        }
        db["students"].append(student)
        save_db(db)
    return student


@app.delete("/api/students/{student_id}")
def delete_student(student_id: str):
    with _lock:
        db = load_db()
        db["students"] = [s for s in db["students"] if s["id"] != student_id]
        save_db(db)
    return {"ok": True}


# ---------- assignments ----------
@app.get("/api/assignments")
def get_assignments():
    return load_db()["assignments"]


@app.post("/api/assignments")
def add_assignment(payload: dict = Body(...)):
    with _lock:
        db = load_db()
        a = {
            "id": "a" + uuid.uuid4().hex[:10],
            "title": str(payload.get("title", "")).strip(),
            "type": payload.get("type", "word"),
            "items": payload.get("items", []),
            "dueDate": payload.get("dueDate") or None,
            "rounds": max(1, min(3, int(payload.get("rounds") or 3))),
            "assignedIds": payload.get("assignedIds", []),
            "assignedClasses": payload.get("assignedClasses", []),
        }
        if not a["title"] or not a["items"]:
            raise HTTPException(400, "제목과 목록을 입력해주세요.")
        db["assignments"].insert(0, a)
        save_db(db)
    return a


@app.delete("/api/assignments/{assignment_id}")
def delete_assignment(assignment_id: str):
    with _lock:
        db = load_db()
        db["assignments"] = [a for a in db["assignments"] if a["id"] != assignment_id]
        save_db(db)
    return {"ok": True}


# ---------- submissions ----------
@app.get("/api/submissions/{assignment_id}")
def submissions_for_assignment(assignment_id: str):
    db = load_db()
    out = {}
    for key, sub in db["submissions"].items():
        if key.startswith(assignment_id + "__"):
            out[key.split("__", 1)[1]] = {
                "status": sub.get("status"),
                "submittedAt": sub.get("submittedAt"),
            }
    return out


@app.get("/api/submission/{assignment_id}/{student_id}")
def get_submission(assignment_id: str, student_id: str):
    db = load_db()
    return db["submissions"].get(f"{assignment_id}__{student_id}") or {}


@app.post("/api/submission/{assignment_id}/{student_id}")
def save_submission(assignment_id: str, student_id: str, payload: dict = Body(...)):
    with _lock:
        db = load_db()
        key = f"{assignment_id}__{student_id}"
        existing = db["submissions"].get(key, {})
        existing.update(payload)
        db["submissions"][key] = existing
        save_db(db)
    return existing


@app.post("/api/audio")
async def upload_audio(audio: UploadFile = File(...)):
    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "빈 오디오 파일이에요.")
    name = uuid.uuid4().hex + ".webm"
    with open(AUDIO_DIR / name, "wb") as f:
        f.write(raw)
    return {"url": f"/api/audio/{name}"}


@app.get("/api/audio/{name}")
def get_audio(name: str):
    path = AUDIO_DIR / name
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="audio/webm")


# ---------- Azure pronunciation assessment ----------
@app.post("/api/assess")
async def assess(text: str = Form(...), audio: UploadFile = File(...)):
    if not AZURE_KEY:
        raise HTTPException(500, "서버에 AZURE_SPEECH_KEY가 설정되어 있지 않아요.")

    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "오디오 파일이 비어있어요.")

    try:
        seg = AudioSegment.from_file(io.BytesIO(raw))
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        wav_bytes = buf.getvalue()
    except Exception as e:
        raise HTTPException(400, f"오디오 변환 실패: {e}")

    pa_config = {
        "ReferenceText": text,
        "GradingSystem": "HundredMark",
        "Granularity": "Word",
        "EnableMiscue": True,
    }
    pa_header = base64.b64encode(json.dumps(pa_config).encode("utf-8")).decode("utf-8")

    url = f"https://{AZURE_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        "Accept": "application/json",
        "Pronunciation-Assessment": pa_header,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url, params={"language": "en-US", "format": "detailed"}, headers=headers, content=wav_bytes
            )
    except httpx.RequestError as e:
        raise HTTPException(502, f"Azure 요청 실패: {e}")

    if resp.status_code != 200:
        raise HTTPException(502, f"Azure 오류 ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    nbest_list = data.get("NBest") or []
    nbest = nbest_list[0] if nbest_list else {}
    pa = nbest.get("PronunciationAssessment", {})
    words = []
    for w in nbest.get("Words", []):
        wpa = w.get("PronunciationAssessment") or {}
        words.append({
            "word": w.get("Word"),
            "accuracy": wpa.get("AccuracyScore"),
            "errorType": wpa.get("ErrorType"),
        })

    return {
        "recognizedText": data.get("DisplayText", ""),
        "accuracyScore": pa.get("AccuracyScore"),
        "fluencyScore": pa.get("FluencyScore"),
        "completenessScore": pa.get("CompletenessScore"),
        "pronScore": pa.get("PronScore"),
        "words": words,
    }


@app.post("/api/suggest-comment/{assignment_id}/{student_id}")
def suggest_comment(assignment_id: str, student_id: str):
    db = load_db()
    sub = db["submissions"].get(f"{assignment_id}__{student_id}")
    assignment = next((a for a in db["assignments"] if a["id"] == assignment_id), None)
    student = next((s for s in db["students"] if s["id"] == student_id), None)
    if not sub or not assignment:
        raise HTTPException(404, "제출 기록이 없어요.")

    name = (student or {}).get("name", "학생")
    items = assignment.get("items", [])
    rounds = assignment.get("rounds", 3)

    scores = []
    weak_words = {}   # word -> lowest accuracy seen
    missed = []       # items with no recording at all
    per_item_best = []

    for i, text in enumerate(items):
        takes = (sub.get("items") or [])
        takes_i = takes[i] if i < len(takes) else []
        takes_i = [t for t in (takes_i or []) if t]
        if not takes_i:
            missed.append(text)
            per_item_best.append(None)
            continue
        item_scores = [t.get("score") for t in takes_i if t.get("score") is not None]
        best = max(item_scores) if item_scores else None
        per_item_best.append(best)
        if best is not None:
            scores.append(best)
        # 약한 단어는 '마지막 회차' 기준으로만 판단 (초반에 틀렸다 고친 건 지적하지 않음)
        last_take = takes_i[-1]
        for w in (last_take.get("words") or []):
            acc = w.get("accuracy")
            word = (w.get("word") or "").strip()
            if not word or acc is None:
                continue
            if acc < 70:
                if word not in weak_words or acc < weak_words[word]:
                    weak_words[word] = acc

    if not scores:
        return {
            "comment": f"{name} 학생, 녹음 잘 제출했어요! 다음에는 조금 더 또박또박 읽어볼까요?",
            "hasScores": False,
        }

    avg = round(sum(scores) / len(scores))

    # 개선한 항목 (1회차 대비 마지막 회차)
    improved = 0
    for i in range(len(items)):
        takes = (sub.get("items") or [])
        takes_i = takes[i] if i < len(takes) else []
        takes_i = takes_i or []
        first = next((t.get("score") for t in takes_i if t and t.get("score") is not None), None)
        last = next((t.get("score") for t in reversed(takes_i) if t and t.get("score") is not None), None)
        if first is not None and last is not None and last - first >= 5:
            improved += 1

    parts = []
    if avg >= 90:
        parts.append(f"{name} 학생, 발음이 아주 좋아요! 평균 {avg}점으로 또박또박 잘 읽었어요.")
    elif avg >= 75:
        parts.append(f"{name} 학생, 전체적으로 잘 읽었어요. 평균 {avg}점이에요.")
    elif avg >= 60:
        parts.append(f"{name} 학생, 열심히 녹음했네요. 평균 {avg}점으로 조금만 더 연습하면 좋아지겠어요.")
    else:
        parts.append(f"{name} 학생, 끝까지 녹음하느라 수고했어요. 평균 {avg}점이니 천천히 다시 연습해볼까요?")

    if improved >= 2:
        parts.append(f"회차를 거듭하면서 {improved}개 항목의 발음이 좋아진 게 보여요. 반복 연습이 효과가 있었어요!")

    if weak_words:
        top = sorted(weak_words.items(), key=lambda x: x[1])[:2]
        wl = ", ".join(w for w, _ in top)
        if avg >= 90:
            parts.append(f"{wl} 정도만 조금 더 또렷하게 발음하면 완벽하겠어요.")
        else:
            parts.append(f"특히 {wl} 이 단어는 소리를 하나씩 나눠서 천천히 연습해보면 좋겠어요.")

    weakest_idx = None
    weakest_val = None
    for i, b in enumerate(per_item_best):
        if b is not None and (weakest_val is None or b < weakest_val):
            weakest_val = b
            weakest_idx = i
    if weakest_idx is not None and weakest_val is not None and weakest_val < 70 and not weak_words:
        parts.append(f'"{items[weakest_idx]}" 문항이 가장 어려웠던 것 같아요. 듣기 버튼으로 여러 번 듣고 따라 해볼까요?')

    if missed:
        parts.append(f"아직 녹음하지 않은 항목이 {len(missed)}개 있어요. 마저 채워주면 좋겠어요.")

    return {"comment": " ".join(parts), "hasScores": True, "average": avg}


# ---------- backup ----------
@app.get("/api/backup")
def backup():
    return load_db()


@app.post("/api/restore")
def restore(payload: dict = Body(...)):
    if not isinstance(payload.get("students"), list) or not isinstance(payload.get("assignments"), list):
        raise HTTPException(400, "백업 파일 형식이 올바르지 않아요.")
    with _lock:
        db = load_db()
        db["students"] = payload["students"]
        db["assignments"] = payload["assignments"]
        if isinstance(payload.get("submissions"), dict):
            db["submissions"] = payload["submissions"]
        save_db(db)
    return {"ok": True}


# ---------- static frontend (must be last) ----------
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
