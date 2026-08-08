import os
import io
import asyncio
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
_sub_locks = {}
_sub_locks_guard = threading.Lock()

DEFAULT_DB = {"students": [], "assignments": [], "submissions": {}}

SUB_DIR = DATA_DIR / "submissions"
SUB_DIR.mkdir(parents=True, exist_ok=True)


def _sub_lock(student_id: str):
    """학생별 잠금 — 서로 다른 학생은 동시에 저장 가능."""
    with _sub_locks_guard:
        if student_id not in _sub_locks:
            _sub_locks[student_id] = threading.Lock()
        return _sub_locks[student_id]


def _safe_id(s: str) -> str:
    return "".join(c for c in str(s) if c.isalnum() or c in "-_")[:64] or "unknown"


def _sub_path(student_id: str) -> Path:
    return SUB_DIR / f"{_safe_id(student_id)}.json"


def load_student_subs(student_id: str) -> dict:
    """한 학생의 제출 기록 전체 {assignment_id: submission}."""
    p = _sub_path(student_id)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_student_subs(student_id: str, data: dict):
    p = _sub_path(student_id)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(p)


def all_student_ids() -> list:
    return [p.stem for p in SUB_DIR.glob("*.json")]


def get_submission_record(assignment_id: str, student_id: str) -> dict:
    return load_student_subs(student_id).get(assignment_id) or {}


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


def migrate_submissions_if_needed():
    """예전 db.json 안에 있던 submissions를 학생별 파일로 옮긴다 (최초 1회)."""
    db = load_db()
    old = db.get("submissions") or {}
    if not old:
        return
    grouped = {}
    for key, sub in old.items():
        if "__" not in key:
            continue
        aid, sid = key.split("__", 1)
        grouped.setdefault(sid, {})[aid] = sub
    for sid, subs in grouped.items():
        existing = load_student_subs(sid)
        existing.update(subs)
        save_student_subs(sid, existing)
    db["submissions"] = {}
    save_db(db)
    print(f"[migrate] {len(old)}건의 제출 기록을 학생 {len(grouped)}명 파일로 이전했어요.")


migrate_submissions_if_needed()


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
            "book": str(payload.get("book", "")).strip(),
            "type": payload.get("type", "word"),
            "items": payload.get("items", []),
            "meanings": payload.get("meanings", []),
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


@app.post("/api/assignments/bulk")
def add_assignments_bulk(payload: dict = Body(...)):
    """여러 과제를 한 번에 생성 (교재 한 권을 Day별로 나눠서 등록)."""
    items = payload.get("assignments") or []
    if not items:
        raise HTTPException(400, "등록할 과제가 없어요.")
    created = []
    with _lock:
        db = load_db()
        for p in items:
            title = str(p.get("title", "")).strip()
            words = p.get("items") or []
            if not title or not words:
                continue
            a = {
                "id": "a" + uuid.uuid4().hex[:10],
                "title": title,
                "book": str(p.get("book", "")).strip(),
                "type": p.get("type", "word"),
                "items": words,
                "meanings": p.get("meanings", []),
                "dueDate": p.get("dueDate") or None,
                "rounds": max(1, min(3, int(p.get("rounds") or 3))),
                "assignedIds": p.get("assignedIds", []),
                "assignedClasses": p.get("assignedClasses", []),
            }
            db["assignments"].insert(0, a)
            created.append(a)
        save_db(db)
    return {"created": len(created), "assignments": created}


@app.post("/api/assignments/delete-many")
def delete_assignments(payload: dict = Body(...)):
    ids = set(payload.get("ids") or [])
    if not ids:
        raise HTTPException(400, "삭제할 과제가 없어요.")
    with _lock:
        db = load_db()
        before = len(db["assignments"])
        db["assignments"] = [a for a in db["assignments"] if a["id"] not in ids]
        save_db(db)
    for sid in all_student_ids():
        with _sub_lock(sid):
            subs = load_student_subs(sid)
            changed = False
            for aid in list(subs.keys()):
                if aid in ids:
                    del subs[aid]; changed = True
            if changed:
                save_student_subs(sid, subs)
    return {"deleted": before - len(db["assignments"])}


@app.patch("/api/assignments/{assignment_id}")
def update_assignment(assignment_id: str, payload: dict = Body(...)):
    """과제 하나 수정 (마감일, 제목, 녹음 횟수 등)."""
    allowed = {"title", "dueDate", "rounds", "type", "book"}
    with _lock:
        db = load_db()
        for a in db["assignments"]:
            if a["id"] == assignment_id:
                for k, v in payload.items():
                    if k not in allowed:
                        continue
                    if k == "rounds":
                        a[k] = max(1, min(3, int(v or 3)))
                    elif k == "dueDate":
                        a[k] = v or None
                    else:
                        a[k] = str(v).strip()
                save_db(db)
                return a
    raise HTTPException(404, "과제를 찾을 수 없어요.")


@app.post("/api/assignments/reschedule")
def reschedule(payload: dict = Body(...)):
    """일정 일괄 조정.
    mode='shift'  : ids 목록의 마감일을 days 만큼 뒤로 미룸
    mode='respread': ids 목록을 startDate 부터 weekdays 요일에 다시 배치
    """
    from datetime import date, timedelta

    ids = payload.get("ids") or []
    mode = payload.get("mode", "shift")
    if not ids:
        raise HTTPException(400, "조정할 과제가 없어요.")

    def parse(s):
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)

    with _lock:
        db = load_db()
        targets = [a for a in db["assignments"] if a["id"] in ids]
        # 기존 마감일 순서 유지 (없는 건 뒤로)
        targets.sort(key=lambda a: (a.get("dueDate") is None, a.get("dueDate") or ""))

        if mode == "shift":
            days = int(payload.get("days") or 0)
            if not days:
                raise HTTPException(400, "미룰 일수를 입력해주세요.")
            for a in targets:
                if a.get("dueDate"):
                    a["dueDate"] = (parse(a["dueDate"]) + timedelta(days=days)).isoformat()

        elif mode == "respread":
            start = payload.get("startDate")
            weekdays = payload.get("weekdays") or [0, 1, 2, 3, 4, 5, 6]
            if not start:
                raise HTTPException(400, "시작일을 입력해주세요.")
            # python: 월=0 → js: 일=0 이므로 변환
            js_wd = set(int(w) for w in weekdays)
            cur = parse(start)
            assigned = 0
            guard = 0
            while assigned < len(targets) and guard < 800:
                if ((cur.weekday() + 1) % 7) in js_wd:
                    targets[assigned]["dueDate"] = cur.isoformat()
                    assigned += 1
                cur += timedelta(days=1)
                guard += 1
        else:
            raise HTTPException(400, "알 수 없는 방식이에요.")

        save_db(db)
    return {"updated": len(targets), "assignments": targets}


@app.get("/api/student-submissions/{student_id}")
def student_submissions(student_id: str):
    """한 학생의 모든 과제 제출 상태를 한 번에 반환."""
    out = {}
    for aid, sub in load_student_subs(student_id).items():
        scores = []
        for takes in (sub.get("items") or []):
            for t in (takes or []):
                if t and t.get("score") is not None:
                    scores.append(t["score"])
        out[aid] = {
            "status": sub.get("status", "none"),
            "submittedAt": sub.get("submittedAt"),
            "average": round(sum(scores) / len(scores)) if scores else None,
        }
    return out


# ---------- submissions ----------
@app.get("/api/submissions/{assignment_id}")
def submissions_for_assignment(assignment_id: str):
    out = {}
    for sid in all_student_ids():
        sub = load_student_subs(sid).get(assignment_id)
        if sub:
            out[sid] = {
                "status": sub.get("status"),
                "submittedAt": sub.get("submittedAt"),
            }
    return out


@app.get("/api/submission/{assignment_id}/{student_id}")
def get_submission(assignment_id: str, student_id: str):
    return get_submission_record(assignment_id, student_id)


@app.post("/api/submission/{assignment_id}/{student_id}")
def save_submission(assignment_id: str, student_id: str, payload: dict = Body(...)):
    # 학생별 잠금 — 다른 학생의 저장을 막지 않음
    with _sub_lock(student_id):
        subs = load_student_subs(student_id)
        existing = subs.get(assignment_id, {})
        existing.update(payload)
        subs[assignment_id] = existing
        save_student_subs(student_id, subs)
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
def decode_audio(raw: bytes):
    """브라우저가 보낸 오디오를 안전하게 디코딩. 실패 시 여러 방법을 시도."""
    errors = []
    # 1) 자동 감지
    try:
        return AudioSegment.from_file(io.BytesIO(raw)), "auto"
    except Exception as e:
        errors.append(f"auto: {e}")
    # 2) 포맷 명시
    for fmt in ("webm", "ogg", "mp4", "m4a", "wav"):
        try:
            return AudioSegment.from_file(io.BytesIO(raw), format=fmt), fmt
        except Exception as e:
            errors.append(f"{fmt}: {e}")
    # 3) 임시파일 + ffmpeg 직접
    try:
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(raw); src = f.name
        dst = src + ".wav"
        subprocess.run(["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", dst],
                       capture_output=True, timeout=30)
        seg = AudioSegment.from_file(dst, format="wav")
        os.unlink(src); os.unlink(dst)
        return seg, "ffmpeg"
    except Exception as e:
        errors.append(f"ffmpeg: {e}")
    raise HTTPException(400, "오디오를 읽을 수 없어요. " + " | ".join(errors[:3]))


def assess_with_sdk(wav_path: str, reference: str):
    """Azure Speech SDK로 발음평가. REST API는 점수를 누락하는 알려진 문제가 있어 SDK를 사용."""
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
    speech_config.speech_recognition_language = "en-US"
    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)

    pa_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Word,
        enable_miscue=len(reference.strip().split()) > 2,
    )

    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    pa_config.apply_to(recognizer)
    result = recognizer.recognize_once()

    if result.reason == speechsdk.ResultReason.Canceled:
        det = result.cancellation_details
        raise HTTPException(502, f"Azure 취소됨: {det.reason} {det.error_details or ''}"[:300])

    if result.reason != speechsdk.ResultReason.RecognizedSpeech:
        return {"ok": False, "status": str(result.reason).split(".")[-1], "text": ""}

    pa = speechsdk.PronunciationAssessmentResult(result)
    raw = result.properties.get(speechsdk.PropertyId.SpeechServiceResponse_JsonResult) or "{}"

    words = []
    try:
        for w in (pa.words or []):
            words.append({
                "word": w.word,
                "accuracy": w.accuracy_score,
                "errorType": w.error_type,
            })
    except Exception:
        pass

    return {
        "ok": pa.pronunciation_score is not None,
        "status": "Success",
        "text": result.text or "",
        "pron": pa.pronunciation_score,
        "accuracy": pa.accuracy_score,
        "fluency": pa.fluency_score,
        "completeness": pa.completeness_score,
        "words": words,
        "raw": raw,
    }


@app.post("/api/assess")
async def assess(text: str = Form(...), audio: UploadFile = File(...), debug: str = Form("")):
    if not AZURE_KEY:
        raise HTTPException(500, "서버에 AZURE_SPEECH_KEY가 설정되어 있지 않아요.")

    raw_bytes = await audio.read()
    if not raw_bytes:
        raise HTTPException(400, "오디오 파일이 비어있어요.")

    seg, decoder = decode_audio(raw_bytes)
    orig_dbfs = seg.dBFS
    orig_ms = len(seg)
    seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    if seg.dBFS != float("-inf") and seg.dBFS < -20:
        seg = seg.apply_gain(min(-20 - seg.dBFS, 25))
    pad = AudioSegment.silent(duration=300, frame_rate=16000).set_channels(1).set_sample_width(2)
    seg = pad + seg + pad

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    seg.export(wav_path, format="wav")

    audio_info = {
        "durationMs": orig_ms,
        "dBFS": None if orig_dbfs == float("-inf") else round(orig_dbfs, 1),
        "bytesIn": len(raw_bytes),
        "decoder": decoder,
        "contentType": audio.content_type,
        "engine": "sdk",
    }

    try:
        r = await asyncio.to_thread(assess_with_sdk, wav_path, text)
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass

    if not r.get("ok"):
        status = r.get("status", "")
        dur = audio_info["durationMs"]
        db = audio_info["dBFS"]
        if db is None:
            note = "녹음이 완전히 무음이에요. 마이크가 켜져 있는지 확인해주세요."
        elif dur < 500:
            note = f"녹음이 너무 짧아요 ({dur/1000:.1f}초). 조금 더 길게 읽어볼까요?"
        elif status == "NoMatch":
            note = "읽은 내용이 잘 인식되지 않았어요. 다시 한번 또박또박 읽어볼까요?"
        else:
            note = f"인식되지 않았어요 ({status}). 다시 녹음해볼까요?"
        out = {
            "recognizedText": r.get("text", ""),
            "accuracyScore": None, "fluencyScore": None,
            "completenessScore": None, "pronScore": None,
            "words": [], "status": status, "note": note, "audio": audio_info,
        }
        if debug:
            out["raw"] = (r.get("raw") or "")[:1500]
        return out

    out = {
        "recognizedText": r.get("text", ""),
        "accuracyScore": r.get("accuracy"),
        "fluencyScore": r.get("fluency"),
        "completenessScore": r.get("completeness"),
        "pronScore": r.get("pron"),
        "words": r.get("words", []),
        "status": "Success",
        "audio": audio_info,
    }
    if debug:
        out["raw"] = (r.get("raw") or "")[:1500]
    return out


@app.post("/api/suggest-comment/{assignment_id}/{student_id}")
def suggest_comment(assignment_id: str, student_id: str):
    db = load_db()
    sub = get_submission_record(assignment_id, student_id)
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


@app.get("/api/report/{student_id}")
def student_report(student_id: str, start: str = "", end: str = ""):
    """기간 내 학생의 학습 요약. start/end 는 YYYY-MM-DD."""
    from datetime import datetime, date, timedelta

    db = load_db()
    student = next((s for s in db["students"] if s["id"] == student_id), None)
    if not student:
        raise HTTPException(404, "학생을 찾을 수 없어요.")
    student_subs = load_student_subs(student_id)

    def parse(d, fallback):
        try:
            y, m, dd = map(int, d.split("-"))
            return date(y, m, dd)
        except Exception:
            return fallback

    today = date.today()
    d_end = parse(end, today)
    d_start = parse(start, d_end - timedelta(days=29))

    def in_range(a):
        due = a.get("dueDate")
        if not due:
            return True
        d = parse(due, None)
        return d is None or (d_start <= d <= d_end)

    assigned = [
        a for a in db["assignments"]
        if in_range(a) and (not a.get("assignedIds") or student_id in a["assignedIds"])
    ]

    rows = []
    all_scores = []
    weak_words = {}
    submitted_count = 0
    weekly = {}
    daily = {}
    acc_all, flu_all, comp_all = [], [], []

    for a in assigned:
        sub = student_subs.get(a["id"]) or {}
        status = sub.get("status", "none")
        if status in ("submitted", "reviewed"):
            submitted_count += 1

        day = a.get("dueDate") or ""
        if day:
            daily.setdefault(day, {"acc": [], "flu": [], "comp": [], "pron": [], "done": 0, "total": 0})
            daily[day]["total"] += 1
            if status in ("submitted", "reviewed"):
                daily[day]["done"] += 1

        item_scores = []
        recorded = 0
        total_slots = len(a.get("items", [])) * (a.get("rounds", 3) or 3)
        for i, text in enumerate(a.get("items", [])):
            takes = (sub.get("items") or [])
            ti = takes[i] if i < len(takes) else []
            ti = [t for t in (ti or []) if t]
            recorded += len(ti)
            s = [t.get("score") for t in ti if t.get("score") is not None]
            if s:
                item_scores.append(max(s))
            for t in ti:
                d = t.get("detail") or {}
                if day:
                    if d.get("accuracy") is not None: daily[day]["acc"].append(d["accuracy"])
                    if d.get("fluency") is not None: daily[day]["flu"].append(d["fluency"])
                    if d.get("completeness") is not None: daily[day]["comp"].append(d["completeness"])
                    if t.get("score") is not None: daily[day]["pron"].append(t["score"])
                if d.get("accuracy") is not None: acc_all.append(d["accuracy"])
                if d.get("fluency") is not None: flu_all.append(d["fluency"])
                if d.get("completeness") is not None: comp_all.append(d["completeness"])
            if ti:
                for w in (ti[-1].get("words") or []):
                    acc = w.get("accuracy")
                    word = (w.get("word") or "").strip()
                    if word and acc is not None and acc < 70:
                        if word not in weak_words or acc < weak_words[word]:
                            weak_words[word] = acc

        avg = round(sum(item_scores) / len(item_scores)) if item_scores else None
        if avg is not None:
            all_scores.append(avg)
            due = a.get("dueDate")
            d = parse(due, None) if due else None
            if d:
                wk = d.isocalendar()
                key = f"{wk[0]}-W{wk[1]:02d}"
                weekly.setdefault(key, []).append(avg)

        rows.append({
            "title": a.get("title"),
            "type": a.get("type"),
            "dueDate": a.get("dueDate"),
            "itemCount": len(a.get("items", [])),
            "rounds": a.get("rounds", 3),
            "status": status,
            "average": avg,
            "recorded": recorded,
            "totalSlots": total_slots,
        })

    rows.sort(key=lambda r: (r["dueDate"] or ""))

    weekly_list = [
        {"week": k, "average": round(sum(v) / len(v))}
        for k, v in sorted(weekly.items())
    ]

    overall = round(sum(all_scores) / len(all_scores)) if all_scores else None
    total_assigned = len(assigned)
    rate = round(submitted_count / total_assigned * 100) if total_assigned else 0

    # 총평
    lines = []
    name = student.get("name", "학생")
    if overall is None:
        lines.append(f"{name} 학생은 이번 기간 동안 낭독 숙제에 참여했어요.")
    elif overall >= 90:
        lines.append(f"{name} 학생은 이번 기간 평균 {overall}점으로 발음이 매우 안정적이에요.")
    elif overall >= 75:
        lines.append(f"{name} 학생은 이번 기간 평균 {overall}점으로 전반적으로 잘 읽고 있어요.")
    elif overall >= 60:
        lines.append(f"{name} 학생은 이번 기간 평균 {overall}점이에요. 꾸준히 연습하면 더 좋아질 거예요.")
    else:
        lines.append(f"{name} 학생은 이번 기간 평균 {overall}점이에요. 소리를 천천히 나눠 읽는 연습이 필요해요.")

    if rate >= 90:
        lines.append(f"제출률 {rate}%로 아주 성실하게 참여했어요.")
    elif rate >= 70:
        lines.append(f"제출률은 {rate}%예요. 조금만 더 챙기면 좋겠어요.")
    else:
        lines.append(f"제출률이 {rate}%로 낮은 편이에요. 숙제를 빠뜨리지 않도록 함께 챙겨주세요.")

    if len(weekly_list) >= 2:
        first, last = weekly_list[0]["average"], weekly_list[-1]["average"]
        if last - first >= 5:
            lines.append(f"주차별로 보면 {first}점에서 {last}점으로 꾸준히 향상됐어요.")
        elif first - last >= 5:
            lines.append(f"최근 점수가 {first}점에서 {last}점으로 조금 떨어졌어요. 다시 천천히 읽는 연습을 해볼까요?")

    def _m(lst):
        return round(sum(lst) / len(lst)) if lst else None
    _a, _f = _m(acc_all), _m(flu_all)
    if _a is not None and _f is not None:
        if _f + 10 <= _a:
            lines.append("소리는 정확한데 읽는 흐름이 조금 끊겨요. 문장을 통째로 이어 읽는 연습을 해보면 좋겠어요.")
        elif _a + 10 <= _f:
            lines.append("읽는 흐름은 자연스러워요. 개별 소리를 조금 더 또렷하게 내면 완성도가 높아지겠어요.")

    if weak_words:
        top = sorted(weak_words.items(), key=lambda x: x[1])[:5]
        lines.append("다음 달에는 " + ", ".join(w for w, _ in top) + " 같은 단어를 집중해서 연습하면 좋겠어요.")

    def avg_of(lst):
        return round(sum(lst) / len(lst)) if lst else None

    daily_list = []
    for day in sorted(daily.keys()):
        v = daily[day]
        daily_list.append({
            "date": day,
            "pron": avg_of(v["pron"]),
            "accuracy": avg_of(v["acc"]),
            "fluency": avg_of(v["flu"]),
            "completeness": avg_of(v["comp"]),
            "submitRate": round(v["done"] / v["total"] * 100) if v["total"] else 0,
        })

    return {
        "student": {"name": student.get("name"), "className": student.get("className")},
        "period": {"start": d_start.isoformat(), "end": d_end.isoformat()},
        "overallAverage": overall,
        "metrics": {
            "accuracy": avg_of(acc_all),
            "fluency": avg_of(flu_all),
            "completeness": avg_of(comp_all),
        },
        "submitRate": rate,
        "submittedCount": submitted_count,
        "totalAssigned": total_assigned,
        "assignments": rows,
        "weekly": weekly_list,
        "daily": daily_list,
        "weakWords": [{"word": w, "accuracy": a} for w, a in sorted(weak_words.items(), key=lambda x: x[1])[:8]],
        "summary": " ".join(lines),
    }


@app.get("/api/diag")
async def diag():
    """발음평가가 왜 안 되는지 확인하는 진단."""
    import shutil, subprocess
    out = {
        "azure_key_set": bool(AZURE_KEY),
        "azure_region": AZURE_REGION,
        "ffmpeg": None,
        "sdk": None,
        "azure_reachable": None,
        "azure_status": None,
        "azure_message": None,
    }

    try:
        import azure.cognitiveservices.speech as _s
        out["sdk"] = "설치됨"
    except Exception as e:
        out["sdk"] = f"설치 안 됨 ({e})"

    ff = shutil.which("ffmpeg")
    out["ffmpeg"] = ff or "설치되지 않음"

    if not AZURE_KEY:
        out["azure_message"] = "AZURE_SPEECH_KEY 환경변수가 없어요."
        return out

    # 무음 WAV 1초를 만들어 Azure에 실제로 보내본다 (인식 결과는 비어도 됨, 응답 코드가 중요)
    try:
        seg = AudioSegment.silent(duration=1000, frame_rate=16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        wav = buf.getvalue()
    except Exception as e:
        out["azure_message"] = f"오디오 라이브러리 오류 (ffmpeg 문제일 수 있어요): {e}"
        return out

    pa_header = base64.b64encode(json.dumps({
        "ReferenceText": "hello",
        "GradingSystem": "HundredMark",
        "Granularity": "Word",
    }).encode()).decode()

    url = f"https://{AZURE_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                url,
                params={"language": "en-US", "format": "detailed"},
                headers={
                    "Ocp-Apim-Subscription-Key": AZURE_KEY,
                    "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                    "Accept": "application/json",
                    "Pronunciation-Assessment": pa_header,
                },
                content=wav,
            )
        out["azure_reachable"] = True
        out["azure_status"] = r.status_code
        if r.status_code == 200:
            out["azure_message"] = "정상! Azure가 응답했어요."
        elif r.status_code == 401:
            out["azure_message"] = "인증 실패 — 키가 틀렸어요. AZURE_SPEECH_KEY를 확인하세요."
        elif r.status_code == 403:
            out["azure_message"] = "권한 없음 — 키와 지역이 맞지 않거나 사용량을 초과했어요."
        elif r.status_code == 404:
            out["azure_message"] = f"주소를 찾을 수 없어요 — 지역({AZURE_REGION})이 틀렸을 수 있어요."
        elif r.status_code == 429:
            out["azure_message"] = "사용량 한도 초과예요. Free F0 월 한도를 다 썼을 수 있어요."
        else:
            out["azure_message"] = f"오류 {r.status_code}: {r.text[:200]}"
    except Exception as e:
        out["azure_reachable"] = False
        out["azure_message"] = f"Azure에 연결할 수 없어요: {e}"

    return out


TRANSLATOR_KEY = os.environ.get("AZURE_TRANSLATOR_KEY")
TRANSLATOR_REGION = os.environ.get("AZURE_TRANSLATOR_REGION", AZURE_REGION)


@app.post("/api/translate")
async def translate(payload: dict = Body(...)):
    """영어 단어/문장 목록을 한국어로 번역."""
    texts = payload.get("texts") or []
    texts = [str(t).strip() for t in texts if str(t).strip()]
    if not texts:
        return {"translations": []}
    if not TRANSLATOR_KEY:
        raise HTTPException(
            400,
            "번역 키가 없어요. Cloudflare 환경변수에 AZURE_TRANSLATOR_KEY를 추가하거나, "
            "목록에 'apple / 사과' 형태로 직접 입력해주세요."
        )

    url = "https://api.cognitive.microsofttranslator.com/translate"
    headers = {
        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    out = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Translator는 한 번에 100개까지
            for i in range(0, len(texts), 100):
                chunk = texts[i:i+100]
                r = await client.post(
                    url,
                    params={"api-version": "3.0", "from": "en", "to": "ko"},
                    headers=headers,
                    json=[{"Text": t} for t in chunk],
                )
                if r.status_code != 200:
                    raise HTTPException(502, f"번역 오류 ({r.status_code}): {r.text[:200]}")
                for item in r.json():
                    tr = (item.get("translations") or [{}])[0]
                    out.append(tr.get("text", ""))
    except httpx.RequestError as e:
        raise HTTPException(502, f"번역 서버에 연결하지 못했어요: {e}")

    return {"translations": out}


# ---------- backup ----------
@app.get("/api/backup")
def backup():
    db = load_db()
    subs = {}
    for sid in all_student_ids():
        subs[sid] = load_student_subs(sid)
    return {
        "students": db.get("students", []),
        "assignments": db.get("assignments", []),
        "studentSubmissions": subs,
    }


@app.post("/api/restore")
def restore(payload: dict = Body(...)):
    if not isinstance(payload.get("students"), list) or not isinstance(payload.get("assignments"), list):
        raise HTTPException(400, "백업 파일 형식이 올바르지 않아요.")
    with _lock:
        db = load_db()
        db["students"] = payload["students"]
        db["assignments"] = payload["assignments"]
        db["submissions"] = {}
        save_db(db)

    # 새 형식
    subs = payload.get("studentSubmissions")
    if isinstance(subs, dict):
        for sid, data in subs.items():
            if isinstance(data, dict):
                with _sub_lock(sid):
                    save_student_subs(sid, data)
    # 예전 형식 ("aid__sid" 평면 구조)도 복원 가능하게
    elif isinstance(payload.get("submissions"), dict):
        grouped = {}
        for key, sub in payload["submissions"].items():
            if "__" in key:
                aid, sid = key.split("__", 1)
                grouped.setdefault(sid, {})[aid] = sub
        for sid, data in grouped.items():
            with _sub_lock(sid):
                save_student_subs(sid, data)
    return {"ok": True}


# ---------- static frontend (must be last) ----------
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
