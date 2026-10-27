"""
영어 레벨테스트 (4영역) — 트리톡 서버에 붙은 별채
======================================================================
왜 여기 있나 (2026-10-27, 원장)
  레벨테스트는 claude.ai 아티팩트였다. 듣기·말하기를 넣으려니 두 가지가 막혔다.
    · 아티팩트는 마이크를 못 쓴다 → 말하기 녹음 불가
    · 아티팩트는 바깥 서버로 요청을 못 보낸다 → 발음 채점 불가
  Azure 키와 발음 채점은 이미 이 서버에 있다. 그래서 시험 화면(static/leveltest.html)과
  필요한 API 를 이 서버로 옮겼다. 기존 숙제 기능과는 경로(/api/lt/…)도 저장 폴더도 따로다.

경로
  GET  /api/lt/audio/{item_id}.mp3   듣기 음성. 처음 한 번 Azure 로 만들고 디스크에 둔다.
  POST /api/lt/prewarm               (관리자) 듣기 음성을 전부 미리 만든다.
  POST /api/lt/result                시험 결과 저장(이름 포함, 관리자만 다시 봄).
  GET  /api/lt/peers                 또래 견주기용 — 이름 없이 숫자만.
  GET  /api/lt/results               (관리자) 결과 전체.
  POST /api/lt/grade/{rid}           (관리자) 선생님 채점(쓰기 등)을 결과에 붙인다.

듣기 문항 원본: leveltest_listen.json (영어레벨테스트/ 에서 빌드해 복사해 온다).
"""
import hashlib
import json
import time
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

LISTEN_FILE = Path(__file__).parent / "leveltest_listen.json"

# 말하는 사람 → Azure 목소리. 아이 목소리는 Ana 하나뿐이라 남자아이는 젊은 성인 남자 목소리로 둔다.
VOICES = {
    "G": "en-US-AnaNeural",          # 여자아이
    "B": "en-US-ChristopherNeural",  # 남자아이(대역)
    "W": "en-US-JennyNeural",        # 성인 여자
    "M": "en-US-GuyNeural",          # 성인 남자
    "N": "en-US-AriaNeural",         # 안내·해설
}

_MAX_RESULT_BYTES = 200_000


def _load_listen():
    try:
        rows = json.loads(LISTEN_FILE.read_text(encoding="utf-8"))
        return {r["id"]: r for r in rows}
    except Exception as e:
        print("[lt] 듣기 문항을 못 읽었다:", e)
        return {}


def _ssml(item):
    """대본 → SSML. 사람이 바뀔 때마다 목소리를 바꾸고 줄 사이를 조금 띄운다.
    아래 단계(1~3)는 조금 천천히 — 초2~초4 가 듣는다."""
    rate = "-12%" if int(item.get("lv", 9)) <= 3 else "-4%"
    parts = []
    for i, ln in enumerate(item.get("script") or []):
        v = VOICES.get(str(ln.get("sp", "N")).upper(), VOICES["N"])
        gap = '<break time="700ms"/>' if i else ""
        parts.append(f'<voice name="{v}">{gap}<prosody rate="{rate}">{escape(str(ln.get("t", "")))}</prosody></voice>')
    return ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            + "".join(parts) + "</speak>")


def make_router(*, data_dir: Path, azure_key, azure_region, admin_only, is_admin):
    r = APIRouter()
    base = Path(data_dir) / "leveltest"
    audio_dir = base / "audio"
    res_dir = base / "results"
    audio_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)
    listen = {"rows": _load_listen()}

    def _audio_path(item):
        # 대본이 바뀌면 이름이 바뀌어 새로 만든다(옛 파일은 남아도 해가 없다).
        h = hashlib.sha1(json.dumps(item.get("script"), ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
        return audio_dir / f"{item['id']}-{h}.mp3"

    def _synth(item):
        if not azure_key:
            raise HTTPException(503, "서버에 음성 키가 없어 듣기 음성을 만들 수 없어요.")
        import azure.cognitiveservices.speech as speechsdk
        cfg = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3)
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        res = synth.speak_ssml_async(_ssml(item)).get()
        if res.reason != speechsdk.ResultReason.SynthesizingAudioCompleted or not res.audio_data:
            detail = ""
            try:
                detail = str(res.cancellation_details.error_details or "")
            except Exception:
                pass
            print("[lt] 음성 생성 실패", item.get("id"), detail[:200])
            raise HTTPException(502, "듣기 음성을 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.")
        return res.audio_data

    def _get_audio(item_id):
        item = listen["rows"].get(item_id)
        if not item:
            raise HTTPException(404, "없는 문항이에요.")
        p = _audio_path(item)
        if not p.exists():
            data = _synth(item)
            tmp = p.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(p)
        return p

    @r.get("/api/lt/audio/{item_id}.mp3")
    def lt_audio(item_id: str):
        p = _get_audio(item_id)
        # 같은 문항 음성은 바뀌지 않는 한 그대로다 — 하루 들고 있어도 된다.
        return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})

    @r.post("/api/lt/prewarm", dependencies=admin_only)
    def lt_prewarm():
        listen["rows"] = _load_listen()
        made, have, fail = 0, 0, []
        for iid, item in listen["rows"].items():
            if _audio_path(item).exists():
                have += 1
                continue
            try:
                _get_audio(iid)
                made += 1
            except HTTPException:
                fail.append(iid)
        return {"items": len(listen["rows"]), "made": made, "already": have, "failed": fail}

    @r.post("/api/lt/result")
    async def lt_result(request: Request):
        raw = await request.body()
        if not raw or len(raw) > _MAX_RESULT_BYTES:
            raise HTTPException(413, "결과가 너무 커요.")
        try:
            rec = json.loads(raw)
            assert isinstance(rec, dict)
        except Exception:
            raise HTTPException(400, "결과 형식이 아니에요.")
        rid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        rec["rid"] = rid
        rec["savedAt"] = int(time.time())
        (res_dir / f"{rid}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "rid": rid}

    def _all_results():
        out = []
        for p in sorted(res_dir.glob("*.json"), reverse=True)[:2000]:
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return out

    # 또래 견주기 — 이름·답안 없이 판정 숫자만 내보낸다.
    PEER_KEYS = ("grade", "m", "v", "g", "r", "h", "s", "w", "ok", "n", "med")

    @r.get("/api/lt/peers")
    def lt_peers():
        rows = []
        for x in _all_results():
            if x.get("test"):
                continue
            rows.append({k: x.get(k) for k in PEER_KEYS})
        return {"rows": rows}

    @r.get("/api/lt/results", dependencies=admin_only)
    def lt_results():
        return {"rows": _all_results()}

    @r.post("/api/lt/grade/{rid}", dependencies=admin_only)
    def lt_grade(rid: str, payload: dict = Body(...)):
        if not rid.replace("-", "").isalnum():
            raise HTTPException(404, "not found")
        p = res_dir / f"{rid}.json"
        if not p.exists():
            raise HTTPException(404, "결과를 찾을 수 없어요.")
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec.setdefault("teacher", {}).update(payload or {})
        rec["teacher"]["at"] = int(time.time())
        p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "teacher": rec["teacher"]}

    return r
