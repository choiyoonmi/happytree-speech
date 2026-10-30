"""파닉스 Lv1(트리톡) — 화면은 static/phonics.html, 성적표는 static/phonics-report.html.

유치부·초1이 알파벳부터 시작한다. 순서: 알파벳 → 단모음 → 장모음 → 이중자음 → 이중모음 → 총복습.
지금은 알파벳(LV1 1권) 26자 · 하루 3글자 · 9일 + 권말 진급시험이 들어 있다.

과제: 보관함에 'LV1 1권' 이름으로 Day 1~9(type=phonics) + 진급시험(type=exam, kind=phonics)을
서버가 처음 뜰 때 넣어 둔다(관리자 열쇠 없이도 원본이 생기게). 선생님이 보관함에서 배정하면 끝.
책 이름이 LV 규칙(^LV\\d+ \\d+권$)을 따르므로 마지막 Day 를 끝내면 진급시험이 저절로 열린다
(app.py _maybe_open_exam). 기록은 제출(submission)의 'phonics' 칸, 시험은 /api/exam 에 그대로 쌓인다.

음원: 글자 소리(/æ/ 같은 것)는 브라우저 음성으로는 못 낸다 → Azure TTS 의 SSML <phoneme> 으로
한 번만 만들어 디스크에 둔다(원장 승인 2026-10-30). **아래 AUDIO 에 적힌 것만** 만든다 —
아무 글자나 받아 합성하면 바깥에서 요금을 태울 수 있어서다.

채점: 단어 하나 녹음은 유창성·완성도가 의미 없고, 발음 약한 아이는 정확히 읽어도 Azure 가
그 둘을 0 으로 줘서 한 자릿수가 나온다(reference_treetalk_word_pa_crush). 그래서 여기선
max(종합, 정확도) 를 쓰고, 소리(음소)별 점수를 같이 돌려 '첫소리 신호등'에 쓴다.
"""
import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

VOICE = "en-US-JennyNeural"
BOOK = "LV1 1권"
BOOK_NAME = "알파벳"

# ipa: SSML 에 넣는 소리(화면엔 안 보임), ko: 아이에게 보여 주는 한글 소리(원장 표기 2026-10-30), words: [단어, 뜻, 그림(emoji)] — 글자마다 5개(원장 2026-10-30)
# pos='end' 는 그 소리가 단어 끝에 있는 글자(x) — 첫소리 문제에서 뺀다.
LETTERS = {
    "a": {"ipa": "æ",  "ko": "애아", "words": [["apple", "사과", "🍎"], ["ant", "개미", "🐜"], ["alligator", "악어", "🐊"], ["ambulance", "구급차", "🚑"], ["astronaut", "우주비행사", "🧑‍🚀"]]},
    "b": {"ipa": "b",  "ko": "ㅂ", "words": [["ball", "공", "⚽"], ["bear", "곰", "🐻"], ["bus", "버스", "🚌"], ["banana", "바나나", "🍌"], ["bird", "새", "🐦"]]},
    "c": {"ipa": "k",  "ko": "ㅋ", "words": [["cat", "고양이", "🐱"], ["car", "자동차", "🚗"], ["cake", "케이크", "🎂"], ["cow", "소", "🐄"], ["carrot", "당근", "🥕"]]},
    "d": {"ipa": "d",  "ko": "ㄷ", "words": [["dog", "개", "🐶"], ["duck", "오리", "🦆"], ["door", "문", "🚪"], ["dinosaur", "공룡", "🦕"], ["dolphin", "돌고래", "🐬"]]},
    "e": {"ipa": "ɛ",  "ko": "에", "words": [["egg", "달걀", "🥚"], ["elephant", "코끼리", "🐘"], ["elf", "요정", "🧝"], ["envelope", "봉투", "✉️"], ["elevator", "엘리베이터", "🛗"]]},
    "f": {"ipa": "f",  "ko": "ㅍ", "words": [["fish", "물고기", "🐟"], ["fork", "포크", "🍴"], ["feather", "깃털", "🪶"], ["fire", "불", "🔥"], ["foot", "발", "🦶"]]},
    "g": {"ipa": "ɡ",  "ko": "ㄱ", "words": [["goat", "염소", "🐐"], ["gift", "선물", "🎁"], ["gorilla", "고릴라", "🦍"], ["guitar", "기타", "🎸"], ["goose", "거위", "🪿"]]},
    "h": {"ipa": "h",  "ko": "ㅎ", "words": [["hat", "모자", "🎩"], ["horse", "말", "🐴"], ["house", "집", "🏠"], ["hippo", "하마", "🦛"], ["hamburger", "햄버거", "🍔"]]},
    "i": {"ipa": "ɪ",  "ko": "이", "words": [["insect", "곤충", "🐞"], ["iguana", "이구아나", "🦎"], ["ink", "잉크", "🖋️"], ["inchworm", "자벌레", "🐛"], ["ill", "아픈", "🤒"]]},
    "j": {"ipa": "dʒ", "ko": "ㅈ", "words": [["juice", "주스", "🧃"], ["jellyfish", "해파리", "🪼"], ["jet", "제트기", "✈️"], ["jeans", "청바지", "👖"], ["jacket", "재킷", "🧥"]]},
    "k": {"ipa": "k",  "ko": "ㅋ", "words": [["kite", "연", "🪁"], ["king", "왕", "🤴"], ["key", "열쇠", "🔑"], ["kangaroo", "캥거루", "🦘"], ["koala", "코알라", "🐨"]]},
    "l": {"ipa": "l",  "ko": "을ㄹ", "words": [["lion", "사자", "🦁"], ["lemon", "레몬", "🍋"], ["leaf", "나뭇잎", "🍃"], ["leg", "다리", "🦵"], ["lollipop", "막대사탕", "🍭"]]},
    "m": {"ipa": "m",  "ko": "음ㅁ", "words": [["monkey", "원숭이", "🐵"], ["moon", "달", "🌙"], ["milk", "우유", "🥛"], ["mouse", "생쥐", "🐭"], ["mango", "망고", "🥭"]]},
    "n": {"ipa": "n",  "ko": "은ㄴ", "words": [["nose", "코", "👃"], ["nest", "둥지", "🪺"], ["nut", "견과", "🥜"], ["nine", "아홉", "9️⃣"], ["noodles", "국수", "🍜"]]},
    "o": {"ipa": "ɑ",  "ko": "아", "words": [["octopus", "문어", "🐙"], ["ox", "황소", "🐂"], ["otter", "수달", "🦦"], ["olive", "올리브", "🫒"], ["octagon", "팔각형", "🛑"]]},
    "p": {"ipa": "p",  "ko": "ㅍ", "words": [["pig", "돼지", "🐷"], ["pizza", "피자", "🍕"], ["pen", "펜", "🖊️"], ["panda", "판다", "🐼"], ["penguin", "펭귄", "🐧"]]},
    "q": {"ipa": "kw", "ko": "워", "words": [["queen", "여왕", "👸"], ["question", "질문", "❓"], ["quack", "꽥꽥", "🦆"], ["quiet", "조용히", "🤫"], ["quarter", "25센트 동전", "🪙"]]},
    "r": {"ipa": "ɹ",  "ko": "얼ㄹ", "words": [["rabbit", "토끼", "🐰"], ["robot", "로봇", "🤖"], ["ring", "반지", "💍"], ["rainbow", "무지개", "🌈"], ["rocket", "로켓", "🚀"]]},
    "s": {"ipa": "s",  "ko": "ㅅ", "words": [["sun", "해", "☀️"], ["sock", "양말", "🧦"], ["seal", "물개", "🦭"], ["snake", "뱀", "🐍"], ["sandwich", "샌드위치", "🥪"]]},
    "t": {"ipa": "t",  "ko": "ㅌ", "words": [["tiger", "호랑이", "🐯"], ["tomato", "토마토", "🍅"], ["tent", "텐트", "⛺"], ["turtle", "거북", "🐢"], ["tooth", "이", "🦷"]]},
    "u": {"ipa": "ʌ",  "ko": "어", "words": [["umbrella", "우산", "☂️"], ["up", "위로", "⬆️"], ["underwear", "속옷", "🩲"], ["uncle", "삼촌", "👨"], ["upset", "속상한", "😣"]]},
    "v": {"ipa": "v",  "ko": "ㅂ", "words": [["van", "승합차", "🚐"], ["violin", "바이올린", "🎻"], ["volcano", "화산", "🌋"], ["vest", "조끼", "🦺"], ["vase", "꽃병", "🏺"]]},
    "w": {"ipa": "w",  "ko": "우워", "words": [["worm", "지렁이", "🪱"], ["web", "거미줄", "🕸️"], ["watch", "손목시계", "⌚"], ["wolf", "늑대", "🐺"], ["watermelon", "수박", "🍉"]]},
    "x": {"ipa": "ks", "ko": "ㅋㅅ", "pos": "end", "words": [["box", "상자", "📦"], ["fox", "여우", "🦊"], ["six", "여섯", "6️⃣"], ["ax", "도끼", "🪓"], ["taxi", "택시", "🚕"]]},
    "y": {"ipa": "j",  "ko": "이여", "words": [["yo-yo", "요요", "🪀"], ["yarn", "털실", "🧶"], ["yawn", "하품", "🥱"], ["yellow", "노란색", "🟡"], ["yes", "네", "🙆"]]},
    "z": {"ipa": "z",  "ko": "ㅈ", "words": [["zebra", "얼룩말", "🦓"], ["zero", "영", "0️⃣"], ["zombie", "좀비", "🧟"], ["zipper", "지퍼", "🤐"], ["zucchini", "애호박", "🥒"]]},
}
for _k, _L in LETTERS.items():
    _L["key"] = _L["words"][0][0]

# 하루 3글자(원장 2026-10-30). 26자 → 9일, 마지막 날은 2글자.
_ORDER = list("abcdefghijklmnopqrstuvwxyz")
DAYS = [{"day": i + 1, "letters": _ORDER[i * 3:i * 3 + 3]} for i in range(9)]


# ── LV1 2권 단모음 ── 하루 = 모음 하나의 단어가족 3개(원장 2026-10-30 '가족별 3개씩 묶기'), 5일.
#   인쇄본(단어급수교재/phonics_builder.py SHORT)의 가족 그대로, 그림 못 그리는 단어(led·not·win…)만 바꿈.
BOOK2 = "LV1 2권"
BOOK2_NAME = "단모음"
VOWEL_KEY = {"a": "apple", "e": "egg", "i": "insect", "o": "octopus", "u": "umbrella"}
SHORT = [
    {"day": 1, "vowel": "a", "families": [
        {"name": "-at", "words": [["cat", "고양이", "🐱"], ["hat", "모자", "🎩"], ["bat", "박쥐", "🦇"], ["rat", "쥐", "🐀"]]},
        {"name": "-an", "words": [["man", "남자", "👨"], ["pan", "프라이팬", "🍳"], ["van", "승합차", "🚐"], ["fan", "부채", "🪭"]]},
        {"name": "-ap · -ag", "words": [["cap", "모자", "🧢"], ["map", "지도", "🗺️"], ["bag", "가방", "👜"], ["tag", "꼬리표", "🏷️"]]}]},
    {"day": 2, "vowel": "e", "families": [
        {"name": "-en", "words": [["hen", "암탉", "🐔"], ["pen", "펜", "🖊️"], ["ten", "열", "🔟"], ["men", "남자들", "👬"]]},
        {"name": "-et", "words": [["net", "그물", "🥅"], ["vet", "수의사", "🩺"], ["jet", "제트기", "✈️"], ["wet", "젖은", "💦"]]},
        {"name": "-ed · -eg", "words": [["bed", "침대", "🛏️"], ["red", "빨강", "🔴"], ["leg", "다리", "🦵"], ["beg", "조르다", "🙏"]]}]},
    {"day": 3, "vowel": "i", "families": [
        {"name": "-ig", "words": [["pig", "돼지", "🐷"], ["big", "큰", "🐘"], ["dig", "파다", "⛏️"], ["wig", "가발", "👩‍🦰"]]},
        {"name": "-in", "words": [["pin", "핀", "📍"], ["fin", "지느러미", "🦈"], ["bin", "쓰레기통", "🗑️"], ["win", "이기다", "🏆"]]},
        {"name": "-it · -ix", "words": [["sit", "앉다", "🪑"], ["hit", "치다", "⚾"], ["six", "여섯", "6️⃣"], ["fix", "고치다", "🔧"]]}]},
    {"day": 4, "vowel": "o", "families": [
        {"name": "-og", "words": [["dog", "개", "🐶"], ["log", "통나무", "🪵"], ["fog", "안개", "🌫️"], ["jog", "조깅하다", "🏃"]]},
        {"name": "-ot", "words": [["hot", "뜨거운", "🔥"], ["pot", "냄비", "🍲"], ["dot", "점", "🔵"], ["cot", "아기 침대", "🛏️"]]},
        {"name": "-op · -ox", "words": [["top", "팽이", "🪀"], ["mop", "대걸레", "🧹"], ["box", "상자", "📦"], ["fox", "여우", "🦊"]]}]},
    {"day": 5, "vowel": "u", "families": [
        {"name": "-un", "words": [["sun", "해", "☀️"], ["run", "달리다", "🏃‍♂️"], ["bun", "빵", "🍞"], ["fun", "재미있는", "🎉"]]},
        {"name": "-ug", "words": [["bug", "벌레", "🐛"], ["hug", "안아 주다", "🤗"], ["mug", "머그컵", "☕"], ["jug", "주전자", "🫖"]]},
        {"name": "-ut · -up", "words": [["nut", "견과", "🥜"], ["cut", "자르다", "✂️"], ["cup", "컵", "🥤"], ["pup", "강아지", "🐕"]]}]},
]
SHORT_WORDS = [w for d in SHORT for f in d["families"] for w in f["words"]]


def _ph(ipa, letter):
    return f'<phoneme alphabet="ipa" ph="{ipa}">{letter}</phoneme>'


def _audio_table():
    """음원 id → SSML 본문. 여기 없는 id 는 만들지 않는다."""
    t = {}
    for k, L in LETTERS.items():
        s = _ph(L["ipa"], k)
        t[f"snd-{k}"] = f'<prosody rate="-25%">{s}</prosody>'
        t[f"name-{k}"] = f"{k.upper()}."
        # 유치부가 따라오게 숨 쉴 틈을 둔다 — 붙여 읽으면 랩처럼 들린다(원장 2026-10-30)
        slow = lambda x: f'<prosody rate="-25%">{x}</prosody>'
        # 쉼: 1초는 너무 떨어지고 0.5초는 '세즈브'로 붙었다 → 0.6~0.7초(원장 2026-10-30)
        t[f"chant-{k}"] = (slow(f"{k.upper()}.") + '<break time="600ms"/>' +
                           slow(f"{k.upper()} says") + '<break time="700ms"/>' +
                           slow(s) + '<break time="600ms"/>' + slow(s) + '<break time="600ms"/>' +
                           slow(s) + '<break time="700ms"/>' + slow(f'{L["key"]}!'))
        for w in L["words"]:
            t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for w in SHORT_WORDS:
        t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for i, ok in enumerate(["Great job!", "Good try!"]):
        t[f"fb-{i}"] = ok
    return t


AUDIO = _audio_table()


def _templates():
    """보관함 원본: Day 1~9 + 진급시험. id 를 고정해 두어 몇 번 떠도 한 벌만 생긴다."""
    rows = []
    for d in DAYS:
        lt = " · ".join(k.upper() for k in d["letters"])
        rows.append({"id": f"phx-lv1-1-d{d['day']:02d}", "title": f"{BOOK} {BOOK_NAME} Day {d['day']} ({lt})",
                     "book": BOOK, "type": "phonics", "phonicsDay": d["day"], "items": d["letters"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-1-exam", "title": f"{BOOK} {BOOK_NAME} 진급시험", "book": BOOK,
                 "type": "exam", "kind": "phonics", "items": _ORDER, "meanings": [], "passScore": 70,
                 "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [], "exampleAudio": [],
                 "recordMode": "each", "published": False})
    for d in SHORT:
        fam = " / ".join(f["name"] for f in d["families"])   # 가족 이름 안에 ' · ' 가 있어 '/' 로 나눈다
        rows.append({"id": f"phx-lv1-2-d{d['day']:02d}", "title": f"{BOOK2} {BOOK2_NAME} Day {d['day']} ({d['vowel']}: {fam})",
                     "book": BOOK2, "type": "phonics", "phonicsDay": d["day"],
                     "items": [w[0] for f in d["families"] for w in f["words"]],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-2-exam", "title": f"{BOOK2} {BOOK2_NAME} 진급시험", "book": BOOK2,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in SHORT_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                 "exampleAudio": [], "recordMode": "each", "published": False})
    return rows


def _mastery(quiz_ok, quiz_n, exam_ok, exam_n, say):
    """글자 하나의 신호등. 시험이 있으면 시험이 우선, 말하기 점수가 낮으면 한 칸 내린다."""
    ok, n = (exam_ok, exam_n) if exam_n else (quiz_ok, quiz_n)
    if not n and say is None:
        return "none"
    r = ok / n if n else 1.0
    lv = "green" if r >= 1 else "yellow" if r >= 0.5 else "red"
    if say is not None and say < 55 and lv == "green":
        lv = "yellow"
    return lv


def make_router(*, data_dir: Path, azure_key, azure_region, run_assessment,
                lock, load_db, save_db, load_db_ro, load_student_subs, load_exam, exam_report):
    r = APIRouter()
    audio_dir = Path(data_dir) / "phonics" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 보관함 원본 넣기(없는 것만). 실패해도 서버는 떠야 한다.
    try:
        with lock:
            db = load_db()
            have = {a.get("id") for a in db["assignments"]}
            new = [a for a in _templates() if a["id"] not in have]
            if new:
                db["assignments"].extend(new)
                save_db(db)
                print(f"[phonics] 보관함에 파닉스 원본 {len(new)}개 넣음")
    except Exception as e:
        print("[phonics] 보관함 원본 넣기 실패:", e)

    def _path(aid):
        # 대본을 고치면 이름이 바뀌어 새로 만든다
        h = hashlib.sha1((VOICE + AUDIO[aid]).encode("utf-8")).hexdigest()[:10]
        return audio_dir / f"{aid}-{h}.mp3"

    def _synth(aid):
        if not azure_key:
            raise HTTPException(503, "서버에 음성 키가 없어요.")
        import azure.cognitiveservices.speech as speechsdk
        cfg = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3)
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        ssml = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
                f'<voice name="{VOICE}">{AUDIO[aid]}</voice></speak>')
        try:
            res = synth.speak_ssml_async(ssml).get()
        finally:
            del synth
            import gc
            gc.collect()
        if res.reason != speechsdk.ResultReason.SynthesizingAudioCompleted or not res.audio_data:
            print("[phonics] 음성 생성 실패", aid)
            raise HTTPException(502, "소리를 만들지 못했어요. 다시 눌러 주세요.")
        return res.audio_data

    @r.get("/api/phonics/content")
    def content():
        # audioVer: 대본이 바뀌면 같이 바뀐다 → 화면이 음원 주소에 ?v= 로 붙여 기기 캐시(하루)에 묻힌 옛 소리를 끊는다
        #   (원장 2026-10-30: 쉼을 고쳤는데도 "또 붙여서 말해" — 태블릿이 어제 받은 노래를 틀고 있었다)
        ver = hashlib.sha1((VOICE + json.dumps(AUDIO, sort_keys=True)).encode("utf-8")).hexdigest()[:8]
        return {"letters": LETTERS, "days": DAYS, "book": BOOK, "bookName": BOOK_NAME, "audioVer": ver,
                "short": {"book": BOOK2, "bookName": BOOK2_NAME, "days": SHORT, "vowelKey": VOWEL_KEY}}

    @r.get("/api/phonics/audio/{aid}.mp3")
    def audio(aid: str):
        if aid not in AUDIO:
            raise HTTPException(404, "없는 소리예요.")
        p = _path(aid)
        if not p.exists():
            tmp = p.with_suffix(".part")
            tmp.write_bytes(_synth(aid))
            tmp.replace(p)
        return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})

    @r.post("/api/phonics/assess")
    async def assess(text: str = Form(...), audio: UploadFile = File(...)):
        if not run_assessment:
            raise HTTPException(503, "채점을 쓸 수 없어요.")
        raw = await audio.read()
        if not raw:
            raise HTTPException(400, "녹음이 비어 있어요.")
        import asyncio
        out = await asyncio.to_thread(run_assessment, raw, text, False, phoneme=True)
        pron, acc = out.get("pronScore"), out.get("accuracyScore")
        if pron is None:
            return {"ok": False, "note": out.get("note") or "잘 안 들렸어요. 다시 해 볼까요?"}
        score = max(pron, acc or 0) if len(text.split()) == 1 else pron
        return {"ok": True, "score": round(score), "words": out.get("words") or []}

    @r.get("/api/phonics/report/{sid}")
    def report(sid: str, book: str = ""):
        """파닉스 성적표: 숙달표(알파벳=글자 26칸, 단모음=단어 60칸·가족별)·영역별·Day 진행·진급시험.
        book 을 안 주면 그 학생이 받은 파닉스 책 중 마지막 권."""
        sid = str(sid)
        db = load_db_ro()
        student = next((s for s in db.get("students", []) if str(s.get("id")) == sid), None)
        mine = lambda a: (a.get("published") is not False and
                          (not a.get("assignedIds") or sid in [str(x) for x in a["assignedIds"]]))
        books = sorted({a.get("book") for a in db["assignments"] if a.get("book") in (BOOK, BOOK2) and mine(a)})
        book = book if book in (BOOK, BOOK2) else (books[-1] if books else BOOK)
        rows = [a for a in db["assignments"] if a.get("book") == book and mine(a)]
        if book == BOOK2:
            keys = [w[0] for w in SHORT_WORDS]
            groups = [{"name": f"{d['vowel']}  {f['name']}", "vowel": d["vowel"], "keys": [w[0] for w in f["words"]]}
                      for d in SHORT for f in d["families"]]
            info = {w[0]: {"ko": w[1], "emoji": w[2]} for w in SHORT_WORDS}
        else:
            keys, groups, info = _ORDER, None, {}
        # 선생님이 보관함에서 배정하면 복사본이라 phonicsDay 가 없다 → 제목의 'Day N' 으로
        dno = lambda a: a.get("phonicsDay") or int((re.search(r"Day\s*0*(\d+)", a.get("title") or "") or [0, 0])[1])
        days = sorted([a for a in rows if a.get("type") == "phonics"], key=dno)
        exam = next((a for a in rows if a.get("type") == "exam" and a.get("kind") == "phonics"), None)
        subs = load_student_subs(sid) or {}

        L = {k: {"qok": 0, "qn": 0, "eok": 0, "en": 0, "say": [], "takes": []} for k in keys}
        areas = {}
        day_rows = []
        for a in days:
            s = subs.get(a["id"]) or {}
            ph = s.get("phonics") or {}
            q = ph.get("quiz") or {}
            for k, v in (q.get("letters") or {}).items():
                if k in L:
                    L[k]["qok"] += int(v.get("ok") or 0); L[k]["qn"] += int(v.get("n") or 0)
            for t, v in (q.get("byType") or {}).items():
                ar = areas.setdefault(t, {"ok": 0, "n": 0})
                ar["ok"] += int(v.get("ok") or 0); ar["n"] += int(v.get("n") or 0)
            for w, tk in (ph.get("takes") or {}).items():
                k = (tk or {}).get("k")
                if k in L and tk.get("score") is not None:
                    L[k]["say"].append(tk["score"])
                    L[k]["takes"].append({"word": w, "score": tk["score"], "url": tk.get("url"), "at": tk.get("at")})
            day_rows.append({"id": a["id"], "day": dno(a) or None, "title": a.get("title"),
                             "letters": a.get("items"), "dueDate": a.get("dueDate"),
                             "done": bool(s.get("completedAt")), "doneAt": s.get("completedAt"),
                             "quiz": q.get("score"), "steps": len(ph.get("done") or {}),
                             "chart": ph.get("chart")})   # 복습 소리표 녹음 {url, at, n, mode, sec}

        exam_out = None
        if exam:
            rec = (load_exam(sid) or {}).get(exam["id"])
            if rec and rec.get("best") is not None:
                for k, v in ((rec.get("bestByType") or {}).get("_letters") or {}).items():
                    if k in L:
                        L[k]["eok"] += int(v.get("ok") or 0); L[k]["en"] += int(v.get("n") or 0)
                for t, v in (rec.get("bestByType") or {}).items():
                    if t.startswith("_"):
                        continue
                    ar = areas.setdefault(t, {"ok": 0, "n": 0})
                    ar["ok"] += int(v.get("ok") or 0); ar["n"] += int(v.get("n") or 0)
                try:
                    exam_out = exam_report(exam["id"], sid)
                except Exception:
                    exam_out = {"score": rec.get("best")}
            exam_out = {"id": exam["id"], "title": exam.get("title"), "report": exam_out}

        letters = {}
        for k, v in L.items():
            say = round(sum(v["say"]) / len(v["say"])) if v["say"] else None
            letters[k] = {"level": _mastery(v["qok"], v["qn"], v["eok"], v["en"], say), "say": say,
                          "quiz": [v["qok"], v["qn"]], "exam": [v["eok"], v["en"]],
                          "takes": sorted(v["takes"], key=lambda t: t.get("at") or "", reverse=True)[:3]}
        return {"student": {"id": sid, "name": (student or {}).get("name") or sid,
                            "grade": (student or {}).get("grade") or ""},
                "book": book, "bookName": BOOK2_NAME if book == BOOK2 else BOOK_NAME, "books": books,
                "days": day_rows, "letters": letters, "groups": groups, "info": info,
                "areas": areas, "exam": exam_out}

    return r
