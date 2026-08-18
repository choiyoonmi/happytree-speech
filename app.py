import os
import io
import asyncio
import json
import base64
import uuid
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, Form, HTTPException, File, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydub import AudioSegment

from notify import send_telegram

AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus")
ADMIN_PASSCODE = os.environ.get("ADMIN_PASSCODE", "happytree")
STUDENT_ACCOUNT_API = os.environ.get(
    "STUDENT_ACCOUNT_API",
    "https://script.google.com/macros/s/AKfycbzRqfFTJeLfcV2_UOgnB6MCGtB7C9peTQCpj3RkR9qH85j1PwudvnF_HR6fpLVCKstb/exec",
)

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

VOCAB_DIR = DATA_DIR / "vocab"   # 단어 자습 점수/진도 (학생별 파일)
VOCAB_DIR.mkdir(parents=True, exist_ok=True)

ACT_DIR = DATA_DIR / "activity"  # 실시간 학습 현황 (학생별, 활동종류별 최근 기록)
ACT_DIR.mkdir(parents=True, exist_ok=True)

PUSH_DIR = DATA_DIR / "push"      # 웹 푸시 구독 정보 (학생별 파일)
PUSH_DIR.mkdir(parents=True, exist_ok=True)
VAPID_FILE = DATA_DIR / "vapid.json"
VAPID_PEM = DATA_DIR / "vapid_private.pem"


def get_vapid():
    """VAPID 키를 로드하거나 없으면 새로 생성해 저장한다. {publicKey, privatePemPath} 반환."""
    import base64
    if VAPID_FILE.exists() and VAPID_PEM.exists():
        try:
            with open(VAPID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("publicKey"):
                return data["publicKey"], str(VAPID_PEM)
        except Exception:
            pass
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    with open(VAPID_PEM, "wb") as f:
        f.write(pem)
    raw = priv.public_key().public_bytes(serialization.Encoding.X962,
                                          serialization.PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with open(VAPID_FILE, "w", encoding="utf-8") as f:
        json.dump({"publicKey": pub_b64}, f)
    return pub_b64, str(VAPID_PEM)


def _push_path(sid: str) -> Path:
    return PUSH_DIR / f"{_safe_id(sid)}.json"


def load_push_subs(sid: str) -> list:
    p = _push_path(sid)
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_push_subs(sid: str, subs: list):
    p = _push_path(sid)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False)
    tmp.replace(p)


def send_push_to_student(sid: str, title: str, body: str, url: str = "/") -> int:
    """한 학생의 모든 기기로 푸시 발송. 성공한 기기 수 반환. 만료된 구독은 정리."""
    subs = load_push_subs(sid)
    if not subs:
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except Exception as e:
        print("[push] pywebpush 없음:", e)
        return 0
    pub, pem_path = get_vapid()
    payload = json.dumps({"title": title, "body": body, "url": url})
    claims = {"sub": "mailto:white21040@gmail.com"}
    ok = 0
    alive = []
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=payload,
                    vapid_private_key=pem_path, vapid_claims=dict(claims))
            ok += 1
            alive.append(sub)
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                continue                      # 만료된 구독 → 제거
            alive.append(sub)                 # 일시 오류는 유지
            print("[push] 발송 실패:", code, e)
        except Exception as e:
            alive.append(sub)
            print("[push] 발송 오류:", e)
    if len(alive) != len(subs):
        save_push_subs(sid, alive)
    return ok


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


# ---------- 단어 자습 저장소 (학생별 파일, assignment_id별 기록) ----------
def _vocab_path(student_id: str) -> Path:
    return VOCAB_DIR / f"{_safe_id(student_id)}.json"


def load_vocab(student_id: str) -> dict:
    p = _vocab_path(student_id)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_vocab(student_id: str, data: dict):
    p = _vocab_path(student_id)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(p)


def all_vocab_student_ids() -> list:
    return [p.stem for p in VOCAB_DIR.glob("*.json")]


# ---------- 실시간 학습 활동 (학생별, 활동종류별 최근 1건) ----------
def _act_path(student_id: str) -> Path:
    return ACT_DIR / f"{_safe_id(student_id)}.json"


def load_activity(student_id: str) -> dict:
    p = _act_path(student_id)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_activity(student_id: str, data: dict):
    p = _act_path(student_id)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(p)


def all_activity_student_ids() -> list:
    return [p.stem for p in ACT_DIR.glob("*.json")]


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



async def fetch_shared_accounts(params: dict) -> dict:
    """해피트리 공용 학생계정 API를 호출한다."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(STUDENT_ACCOUNT_API, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        print("[student-sync] 공용 계정 API 오류:", exc)
        raise HTTPException(503, "학생계정 서버 연결이 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    return data if isinstance(data, dict) else {}


def merge_student_file(path_factory, old_id: str, new_id: str):
    """아이디 변경 시 학생별 JSON 파일을 새 아이디로 안전하게 합친다."""
    old_path = path_factory(old_id)
    new_path = path_factory(new_id)
    if old_path == new_path or not old_path.exists():
        return
    try:
        with open(old_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        new_data = None
        if new_path.exists():
            with open(new_path, "r", encoding="utf-8") as f:
                new_data = json.load(f)
        if isinstance(old_data, dict):
            merged = dict(old_data)
            if isinstance(new_data, dict):
                merged.update(new_data)
        elif isinstance(old_data, list):
            merged = list(old_data)
            if isinstance(new_data, list):
                seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in merged}
                for item in new_data:
                    key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if key not in seen:
                        merged.append(item)
                        seen.add(key)
        else:
            merged = new_data if new_data is not None else old_data
        tmp = new_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
        tmp.replace(new_path)
        old_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"[student-sync] {old_id} → {new_id} 파일 이전 실패:", exc)


def upsert_shared_student(shared: dict) -> dict:
    """공용 명단 학생을 트리톡 DB에 반영하고 기존 학습 기록은 보존한다."""
    sid = str(shared.get("id", "")).strip()
    name = str(shared.get("name", "")).strip()
    if not sid or not name:
        raise HTTPException(502, "학생계정 응답이 올바르지 않아요.")

    with _lock:
        db = load_db()
        student = next((s for s in db["students"] if str(s.get("id")) == sid), None)
        if student is None:
            student = next((s for s in db["students"] if str(s.get("name", "")).strip() == name), None)

        if student is None:
            student = {"id": sid, "pw": "", "name": name, "className": ""}
            db["students"].append(student)
        else:
            old_id = str(student.get("id", "")).strip()
            if old_id and old_id != sid:
                for assignment in db.get("assignments", []):
                    ids = assignment.get("assignedIds") or []
                    assignment["assignedIds"] = list(dict.fromkeys(
                        sid if str(item) == old_id else item for item in ids
                    ))
                merge_student_file(_sub_path, old_id, sid)
                merge_student_file(_vocab_path, old_id, sid)
                merge_student_file(_act_path, old_id, sid)
                merge_student_file(_push_path, old_id, sid)
                student["id"] = sid
                print(f"[student-sync] {name}: {old_id} → {sid} 기록 이전")

        student["name"] = name
        student["className"] = str(shared.get("cls", "")).strip()
        if shared.get("pw") is not None:
            student["pw"] = str(shared.get("pw", "")).strip()
        save_db(db)
        return dict(student)


async def sync_shared_roster() -> list:
    """공용 관리자 명단을 트리톡에 병합한다. 트리톡 전용 기록은 삭제하지 않는다."""
    data = await fetch_shared_accounts({"action": "rosterInfo"})
    if not data.get("ok") or not isinstance(data.get("students"), list):
        raise HTTPException(502, "공용 학생명단을 불러오지 못했어요.")
    for shared in data["students"]:
        upsert_shared_student(shared or {})
    return load_db()["students"]

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
async def login_student(payload: dict = Body(...)):
    sid = str(payload.get("id", "")).strip()
    pw = str(payload.get("pw", "")).strip()
    if not sid or not pw:
        raise HTTPException(400, "아이디와 비밀번호를 입력해 주세요.")

    shared = await fetch_shared_accounts({"action": "login", "id": sid, "pw": pw})
    if not shared.get("ok"):
        raise HTTPException(401, "아이디 또는 비밀번호가 일치하지 않아요.")
    shared["id"] = sid
    shared["pw"] = pw
    student = upsert_shared_student(shared)
    return {"ok": True, "student": student}


@app.post("/api/login/admin")
def login_admin(payload: dict = Body(...)):
    if str(payload.get("pw", "")) != ADMIN_PASSCODE:
        raise HTTPException(401, "비밀번호가 올바르지 않아요.")
    return {"ok": True}


# ---------- students ----------
@app.get("/api/students")
async def get_students():
    try:
        return await sync_shared_roster()
    except HTTPException as exc:
        print("[student-sync] 명단 동기화 실패, 로컬 명단 사용:", exc.detail)
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


@app.post("/api/students/bulk")
def add_students_bulk(payload: dict = Body(...)):
    """엑셀 명단으로 학생 여러 명을 한 번에 등록. body: {students:[{name, className?, id?, pw?}]}"""
    items = payload.get("students") or []
    created = []
    with _lock:
        db = load_db()
        existing = {s["id"] for s in db["students"]}
        for it in items:
            name = str((it or {}).get("name", "")).strip()
            if not name:
                continue
            sid = str((it or {}).get("id", "")).strip()
            if not sid or sid in existing:   # 비었거나 겹치면 자동 발급
                while True:
                    sid = "ht" + uuid.uuid4().hex[:4]
                    if sid not in existing:
                        break
            existing.add(sid)
            student = {
                "id": sid,
                "pw": str((it or {}).get("pw", "")).strip() or uuid.uuid4().hex[:4],
                "name": name,
                "className": str((it or {}).get("className", "")).strip(),
            }
            db["students"].append(student)
            created.append(student)
        save_db(db)
    return {"created": len(created), "students": created}


@app.patch("/api/students/{student_id}")
def update_student(student_id: str, payload: dict = Body(...)):
    """학생 정보 수정 (반, 이름 등)."""
    allowed = {"name", "className", "pw"}
    with _lock:
        db = load_db()
        for s in db["students"]:
            if s["id"] == student_id:
                for k, v in payload.items():
                    if k in allowed:
                        s[k] = str(v).strip()
                save_db(db)
                return s
    raise HTTPException(404, "학생을 찾을 수 없어요.")


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
            "exampleAudio": payload.get("exampleAudio", []),
            "recordMode": ("whole" if payload.get("recordMode") == "whole" else "each"),
            "published": bool(payload.get("published", True)),
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
                "exampleAudio": p.get("exampleAudio", []),
                "recordMode": ("whole" if p.get("recordMode") == "whole" else "each"),
                "published": bool(p.get("published", True)),
            }
            db["assignments"].insert(0, a)
            created.append(a)
        save_db(db)
    return {"created": len(created), "assignments": created}


@app.post("/api/assignments/delete-all")
def delete_all_assignments(payload: dict = Body(...)):
    """과제 일괄 삭제. scope='published'(배포된 것만) | 'archived'(보관함만) | 'all'(전부)."""
    scope = str(payload.get("scope") or "published")
    with _lock:
        db = load_db()
        before = len(db["assignments"])
        if scope == "all":
            db["assignments"] = []
        elif scope == "published":
            db["assignments"] = [a for a in db["assignments"] if not a.get("published", True)]
        elif scope == "archived":
            db["assignments"] = [a for a in db["assignments"] if a.get("published", True)]
        else:
            raise HTTPException(400, "알 수 없는 삭제 범위예요.")
        save_db(db)
        deleted = before - len(db["assignments"])
    return {"deleted": deleted}


def _has_recording(sub) -> bool:
    """제출 기록에 실제 녹음/제출이 있는지."""
    if not isinstance(sub, dict):
        return False
    if sub.get("status") in ("submitted", "reviewed"):
        return True
    for row in (sub.get("items") or []):
        for t in (row or []):
            if t:
                return True
    for t in (sub.get("whole") or []):
        if t:
            return True
    return False


@app.post("/api/assignments/dedupe")
def dedupe_assignments(payload: dict = Body(...)):
    """중복 과제(같은 책·제목·마감·문항수) 정리. 학생 녹음이 있는 건 보존하고 빈 복사본만 삭제.
    dryRun=true면 삭제하지 않고 몇 개 지울지만 알려준다."""
    dry = bool(payload.get("dryRun"))
    # 녹음이 있는 과제 id 모으기 (학생 제출 파일 전체 1회 스캔)
    subbed = set()
    for sid in all_student_ids():
        try:
            data = load_student_subs(sid) or {}
            for aid, sub in data.items():
                if aid not in subbed and _has_recording(sub):
                    subbed.add(aid)
        except Exception:
            pass
    with _lock:
        db = load_db()
        from collections import defaultdict
        groups = defaultdict(list)
        for a in db["assignments"]:
            key = (a.get("book", ""), a.get("title", ""), a.get("dueDate") or "", len(a.get("items") or []))
            groups[key].append(a)
        to_delete = set()
        kept_conflict = 0
        for g in groups.values():
            if len(g) < 2:
                continue
            with_subs = [a for a in g if a["id"] in subbed]
            if not with_subs:
                for a in g[1:]:                 # 첫 개만 남기고 삭제
                    to_delete.add(a["id"])
            else:
                for a in g:                     # 빈 복사본만 삭제
                    if a["id"] not in subbed:
                        to_delete.add(a["id"])
                if len(with_subs) > 1:
                    kept_conflict += 1
        if dry:
            return {"wouldDelete": len(to_delete), "keptConflict": kept_conflict}
        before = len(db["assignments"])
        db["assignments"] = [a for a in db["assignments"] if a["id"] not in to_delete]
        save_db(db)
        deleted = before - len(db["assignments"])
    return {"deleted": deleted, "keptConflict": kept_conflict}


@app.post("/api/students/{sid}/clean-books")
def clean_student_books(sid: str, payload: dict = Body(...)):
    """한 학생의 교재 정리.
    body {keep: '책이름'}  → 그 책만 남기고 이 학생이 받는 나머지 책을 뺌
    body {remove: ['책1','책2']} → 지정한 책만 뺌
    이 학생 전용 과제는 삭제, 다른 학생과 공유된 과제는 이 학생만 배정 해제."""
    keep = payload.get("keep")
    remove = set(payload.get("remove") or [])
    if keep is None and not remove:
        raise HTTPException(400, "keep 또는 remove를 지정해주세요.")
    unassigned = 0
    deleted = 0
    with _lock:
        db = load_db()
        remaining = []
        for a in db["assignments"]:
            ids = a.get("assignedIds") or []
            book = a.get("book", "")
            hit = (sid in ids) and ((keep is not None and book != keep) or (book in remove))
            if not hit:
                remaining.append(a)
                continue
            classes = a.get("assignedClasses") or []
            new_ids = [x for x in ids if x != sid]
            if not new_ids and not classes:
                deleted += 1            # 이 학생 전용 → 과제 삭제(목록에서 제외)
            else:
                a["assignedIds"] = new_ids
                unassigned += 1
                remaining.append(a)
        db["assignments"] = remaining
        save_db(db)
    return {"unassigned": unassigned, "deleted": deleted}


@app.post("/api/assignments/fill-meanings")
async def fill_assignment_meanings():
    """기존 과제에서 비어 있는 한글 뜻만 자동 번역해 채운다."""
    with _lock:
        db = load_db()
        missing = []
        for a in db["assignments"]:
            meanings = a.get("meanings") or []
            for idx, text in enumerate(a.get("items") or []):
                meaning = meanings[idx] if idx < len(meanings) else ""
                if not str(meaning or "").strip() and str(text or "").strip():
                    missing.append((a["id"], idx, str(text).strip()))

    if not missing:
        return {"updatedAssignments": 0, "updatedMeanings": 0}

    translations = await translate_text_list([row[2] for row in missing])
    changed_assignments = set()
    changed_meanings = 0
    with _lock:
        db = load_db()
        by_id = {a["id"]: a for a in db["assignments"]}
        for (aid, idx, source), translated in zip(missing, translations):
            a = by_id.get(aid)
            if not a or idx >= len(a.get("items") or []) or a["items"][idx] != source:
                continue
            meanings = list(a.get("meanings") or [])
            if len(meanings) < len(a["items"]):
                meanings.extend([""] * (len(a["items"]) - len(meanings)))
            if not str(meanings[idx] or "").strip() and str(translated or "").strip():
                meanings[idx] = translated
                a["meanings"] = meanings
                changed_assignments.add(aid)
                changed_meanings += 1
        if changed_meanings:
            save_db(db)

    return {
        "updatedAssignments": len(changed_assignments),
        "updatedMeanings": changed_meanings,
    }


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
    """과제 하나 수정 (마감일, 제목, 녹음 횟수, 배정 대상 등)."""
    allowed = {"title", "dueDate", "rounds", "type", "book", "assignedIds", "assignedClasses", "published", "items", "meanings", "exampleAudio", "recordMode"}
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
                    elif k == "published":
                        a[k] = bool(v)
                    elif k in ("assignedIds", "assignedClasses", "items", "meanings", "exampleAudio"):
                        a[k] = v if isinstance(v, list) else []
                    else:
                        a[k] = str(v).strip()
                save_db(db)
                return a
    raise HTTPException(404, "과제를 찾을 수 없어요.")


@app.post("/api/assignments/reschedule")
def reschedule(payload: dict = Body(...)):
    """일정 일괄 조정.
    mode='shift'  : ids 목록의 마감일을 days 만큼 뒤로 미룸
    mode='shift_sessions': ids의 요일 패턴(예: 화·목·금)을 유지하며 sessions 회분만큼 뒤로 미룸
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

        elif mode == "shift_sessions":
            # 요일 패턴 유지: 대상들의 현재 요일 집합을 패턴으로 삼아, 각 과제를 그 패턴에서 N칸 뒤로.
            n = int(payload.get("sessions") or 0)
            if not n:
                raise HTTPException(400, "미룰 횟수를 입력해주세요.")
            dated = [a for a in targets if a.get("dueDate")]
            pattern = {parse(a["dueDate"]).weekday() for a in dated}   # python 월=0..일=6
            if not pattern:
                pattern = set(range(7))
            for a in dated:
                d = parse(a["dueDate"])
                cnt = 0
                guard = 0
                while cnt < n and guard < 800:
                    d = d + timedelta(days=1)
                    if d.weekday() in pattern:
                        cnt += 1
                    guard += 1
                a["dueDate"] = d.isoformat()

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


def _avg_score_from_items(items):
    scores = []
    for takes in (items or []):
        for t in (takes or []):
            if t and t.get("score") is not None:
                scores.append(t["score"])
    return round(sum(scores) / len(scores)) if scores else None


def _notify_reading_submission(student_id, assignment_id, sub):
    """학생이 낭독 숙제를 '제출'하면 원장님 텔레그램으로 알림."""
    db = load_db()
    student = next((s for s in db.get("students", []) if s.get("id") == student_id), None)
    assignment = next((a for a in db.get("assignments", []) if a.get("id") == assignment_id), None)
    name = (student or {}).get("name") or student_id
    cls = (student or {}).get("className") or ""
    title = (assignment or {}).get("title") or "과제"
    who = "%s (%s)" % (name, cls) if cls else name
    lines = ["🎤 <b>%s</b> 낭독 제출 완료" % who, "과제: %s" % title]
    avg = _avg_score_from_items(sub.get("items"))
    if avg is not None:
        lines.append("평균 점수: %s점" % avg)
    if sub.get("submittedAt"):
        lines.append("시간: %s" % sub["submittedAt"])
    send_telegram("\n".join(lines))


def _rounds_done(items, item_count, rounds_total):
    """모든 항목이 녹음된 회차 수(완료 회차)를 센다."""
    done = 0
    for r in range(rounds_total):
        ok = item_count > 0
        for i in range(item_count):
            row = items[i] if (items and i < len(items)) else []
            take = row[r] if (row and r < len(row)) else None
            if not take:
                ok = False
                break
        if ok:
            done += 1
    return done


@app.post("/api/submission/{assignment_id}/{student_id}")
def save_submission(assignment_id: str, student_id: str, payload: dict = Body(...)):
    import time
    now = _now_kr()
    # 과제 정보(회차·항목 수)
    db = load_db()
    assignment = next((a for a in db["assignments"] if a["id"] == assignment_id), None)
    rounds_total = int((assignment or {}).get("rounds", 3) or 3)
    item_count = len((assignment or {}).get("items", []))
    a_title = (assignment or {}).get("title", "")
    # 학생별 잠금 — 다른 학생의 저장을 막지 않음
    with _sub_lock(student_id):
        subs = load_student_subs(student_id)
        existing = subs.get(assignment_id, {})
        prev_status = existing.get("status")
        existing.update(payload)
        if not existing.get("startedAt"):
            existing["startedAt"] = now
        # 회차 진행 계산 (전체 한 번에 모드면 whole 배열 기준)
        if (assignment or {}).get("recordMode") == "whole":
            whole = existing.get("whole") or []
            rounds_done = sum(1 for r in range(rounds_total) if r < len(whole) and whole[r])
        else:
            rounds_done = _rounds_done(existing.get("items") or [], item_count, rounds_total)
        existing["roundsDone"] = rounds_done
        existing["roundsTotal"] = rounds_total
        newly_submitted = payload.get("status") == "submitted" and prev_status != "submitted"
        if (existing.get("status") == "submitted" or rounds_done >= rounds_total) and not existing.get("completedAt"):
            existing["completedAt"] = existing.get("submittedAt") or now
        subs[assignment_id] = existing
        save_student_subs(student_id, subs)

        # 실시간 현황판(activity)에도 진행상황 반영 — 같은 학생 락 안이라 안전
        act = load_activity(student_id)
        ra = act.get("record") or {}
        if not ra.get("startedAt"):
            ra["startedAt"] = existing["startedAt"]
        ra.update({"at": now, "ts": int(time.time()), "title": a_title,
                   "done": rounds_done, "total": rounds_total})
        if existing.get("completedAt"):
            ra["completedAt"] = existing["completedAt"]
        act["record"] = ra
        save_activity(student_id, act)

    # 이번 저장으로 '제출됨' 상태가 새로 된 경우에만 알림 (중간 저장·재저장 시엔 안 보냄)
    if payload.get("status") == "submitted" and prev_status != "submitted":
        try:
            _notify_reading_submission(student_id, assignment_id, existing)
        except Exception as e:
            print("[telegram] 낭독 제출 알림 실패:", e)

    return existing


@app.delete("/api/submission/{assignment_id}/{student_id}")
def delete_submission(assignment_id: str, student_id: str):
    """한 학생의 특정 과제 제출(녹음·점수·코멘트)을 삭제 → '미제출' 상태로 되돌림."""
    with _sub_lock(student_id):
        subs = load_student_subs(student_id)
        had = assignment_id in subs
        if had:
            del subs[assignment_id]
            save_student_subs(student_id, subs)
    return {"ok": True, "deleted": had}


@app.post("/api/audio")
async def upload_audio(audio: UploadFile = File(...)):
    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "빈 오디오 파일이에요.")
    name = uuid.uuid4().hex + ".webm"
    with open(AUDIO_DIR / name, "wb") as f:
        f.write(raw)
    return {"url": f"/api/audio/{name}"}


AUDIO_TYPES = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".webm": "audio/webm",
    ".aac": "audio/aac",
}


@app.get("/api/audio/{name}")
def get_audio(name: str):
    path = AUDIO_DIR / name
    if not path.exists():
        raise HTTPException(404, "not found")
    ext = os.path.splitext(name)[1].lower()
    return FileResponse(path, media_type=AUDIO_TYPES.get(ext, "audio/webm"))


@app.post("/api/assignments/{assignment_id}/example-audio")
async def set_example_audio(assignment_id: str, index: int = Form(...), audio: UploadFile = File(...)):
    """과제 한 항목(예: 알파벳)에 선생님 발음/음가 음원 파일을 올려 붙인다."""
    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "빈 오디오 파일이에요.")
    ext = os.path.splitext(audio.filename or "")[1].lower()
    if ext not in AUDIO_TYPES:
        ext = ".mp3"
    name = "ex_" + uuid.uuid4().hex + ext
    with open(AUDIO_DIR / name, "wb") as f:
        f.write(raw)
    url = f"/api/audio/{name}"
    with _lock:
        db = load_db()
        for a in db["assignments"]:
            if a["id"] == assignment_id:
                n = len(a.get("items", []))
                arr = a.get("exampleAudio") or []
                while len(arr) < n:
                    arr.append(None)
                if 0 <= index < n:
                    arr[index] = url
                a["exampleAudio"] = arr
                save_db(db)
                return {"url": url, "index": index}
    raise HTTPException(404, "과제를 찾을 수 없어요.")


@app.post("/api/assignments/{assignment_id}/tts-audio")
def gen_tts_audio(assignment_id: str, payload: dict = Body(...)):
    """적어준 텍스트를 Azure TTS로 음원 생성해 항목에 붙인다. body: {index, text, voice?}"""
    if not AZURE_KEY:
        raise HTTPException(500, "서버에 AZURE_SPEECH_KEY가 없어 음성 생성을 할 수 없어요.")
    index = int(payload.get("index", -1))
    text = str(payload.get("text") or "").strip()
    voice = str(payload.get("voice") or "en-US-AriaNeural")
    if not text:
        raise HTTPException(400, "읽을 텍스트를 입력해주세요.")
    import azure.cognitiveservices.speech as speechsdk
    cfg = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
    cfg.speech_synthesis_voice_name = voice
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3)
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synth.speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        detail = ""
        try:
            if result.reason == speechsdk.ResultReason.Canceled:
                detail = str(result.cancellation_details.reason) + " " + (result.cancellation_details.error_details or "")
        except Exception:
            pass
        raise HTTPException(502, f"음성 생성 실패. {detail}"[:300])
    data = result.audio_data
    if not data:
        raise HTTPException(502, "생성된 음성이 비어 있어요.")
    name = "tts_" + uuid.uuid4().hex + ".mp3"
    with open(AUDIO_DIR / name, "wb") as f:
        f.write(data)
    url = f"/api/audio/{name}"
    with _lock:
        db = load_db()
        for a in db["assignments"]:
            if a["id"] == assignment_id:
                n = len(a.get("items", []))
                arr = a.get("exampleAudio") or []
                while len(arr) < n:
                    arr.append(None)
                if 0 <= index < n:
                    arr[index] = url
                a["exampleAudio"] = arr
                save_db(db)
                return {"url": url, "index": index}
    raise HTTPException(404, "과제를 찾을 수 없어요.")


@app.delete("/api/assignments/{assignment_id}/example-audio/{index}")
def clear_example_audio(assignment_id: str, index: int):
    with _lock:
        db = load_db()
        for a in db["assignments"]:
            if a["id"] == assignment_id and a.get("exampleAudio") and 0 <= index < len(a["exampleAudio"]):
                a["exampleAudio"][index] = None
                save_db(db)
                return {"ok": True}
    return {"ok": True}


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
        if a.get("published", True) and in_range(a) and (not a.get("assignedIds") or student_id in a["assignedIds"])
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

    # 단어 자습 요약 (기간 내 배정된 단어 과제 기준)
    vocab = load_vocab(student_id)
    vocab_rows = []
    vocab_bests = []
    mode_bests = {"choice": [], "spell": [], "test": []}
    flash_count = 0
    for a in assigned:
        rec = vocab.get(a["id"])
        if not rec:
            continue
        by = rec.get("byMode") or {}
        if by.get("flash"):
            flash_count += 1
        vocab_rows.append({
            "title": a.get("title"),
            "best": rec.get("best"),
            "attempts": rec.get("attempts", 0),
            "choice": (by.get("choice") or {}).get("best"),
            "spell": (by.get("spell") or {}).get("best"),
            "test": (by.get("test") or {}).get("best"),
        })
        if rec.get("best") is not None:
            vocab_bests.append(rec["best"])
        for mkey in mode_bests:
            b = (by.get(mkey) or {}).get("best")
            if b is not None:
                mode_bests[mkey].append(b)
    vocab_rows.sort(key=lambda r: (r.get("title") or ""))
    vocab_summary = {
        "studiedSets": len(vocab_rows),
        "avgBest": avg_of(vocab_bests),
        "byMode": {mkey: avg_of(v) for mkey, v in mode_bests.items()},
        "flashSets": flash_count,
        "rows": vocab_rows,
    }
    if vocab_summary["studiedSets"] and vocab_summary["avgBest"] is not None:
        lines.append(
            f"단어 자습도 {vocab_summary['studiedSets']}개 단어장에서 평균 {vocab_summary['avgBest']}점을 기록하며 스스로 복습했어요."
        )

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
        "vocab": vocab_summary,
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


async def translate_text_list(texts, src="en", dst="ko"):
    """문자열 목록을 번역한다 (기본 영어→한국어, src/dst로 방향 지정 가능)."""
    texts = [str(t).strip() for t in texts if str(t).strip()]
    if not texts:
        return []
    if not TRANSLATOR_KEY:
        raise HTTPException(
            400,
            "번역 키가 없어요. Render 환경변수에 AZURE_TRANSLATOR_KEY를 추가하거나, "
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
                    params={"api-version": "3.0", "from": src, "to": dst},
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

    return out


@app.post("/api/translate")
async def translate(payload: dict = Body(...)):
    """목록 번역. 기본 영어→한국어. body에 from/to로 방향 지정(예: 한글뜻→영어는 from=ko,to=en)."""
    src = str(payload.get("from") or "en")
    dst = str(payload.get("to") or "ko")
    out = await translate_text_list(payload.get("texts") or [], src, dst)
    return {"translations": out}


VOCAB_BASE_URL = "https://vocab-test-generator.onrender.com"
VOCAB_TEST_URL = VOCAB_BASE_URL + "/api/generate-all"
VOCAB_PARSE_URL = VOCAB_BASE_URL + "/api/parse"


async def _post_to_generator(url, attempts=3, read_timeout=220.0, **kw):
    """생성기(word) 서버로 POST.
    Render 무료 서버가 자고 있으면 '연결' 단계가 실패하는데, 이때만 서버를 깨우고 재시도한다.
    일단 연결된 뒤의 '처리 지연(read)'은 재시도하지 않고 한 번만 넉넉히 기다린다
    (재시도하면 무거운 AI 파싱이 매번 처음부터 다시 돌아 끝나지 않기 때문)."""
    timeout = httpx.Timeout(connect=15.0, read=read_timeout, write=60.0, pool=15.0)
    last = None
    for i in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.post(url, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadError) as e:
            # 연결 단계 실패(서버가 자는 중) → 깨우고 재시도
            last = e
            try:
                async with httpx.AsyncClient(timeout=60) as w:
                    await w.get(VOCAB_BASE_URL + "/")
            except Exception:
                pass
            if i < attempts - 1:
                await asyncio.sleep(3)
        # ReadTimeout 등 처리 지연은 재시도하지 않고 그대로 올려서 명확히 안내
    raise last if last else httpx.HTTPError("연결 실패")


@app.post("/api/parse-book")
async def parse_book(file: UploadFile = File(...)):
    """교재 파일(PDF/엑셀)을 AI 파서(단어시험지 생성기)로 보내 유닛/단어를 구조화해 받는다.
    여러 단(열) 레이아웃 등 복잡한 표도 정확히 읽힘."""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "빈 파일이에요.")
    files = {"file": (file.filename or "book.pdf", raw, file.content_type or "application/octet-stream")}
    try:
        # AI 파싱은 유닛이 많으면 4~5분까지 걸려서 넉넉히 대기
        r = await _post_to_generator(VOCAB_PARSE_URL, files=files, read_timeout=300.0)
    except httpx.TimeoutException:
        raise HTTPException(504, "AI 분석이 시간 안에 끝나지 않았어요. 유닛이 많은 파일이면 나눠서 올리거나, '엑셀·PDF 올리기(빠름)'를 이용해보세요.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"분석 서버 연결 실패: {e}")
    if r.status_code != 200:
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            pass
        raise HTTPException(502, f"AI 분석 실패 ({r.status_code}) {detail}"[:300])
    return r.json()


@app.post("/api/vocab-test")
async def vocab_test(payload: dict = Body(...)):
    """과제 단어(units)를 시험지 생성기로 프록시해 시험지 PDF를 받아온다.
    브라우저는 같은 출처만 호출하므로 CORS/프리플라이트가 필요 없다."""
    units = payload.get("units") or []
    if not units:
        raise HTTPException(400, "시험지로 만들 단어가 없어요.")
    body = {
        "academy_name": payload.get("academy_name") or "해피트리학원 국영수문해력센터",
        "book_title": payload.get("book_title") or "",
        "units": units,
        "shuffle": bool(payload.get("shuffle")),
        "direction": payload.get("direction") or "kor_to_eng",
    }
    try:
        # 생성기가 자고 있으면 깨어나는 데 시간이 걸려, 깨우고 자동 재시도
        r = await _post_to_generator(VOCAB_TEST_URL, json=body)
    except httpx.TimeoutException:
        raise HTTPException(504, "시험지 생성이 시간 안에 끝나지 않았어요. 잠시 후 다시 시도해주세요.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"시험지 생성기 연결 실패: {e}")
    if r.status_code != 200:
        raise HTTPException(502, f"시험지 생성기 오류 ({r.status_code})")
    return Response(
        content=r.content,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=vocab_test.pdf"},
    )


# ---------- 단어 자습 (같은 과제 단어를 자습·시험, 점수 저장) ----------
def _now_kr() -> str:
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc) + timedelta(hours=9)  # 서버 UTC → 한국시간(KST)
    return f"{d.month}/{d.day} {d.hour:02d}:{d.minute:02d}"


VOCAB_STAGES = {"flash", "choice", "spell", "test"}   # 자습 4단계


@app.post("/api/vocab/{assignment_id}/{student_id}")
def save_vocab_result(assignment_id: str, student_id: str, payload: dict = Body(...)):
    """단어 자습 한 판 결과 저장. body: {mode, correct, total}
    mode='flash'(카드암기)는 점수 없이 '했음'만 기록. 4단계 모두 하면 completedAt 기록."""
    mode = str(payload.get("mode") or "test")[:20]
    is_flash = (mode == "flash")
    correct = max(0, int(payload.get("correct") or 0))
    total = int(payload.get("total") or 0)
    score = 0
    if not is_flash:
        if total <= 0:
            raise HTTPException(400, "문항 수가 없어요.")
        correct = min(correct, total)
        score = round(correct * 100 / total)
    now = _now_kr()
    with _sub_lock(student_id):
        data = load_vocab(student_id)
        rec = data.get(assignment_id) or {"attempts": 0, "best": 0, "byMode": {}}
        if not rec.get("startedAt"):
            rec["startedAt"] = now
        rec["attempts"] = rec.get("attempts", 0) + 1
        by = rec.get("byMode") or {}
        if is_flash:
            bm = by.get("flash") or {"attempts": 0}
            bm["attempts"] = bm.get("attempts", 0) + 1
            bm["done"] = True
            bm["last"] = {"at": now}
            by["flash"] = bm
            rec["last"] = {"mode": "flash", "at": now}
        else:
            rec["best"] = max(rec.get("best", 0), score)
            rec["last"] = {"mode": mode, "correct": correct, "total": total, "score": score, "at": now}
            bm = by.get(mode) or {"attempts": 0, "best": 0}
            bm["attempts"] = bm.get("attempts", 0) + 1
            bm["best"] = max(bm.get("best", 0), score)
            bm["last"] = {"correct": correct, "total": total, "score": score, "at": now}
            by[mode] = bm
        rec["byMode"] = by
        complete = VOCAB_STAGES.issubset(set(by.keys()))
        rec["complete"] = complete
        if complete and not rec.get("completedAt"):
            rec["completedAt"] = now
        data[assignment_id] = rec
        save_vocab(student_id, data)
    return rec


@app.get("/api/vocab/{student_id}")
def get_vocab(student_id: str):
    """한 학생의 단어 자습 기록 전체 {assignment_id: record}."""
    return load_vocab(student_id)


@app.get("/api/vocab-all")
def get_vocab_all():
    """선생님 대시보드용: 모든 학생의 단어 자습 기록 {student_id: {aid: record}}."""
    return {sid: load_vocab(sid) for sid in all_vocab_student_ids()}


# ---------- 실시간 학습 현황 ----------
ACTIVITY_KINDS = {"record", "flash", "choice", "spell", "test"}


@app.post("/api/activity/{student_id}")
def ping_activity(student_id: str, payload: dict = Body(...)):
    """학생이 어떤 학습을 시작하면 호출. body: {kind, title}"""
    import time
    kind = str(payload.get("kind") or "").strip()
    if kind not in ACTIVITY_KINDS:
        raise HTTPException(400, "알 수 없는 활동이에요.")
    title = str(payload.get("title") or "")[:120]
    with _sub_lock(student_id):
        data = load_activity(student_id)
        data[kind] = {"at": _now_kr(), "ts": int(time.time()), "title": title}
        save_activity(student_id, data)
    return {"ok": True}


@app.get("/api/activity-all")
def get_activity_all():
    """선생님 실시간 현황판용: {student_id: {kind: {at, ts, title}}}."""
    return {sid: load_activity(sid) for sid in all_activity_student_ids()}


# ---------- 웹 푸시 알림 ----------
def _today_kr() -> str:
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc) + timedelta(hours=9)
    return d.strftime("%Y-%m-%d")


@app.get("/api/push/key")
def push_public_key():
    pub, _ = get_vapid()
    return {"publicKey": pub}


@app.post("/api/push/subscribe/{student_id}")
def push_subscribe(student_id: str, payload: dict = Body(...)):
    """학생 기기의 푸시 구독 저장. body = PushSubscription(JSON)."""
    endpoint = (payload or {}).get("endpoint")
    if not endpoint:
        raise HTTPException(400, "구독 정보가 올바르지 않아요.")
    with _sub_lock(student_id):
        subs = load_push_subs(student_id)
        subs = [s for s in subs if s.get("endpoint") != endpoint]  # 같은 기기 중복 제거
        subs.append(payload)
        save_push_subs(student_id, subs)
    return {"ok": True, "devices": len(subs)}


@app.post("/api/push/unsubscribe/{student_id}")
def push_unsubscribe(student_id: str, payload: dict = Body(default={})):
    endpoint = (payload or {}).get("endpoint")
    with _sub_lock(student_id):
        subs = load_push_subs(student_id)
        subs = [s for s in subs if endpoint and s.get("endpoint") != endpoint] if endpoint else []
        save_push_subs(student_id, subs)
    return {"ok": True, "devices": len(subs)}


@app.post("/api/push/test/{student_id}")
def push_test(student_id: str):
    """이 학생 기기로 테스트 알림 발송."""
    db = load_db()
    st = next((s for s in db.get("students", []) if s.get("id") == student_id), None)
    name = (st or {}).get("name") or "학생"
    sent = send_push_to_student(student_id, "트리톡 알림 테스트 🔔",
                                f"{name}야, 알림이 잘 오는지 확인 중이에요!", "/")
    return {"sent": sent}


def _do_remind_due(day: str) -> dict:
    """지정일 마감인데 아직 제출 안 한 학생들에게 낭독 숙제 알림 발송."""
    db = load_db()
    students = db.get("students", [])
    assignments = db.get("assignments", [])
    sent = 0
    reached = 0
    for s in students:
        sid = s.get("id")
        due = [a for a in assignments
               if a.get("published", True) and (a.get("dueDate") == day)
               and ((not a.get("assignedIds")) or sid in a.get("assignedIds", []))]
        if not due:
            continue
        subs_map = load_student_subs(sid)
        undone = [a for a in due if (subs_map.get(a["id"]) or {}).get("status") not in ("submitted", "reviewed")]
        if not undone:
            continue
        n = len(undone)
        got = send_push_to_student(sid, "오늘 낭독 숙제 🎤",
                                   f"{s.get('name','')}야, 오늘 할 낭독 숙제 {n}개가 있어요!", "/")
        if got:
            sent += 1
            reached += got
    return {"students": sent, "devices": reached, "date": day}


@app.post("/api/push/remind-due")
def push_remind_due(payload: dict = Body(default={})):
    """오늘(또는 지정일) 마감인데 아직 제출 안 한 학생들에게 낭독 숙제 알림 발송."""
    day = str((payload or {}).get("date") or _today_kr())
    return _do_remind_due(day)


# ---- 자동 발송 스케줄러 (KST): 평일 오후5시·저녁8시 / 주말 오후4시·저녁8시 ----
PUSH_SCHED_FILE = DATA_DIR / "push_sched.json"


def _remind_hours_for(dt) -> set:
    return {16, 20} if dt.weekday() >= 5 else {17, 20}   # 토(5)·일(6)은 4시·8시


def _load_last_slot() -> str:
    try:
        with open(PUSH_SCHED_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last", "")
    except Exception:
        return ""


def _save_last_slot(slot: str):
    try:
        with open(PUSH_SCHED_FILE, "w", encoding="utf-8") as f:
            json.dump({"last": slot}, f)
    except Exception:
        pass


def _reminder_loop():
    import time as _t
    from datetime import datetime, timezone, timedelta
    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=9)   # KST
            if now.hour in _remind_hours_for(now):
                slot = f"{now:%Y-%m-%d}T{now.hour:02d}"
                if _load_last_slot() != slot:
                    _save_last_slot(slot)
                    try:
                        res = _do_remind_due(now.strftime("%Y-%m-%d"))
                        print("[push] auto reminder", slot, res)
                    except Exception as e:
                        print("[push] auto reminder failed:", e)
        except Exception as e:
            print("[push] scheduler loop error:", e)
        _t.sleep(50)


threading.Thread(target=_reminder_loop, daemon=True).start()


# ---------- 실시간 단어 배틀 (WebSocket, 메모리 방) ----------
import random as _rnd
import time as _time

battle_rooms = {}   # code -> room dict (메모리, 배틀 진행 중에만 유지)


def _gen_code() -> str:
    """숫자 4자리 랜덤 코드 (안 겹치게)."""
    import random as _r
    candidates = [f"{n:04d}" for n in range(10000) if f"{n:04d}" not in battle_rooms]
    if candidates:
        return _r.choice(candidates)
    return "".join(_rnd.choice("0123456789") for _ in range(4))


def _pairs_from_assignment(a: dict):
    """단어 과제 → [(정답=용어, 문제=설명)] 목록."""
    items = a.get("items") or []
    meanings = a.get("meanings") or []
    out = []
    for i, w in enumerate(items):
        m = meanings[i] if i < len(meanings) else ""
        w = (w or "").strip()
        m = (m or "").strip()
        if w and m:
            out.append((w, m))
    return out


def _questions_from_pairs(pairs):
    """[(정답, 문제)] → 4지선다 문제. 오답 보기는 다른 정답들에서 뽑음.
    정답 위치(0~3)를 균등 분배해서 한 번호에 몰리지 않게 한다(찍기 방지)."""
    answers = [a for a, _ in pairs]
    if len(set(answers)) < 4:
        return []
    n = len(pairs)
    positions = [i % 4 for i in range(n)]   # 0,1,2,3,0,1,2,3...
    _rnd.shuffle(positions)
    qs = []
    for k, (ans, prompt) in enumerate(pairs):
        others = [x for x in answers if x != ans]
        _rnd.shuffle(others)
        picks = others[:3]
        pos = positions[k] if picks and len(picks) == 3 else 0
        opts = picks[:pos] + [ans] + picks[pos:]
        qs.append({"prompt": prompt, "options": opts, "correct": opts.index(ans)})
    _rnd.shuffle(qs)
    return qs


def _prune_battle_rooms():
    now = _time.time()
    for code in list(battle_rooms.keys()):
        if now - battle_rooms[code].get("createdAt", now) > 3 * 3600:
            battle_rooms.pop(code, None)


def _battle_scoreboard(room):
    ps = sorted(room["players"].values(), key=lambda p: -p["score"])
    return [{"name": p["name"], "score": p["score"]} for p in ps[:20]]


async def _bsend(ws, obj):
    if ws is None:
        return
    try:
        await ws.send_json(obj)
    except Exception:
        pass


async def _battle_broadcast(room, obj, to_host=True, to_players=True):
    if to_host:
        await _bsend(room.get("host"), obj)
    if to_players:
        for p in list(room["players"].values()):
            await _bsend(p.get("ws"), obj)


@app.post("/api/battle/create")
def battle_create(payload: dict = Body(...)):
    """배틀 방 생성.
    body: { assignmentIds?[], assignmentId?, custom?[{prompt,answer}], title?, duration?, totalSec? }
    - assignmentIds: 여러 단어 Day를 합쳐서 (과목 무관, 용어+설명)
    - custom: 영어와 무관한 직접 퀴즈 (문제+정답)
    """
    duration = max(5, min(120, int(payload.get("duration") or 15)))     # 문제당 제한시간
    total_sec = max(30, min(1800, int(payload.get("totalSec") or 90)))  # 전체 배틀 시간(기본 1분30초)
    pairs = []
    title = (payload.get("title") or "").strip()

    custom = payload.get("custom")
    if custom:
        for it in custom:
            ans = str((it or {}).get("answer") or "").strip()
            pr = str((it or {}).get("prompt") or "").strip()
            if ans and pr:
                pairs.append((ans, pr))
        if not title:
            title = "직접 만든 퀴즈"
    else:
        aids = payload.get("assignmentIds")
        if not aids:
            aids = [payload["assignmentId"]] if payload.get("assignmentId") else []
        db = load_db()
        titles = []
        for aid in aids:
            a = next((x for x in db["assignments"] if x["id"] == aid), None)
            if not a:
                continue
            pairs += _pairs_from_assignment(a)
            titles.append(a.get("title", ""))
        if not title and titles:
            title = titles[0] + (f" 외 {len(titles) - 1}개" if len(titles) > 1 else "")

    if not title:
        title = "배틀"
    qs = _questions_from_pairs(pairs)
    if len(qs) < 4:
        raise HTTPException(400, "정답이 4개 이상이어야 배틀을 만들 수 있어요. (문제/단어를 더 넣어주세요)")
    _prune_battle_rooms()
    code = _gen_code()
    battle_rooms[code] = {
        "code": code,
        "title": title,
        "questions": qs,
        "players": {},
        "host": None,
        "phase": "lobby",
        "qIndex": -1,
        "duration": duration,
        "totalSec": total_sec,
        "qStart": 0,
        "skip": False,
        "started": False,
        "createdAt": _time.time(),
    }
    return {"code": code, "title": title, "count": len(qs), "duration": duration, "totalSec": total_sec}


async def _run_battle(room):
    room["started"] = True
    room["phase"] = "starting"
    await _battle_broadcast(room, {"type": "starting", "count": len(room["questions"])})
    await asyncio.sleep(2)
    battle_start = _time.time()
    shown_mid = False
    for qi, q in enumerate(room["questions"]):
        if _time.time() - battle_start >= room.get("totalSec", 90):
            break   # 전체 배틀 시간(예: 1분30초) 지나면 종료
        room["qIndex"] = qi
        room["phase"] = "question"
        room["qStart"] = _time.time()
        room["skip"] = False
        for p in room["players"].values():
            p["answered"] = False
            p["lastCorrect"] = False
        await _bsend(room.get("host"), {
            "type": "question", "index": qi, "total": len(room["questions"]),
            "prompt": q["prompt"], "options": q["options"], "correct": q["correct"],
            "duration": room["duration"],
        })
        for p in room["players"].values():
            await _bsend(p.get("ws"), {
                "type": "question", "index": qi, "total": len(room["questions"]),
                "prompt": q["prompt"], "options": q["options"], "duration": room["duration"],
            })
        t0 = _time.time()
        while _time.time() - t0 < room["duration"]:
            await asyncio.sleep(0.4)
            if room.get("skip"):
                break
            players = list(room["players"].values())
            if players and all(p["answered"] for p in players):
                await asyncio.sleep(0.3)
                break
        room["phase"] = "reveal"
        await _battle_broadcast(room, {
            "type": "reveal", "correct": q["correct"],
            "answer": q["options"][q["correct"]],
        })
        await asyncio.sleep(1.0)   # 정답 표시 후 다음 문제까지 (짧게)
        # 중간점검 순위: 배틀 절반 지점에 딱 한 번만
        if not shown_mid and (_time.time() - battle_start) >= room.get("totalSec", 90) / 2:
            room["phase"] = "standings"
            await _battle_broadcast(room, {"type": "standings", "board": _battle_scoreboard(room)})
            await asyncio.sleep(5)
            shown_mid = True
    room["phase"] = "end"
    await _battle_broadcast(room, {"type": "end", "board": _battle_scoreboard(room)})


@app.websocket("/ws/battle/{code}")
async def battle_ws(ws: WebSocket, code: str):
    await ws.accept()
    room = battle_rooms.get(code)
    if not room:
        await _bsend(ws, {"type": "error", "msg": "방을 찾을 수 없어요. 코드를 확인해주세요."})
        await ws.close()
        return
    role = ws.query_params.get("role", "player")

    if role == "host":
        room["host"] = ws
        await _bsend(ws, {"type": "lobby", "code": code, "title": room["title"],
                          "count": len(room["questions"]),
                          "players": [p["name"] for p in room["players"].values()],
                          "phase": room["phase"]})
        try:
            while True:
                msg = await ws.receive_json()
                t = msg.get("type")
                if t == "start" and not room["started"]:
                    asyncio.create_task(_run_battle(room))
                elif t == "next":
                    room["skip"] = True
        except WebSocketDisconnect:
            room["host"] = None
        except Exception:
            room["host"] = None
        return

    # player
    name = (ws.query_params.get("name") or "학생").strip()[:20] or "학생"
    pid = uuid.uuid4().hex
    room["players"][pid] = {"name": name, "ws": ws, "score": 0, "answered": False, "lastCorrect": False}
    await _bsend(ws, {"type": "joined", "name": name, "title": room["title"], "phase": room["phase"]})
    await _bsend(room.get("host"), {"type": "players",
                                    "players": [p["name"] for p in room["players"].values()]})
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "answer" and room["phase"] == "question":
                p = room["players"].get(pid)
                if p and not p["answered"]:
                    p["answered"] = True
                    q = room["questions"][room["qIndex"]]
                    correct = int(msg.get("choice", -1)) == q["correct"]
                    if correct:
                        remaining = max(0.0, room["duration"] - (_time.time() - room["qStart"]))
                        pts = 500 + round(500 * remaining / room["duration"])
                        p["score"] += pts
                        p["lastCorrect"] = True
                        await _bsend(room.get("host"), {"type": "balloon", "name": p["name"], "score": p["score"]})
                    await _bsend(ws, {"type": "answered", "correct": correct, "score": p["score"]})
    except WebSocketDisconnect:
        room["players"].pop(pid, None)
        await _bsend(room.get("host"), {"type": "players",
                                        "players": [p["name"] for p in room["players"].values()]})
    except Exception:
        room["players"].pop(pid, None)


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


@app.get("/")
def index_html():
    # index.html은 항상 최신 확인(no-cache) → 배포 후 옛 화면이 캐시되지 않게
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
