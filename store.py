"""
트리톡 저장소 — 파일(Render 디스크) ↔ D1 전환 계층
======================================================================
왜 필요한가
----------
트리톡은 상태를 전부 Render 인스턴스의 디스크에 들고 있다(db.json + 학생별 JSON 파일).
그래서 두 가지가 막혀 있다.

  1) 서버를 한 대밖에 못 띄운다. 디스크가 그 인스턴스에 붙어 있어서, 학생이 늘어도
     인스턴스를 늘려 나눠 받을 수가 없다. 동시접속의 진짜 천장은 여기다.
  2) 동기 라우트 42개가 FastAPI 스레드풀에서 같은 파일을 락 없이 읽고-고쳐-쓴다.
     두 요청이 겹치면 나중 것이 앞 것을 덮어써서 기록이 조용히 사라진다.

이 파일은 저장소를 밖(D1)으로 빼서 둘 다 푼다. 앱 코드의 호출 모양
(load_X(sid) / save_X(sid, data) / all_X_ids())은 그대로 두었다.

전환 사다리 (환경변수 TT_STORE)
------------------------------
  file    지금까지와 똑같다. 파일만 쓴다.                        ← 기본값
  mirror  파일이 원본이고, D1 에도 같이 써 둔다. 위험 0.
  d1      D1 이 원본이다. 파일은 비상용 사본으로만 남는다.        ← 인스턴스를 늘릴 수 있는 지점

  ★mirror 로 며칠 → backfill_treetalk.py 로 옛 기록 옮기기 → d1
  ★d1 로 올리기 전에는 절대 인스턴스를 늘리지 마라(파일이 원본인 동안은 한 대여야 한다).

환경변수
--------
  TT_STORE    file | mirror | d1        (기본 file)
  TT_API      Worker 의 /tt 주소
  TT_KEY      Worker 에 넣어 둔 공유키 (wrangler secret put TT_KEY)
  TT_ACADEMY  학원 구분 (기본 happytree) — 나중에 학원이 늘 때 쓴다
"""

import json
import os
import threading
from pathlib import Path

import httpx

MODE = os.environ.get("TT_STORE", "file").strip().lower()
API = os.environ.get("TT_API", "https://happytree-math-proxy.white21040.workers.dev/tt").strip()
KEY = os.environ.get("TT_KEY", "").strip()
ACADEMY = os.environ.get("TT_ACADEMY", "happytree").strip() or "happytree"

_client = httpx.Client(timeout=8.0)

# 파일을 읽고-고쳐-쓰는 동안 다른 스레드가 끼어들지 못하게 한다.
# (동기 라우트는 스레드풀에서 진짜로 동시에 돈다 — 여태 이 자물쇠가 없었다.)
LOCK = threading.RLock()

_warned = set()


def _warn(tag: str, msg: str):
    """같은 경고로 로그를 도배하지 않는다."""
    if tag in _warned:
        return
    _warned.add(tag)
    print(f"[store] {tag}: {msg}")


def _remote(op: str, **kw):
    """Worker 의 /tt 창구를 부른다. 실패하면 None."""
    if not KEY:
        _warn("nokey", "TT_KEY 가 비어 있다 — 원격 저장소를 못 쓴다")
        return None
    body = {"op": op, "academy": ACADEMY}
    body.update(kw)
    try:
        r = _client.post(API, json=body, headers={"x-ht-key": KEY})
        j = r.json()
        if not j.get("ok"):
            print(f"[store] 원격 실패 {op}: {j.get('msg')}")
            return None
        return j
    except Exception as e:
        print(f"[store] 원격 오류 {op}: {e}")
        return None


# ── 파일 계층 ────────────────────────────────────────────────────
def _read_file(path: Path, default):
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))


def _write_file(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


# ── 학생별 저장소 (subs / vocab / exam / activity / push) ─────────
def get(kind: str, sid: str, path: Path, default):
    """한 학생의 기록을 읽는다."""
    with LOCK:
        if MODE == "d1":
            j = _remote("get", kind=kind, sid=sid)
            if j is not None:
                data = j.get("data")
                return json.loads(json.dumps(default)) if data is None else data
            # 원격이 흔들리면 앱을 멈추는 대신 디스크 사본으로 버틴다(옛 값일 수 있다).
            _warn(f"fallback:{kind}", "원격 조회 실패 → 디스크 사본으로 응답")
        return _read_file(path, default)


def put(kind: str, sid: str, path: Path, data):
    """한 학생의 기록을 쓴다."""
    with LOCK:
        if MODE == "file":
            _write_file(path, data)
            return
        j = _remote("put", kind=kind, sid=sid, data=data)
        if MODE == "mirror":
            _write_file(path, data)          # 파일이 원본 — 원격 실패해도 손실 없음
            return
        # MODE == "d1": D1 이 원본. 그래도 디스크에 사본을 남겨 둔다.
        # 원격이 실패했는데 사본까지 없으면 학생이 방금 한 학습이 그냥 사라진다.
        _write_file(path, data)
        if j is None:
            print(f"[store] ★원격 쓰기 실패 {kind}/{sid} — 디스크 사본만 남았다. 복구 필요")


def ids(kind: str, directory: Path) -> list:
    """그 저장소에 기록이 있는 학생 아이디 전부."""
    with LOCK:
        if MODE == "d1":
            j = _remote("ids", kind=kind)
            if j is not None:
                return list(j.get("ids") or [])
            _warn(f"fallback-ids:{kind}", "원격 목록 실패 → 디스크 목록으로 응답")
        if not directory.exists():
            return []
        return [p.stem for p in directory.glob("*.json")]


def mget(kind: str, directory: Path, default, sids=None) -> dict:
    """여러 학생을 한 번에 읽는다(관리자 대시보드용).
    파일 모드에서는 한 명씩 읽는 것과 같지만, D1 모드에서는 왕복이 1번으로 줄어든다."""
    with LOCK:
        if MODE == "d1":
            j = _remote("mget", kind=kind, sids=list(sids) if sids else None)
            if j is not None:
                return j.get("map") or {}
            _warn(f"fallback-mget:{kind}", "원격 일괄조회 실패 → 디스크로 응답")
        out = {}
        target = list(sids) if sids else ([p.stem for p in directory.glob("*.json")] if directory.exists() else [])
        for sid in target:
            out[sid] = _read_file(directory / f"{sid}.json", default)
        return out


# ── 전역 저장소 (db.json 의 students / assignments) ───────────────
DB_DEFAULT = {"students": [], "assignments": [], "submissions": {}}


def load_db(path: Path) -> dict:
    with LOCK:
        if MODE == "d1":
            s = _remote("gget", k="students")
            a = _remote("gget", k="assignments")
            if s is not None and a is not None:
                return {
                    "students": s.get("data") or [],
                    "assignments": a.get("data") or [],
                    "submissions": {},
                }
            _warn("fallback:db", "원격 db 조회 실패 → 디스크 사본으로 응답")
        db = _read_file(path, DB_DEFAULT)
        for k, v in DB_DEFAULT.items():
            db.setdefault(k, json.loads(json.dumps(v)))
        return db


def save_db(path: Path, db: dict):
    with LOCK:
        if MODE == "file":
            _write_file(path, db)
            return
        s = _remote("gput", k="students", data=db.get("students") or [])
        a = _remote("gput", k="assignments", data=db.get("assignments") or [])
        _write_file(path, db)
        if MODE == "d1" and (s is None or a is None):
            print("[store] ★원격 db 쓰기 실패 — 디스크 사본만 남았다. 복구 필요")


def info() -> dict:
    """/api/health 같은 데서 지금 어느 모드인지 확인용."""
    return {"mode": MODE, "api": API, "keyed": bool(KEY), "academy": ACADEMY}
