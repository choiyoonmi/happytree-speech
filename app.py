import os
import io
import math
import re
import asyncio
import hmac
import json
import base64
import uuid
import threading
from pathlib import Path

import httpx
from fastapi import (FastAPI, UploadFile, Form, HTTPException, File, Body, WebSocket,
                     WebSocketDisconnect, Depends, Request, BackgroundTasks)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydub import AudioSegment

from notify import send_telegram
# 저장소 계층(파일 ↔ D1). 기본값 TT_STORE=file 이면 지금까지와 완전히 같게 동작한다.
import store

AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus")

# ── 관리자 인증 ────────────────────────────────────────────────
# ★기본값을 두지 않는다. 예전에는 os.environ.get("ADMIN_PASSCODE", "happytree") 였다 —
#   환경변수를 안 넣은 인스턴스가 하나라도 생기면 관리자 암호가 공개 저장소에 적힌 그 값이 된다.
#   없으면 관리자 기능만 잠기고(503), 학생 낭독은 그대로 돌아간다.
ADMIN_PASSCODE = (os.environ.get("ADMIN_PASSCODE") or "").strip()
# 상시 테스트용 관리자 비밀번호 — 넣었을 때만 동작한다(기본값 없음).
TEST_ADMIN_PASSCODE = (os.environ.get("TEST_ADMIN_PASSCODE") or "").strip()
# 서버끼리 부를 때 쓰는 키(Apps Script 학생등록, 단어 일괄업로드 스크립트 등).
# 사람 비밀번호와 분리해 두면 나중에 한쪽만 바꿀 수 있다.
API_ADMIN_KEY = (os.environ.get("API_ADMIN_KEY") or "").strip()
# on: 막는다(기본) · log: 막지 않고 누가 걸렸을지 로그만 · off: 검사 안 함(비상 복귀)
API_AUTH = (os.environ.get("API_AUTH") or "on").strip().lower()
# 상시 테스트 학생 계정 — 공용 학생계정 서버를 거치지 않고 바로 통과시킨다(기간 제한·중복 로그인 제한 없음).
TEST_STUDENTS = {
    "test0000": {"pw": "test0000", "name": "테스트학생", "cls": "테스트"},
}
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
    return store.get("push", _safe_id(sid), _push_path(sid), [])


def save_push_subs(sid: str, subs: list):
    store.put("push", _safe_id(sid), _push_path(sid), subs)


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
    return store.get("subs", _safe_id(student_id), _sub_path(student_id), {})


def save_student_subs(student_id: str, data: dict):
    store.put("subs", _safe_id(student_id), _sub_path(student_id), data)


def all_student_ids() -> list:
    return store.ids("subs", SUB_DIR)


# ---------- 단어 자습 저장소 (학생별 파일, assignment_id별 기록) ----------
def _vocab_path(student_id: str) -> Path:
    return VOCAB_DIR / f"{_safe_id(student_id)}.json"


def load_vocab(student_id: str) -> dict:
    return store.get("vocab", _safe_id(student_id), _vocab_path(student_id), {})


def save_vocab(student_id: str, data: dict):
    store.put("vocab", _safe_id(student_id), _vocab_path(student_id), data)


def all_vocab_student_ids() -> list:
    return store.ids("vocab", VOCAB_DIR)


# ---------- 권말 진급 시험 저장소 (학생별 파일, exam assignment_id별 최고 기록) ----------
EXAM_DIR = DATA_DIR / "exam"
EXAM_DIR.mkdir(parents=True, exist_ok=True)


def _exam_path(student_id: str) -> Path:
    return EXAM_DIR / f"{_safe_id(student_id)}.json"


def load_exam(student_id: str) -> dict:
    return store.get("exam", _safe_id(student_id), _exam_path(student_id), {})


def save_exam(student_id: str, data: dict):
    store.put("exam", _safe_id(student_id), _exam_path(student_id), data)


def all_exam_student_ids() -> list:
    return store.ids("exam", EXAM_DIR)


# ---------- 실시간 학습 활동 (학생별, 활동종류별 최근 1건) ----------
def _act_path(student_id: str) -> Path:
    return ACT_DIR / f"{_safe_id(student_id)}.json"


def load_activity(student_id: str) -> dict:
    return store.get("activity", _safe_id(student_id), _act_path(student_id), {})


def save_activity(student_id: str, data: dict):
    store.put("activity", _safe_id(student_id), _act_path(student_id), data)


def all_activity_student_ids() -> list:
    return store.ids("activity", ACT_DIR)


def get_submission_record(assignment_id: str, student_id: str) -> dict:
    return load_student_subs(student_id).get(assignment_id) or {}


def load_db():
    return store.load_db(DB_PATH)


def save_db(db):
    store.save_db(DB_PATH, db)



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
            student = {"id": sid, "pw": "", "name": name, "className": ""}
            db["students"].append(student)

        student["name"] = name
        student["className"] = str(shared.get("cls", "")).strip()
        # 학원은 공용 학생계정(Apps Script)이 알려 준 값만 쓴다. 학생이 못 정한다.
        # 옛 배포는 academy 를 안 보내므로, 그때는 기존 값을 지우지 않고 그대로 둔다.
        ac = str(shared.get("academy") or "").strip()
        if ac:
            student["academy"] = ac
        elif not student.get("academy"):
            student["academy"] = ACADEMY_DEFAULT
        if shared.get("pw") is not None:
            student["pw"] = str(shared.get("pw", "")).strip()
        save_db(db)
        return dict(student)


def _merge_shared_students(shared_list) -> list:
    """공용 명단 여러 명을 트리톡 DB에 '한 번의' 저장으로 병합한다.

    예전에는 학생마다 upsert_shared_student 가 db 전체를 다시 저장했다.
    그래서 관리자 화면이 뜰 때마다 학생 수(N)만큼 db 를 재기록 →
    로딩이 수십 초~1분씩 걸렸다(0.5 CPU). D1/mirror 모드에서는 학생당
    원격 왕복이 겹쳐 훨씬 더 느려진다. 여기서는 load_db·save_db 를 딱 한 번만 한다.
    병합 규칙(이름·반·학원·비번)은 upsert_shared_student 와 똑같이 맞춘다."""
    with _lock:
        db = load_db()
        by_id = {str(s.get("id")): s for s in db["students"]}
        for shared in shared_list:
            shared = shared or {}
            sid = str(shared.get("id", "")).strip()
            name = str(shared.get("name", "")).strip()
            if not sid or not name:
                continue  # 명단에 이상한 줄이 있어도 전체 동기화를 멈추지 않는다
            student = by_id.get(sid)
            if student is None:
                student = {"id": sid, "pw": "", "name": name, "className": ""}
                db["students"].append(student)
                by_id[sid] = student
            student["name"] = name
            student["className"] = str(shared.get("cls", "")).strip()
            ac = str(shared.get("academy") or "").strip()
            if ac:
                student["academy"] = ac
            elif not student.get("academy"):
                student["academy"] = ACADEMY_DEFAULT
            if shared.get("pw") is not None:
                student["pw"] = str(shared.get("pw", "")).strip()
        save_db(db)  # ★학생마다가 아니라 여기서 딱 한 번만 저장한다
        return db["students"]


async def sync_shared_roster() -> list:
    """공용 관리자 명단을 트리톡에 병합한다. 트리톡 전용 기록은 삭제하지 않는다."""
    data = await fetch_shared_accounts({"action": "rosterInfo"})
    if not data.get("ok") or not isinstance(data.get("students"), list):
        raise HTTPException(502, "공용 학생명단을 불러오지 못했어요.")
    return _merge_shared_students(data["students"])

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://admin.happytreeacademy.com"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------- 관리자 게이트 ----------
# 왜 필요한가: 이 서버의 API 54개는 여태 아무 검사도 하지 않았다.
# 특히 `GET /api/backup` 은 전교생 명단·과제·제출기록 전부를 아무나 받아갈 수 있었고
# (실측 2026-09-06: 인증 없이 200, 5.3MB), `POST /api/restore` 는 그걸 아무나 덮어쓸 수 있었다.
# 학생 화면이 쓰는 조회는 건드리지 않고, '전교생 단위'와 '지우는' 동작에만 문을 단다.
#
# 여는 방법 세 가지 — 헤더 x-ht-admin / 쿼리 ?pw= / 서버끼리는 API_ADMIN_KEY
"""══════════ 학원(테넌트) ══════════════════════════════════════════
학원이 세 곳이 되면서 필요해진 것들이다.

★관리자 비밀번호가 곧 '어느 학원 사람인지'를 증명한다.
  ACADEMY_PASSCODES 환경변수에 학원별 비밀번호를 넣는다.
      {"readingon":"리딩온비번","zestedu":"제스트비번"}
  기존 ADMIN_PASSCODE 는 해피트리로 친다 — 그래야 지금 화면이 안 깨진다.

★학생의 학원은 학생 자신이 못 정한다.
  로그인할 때 공용 학생계정(Apps Script)이 알려 주는 값만 쓴다.
  로그인 응답에 academy 가 없으면(옛 배포) 해피트리로 친다.
"""
ACADEMY_DEFAULT = "happytree"
try:
    ACADEMY_PASSCODES = json.loads(os.environ.get("ACADEMY_PASSCODES") or "{}")
    if not isinstance(ACADEMY_PASSCODES, dict):
        ACADEMY_PASSCODES = {}
except Exception:
    print("[학원] ACADEMY_PASSCODES 를 못 읽었다 — 해피트리 단독으로 돈다")
    ACADEMY_PASSCODES = {}


def _admin_secrets():
    """비밀번호 → 학원. 지금까지 쓰던 비번들은 전부 해피트리."""
    out = {}
    for s in (ADMIN_PASSCODE, TEST_ADMIN_PASSCODE, API_ADMIN_KEY):
        if s:
            out.setdefault(s, ACADEMY_DEFAULT)
    for ac, pw in ACADEMY_PASSCODES.items():
        ac = str(ac).strip()
        pw = str(pw or "").strip()
        # 학원 비번이 기존 관리자 비번과 같으면 학원 구분이 무의미해진다 — 막는다.
        if ac and pw and pw not in out:
            out[pw] = ac
    return out


def academy_of(request: Request) -> str:
    """이 요청을 보낸 관리자가 어느 학원인지. 학생 화면 요청에는 쓰지 않는다."""
    got = (request.headers.get("x-ht-admin") or request.query_params.get("pw") or "").strip()
    for pw, ac in _admin_secrets().items():
        if got and hmac.compare_digest(got, pw):
            return ac
    return ACADEMY_DEFAULT


def academy_of_student(rec: dict) -> str:
    """학생·과제 한 건이 어느 학원 것인지. 값이 없으면 해피트리(기존 자료)."""
    v = str((rec or {}).get("academy") or "").strip()
    return v or ACADEMY_DEFAULT


def only_academy(rows, ac):
    """그 학원 것만 걸러 준다. 명단·과제를 내보내는 곳은 전부 이걸 거친다."""
    return [r for r in (rows or []) if academy_of_student(r) == ac]


def is_admin(request: Request) -> bool:
    got = (request.headers.get("x-ht-admin") or request.query_params.get("pw") or "").strip()
    if not got:
        return False
    # compare_digest: 맞는 글자 수만큼 시간이 더 걸리는 것으로 비밀번호를 알아내는 수법을 막는다.
    return any(hmac.compare_digest(got, s) for s in _admin_secrets().keys())


def require_admin(request: Request):
    """관리자 전용 엔드포인트에 건다. 학생 화면이 쓰는 경로에는 절대 걸지 않는다."""
    if API_AUTH == "off":
        return
    if not _admin_secrets():
        # 비밀번호가 아예 없는 서버 = 아무나 들어올 수 있는 상태다. 열어 두느니 잠근다.
        raise HTTPException(503, "서버에 ADMIN_PASSCODE 가 설정되지 않았어요. 관리자 기능을 잠급니다.")
    if is_admin(request):
        return
    if API_AUTH == "log":
        # 켜기 전에 '누가 막혔을지' 먼저 보고 싶을 때 쓴다(막지 않고 로그만).
        print(f"[auth] 막힐 요청(log 모드): {request.method} {request.url.path}")
        return
    raise HTTPException(401, "관리자 권한이 필요해요.")


ADMIN_ONLY = [Depends(require_admin)]


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

    test = TEST_STUDENTS.get(sid)
    if test:
        if pw != test["pw"]:
            raise HTTPException(401, "아이디 또는 비밀번호가 일치하지 않아요.")
        student = upsert_shared_student({"id": sid, "pw": pw, "name": test["name"], "cls": test["cls"]})
        return {"ok": True, "student": student}

    # app=treetalk: '이 학원이 트리톡을 쓰기로 했는가'를 공용 학생계정이 판단하게 한다.
    # 안 밝히면 검사를 건너뛰므로, 안 산 학원 학생도 그냥 들어온다.
    shared = await fetch_shared_accounts({"action": "login", "id": sid, "pw": pw, "app": "treetalk"})
    if not shared.get("ok"):
        # 학원이 트리톡을 안 쓰는 경우는 비밀번호 문제가 아니므로 그대로 알려 준다.
        if shared.get("code") == "APP_NOT_SUBSCRIBED":
            raise HTTPException(403, shared.get("msg") or "우리 학원에서 사용하지 않는 앱이에요.")
        raise HTTPException(401, "아이디 또는 비밀번호가 일치하지 않아요.")
    shared["id"] = sid
    shared["pw"] = pw
    student = upsert_shared_student(shared)
    return {"ok": True, "student": student}


@app.post("/api/login/admin")
def login_admin(payload: dict = Body(...)):
    if not _admin_secrets():
        raise HTTPException(503, "서버에 ADMIN_PASSCODE 가 설정되지 않았어요.")
    got = str(payload.get("pw", ""))
    if not any(hmac.compare_digest(got, s) for s in _admin_secrets()):
        raise HTTPException(401, "비밀번호가 올바르지 않아요.")
    # 화면을 여는 것뿐 아니라, 이 비밀번호가 관리자 API 를 여는 열쇠이기도 하다.
    # 프런트는 이걸 x-ht-admin 헤더로 다시 보낸다(static/index.html 의 api()).
    return {"ok": True}


def _store_sources():
    return [("subs", SUB_DIR), ("vocab", VOCAB_DIR), ("exam", EXAM_DIR),
            ("activity", ACT_DIR), ("push", PUSH_DIR)]


# 마지막 동기화 결과 — /api/admin/store-status 에서 확인한다
_last_sync = {"state": "아직 안 함"}


@app.on_event("startup")
def _mirror_sync_on_boot():
    """mirror 모드로 켜지면 디스크 내용을 D1 로 저절로 밀어 올린다.

    이걸 두는 이유: 이렇게 안 하면 배포한 뒤 관리자가 백필 엔드포인트를 손으로
    한 번 불러야 한다. Render 에서 TT_STORE=mirror 로 바꾸는 것만으로 끝나게 한다.
    부팅을 막지 않도록 뒤에서 돌린다(Render 헬스체크가 기다리지 않게).
    """
    if store.MODE != "mirror":
        _last_sync["state"] = f"{store.MODE} 모드 — 동기화 안 함"
        return

    def run():
        _last_sync["state"] = "도는 중"
        try:
            _last_sync.update(store.sync_to_remote(_store_sources(), DB_PATH))
            _last_sync["state"] = "끝"
        except Exception as e:
            _last_sync["state"] = f"실패: {e}"
        print("[store] 시작 동기화:", _last_sync)

    threading.Thread(target=run, daemon=True).start()


@app.get("/api/admin/store-status", dependencies=ADMIN_ONLY)
def store_status(pw: str = ""):
    """지금 저장소가 어느 모드인지, 디스크에 학생 몇 명분이 있는지."""
    # 비밀번호 검사는 require_admin(ADMIN_ONLY) 이 이미 했다. ?pw= 도 거기서 받는다.
    counts = {}
    for kind, d in _store_sources():
        counts[kind] = len(list(d.glob("*.json"))) if d.exists() else 0
    return {"ok": True, "store": store.info(), "disk": counts,
            "db_exists": DB_PATH.exists(), "sync": _last_sync}


@app.post("/api/admin/store-backfill", dependencies=ADMIN_ONLY)
def store_backfill(payload: dict = Body(...)):
    """디스크에 있는 옛 기록을 D1 로 한 번에 올린다 (일회성).

    쓰는 법: TT_STORE=mirror 로 배포한 뒤 딱 한 번 부른다.
      curl -X POST .../api/admin/store-backfill -H 'Content-Type: application/json' \
           -d '{"pw":"<관리자비번>"}'
    ★디스크가 원본이므로 몇 번을 불러도 안전하다(D1 을 디스크에 맞춘다).
    ★TT_STORE=d1 로 전환한 뒤에는 부르지 마라 — 그때부터는 D1 이 원본이다.
    """
    # 비밀번호 검사는 require_admin(ADMIN_ONLY) 이 이미 했다.
    if store.MODE == "d1":
        raise HTTPException(400, "이미 D1 이 원본이다. 백필을 돌리면 최신 기록을 옛 파일로 덮는다.")

    r = store.sync_to_remote(_store_sources(), DB_PATH)
    _last_sync.update(r)
    _last_sync["state"] = "끝(수동)"
    return r


# ---------- students ----------
@app.get("/api/students", dependencies=ADMIN_ONLY)
async def get_students(request: Request):
    """★그 학원 학생만 돌려준다. 예전에는 전교생을 다 내줬다(학원이 하나일 땐 무해했다)."""
    ac = academy_of(request)
    rows = None
    if ac == ACADEMY_DEFAULT:
        # 공용 명단 동기화(rosterInfo)는 선생님 토큰이 없으면 해피트리 것만 준다.
        # 그래서 다른 학원일 때는 부르지 않는다 — 불러 봤자 다 걸러진다.
        # (다른 학원 학생은 처음 로그인할 때 login_student 가 academy 와 함께 넣어 준다)
        try:
            rows = await sync_shared_roster()
        except HTTPException as exc:
            print("[student-sync] 명단 동기화 실패, 로컬 명단 사용:", exc.detail)
    if rows is None:
        rows = load_db()["students"]
    return only_academy(rows, ac)


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
            "grade": str(payload.get("grade", "")).strip(),
            # ★학원. 공용 학생계정(Apps Script)이 등록을 밀어 넣을 때 같이 보낸다.
            #   없으면 해피트리로 친다 — 예전에 등록된 학생들이 그렇다.
            "academy": str(payload.get("academy") or "").strip() or ACADEMY_DEFAULT,
        }
        db["students"].append(student)
        save_db(db)
    return student


@app.post("/api/students/bulk", dependencies=ADMIN_ONLY)
def add_students_bulk(request: Request, payload: dict = Body(...)):
    """엑셀 명단으로 학생 여러 명을 한 번에 등록. body: {students:[{name, className?, id?, pw?}]}"""
    bulk_stu_ac = academy_of(request)   # 등록하는 사람의 학원으로 새긴다
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
                "grade": str((it or {}).get("grade", "")).strip(),
                "academy": bulk_stu_ac,
            }
            db["students"].append(student)
            created.append(student)
        save_db(db)
    return {"created": len(created), "students": created}


@app.patch("/api/students/{student_id}", dependencies=ADMIN_ONLY)
def update_student(request: Request, student_id: str, payload: dict = Body(...)):
    """학생 정보 수정 (반, 이름, 학년 등)."""
    ac = academy_of(request)
    allowed = {"name", "className", "pw", "grade"}
    with _lock:
        db = load_db()
        for s in db["students"]:
            if s["id"] == student_id:
                # ★남의 학원 학생은 '없는 학생'으로 답한다(있는지 없는지도 알려주지 않는다)
                if academy_of_student(s) != ac:
                    raise HTTPException(404, "학생을 찾을 수 없어요.")
                for k, v in payload.items():
                    if k in allowed:
                        s[k] = str(v).strip()
                save_db(db)
                return s
    raise HTTPException(404, "학생을 찾을 수 없어요.")


@app.delete("/api/students/{student_id}", dependencies=ADMIN_ONLY)
def delete_student(request: Request, student_id: str):
    """★2026-09-06 잠금.
    여태 인증이 아예 없었다 — 아무나 `DELETE /api/students/<아이디>` 로
    학생을 지울 수 있었다(실측 200). 되돌릴 수 없는 동작이다."""
    ac = academy_of(request)
    with _lock:
        db = load_db()
        target = next((s for s in db["students"] if s["id"] == student_id), None)
        if target is None:
            raise HTTPException(404, "학생을 찾을 수 없어요.")
        if academy_of_student(target) != ac:
            raise HTTPException(404, "학생을 찾을 수 없어요.")
        db["students"] = [s for s in db["students"] if s["id"] != student_id]
        save_db(db)
    return {"ok": True}


# ---------- assignments ----------
@app.get("/api/assignments")
def get_assignments(request: Request):
    """★그 학원 과제만.

    학생 화면도 이걸 부른다. 학생은 비밀번호가 없으니 해피트리로 떨어지는데,
    그러면 다른 학원 학생이 과제를 못 본다. 그래서 학생은 id 를 함께 보내고
    (프런트가 이미 학생 아이디를 갖고 있다) 그 학생의 학원 것을 준다.
    ★id 로 '남의 학원'을 볼 수는 없다 — 그 학생이 실제로 속한 학원만 나오기 때문이다."""
    db = load_db()   # ★한 번만 읽는다(예전엔 학생 조회 때 load_db 를 두 번 불렀다)
    sid = str(request.query_params.get("student") or "").strip()
    admin = is_admin(request)
    if admin:
        # ★관리자 열쇠가 있으면 그 열쇠의 학원만 본다. ?student= 는 무시한다.
        #   안 그러면 A학원 관리자가 ?student=<B학원 학생> 을 붙여 B학원 과제를 통째로 읽는다.
        ac = academy_of(request)
    elif sid:
        st = next((s for s in db["students"] if str(s.get("id")) == sid), None)
        ac = academy_of_student(st) if st else ACADEMY_DEFAULT
    else:
        ac = ACADEMY_DEFAULT
    rows = only_academy(db["assignments"], ac)
    # ★기본은 보관함(published=false) 제외. 학생 화면은 어차피 보관함을 안 쓰므로
    #   그만큼 응답이 가벼워진다(자료가 쌓여도 학생 로딩이 안 무거워짐).
    #   관리자가 보관함을 관리할 때만 ?archived=1 로 전체를 받는다.
    if not (admin and request.query_params.get("archived") == "1"):
        rows = [a for a in rows if a.get("published") is not False]
    return _light_assignments(rows)


def _light_assignments(lst):
    """목록 응답 경량화: 권말 시험(type=exam)의 무거운 문제은행(items/meanings/examples/exampleKo)을
    빼고 poolSize만 남긴다(응시할 때 /api/assignment/{id}로 전체를 받음). 예문 배열은 전 과제에서 제거."""
    out = []
    for a in lst:
        b = dict(a)
        if b.get("type") == "exam":
            b["poolSize"] = len(b.get("items") or [])
            for k in ("items", "meanings", "examples", "exampleKo"):
                b[k] = []
        else:
            b.pop("examples", None); b.pop("exampleKo", None)
        out.append(b)
    return out


@app.get("/api/assignment/{assignment_id}")
def get_one_assignment(assignment_id: str, request: Request):
    """과제 하나 전체(시험 문제은행 포함) — 시험 응시 화면에서만 호출."""
    a = next((x for x in load_db()["assignments"] if x.get("id") == assignment_id), None)
    if not a:
        raise HTTPException(404, "과제를 찾을 수 없어요.")
    return a


@app.post("/api/assignments", dependencies=ADMIN_ONLY)
def add_assignment(request: Request, payload: dict = Body(...)):
    with _lock:
        db = load_db()
        a = {
            "id": "a" + uuid.uuid4().hex[:10],
            "academy": academy_of(request),
            "title": str(payload.get("title", "")).strip(),
            "book": str(payload.get("book", "")).strip(),
            "type": payload.get("type", "word"),
            "items": payload.get("items", []),
            "meanings": payload.get("meanings", []),
            "examples": payload.get("examples", []),
            "exampleKo": payload.get("exampleKo", []),
            "passScore": int(payload.get("passScore") or 70),
            "dueDate": payload.get("dueDate") or None,
            "rounds": max(1, min(3, int(payload.get("rounds") or 3))),
            "assignedIds": payload.get("assignedIds", []),
            "assignedClasses": payload.get("assignedClasses", []),
            "exampleAudio": payload.get("exampleAudio", []),
            # 권말 시험의 철자 입력 방식. tiles = 알파벳 타일을 눌러 세운다(저학년),
            # type = 자판으로 친다. 없으면 학생 앱이 책 이름의 LV로 어림잡는다(LV3 이하 타일).
            "spellMode": (payload.get("spellMode") or None),
            "spellDecoys": payload.get("spellDecoys"),
            "recordMode": ("whole" if payload.get("recordMode") == "whole" else "each"),
            "published": bool(payload.get("published", True)),
        }
        if not a["title"] or not a["items"]:
            raise HTTPException(400, "제목과 목록을 입력해주세요.")
        db["assignments"].insert(0, a)
        save_db(db)
    return a


@app.delete("/api/assignments/{assignment_id}", dependencies=ADMIN_ONLY)
def delete_assignment(request: Request, assignment_id: str):
    """★관리자 열쇠만으로는 부족하다. 그 과제가 '내 학원' 것이어야 한다.
    안 그러면 리딩온 열쇠(7330)로 해피트리 과제를 지울 수 있다(실측 200이었다)."""
    ac = academy_of(request)
    with _lock:
        db = load_db()
        target = next((a for a in db["assignments"] if a["id"] == assignment_id), None)
        if target is None or academy_of_student(target) != ac:
            raise HTTPException(404, "과제를 찾을 수 없어요.")
        db["assignments"] = [a for a in db["assignments"] if a["id"] != assignment_id]
        save_db(db)
    return {"ok": True}


@app.post("/api/assignments/bulk", dependencies=ADMIN_ONLY)
def add_assignments_bulk(request: Request, payload: dict = Body(...)):
    """여러 과제를 한 번에 생성 (교재 한 권을 Day별로 나눠서 등록)."""
    bulk_ac = academy_of(request)
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
                "academy": bulk_ac,
                "title": title,
                "book": str(p.get("book", "")).strip(),
                "type": p.get("type", "word"),
                "items": words,
                "meanings": p.get("meanings", []),
                "examples": p.get("examples", []),
                "exampleKo": p.get("exampleKo", []),
                "passScore": int(p.get("passScore") or 70),
                "dueDate": p.get("dueDate") or None,
                "rounds": max(1, min(3, int(p.get("rounds") or 3))),
                "assignedIds": p.get("assignedIds", []),
                "assignedClasses": p.get("assignedClasses", []),
                "exampleAudio": p.get("exampleAudio", []),
                "spellMode": (p.get("spellMode") or None),
                "spellDecoys": p.get("spellDecoys"),
                "recordMode": ("whole" if p.get("recordMode") == "whole" else "each"),
                "published": bool(p.get("published", True)),
            }
            db["assignments"].insert(0, a)
            created.append(a)
        save_db(db)
    return {"created": len(created), "assignments": created}


@app.post("/api/assignments/delete-all", dependencies=ADMIN_ONLY)
def delete_all_assignments(request: Request, payload: dict = Body(...)):
    """과제 일괄 삭제. scope='published'(배포된 것만) | 'archived'(보관함만) | 'all'(전부).

    ★'전부'는 **내 학원 전부**다. 남의 학원 과제는 손대지 않는다.
      학원이 하나일 땐 같은 말이었지만, 셋이 되면 '전부'가 남의 학원까지 지워 버린다."""
    ac = academy_of(request)
    scope = str(payload.get("scope") or "published")
    mine = lambda a: academy_of_student(a) == ac      # 내 학원 것인가
    with _lock:
        db = load_db()
        before = sum(1 for a in db["assignments"] if mine(a))
        if scope == "all":
            db["assignments"] = [a for a in db["assignments"] if not mine(a)]
        elif scope == "published":
            db["assignments"] = [a for a in db["assignments"] if not (mine(a) and a.get("published", True))]
        elif scope == "archived":
            db["assignments"] = [a for a in db["assignments"] if not (mine(a) and not a.get("published", True))]
        else:
            raise HTTPException(400, "알 수 없는 삭제 범위예요.")
        save_db(db)
        # before 는 '내 학원 것'만 셌으므로 남은 것도 같은 기준으로 세야 한다
        deleted = before - sum(1 for a in db["assignments"] if mine(a))
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


@app.post("/api/assignments/dedupe", dependencies=ADMIN_ONLY)
def dedupe_assignments(request: Request, payload: dict = Body(...)):
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
        _dd_ac = academy_of(request)
        for a in db["assignments"]:
            # ★내 학원 과제끼리만 묶는다. 안 그러면 제목이 같다는 이유로
            #   남의 학원 과제가 '중복'으로 몰려 지워진다.
            if academy_of_student(a) != _dd_ac:
                continue
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


@app.post("/api/assignments/dedupe-book", dependencies=ADMIN_ONLY)
def dedupe_book(request: Request, payload: dict = Body(...)):
    """지정한 과제(ids) 안에서 같은 '제목'이 여러 번 있으면 하나만 남기고 정리.
    (마감일이 서로 달라도 같은 Day면 중복으로 봄 — 같은 책을 두 번 배정한 경우)
    남길 하나: 녹음이 있는 것 우선, 없으면 마감일이 가장 이른 것.
    dryRun=true면 삭제하지 않고 몇 개 지울지만 알려준다."""
    ids = payload.get("ids") or []
    dry = bool(payload.get("dryRun"))
    if not ids:
        raise HTTPException(400, "정리할 과제를 지정해주세요.")
    # ★내 학원 과제만 대상으로 삼는다(남의 학원 id 를 섞어 보내도 건드리지 않는다)
    _db_ac = academy_of(request)
    idset = {a["id"] for a in load_db()["assignments"]
             if a["id"] in set(ids) and academy_of_student(a) == _db_ac}
    if not idset:
        raise HTTPException(404, "정리할 과제를 찾을 수 없어요.")
    # 녹음이 있는 과제 id 모으기
    subbed = set()
    for sid in all_student_ids():
        try:
            data = load_student_subs(sid) or {}
            for aid, sub in data.items():
                if aid in idset and aid not in subbed and _has_recording(sub):
                    subbed.add(aid)
        except Exception:
            pass
    with _lock:
        db = load_db()
        from collections import defaultdict
        groups = defaultdict(list)
        for a in db["assignments"]:
            if a["id"] in idset:
                groups[a.get("title", "")].append(a)
        to_delete = set()
        for g in groups.values():
            if len(g) < 2:
                continue
            # 정렬: 녹음 있는 것 먼저, 그다음 마감일 이른 순 → 첫 개를 남긴다
            g.sort(key=lambda a: (a["id"] not in subbed, a.get("dueDate") or "9999-99-99"))
            for a in g[1:]:
                to_delete.add(a["id"])
        if dry:
            return {"wouldDelete": len(to_delete)}
        before = len(db["assignments"])
        db["assignments"] = [a for a in db["assignments"] if a["id"] not in to_delete]
        save_db(db)
        deleted = before - len(db["assignments"])
    return {"deleted": deleted}


@app.post("/api/students/{sid}/clean-books", dependencies=ADMIN_ONLY)
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
    converted = 0
    with _lock:
        db = load_db()
        all_ids = [s.get("id") for s in db.get("students", []) if s.get("id")]
        remaining = []
        for a in db["assignments"]:
            if a.get("published") is False:      # 보관함은 건드리지 않음
                remaining.append(a)
                continue
            ids = a.get("assignedIds") or []
            classes = a.get("assignedClasses") or []
            book = a.get("book", "")
            is_all = (not ids) and (not classes)             # 전체(모든 학생) 배정
            student_has = (sid in ids) or is_all             # 이 학생이 받는 책인지
            hit = student_has and ((keep is not None and book != keep) or (book in remove))
            if not hit:
                remaining.append(a)
                continue
            if is_all:
                # 전체 → 이 학생만 빼기 = 나머지 학생에게만 개별 배정
                others = [x for x in all_ids if x != sid]
                if others:
                    a["assignedIds"] = others
                    converted += 1
                    remaining.append(a)
                else:
                    deleted += 1                              # 학생이 이 사람뿐이면 삭제
            else:
                new_ids = [x for x in ids if x != sid]
                if not new_ids and not classes:
                    deleted += 1                              # 이 학생 전용 → 과제 삭제
                else:
                    a["assignedIds"] = new_ids
                    unassigned += 1
                    remaining.append(a)
        db["assignments"] = remaining
        save_db(db)
    return {"unassigned": unassigned + converted, "deleted": deleted}


@app.post("/api/assignments/fill-meanings", dependencies=ADMIN_ONLY)
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


@app.post("/api/assignments/delete-many", dependencies=ADMIN_ONLY)
def delete_assignments(request: Request, payload: dict = Body(...)):
    ids = set(payload.get("ids") or [])
    if not ids:
        raise HTTPException(400, "삭제할 과제가 없어요.")
    ac = academy_of(request)
    with _lock:
        db = load_db()
        # ★받은 id 중 '내 학원' 것만 남긴다. 남의 학원 id 를 섞어 보내도 안 지워진다.
        ids = {a["id"] for a in db["assignments"] if a["id"] in ids and academy_of_student(a) == ac}
        if not ids:
            raise HTTPException(404, "삭제할 과제를 찾을 수 없어요.")
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


def _sync_exam_dates(db):
    """각 권말 시험(type=exam, autoDate!=False)의 마감일을 그 책 마지막 Day + 1일로 맞춘다.
    선생님이 시험 날짜를 직접 바꾸면 autoDate=False가 되어 더는 자동 조정하지 않는다."""
    from datetime import date, timedelta
    def parse(s):
        y, m, d = map(int, s.split("-")); return date(y, m, d)
    for ex in db.get("assignments", []):
        if ex.get("type") != "exam" or ex.get("autoDate") is False:
            continue
        book = ex.get("book", "")
        days = [a for a in db["assignments"]
                if a.get("book") == book and a.get("type") != "exam" and a.get("dueDate")]
        if not days:
            continue
        last = max(parse(a["dueDate"]) for a in days)
        ex["dueDate"] = (last + timedelta(days=1)).isoformat()


@app.patch("/api/assignments/{assignment_id}")
def update_assignment(assignment_id: str, payload: dict = Body(...)):
    """과제 하나 수정 (마감일, 제목, 녹음 횟수, 배정 대상 등)."""
    allowed = {"title", "dueDate", "rounds", "type", "book", "assignedIds", "assignedClasses", "published", "items", "meanings", "exampleAudio", "recordMode", "examples", "exampleKo", "passScore", "spellMode", "spellDecoys"}
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
                # 시험 날짜를 직접 바꾸면 자동조정 해제 / 그 외엔 시험 날짜 재동기화
                if a.get("type") == "exam" and "dueDate" in payload:
                    a["autoDate"] = False
                else:
                    _sync_exam_dates(db)
                save_db(db)
                return a
    raise HTTPException(404, "과제를 찾을 수 없어요.")


@app.post("/api/assignments/reschedule", dependencies=ADMIN_ONLY)
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

        _sync_exam_dates(db)   # 책 일정이 바뀌면 권말 시험을 마지막 날 다음날로 재조정
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


def _avg_score_from_sub(sub):
    """items(항목별) + whole(통문장) 양쪽 take 점수를 모두 모아 평균낸다.
    ★통문장 녹음은 점수가 sub['whole'] 에 저장되므로 items 만 보면 통문장이 통째로 누락됐다."""
    scores = []
    for takes in ((sub or {}).get("items") or []):
        for t in (takes or []):
            if t and t.get("score") is not None:
                scores.append(t["score"])
    for t in ((sub or {}).get("whole") or []):
        if t and t.get("score") is not None:
            scores.append(t["score"])
    return round(sum(scores) / len(scores)) if scores else None


# ---------- 트리톡 알림: 오늘의 4활동(단어녹음·문장녹음·단어자습·문장자습) 현황 ----------
BOT_NOTIFY_URL = os.environ.get("BOT_NOTIFY_URL",
    "https://script.google.com/macros/s/AKfycbwHxEXK4Lz80L8A9zDiqIE8CNzNKSSiFCk6HYevmRdhde5eSRmSVATwHuRxsHBnv7Uh/exec")

def _treetalk_today_status(student_id):
    """오늘 트리톡 4활동 현황: 단어녹음/문장녹음 점수 + 단어자습/문장자습 완료(50%↑)."""
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc) + timedelta(hours=9)
    today = "%d/%d" % (d.month, d.day)   # _now_kr()과 같은 'M/D'
    db = load_db()
    atype = {}
    for a in db.get("assignments", []):
        atype[a.get("id")] = a.get("type", "word")
    res = {"word_rec": None, "sent_rec": None, "word_study": False, "sent_study": False}
    is_today = lambda ts: str(ts or "").split(" ")[0] == today
    try:
        subs = load_student_subs(student_id) or {}
    except Exception:
        subs = {}
    for aid, sub in subs.items():
        if (sub or {}).get("status") not in ("submitted", "reviewed"):
            continue
        if not (is_today(sub.get("submittedAt")) or is_today(sub.get("completedAt"))):
            continue
        avg = _avg_score_from_sub(sub)
        if avg is None:
            continue
        if atype.get(aid, "word") == "sentence":
            res["sent_rec"] = avg if res["sent_rec"] is None else max(res["sent_rec"], avg)
        else:
            res["word_rec"] = avg if res["word_rec"] is None else max(res["word_rec"], avg)
    try:
        vocab = load_vocab(student_id) or {}
    except Exception:
        vocab = {}
    for aid, rec in vocab.items():
        by = (rec or {}).get("byMode") or {}
        touched = any(is_today(((bm or {}).get("last") or {}).get("at")) for bm in by.values())
        if not touched:
            continue
        stages = ["smeaning", "unscramble"] if atype.get(aid, "word") == "sentence" else ["flash", "choice", "spell", "test"]
        if sum(1 for s in stages if by.get(s)) / len(stages) >= 0.5:
            if atype.get(aid, "word") == "sentence":
                res["sent_study"] = True
            else:
                res["word_study"] = True
    return res


def _treetalk_done_ids_today() -> set:
    """오늘(KST) 트리톡을 '다 한' 학생 id 집합. 관리자 '오늘 밀린 학습(트리톡)' 계산용.

    ★단어녹음만 하고 문장녹음을 안 하면 완료가 아니다(문장녹음 하는 학년 대비, 2026-09-10 원장님).
      완료 기준 = 그 학생이 '평소 하는 녹음 유형'을 오늘 다 녹음했는가.
      - 평소 유형 = 지금까지 녹음해 본 유형(단어/문장). 문장녹음을 해온 학생이면 오늘도 문장녹음까지 해야 완료.
      - 녹음 이력이 아직 없는 학생(유형을 알 수 없음)은 예전처럼 오늘 녹음이나 자습이 하나라도 있으면 완료로 본다.
    db·제출·자습 파일은 학생당 한 번씩만 읽는다."""
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc) + timedelta(hours=9)
    today = "%d/%d" % (d.month, d.day)
    is_today = lambda ts: str(ts or "").split(" ")[0] == today
    db = load_db()
    atype = {a.get("id"): a.get("type", "word") for a in db.get("assignments", [])}

    # (1) 녹음: 학생별로 오늘 녹음한 유형(rec_*) + 지금까지 녹음해 온 유형(ever_*)
    recinfo = {}
    for sid in all_student_ids():
        try:
            subs = load_student_subs(sid) or {}
        except Exception:
            continue
        rec_w = rec_s = ever_w = ever_s = False
        for aid, sub in subs.items():
            if (sub or {}).get("status") not in ("submitted", "reviewed"):
                continue
            if _avg_score_from_sub(sub) is None:
                continue
            is_sent = (atype.get(aid, "word") == "sentence")
            if is_sent:
                ever_s = True
            else:
                ever_w = True
            if is_today(sub.get("submittedAt")) or is_today(sub.get("completedAt")):
                if is_sent:
                    rec_s = True
                else:
                    rec_w = True
        recinfo[sid] = (rec_w, rec_s, ever_w, ever_s)

    # (2) 오늘 자습한 학생(녹음 이력이 없는 학생의 완료 판정에만 쓴다)
    studied = set()
    for sid in all_vocab_student_ids():
        try:
            vocab = load_vocab(sid) or {}
        except Exception:
            continue
        for aid, rec in vocab.items():
            by = (rec or {}).get("byMode") or {}
            if not any(is_today(((bm or {}).get("last") or {}).get("at")) for bm in by.values()):
                continue
            stages = ["smeaning", "unscramble"] if atype.get(aid, "word") == "sentence" else ["flash", "choice", "spell", "test"]
            if sum(1 for s in stages if by.get(s)) / len(stages) >= 0.5:
                studied.add(sid)
                break

    done = set()
    for sid in set(recinfo) | studied:
        rec_w, rec_s, ever_w, ever_s = recinfo.get(sid, (False, False, False, False))
        if ever_w or ever_s:
            # 녹음 하는 학생: 평소 하는 녹음 유형을 오늘 다 해야 완료(문장녹음 빠지면 미완료)
            if (rec_w or rec_s) and (not ever_w or rec_w) and (not ever_s or rec_s):
                done.add(sid)
        else:
            # 녹음 이력 없음: 오늘 녹음이든 자습이든 하나라도 있으면 완료(옛 기준)
            if rec_w or rec_s or (sid in studied):
                done.add(sid)
    return done


@app.get("/api/practiced-today")
def practiced_today():
    """오늘(KST) 트리톡을 한 학생 id 목록만 돌려준다(이름·점수 등 개인정보 없음).
    관리자 대시보드가 '오늘 밀린 학습(트리톡)'을 계산할 때 쓴다.
    CORS 로 admin.happytreeacademy.com 브라우저만 접근할 수 있고, 내용은 불투명한 아이디뿐이다."""
    return {"ok": True, "date": _today_kr(), "ids": sorted(_treetalk_done_ids_today())}


def _notify_treetalk(student_id, lesson=""):
    """트리톡 활동 완료 시 담당쌤(학년별, 입력봇이 결정)+원장께 4활동 현황 알림. best-effort."""
    try:
        db = load_db()
        student = next((s for s in db.get("students", []) if s.get("id") == student_id), None)
        if not student:
            return
        name = student.get("name") or student_id
        cls = student.get("className") or ""
        st = _treetalk_today_status(student_id)
        wr = ("%d점" % st["word_rec"]) if st["word_rec"] is not None else "⬜"
        sr = ("%d점" % st["sent_rec"]) if st["sent_rec"] is not None else "⬜"
        what = ("단어 녹음 %s · 문장 녹음 %s\n단어 자습 %s · 문장 자습 %s"
                % (wr, sr, "✅" if st["word_study"] else "⬜", "✅" if st["sent_study"] else "⬜"))
        import urllib.request, urllib.parse
        _params = {"learndone": "1", "app": "트리톡", "student": name, "cls": cls, "what": what}
        if lesson:
            _params["lesson"] = lesson
        q = urllib.parse.urlencode(_params)
        try:
            urllib.request.urlopen(BOT_NOTIFY_URL + "?" + q, timeout=8).read()
        except Exception as e:
            print("[treetalk] relay fail:", e)
    except Exception as e:
        print("[treetalk] notify err:", e)


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
    avg = _avg_score_from_sub(sub)
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
            _notify_treetalk(student_id, lesson=a_title)   # 담당쌤(학년별)+원장께 4활동 현황
        except Exception as e:
            print("[telegram] 트리톡 제출 알림 실패:", e)

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


MAX_AUDIO_BYTES = 25 * 1024 * 1024   # 한 번 녹음이 25MB 를 넘을 일은 없다


@app.post("/api/audio")
async def upload_audio(audio: UploadFile = File(...)):
    """학생 녹음 저장.
    ★여기는 학생이 부르는 곳이라 관리자 문을 달 수 없다. 지금은 세션이라는 게 없어서
      '누가 올렸는지' 를 서버가 확인할 방법이 아직 없다(2단계 인증 이전에서 함께 해결).
      그때까지는 최소한 디스크를 채우는 장난은 막아 둔다. """
    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "빈 오디오 파일이에요.")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "녹음 파일이 너무 커요.")
    name = uuid.uuid4().hex + ".webm"
    with open(AUDIO_DIR / name, "wb") as f:
        f.write(raw)
    return {"url": f"/api/audio/{name}"}


AUDIO_TYPES = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".webm": "audio/webm",
    ".aac": "audio/aac",
}

# 이 서버가 직접 만든 파일 이름만 (<uuid>.webm / ex_<uuid>.mp3 / tts_<uuid>.mp3)
AUDIO_NAME = re.compile(r"^(ex_|tts_)?[0-9a-f]{32}\.[a-z0-9]{2,4}$")


@app.get("/api/audio/{name}")
def get_audio(name: str):
    # 파일 이름은 이 서버가 만든 모양(<uuid>.webm, ex_…, tts_…)만 받는다.
    # 폴더에 다른 파일이 섞여 들어와도 그건 내보내지 않는다.
    if not AUDIO_NAME.match(name):
        raise HTTPException(404, "not found")
    path = AUDIO_DIR / name
    if not path.exists():
        raise HTTPException(404, "not found")
    ext = os.path.splitext(name)[1].lower()
    # 녹음은 검색엔진에 올라가면 안 된다.
    return FileResponse(path, media_type=AUDIO_TYPES.get(ext, "audio/webm"),
                        headers={"X-Robots-Tag": "noindex, noimageindex"})


@app.post("/api/assignments/{assignment_id}/example-audio", dependencies=ADMIN_ONLY)
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


@app.post("/api/assignments/{assignment_id}/tts-audio", dependencies=ADMIN_ONLY)
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


@app.delete("/api/assignments/{assignment_id}/example-audio/{index}", dependencies=ADMIN_ONLY)
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


def _pa_words(pa):
    out = []
    try:
        for w in (pa.words or []):
            out.append({"word": w.word, "accuracy": w.accuracy_score, "errorType": w.error_type})
    except Exception:
        pass
    return out


def _assess_once(recognizer):
    """짧은 발화(단어·문장 하나): recognize_once. 반환 (kind, payload) — kind='ok'|'nomatch'|'cancel'."""
    import azure.cognitiveservices.speech as speechsdk
    result = recognizer.recognize_once()
    if result.reason == speechsdk.ResultReason.Canceled:
        det = result.cancellation_details
        return ("cancel", f"{det.reason} {det.error_details or ''}")
    if result.reason != speechsdk.ResultReason.RecognizedSpeech:
        return ("nomatch", str(result.reason).split(".")[-1])
    pa = speechsdk.PronunciationAssessmentResult(result)
    raw = result.properties.get(speechsdk.PropertyId.SpeechServiceResponse_JsonResult) or "{}"
    return ("ok", {
        "ok": pa.pronunciation_score is not None, "status": "Success",
        "text": result.text or "", "pron": pa.pronunciation_score,
        "accuracy": pa.accuracy_score, "fluency": pa.fluency_score,
        "completeness": pa.completeness_score, "words": _pa_words(pa), "raw": raw,
    })


def _assess_continuous(recognizer, reference):
    """긴 지문(통문장): 연속 인식으로 전체를 듣고 조각별 점수를 합친다. 반환 (kind, payload).
    recognize_once 는 ~15초 단일 발화용이라 지문 전체는 앞부분만 인식된다 → 통문장은 이 경로로 채점."""
    import azure.cognitiveservices.speech as speechsdk
    import time as _t
    results = []
    state = {"done": False, "cancel_raw": None, "cancel_err": False}

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            results.append(evt.result)

    def on_canceled(evt):
        try:
            state["cancel_err"] = (evt.reason == speechsdk.CancellationReason.Error)
            state["cancel_raw"] = f"{evt.reason} {getattr(evt, 'error_details', '') or ''}"
        except Exception:
            state["cancel_raw"] = "Canceled"
        state["done"] = True

    def on_stopped(evt):
        state["done"] = True

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_stopped)
    recognizer.start_continuous_recognition()
    waited = 0.0
    while not state["done"] and waited < 240:   # 긴 지문(천천히 읽으면 2~3분)도 안 잘리게
        _t.sleep(0.1); waited += 0.1
    try:
        recognizer.stop_continuous_recognition()
    except Exception:
        pass

    if not results:
        if state["cancel_err"]:
            return ("cancel", state["cancel_raw"] or "Canceled")
        return ("nomatch", "NoMatch")

    segs, all_words = [], []
    for res in results:
        pa = speechsdk.PronunciationAssessmentResult(res)
        ws = _pa_words(pa)
        all_words += ws
        segs.append((pa.pronunciation_score, pa.accuracy_score, pa.fluency_score, len(ws) or 1))
    totw = sum(s[3] for s in segs) or 1
    def wavg(i):
        return sum((s[i] or 0) * s[3] for s in segs) / totw
    ref_n = len(reference.replace("\n", " ").split()) or 1
    spoken = len([w for w in all_words if (w.get("errorType") or "None") != "Omission"])
    completeness = min(100.0, spoken / ref_n * 100.0)
    return ("ok", {
        "ok": True, "status": "Success",
        "text": " ".join(w["word"] for w in all_words),
        "pron": round(wavg(0), 1), "accuracy": round(wavg(1), 1),
        "fluency": round(wavg(2), 1), "completeness": round(completeness, 1),
        "words": all_words, "raw": "",
    })


def assess_with_sdk(wav_path: str, reference: str, debug: bool = False):
    """Azure Speech SDK로 발음평가. REST API는 점수를 누락하는 알려진 문제가 있어 SDK를 사용."""
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
    speech_config.speech_recognition_language = "en-US"

    pa_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Word,
        enable_miscue=len(reference.strip().split()) > 2,
    )

    # 통문장(긴 지문)이면 연속 인식으로 채점한다. recognize_once 는 ~15초 단일 발화용이라
    # 지문 전체(여러 문장)는 앞부분만 인식돼 점수가 안 나온다 → 통문장 채점이 '안 되던' 원인.
    is_long = ("\n" in reference) or (len(reference.split()) > 20)

    # 채점이 몰리면(Canceled=주로 Azure 속도제한) 바로 실패시키지 않고 짧게 쉬며 재시도한다.
    # (무음·NoMatch 같은 '진짜 인식 실패'는 재시도 안 하고 그대로 안내)
    import time as _time
    for attempt in range(3):
        audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        pa_config.apply_to(recognizer)

        kind, payload = _assess_continuous(recognizer, reference) if is_long else _assess_once(recognizer)

        if kind == "cancel":
            print(f"[assess] canceled (attempt {attempt+1}/3, long={is_long}): {payload}")   # 원본 기술 에러는 서버 로그에만
            if attempt < 2:
                _time.sleep(0.8 * (attempt + 1))   # 0.8s → 1.6s 백오프 후 재시도
                continue
            msg = "지금 발음 채점이 잠시 몰려서 안 돼요. 녹음은 저장됐으니 그대로 제출하면 돼요 🙂"
            if debug:
                msg += f" [DEBUG cancel: {payload}]"
            raise HTTPException(502, msg)
        if kind == "nomatch":
            return {"ok": False, "status": payload, "text": ""}
        return payload   # ok


def _run_assessment(raw_bytes: bytes, text: str, debug: bool = False) -> dict:
    """오디오 bytes → 발음평가 결과(out dict). /api/assess 와 백그라운드 채점(score-take)이 함께 쓴다."""
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
        "contentType": None,
        "engine": "sdk",
    }

    try:
        r = assess_with_sdk(wav_path, text, debug)
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


@app.post("/api/assess")
async def assess(text: str = Form(...), audio: UploadFile = File(...), debug: str = Form("")):
    if not AZURE_KEY:
        raise HTTPException(500, "서버에 AZURE_SPEECH_KEY가 설정되어 있지 않아요.")
    raw_bytes = await audio.read()
    if not raw_bytes:
        raise HTTPException(400, "오디오 파일이 비어있어요.")
    ct = audio.content_type
    out = await asyncio.to_thread(_run_assessment, raw_bytes, text, bool(debug))
    if isinstance(out, dict) and isinstance(out.get("audio"), dict):
        out["audio"]["contentType"] = ct
    return out


def _take_from_assessment(out: dict) -> dict:
    """assess 결과(out)를 프런트 take 모양(score/detail/recognized/…)으로 바꾼다.
    점수가 없으면 scoring=False + assessError 로 채운다. 항상 scoring 을 끈다."""
    pron = (out or {}).get("pronScore")
    d = (out or {}).get("audio") or {}
    if pron is not None:
        rnd = lambda v: None if v is None else round(v)
        return {
            "score": round(pron),
            "detail": {"accuracy": rnd(out.get("accuracyScore")),
                       "fluency": rnd(out.get("fluencyScore")),
                       "completeness": rnd(out.get("completenessScore"))},
            "recognized": out.get("recognizedText") or None,
            "words": out.get("words") or None,
            "durationMs": d.get("durationMs"),
            "scoring": False, "assessError": None, "assessDebug": None,
        }
    dbg = " · ".join([x for x in [
        (f"상태 {out.get('status')}" if (out or {}).get("status") else None),
        (f"길이 {d['durationMs']/1000:.1f}초" if d.get("durationMs") is not None else None),
        (f"음량 {d['dBFS']}dB" if d.get("dBFS") is not None else None),
    ] if x])
    return {"score": None, "scoring": False,
            "assessError": (out or {}).get("note") or "채점에 실패했어요. 다시 녹음해 주세요.",
            "assessDebug": dbg or None}


def _score_take_bg(aid: str, sid: str, raw_bytes: bytes, text: str, rnd: int, mode: str, index: int):
    """백그라운드에서 채점한 뒤 그 학생 제출의 해당 take 에 점수를 써넣는다(학생은 안 기다림)."""
    try:
        patch = _take_from_assessment(_run_assessment(raw_bytes, text, False))
    except Exception as e:
        print("[score-take] 채점 실패:", str(e)[:150])
        patch = {"score": None, "scoring": False, "assessError": "채점이 지연됐어요. 다시 녹음해 주세요."}
    try:
        with _sub_lock(sid):
            subs = load_student_subs(sid)
            sub = subs.get(aid) or {}
            if mode == "whole":
                whole = list(sub.get("whole") or [])
                while len(whole) <= rnd:
                    whole.append(None)
                take = dict(whole[rnd] or {}); take.update(patch); whole[rnd] = take
                sub["whole"] = whole
            else:
                items = [list(x or []) for x in (sub.get("items") or [])]
                while len(items) <= index:
                    items.append([])
                row = items[index]
                while len(row) <= rnd:
                    row.append(None)
                take = dict(row[rnd] or {}); take.update(patch); row[rnd] = take
                items[index] = row
                sub["items"] = items
            subs[aid] = sub
            save_student_subs(sid, subs)
    except Exception as e:
        print("[score-take] 저장 실패:", str(e)[:150])


@app.post("/api/score-take/{assignment_id}/{student_id}")
async def score_take(assignment_id: str, student_id: str, background: BackgroundTasks,
                     audio: UploadFile = File(...), text: str = Form(...),
                     round: int = Form(0), mode: str = Form("whole"), index: int = Form(0)):
    """오래 걸리는 채점(통문장 등)을 백그라운드로 돌린다. 즉시 반환하고, 끝나면
    그 학생 제출의 whole[round](또는 items[index][round]) take 에 점수를 써넣는다."""
    if not AZURE_KEY:
        raise HTTPException(500, "서버에 AZURE_SPEECH_KEY가 설정되어 있지 않아요.")
    raw_bytes = await audio.read()
    if not raw_bytes:
        raise HTTPException(400, "오디오가 비어 있어요.")
    background.add_task(_score_take_bg, assignment_id, student_id, raw_bytes, text,
                        int(round), (mode or "whole"), int(index))
    return {"ok": True, "scoring": True}


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
    recording_ms = []
    recording_attempts = 0

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
                recording_attempts += 1
                if t.get("durationMs") is not None:
                    try:
                        recording_ms.append(max(0, int(t.get("durationMs"))))
                    except Exception:
                        pass
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
        "time": {
            "recordingSeconds": round(sum(recording_ms) / 1000) if recording_ms else None,
            "averageRecordingSeconds": round(sum(recording_ms) / len(recording_ms) / 1000, 1) if recording_ms else None,
            "recordingAttempts": recording_attempts,
        },
        "submittedCount": submitted_count,
        "totalAssigned": total_assigned,
        "assignments": rows,
        "weekly": weekly_list,
        "daily": daily_list,
        "weakWords": [{"word": w, "accuracy": a} for w, a in sorted(weak_words.items(), key=lambda x: x[1])[:8]],
        "vocab": vocab_summary,
        "summary": " ".join(lines),
    }


@app.get("/api/diag", dependencies=ADMIN_ONLY)
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
    is_noscore = mode in ("flash", "smeaning")   # 점수 없이 '했음'만 기록하는 모드(카드암기·문장 뜻확인)
    correct = max(0, int(payload.get("correct") or 0))
    total = int(payload.get("total") or 0)
    score = 0
    if not is_noscore:
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
        _prev_keys = set(by.keys())
        if is_noscore:
            bm = by.get(mode) or {"attempts": 0}
            bm["attempts"] = bm.get("attempts", 0) + 1
            bm["done"] = True
            bm["last"] = {"at": now}
            by[mode] = bm
            rec["last"] = {"mode": mode, "at": now}
        else:
            rec["best"] = max(rec.get("best", 0), score)
            rec["last"] = {"mode": mode, "correct": correct, "total": total, "score": score, "at": now}
            bm = by.get(mode) or {"attempts": 0, "best": 0}
            bm["attempts"] = bm.get("attempts", 0) + 1
            bm["best"] = max(bm.get("best", 0), score)
            bm["last"] = {"correct": correct, "total": total, "score": score, "at": now}
            by[mode] = bm
        rec["byMode"] = by
        # 자습 완료(단계 50%↑) 새로 도달 시 트리톡 알림 트리거
        _adb = load_db()
        _a = next((x for x in _adb.get("assignments", []) if x.get("id") == assignment_id), None)
        _stg = ["smeaning", "unscramble"] if (_a or {}).get("type", "word") == "sentence" else ["flash", "choice", "spell", "test"]
        _fire_study = (sum(1 for s in _stg if s in _prev_keys) / len(_stg)) < 0.5 <= (sum(1 for s in _stg if s in by) / len(_stg))
        complete = VOCAB_STAGES.issubset(set(by.keys()))
        rec["complete"] = complete
        if complete and not rec.get("completedAt"):
            rec["completedAt"] = now
        data[assignment_id] = rec
        save_vocab(student_id, data)
    if _fire_study:
        try:
            _notify_treetalk(student_id, lesson=(_a or {}).get("title", ""))   # 자습 완료 → 담당쌤(학년별)+원장께
        except Exception as e:
            print("[treetalk] 자습 알림 실패:", e)
    return rec


@app.get("/api/vocab/{student_id}")
def get_vocab(student_id: str):
    """한 학생의 단어 자습 기록 전체 {assignment_id: record}."""
    return load_vocab(student_id)


@app.get("/api/vocab-all", dependencies=ADMIN_ONLY)
def get_vocab_all():
    """선생님 대시보드용: 모든 학생의 단어 자습 기록 {student_id: {aid: record}}."""
    return {sid: load_vocab(sid) for sid in all_vocab_student_ids()}


# ---------- 권말 진급 시험: 응시·채점·성적표(백분위+시간, 전체/동학년) ----------
EXAM_BANDS = [(4, 1), (11, 2), (23, 3), (40, 4), (60, 5), (77, 6), (89, 7), (96, 8), (100, 9)]


def _band_of(top_pct: int) -> int:
    for cut, g in EXAM_BANDS:
        if top_pct <= cut:
            return g
    return 9


def _top_percent(values, my, higher_is_better=True):
    """상위 몇 %인지. higher_is_better=True면 값이 클수록 상위(점수),
    False면 값이 작을수록 상위(시간). 본인 포함 모집단 기준."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n <= 0:
        return None
    if higher_is_better:
        better = sum(1 for v in vals if v > my)
    else:
        better = sum(1 for v in vals if v < my)
    return max(1, math.ceil((better + 1) / n * 100))


def _fmt_secs(s):
    try:
        s = int(round(s))
    except Exception:
        return "-"
    return f"{s//60}분 {s%60}초" if s >= 60 else f"{s}초"


@app.post("/api/exam/{assignment_id}/{student_id}")
def submit_exam(assignment_id: str, student_id: str, payload: dict = Body(...)):
    """권말 진급 시험 결과 저장. body: {correct, total, seconds, byType:{choice,write,clozeWrite,clozeChoice}}
    최고 점수를 보관하고, 동점이면 더 짧은 시간을 보관한다."""
    correct = max(0, int(payload.get("correct") or 0))
    total = int(payload.get("total") or 0)
    if total <= 0:
        raise HTTPException(400, "문항 수가 없어요.")
    correct = min(correct, total)
    score = round(correct * 100 / total)
    seconds = max(0, int(payload.get("seconds") or 0))
    by_type = payload.get("byType") or {}
    now = _now_kr()
    with _sub_lock(student_id):
        data = load_exam(student_id)
        rec = data.get(assignment_id) or {"attempts": 0, "best": None, "bestSeconds": None}
        rec["attempts"] = rec.get("attempts", 0) + 1
        rec["last"] = {"score": score, "correct": correct, "total": total, "seconds": seconds, "byType": by_type, "at": now}
        prev = rec.get("best")
        # 최고점 갱신(동점이면 더 빠른 시간)
        if prev is None or score > prev or (score == prev and (rec.get("bestSeconds") is None or seconds < rec["bestSeconds"])):
            rec["best"] = score
            rec["bestSeconds"] = seconds
            rec["bestByType"] = by_type
            rec["bestAt"] = now
        data[assignment_id] = rec
        save_exam(student_id, data)
    return rec


def _exam_population(assignment_id: str):
    """이 시험을 친 모든 학생의 (grade, best, bestSeconds) 목록."""
    db = load_db()
    gmap = {str(s.get("id")): str(s.get("grade") or "") for s in db.get("students", [])}
    out = []
    for sid in all_exam_student_ids():
        rec = (load_exam(sid) or {}).get(assignment_id)
        if not rec or rec.get("best") is None:
            continue
        out.append({"sid": sid, "grade": gmap.get(sid, ""), "score": rec.get("best"),
                    "seconds": rec.get("bestSeconds")})
    return out


@app.get("/api/exam-report/{assignment_id}/{student_id}")
def exam_report(assignment_id: str, student_id: str):
    """한 학생의 성적표: 점수·시간을 전체(학년혼합)와 동학년 대비 백분위/평균으로."""
    rec = (load_exam(student_id) or {}).get(assignment_id)
    if not rec or rec.get("best") is None:
        raise HTTPException(404, "아직 이 시험 기록이 없어요.")
    db = load_db()
    student = next((s for s in db.get("students", []) if str(s.get("id")) == str(student_id)), None)
    grade = str((student or {}).get("grade") or "")
    a = next((x for x in db.get("assignments", []) if x.get("id") == assignment_id), None)
    pass_score = int((a or {}).get("passScore") or 70)
    pop = _exam_population(assignment_id)
    all_scores = [p["score"] for p in pop]
    all_secs = [p["seconds"] for p in pop if p.get("seconds") is not None]
    gr_pop = [p for p in pop if p["grade"] == grade] if grade else []
    gr_scores = [p["score"] for p in gr_pop]
    gr_secs = [p["seconds"] for p in gr_pop if p.get("seconds") is not None]

    my_score = rec["best"]
    my_secs = rec.get("bestSeconds")

    def avg(xs):
        return round(sum(xs) / len(xs)) if xs else None

    top_all = _top_percent(all_scores, my_score, True)
    top_gr = _top_percent(gr_scores, my_score, True) if gr_scores else None
    time_top_all = _top_percent(all_secs, my_secs, False) if (my_secs is not None and all_secs) else None
    time_top_gr = _top_percent(gr_secs, my_secs, False) if (my_secs is not None and gr_secs) else None

    return {
        "score": my_score,
        "seconds": my_secs,
        "secondsText": _fmt_secs(my_secs) if my_secs is not None else None,
        "byType": rec.get("bestByType") or {},
        "grade": grade,
        "passScore": pass_score,
        "pass": my_score >= pass_score,
        "band": _band_of(top_all) if top_all else None,
        "score_all": {"top": top_all, "n": len(all_scores), "avg": avg(all_scores)},
        "score_grade": {"top": top_gr, "n": len(gr_scores), "avg": avg(gr_scores)},
        "time_all": {"top": time_top_all, "n": len(all_secs), "avg": avg(all_secs), "avgText": _fmt_secs(avg(all_secs)) if all_secs else None},
        "time_grade": {"top": time_top_gr, "n": len(gr_secs), "avg": avg(gr_secs), "avgText": _fmt_secs(avg(gr_secs)) if gr_secs else None},
        "attempts": rec.get("attempts", 1),
    }


@app.get("/api/exam-all", dependencies=ADMIN_ONLY)
def exam_all():
    """선생님 대시보드용: 모든 학생의 권말 시험 기록 {student_id: {aid: record}}."""
    return {sid: load_exam(sid) for sid in all_exam_student_ids()}


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


@app.get("/api/activity-all", dependencies=ADMIN_ONLY)
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
@app.get("/api/backup", dependencies=ADMIN_ONLY)
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


@app.post("/api/restore", dependencies=ADMIN_ONLY)
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
