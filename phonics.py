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
    "a": {"ipa": "æ",  "ko": "애아", "words": [["ant", "개미", "🐜"], ["alligator", "악어", "🐊"], ["apple", "사과", "🍎"], ["ambulance", "구급차", "🚑"], ["astronaut", "우주비행사", "🧑‍🚀"]]},
    "b": {"ipa": "b",  "ko": "ㅂ", "words": [["ball", "공", "⚽"], ["book", "책", "📕"], ["bear", "곰", "🐻"], ["bus", "버스", "🚌"], ["banana", "바나나", "🍌"]]},
    "c": {"ipa": "k",  "ko": "ㅋ", "words": [["car", "자동차", "🚗"], ["cow", "소", "🐄"], ["cat", "고양이", "🐱"], ["cake", "케이크", "🎂"], ["carrot", "당근", "🥕"]]},
    "d": {"ipa": "d",  "ko": "ㄷ", "words": [["door", "문", "🚪"], ["dog", "개", "🐶"], ["desk", "책상", "🧑‍💻"], ["duck", "오리", "🦆"], ["dinosaur", "공룡", "🦕"]]},
    "e": {"ipa": "ɛ",  "ko": "에", "words": [["egg", "달걀", "🥚"], ["elephant", "코끼리", "🐘"], ["elbow", "팔꿈치", "💪"], ["elf", "요정", "🧝"], ["envelope", "봉투", "✉️"]]},
    "f": {"ipa": "f",  "ko": "ㅍ", "words": [["fish", "물고기", "🐟"], ["five", "다섯", "5️⃣"], ["fox", "여우", "🦊"], ["fork", "포크", "🍴"], ["feather", "깃털", "🪶"]]},
    "g": {"ipa": "ɡ",  "ko": "ㄱ", "words": [["green", "초록색", "🟢"], ["girl", "소녀", "👧"], ["gorilla", "고릴라", "🦍"], ["goat", "염소", "🐐"], ["gift", "선물", "🎁"]]},
    "h": {"ipa": "h",  "ko": "ㅎ", "words": [["hat", "모자", "🎩"], ["hand", "손", "✋"], ["house", "집", "🏠"], ["horse", "말", "🐴"], ["hippo", "하마", "🦛"]]},
    "i": {"ipa": "ɪ",  "ko": "이", "words": [["igloo", "이글루", "🧊🏠"], ["insect", "곤충", "🐞"], ["iguana", "이구아나", "🦎"], ["ink", "잉크", "🖋️"], ["inchworm", "자벌레", "🐛"]]},
    "j": {"ipa": "dʒ", "ko": "ㅈ", "words": [["jet", "제트기", "✈️"], ["jam", "잼", "🍯"], ["jacket", "재킷", "🧥"], ["juice", "주스", "🧃"], ["jellyfish", "해파리", "🪼"]]},
    "k": {"ipa": "k",  "ko": "ㅋ", "words": [["kangaroo", "캥거루", "🦘"], ["kid", "아이", "🧒"], ["king", "왕", "🤴"], ["kite", "연", "🪁"], ["key", "열쇠", "🔑"]]},
    "l": {"ipa": "l",  "ko": "을ㄹ", "words": [["lamp", "램프", "💡"], ["lion", "사자", "🦁"], ["leaf", "나뭇잎", "🍃"], ["lemon", "레몬", "🍋"], ["leg", "다리", "🦵"]]},
    "m": {"ipa": "m",  "ko": "음ㅁ", "words": [["monster", "괴물", "👾"], ["mouse", "생쥐", "🐭"], ["map", "지도", "🗺️"], ["moon", "달", "🌙"], ["milk", "우유", "🥛"]]},
    "n": {"ipa": "n",  "ko": "은ㄴ", "words": [["nest", "둥지", "🪺"], ["nut", "견과", "🥜"], ["neck", "목", "🦒"], ["nose", "코", "👃"], ["nine", "아홉", "9️⃣"]]},
    "o": {"ipa": "ɑ",  "ko": "아", "words": [["ox", "황소", "🐂"], ["octopus", "문어", "🐙"], ["ostrich", "타조", "🦤"], ["otter", "수달", "🦦"], ["olive", "올리브", "🫒"]]},
    "p": {"ipa": "p",  "ko": "ㅍ", "words": [["pen", "펜", "🖊️"], ["pig", "돼지", "🐷"], ["pizza", "피자", "🍕"], ["panda", "판다", "🐼"], ["penguin", "펭귄", "🐧"]]},
    "q": {"ipa": "kw", "ko": "워", "words": [["question", "질문", "❓"], ["queen", "여왕", "👸"], ["quiet", "조용히", "🤫"], ["quack", "꽥꽥", "🦆"], ["quarter", "25센트 동전", "🪙"]]},
    "r": {"ipa": "ɹ",  "ko": "얼ㄹ", "words": [["robot", "로봇", "🤖"], ["ring", "반지", "💍"], ["rabbit", "토끼", "🐰"], ["rainbow", "무지개", "🌈"], ["rocket", "로켓", "🚀"]]},
    "s": {"ipa": "s",  "ko": "ㅅ", "words": [["sun", "해", "☀️"], ["sock", "양말", "🧦"], ["six", "여섯", "6️⃣"], ["snake", "뱀", "🐍"], ["seal", "물개", "🦭"]]},
    "t": {"ipa": "t",  "ko": "ㅌ", "words": [["tiger", "호랑이", "🐯"], ["tape", "테이프", "📼"], ["tent", "텐트", "⛺"], ["tomato", "토마토", "🍅"], ["turtle", "거북", "🐢"]]},
    "u": {"ipa": "ʌ",  "ko": "어", "words": [["up", "위로", "⬆️"], ["under", "아래에", "⬇️"], ["umbrella", "우산", "☂️"], ["uncle", "삼촌", "👨"], ["upset", "속상한", "😣"]]},
    "v": {"ipa": "v",  "ko": "ㅂ", "words": [["van", "승합차", "🚐"], ["vase", "꽃병", "🏺"], ["violin", "바이올린", "🎻"], ["vest", "조끼", "🦺"], ["volcano", "화산", "🌋"]]},
    "w": {"ipa": "w",  "ko": "우워", "words": [["web", "거미줄", "🕸️"], ["wolf", "늑대", "🐺"], ["watch", "손목시계", "⌚"], ["worm", "지렁이", "🪱"], ["watermelon", "수박", "🍉"]]},
    "x": {"ipa": "ks", "ko": "ㅋㅅ", "pos": "end", "words": [["box", "상자", "📦"], ["fox", "여우", "🦊"], ["ax", "도끼", "🪓"], ["six", "여섯", "6️⃣"], ["taxi", "택시", "🚕"]]},
    "y": {"ipa": "j",  "ko": "이여", "words": [["yo-yo", "요요", "🪀"], ["yacht", "요트", "⛵"], ["yellow", "노란색", "🟡"], ["yarn", "털실", "🧶"], ["yawn", "하품", "🥱"]]},
    "z": {"ipa": "z",  "ko": "ㅈ", "words": [["zebra", "얼룩말", "🦓"], ["zero", "영", "0️⃣"], ["zoo", "동물원", "🦒🐘"], ["zipper", "지퍼", "🤐"], ["zombie", "좀비", "🧟"]]},
}
for _k, _L in LETTERS.items():
    _L["key"] = _L["words"][0][0]

# 1권 = Phonics Monster 1 목차(원장 2026-11-02): Zero Unit → Unit 1~4 · Game 1·2 · Unit 5 Review → Unit 6~9 · Game 3·4 ·
#   Unit 10 Review → Can You Read?. 16일. kind: zero/unit/game/review/read. letters = 그날 다루는 글자.
_ORDER = list("abcdefghijklmnopqrstuvwxyz")
_U1 = {1: "abc", 2: "def", 3: "ghi", 4: "jkl", 6: "mno", 7: "pqr", 8: "stuv", 9: "wxyz"}
_PLAN1 = [("zero", "Zero Unit", "알파벳 연습", None), ("unit", "Unit 1", None, [1]), ("unit", "Unit 2", None, [2]),
          ("game", "Game 1", "Unit 1~2", [1, 2]), ("unit", "Unit 3", None, [3]), ("unit", "Unit 4", None, [4]),
          ("game", "Game 2", "Unit 3~4", [3, 4]), ("review", "Unit 5", "Review · Unit 1~4", [1, 2, 3, 4]),
          ("unit", "Unit 6", None, [6]), ("unit", "Unit 7", None, [7]), ("game", "Game 3", "Unit 6~7", [6, 7]),
          ("unit", "Unit 8", None, [8]), ("unit", "Unit 9", None, [9]), ("game", "Game 4", "Unit 8~9", [8, 9]),
          ("review", "Unit 10", "Review · Unit 6~9", [6, 7, 8, 9]), ("read", "Can You Read?", "단어·사이트워즈 읽기", None)]
READ1 = ["cat", "dog", "pig", "sun", "fox", "hat", "bus", "jet", "pen", "box"]   # Can You Read? — 소리로 읽히는 쉬운 단어
SIGHT1 = ["I", "a", "the", "see", "can", "it"]
DAYS = []
for _i, (_kind, _name, _label, _units) in enumerate(_PLAN1):
    _lt = [c for u in (_units or []) for c in _U1[u]] if _units else (list(_ORDER) if _kind in ("zero", "read") else [])
    DAYS.append({"day": _i + 1, "kind": _kind, "name": _name, "units": _units or [],
                 "label": _label or " · ".join(c.upper() for c in _lt), "letters": _lt})
for _d in DAYS:   # 과제 items = 그날 글자(복사돼도 남아 날을 찾는 열쇠). Can You Read? 는 읽을 단어
    _d["items"] = (READ1 + SIGHT1) if _d["kind"] == "read" else _d["letters"]
    if _d["kind"] == "read":
        _d["readWords"], _d["sightWords"] = READ1, SIGHT1
for _d in SHORT if False else []:
    pass


# ── LV1 2권 단모음 ── Phonics Monster 2 목차(원장 2026-11-02). 16일: Zero Unit(소리 연습) → Unit 1·2 짧은 a →
#   Game 1 → Unit 3·4 짧은 i → Game 2 → Unit 5 Review → Unit 6·7 짧은 u → Game 3 → Unit 8 짧은 e → Unit 9 짧은 o →
#   Game 4 → Unit 10 Review → Can You Read?. Unit 날만 단어가족(families)이 있고, Game·Review 는 그 Unit 들을 섞는다.
BOOK2 = "LV1 2권"
BOOK2_NAME = "단모음"
VOWEL_KEY = {"a": "apple", "e": "egg", "i": "insect", "o": "octopus", "u": "umbrella"}
_U2 = {
    1: ("a", [("-ad", [["dad", "아빠", "👨"], ["bad", "나쁜", "👎"], ["sad", "슬픈", "😢"]]),
              ("-ag", [["bag", "가방", "👜"], ["tag", "꼬리표", "🏷️"], ["wag", "꼬리를 흔들다", "🐕"]]),
              ("-am", [["jam", "잼", "🍯"], ["ram", "숫양", "🐏"], ["ham", "햄", "🍖"]])]),
    2: ("a", [("-an", [["fan", "부채", "🪭"], ["can", "깡통", "🥫"], ["man", "남자", "🧍‍♂️"]]),
              ("-ap", [["map", "지도", "🗺️"], ["cap", "모자", "🧢"], ["tap", "수도꼭지", "🚰"]]),
              ("-at", [["cat", "고양이", "🐱"], ["fat", "뚱뚱한", "🐖"], ["hat", "모자", "🎩"]])]),
    3: ("i", [("-ig", [["pig", "돼지", "🐷"], ["big", "큰", "🐘"], ["wig", "가발", "👩‍🦰"]]),
              ("-in", [["bin", "쓰레기통", "🗑️"], ["win", "이기다", "🏆"], ["pin", "핀", "📍"]]),
              ("-ip", [["lip", "입술", "👄"], ["hip", "엉덩이", "🕺"], ["rip", "찢다", "📄"]])]),
    4: ("i", [("-it", [["kit", "도구 상자", "🧰"], ["sit", "앉다", "🪑"], ["hit", "치다", "⚾"]]),
              ("-ix", [["mix", "섞다", "🥣"], ["fix", "고치다", "🔧"], ["six", "여섯", "6️⃣"]]),
              ("-id", [["lid", "뚜껑", "🫕"], ["kid", "아이", "🧒"]])]),
    6: ("u", [("-ug", [["bug", "벌레", "🐛"], ["hug", "안아 주다", "🤗"], ["rug", "깔개", "🟫"]]),
              ("-un", [["sun", "해", "☀️"], ["bun", "빵", "🍞"], ["run", "달리다", "🏃"]]),
              ("-ut", [["nut", "견과", "🥜"], ["hut", "오두막", "🛖"], ["cut", "자르다", "✂️"]])]),
    7: ("u", [("-ub · -ud", [["tub", "욕조", "🛁"], ["cub", "아기 곰", "🧸"], ["mud", "진흙", "🟤"], ["bud", "새싹", "🌱"]]),
              ("-um", [["gum", "껌", "🍬"], ["hum", "흥얼거리다", "🎵"]]),
              ("-up", [["cup", "컵", "🥤"], ["pup", "강아지", "🐕"]])]),
    8: ("e", [("-ed", [["red", "빨강", "🔴"], ["bed", "침대", "🛏️"], ["Ted", "테드(곰 인형)", "🧸"]]),
              ("-en", [["hen", "암탉", "🐔"], ["ten", "열", "🔟"], ["pen", "펜", "🖊️"]]),
              ("-et", [["jet", "제트기", "✈️"], ["wet", "젖은", "💦"], ["pet", "반려동물", "🐶"]])]),
    9: ("o", [("-og", [["dog", "개", "🐶"], ["log", "통나무", "🪵"], ["jog", "조깅하다", "🏃"]]),
              ("-ot", [["pot", "냄비", "🍲"], ["hot", "뜨거운", "🔥"], ["dot", "점", "🔵"]]),
              ("-ox", [["fox", "여우", "🦊"], ["box", "상자", "📦"], ["ox", "황소", "🐂"]])]),
}
_S2 = {
    1: [["Dad has a bag.", "아빠가 가방을 가졌어요.", "👨👜"], ["The ram is sad.", "숫양이 슬퍼요.", "🐏😢"]],
    2: [["The cat has a hat.", "고양이가 모자를 썼어요.", "🐱🎩"], ["A man has a fan.", "남자가 부채를 가졌어요.", "🧍‍♂️🪭"]],
    3: [["The pig is big.", "돼지가 커요.", "🐷🐘"], ["The pin is in the bin.", "핀이 통 안에 있어요.", "📍🗑️"]],
    4: [["The kid can sit.", "아이가 앉을 수 있어요.", "🧒🪑"], ["I can fix it.", "나는 그걸 고칠 수 있어요.", "🙋🔧"]],
    6: [["The bug is on the rug.", "벌레가 깔개 위에 있어요.", "🐛🟫"], ["I can run in the sun.", "나는 햇볕 아래에서 달릴 수 있어요.", "🏃☀️"]],
    7: [["The pup is in the tub.", "강아지가 욕조 안에 있어요.", "🐕🛁"], ["The cub has a cup.", "아기 곰이 컵을 가졌어요.", "🧸🥤"]],
    8: [["The hen is on the bed.", "암탉이 침대 위에 있어요.", "🐔🛏️"], ["Ted has a red pen.", "테드는 빨간 펜이 있어요.", "🧸🖊️"]],
    9: [["The fox is in the box.", "여우가 상자 안에 있어요.", "🦊📦"], ["The dog is on the log.", "개가 통나무 위에 있어요.", "🐶🪵"]],
}
_PLAN2 = [("zero", "Zero Unit", "소리 연습", None), ("unit", "Unit 1", None, [1]), ("unit", "Unit 2", None, [2]),
          ("game", "Game 1", "Unit 1~2", [1, 2]), ("unit", "Unit 3", None, [3]), ("unit", "Unit 4", None, [4]),
          ("game", "Game 2", "Unit 3~4", [3, 4]), ("review", "Unit 5", "Review · Unit 1~4", [1, 2, 3, 4]),
          ("unit", "Unit 6", None, [6]), ("unit", "Unit 7", None, [7]), ("game", "Game 3", "Unit 6~7", [6, 7]),
          ("unit", "Unit 8", None, [8]), ("unit", "Unit 9", None, [9]), ("game", "Game 4", "Unit 8~9", [8, 9]),
          ("review", "Unit 10", "Review · Unit 6~9", [6, 7, 8, 9]), ("read", "Can You Read?", "단어·사이트워즈 읽기", None)]
READ2 = ["cat", "map", "pig", "six", "bug", "cup", "bed", "pen", "dog", "box"]
SIGHT2 = ["I", "a", "the", "is", "can", "see"]
SHORT = []
for _i, (_kind, _name, _label, _units) in enumerate(_PLAN2):
    _d = {"day": _i + 1, "kind": _kind, "name": _name, "units": _units or [], "families": [], "sents": []}
    if _kind == "unit":
        _v, _fams = _U2[_units[0]]
        _d.update(vowel=_v, label=f"짧은 {_v}", families=[{"name": n, "words": ws} for n, ws in _fams],
                  sents=[{"id": f"s{_units[0]}{j + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for j, x in enumerate(_S2[_units[0]])])
    else:
        _d.update(vowel=("aeiou" if _kind in ("zero", "read") else ""), label=_label)
    SHORT.append(_d)
SHORT_WORDS = [w for d in SHORT for f in d["families"] for w in f["words"]]
for _d in SHORT:   # 과제 items(복사돼도 남아 날을 찾는 열쇠) — Game·Review 는 섞는 Unit 들의 단어
    if _d["kind"] == "unit":
        _d["items"] = [w[0] for f in _d["families"] for w in f["words"]]
    elif _d["kind"] in ("game", "review"):
        _d["items"] = [w[0] for x in SHORT if x["kind"] == "unit" and x["units"][0] in _d["units"] for f in x["families"] for w in f["words"]]
    elif _d["kind"] == "zero":
        _d["items"] = list("aeiou")
    else:
        _d["items"] = READ2 + SIGHT2
        _d["readWords"], _d["sightWords"] = READ2, SIGHT2


def _ce(w, lv):
    """매직 e 단어 조각: 'cake' → c|a:La|k|e*. 부드러운 c(dice·mice·rice)=ㅅ, s 가 z 로 나는 것(rose·nose·hose)=ㅈ"""
    soft = {"dice": "c:s", "mice": "c:s", "rice": "c:s"}
    zs = {"rose", "nose", "hose"}
    head, v, mid = w[0], w[1], w[2:-1]
    mid = soft.get(w, (mid + ":z") if w in zs else mid)
    return f"{head}|{v}:L{lv}|{mid}|e*"


def _fam(name, pat, lv, words):
    return {"name": name, "pat": pat, "snd": lv, "words": [[w, ko, em, _ce(w, lv)] for w, ko, em in words]}


# ── LV1 3권 장모음 ── Phonics Monster 3 목차(원장 2026-11-02): Before You Start(단모음 복습) → Unit 1·2 긴 a → Unit 3·4 긴 i →
#   Unit 5 Review → Unit 6·7 긴 o → Unit 8 긴 u → Unit 9 Magic e(cap→cape 짝) → Unit 10 Review. 11일. 학습 달(3~4달)은 그대로.
#   (모음 팀 ai·ee·oa… 는 교재처럼 5권=7~8달로 옮김)
BOOK3 = "LV1 3권"
BOOK3_NAME = "장모음"
LONG_SND = {"a": ("eɪ", "에이"), "i": ("aɪ", "아이"), "o": ("oʊ", "오우"), "u": ("uː", "우-"), "yu": ("juː", "유-"), "e": ("iː", "이-")}
_U3 = {
    1: ("a", "a", [_fam("-ake", "a_e", "a", [("bake", "굽다", "🧁"), ("cake", "케이크", "🎂"), ("lake", "호수", "🏞️")]),
                   _fam("-ase", "a_e", "a", [("case", "상자·케이스", "💼"), ("base", "야구 베이스", "⚾"), ("vase", "꽃병", "🏺")]),
                   _fam("-ate", "a_e", "a", [("date", "날짜", "📅"), ("gate", "대문", "⛩️"), ("late", "늦은", "⏰")])]),
    2: ("a", "a", [_fam("-ame", "a_e", "a", [("game", "게임", "🎮"), ("name", "이름", "📛"), ("same", "똑같은", "👯")]),
                   _fam("-ave", "a_e", "a", [("wave", "파도", "🌊"), ("cave", "동굴", "🕳️"), ("save", "구하다", "🛟")]),
                   _fam("-ape", "a_e", "a", [("tape", "테이프", "📼"), ("cape", "망토", "🦸")])]),
    3: ("i", "i", [_fam("-ice", "i_e", "i", [("dice", "주사위", "🎲"), ("mice", "생쥐들", "🐭"), ("rice", "밥", "🍚")]),
                   _fam("-ike", "i_e", "i", [("bike", "자전거", "🚲"), ("hike", "등산하다", "🥾"), ("mike", "마이크", "🎤")]),
                   _fam("-ine", "i_e", "i", [("line", "줄", "📏"), ("nine", "아홉", "9️⃣"), ("pine", "소나무", "🌲")])]),
    4: ("i", "i", [_fam("-ide", "i_e", "i", [("hide", "숨다", "🙈"), ("ride", "타다", "🏇"), ("wide", "넓은", "↔️")]),
                   _fam("-ive", "i_e", "i", [("dive", "다이빙하다", "🤿"), ("five", "다섯", "5️⃣"), ("hive", "벌집", "🐝")]),
                   _fam("-ite", "i_e", "i", [("bite", "물다", "🦷"), ("kite", "연", "🪁")])]),
    6: ("o", "o", [_fam("-ole", "o_e", "o", [("hole", "구멍", "🕳️"), ("pole", "막대", "🚏"), ("mole", "두더지", "🦡")]),
                   _fam("-ome", "o_e", "o", [("dome", "둥근 지붕", "🕌"), ("home", "집", "🏠")]),
                   _fam("-one", "o_e", "o", [("bone", "뼈다귀", "🦴"), ("cone", "콘", "🍦")])]),
    7: ("o", "o", [_fam("-ose", "o_e", "o", [("rose", "장미", "🌹"), ("nose", "코", "👃"), ("hose", "호스", "🚿")]),
                   _fam("-ope", "o_e", "o", [("hope", "바라다", "🙏"), ("rope", "밧줄", "🪢")]),
                   _fam("-ote", "o_e", "o", [("note", "쪽지", "📝"), ("vote", "투표하다", "🗳️")])]),
    8: ("u", "yu", [_fam("-ube", "u_e", "yu", [("cube", "정육면체", "🧊"), ("tube", "튜브", "🧪")]),
                    _fam("-une", "u_e", "u", [("June", "6월", "🌸"), ("tune", "곡조", "🎵")]),
                    _fam("-ute", "u_e", "yu", [("cute", "귀여운", "🥰"), ("mute", "소리 끈", "🔇")])]),
}
_U3[8][2][0]["words"][1][3] = "t|u:Lu|b|e*"     # tube 는 '우-'
# Unit 9 Magic e — 짧은 단어와 e 가 붙은 짝(can → cane)
def _pair(name, pat, lv, pairs):
    ws = []
    for (s, sk, se), (l, lk, le) in pairs:
        ws.append([s, sk, se])                    # 짧은 단어: 조각 없음(글자 하나씩·짧은 소리)
        ws.append([l, lk, le, _ce(l, lv)])
    return {"name": name, "pat": pat, "snd": lv, "words": ws}
_U3[9] = ("e", "a", [_pair("a → a_e", "a_e", "a", [(("can", "깡통", "🥫"), ("cane", "지팡이", "🦯")), (("tap", "수도꼭지", "🚰"), ("tape", "테이프", "📼"))]),
                     _pair("i → i_e", "i_e", "i", [(("kit", "도구 상자", "🧰"), ("kite", "연", "🪁")), (("pin", "핀", "📍"), ("pine", "소나무", "🌲"))]),
                     _pair("o → o_e", "o_e", "o", [(("hop", "깡충 뛰다", "🐇"), ("hope", "바라다", "🙏")), (("pop", "펑 터지다", "🎈"), ("pope", "교황", "⛪"))]),
                     _pair("u → u_e", "u_e", "yu", [(("tub", "욕조", "🛁"), ("tube", "튜브", "🧪")), (("cub", "아기 곰", "🧸"), ("cube", "정육면체", "🧊"))])])
_U3[9][2][3]["words"][1][3] = "t|u:Lu|b|e*"
_S3 = {
    1: [["I bake a cake.", "나는 케이크를 구워요.", "🧁🎂"], ["The vase is in the case.", "꽃병이 상자 안에 있어요.", "🏺💼"]],
    2: [["I see a big wave.", "나는 큰 파도를 봐요.", "🌊"], ["My name is on the tape.", "내 이름이 테이프에 있어요.", "📛📼"]],
    3: [["The mice eat rice.", "생쥐들이 밥을 먹어요.", "🐭🍚"], ["I see nine pine trees.", "나는 소나무 아홉 그루를 봐요.", "9️⃣🌲"]],
    4: [["I can ride a bike.", "나는 자전거를 탈 수 있어요.", "🏇🚲"], ["I see five kites.", "나는 연 다섯 개를 봐요.", "5️⃣🪁"]],
    6: [["The dog has a bone.", "개가 뼈다귀를 가졌어요.", "🐶🦴"], ["I am at home.", "나는 집에 있어요.", "🏠"]],
    7: [["I see a rose.", "나는 장미를 봐요.", "🌹"], ["I have a rope.", "나는 밧줄이 있어요.", "🪢"]],
    8: [["The cube is cute.", "큐브가 귀여워요.", "🧊🥰"], ["I like the tune.", "나는 그 곡이 좋아요.", "🎵"]],
    9: [["The cub has a cube.", "아기 곰이 큐브를 가졌어요.", "🧸🧊"], ["I can tap the tape.", "나는 테이프를 톡톡 칠 수 있어요.", "🚰📼"]],
}
_PLAN3 = [("zero", "Before You Start", "단모음 복습", None), ("unit", "Unit 1", None, [1]), ("unit", "Unit 2", None, [2]),
          ("unit", "Unit 3", None, [3]), ("unit", "Unit 4", None, [4]), ("review", "Unit 5", "Review · Unit 1~4", [1, 2, 3, 4]),
          ("unit", "Unit 6", None, [6]), ("unit", "Unit 7", None, [7]), ("unit", "Unit 8", None, [8]),
          ("unit", "Unit 9", None, [9]), ("review", "Unit 10", "Review · Unit 6~9", [6, 7, 8, 9])]
LONG = []
for _i, (_kind, _name, _label, _units) in enumerate(_PLAN3):
    _d = {"day": _i + 1, "kind": _kind, "name": _name, "units": _units or [], "families": [], "sents": []}
    if _kind == "unit":
        _v, _snd, _fams = _U3[_units[0]]
        _d.update(vowel=_v, snd=_snd, families=_fams, label=("Magic e" if _units[0] == 9 else f"긴 {_v}"),
                  nomeet=(_units[0] == 9),
                  sents=[{"id": f"l{_units[0]}{j + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for j, x in enumerate(_S3[_units[0]])])
    else:
        _d.update(vowel=("aeiou" if _kind == "zero" else ""), snd="a", label=_label)
    LONG.append(_d)
LONG_WORDS = [w for d in LONG for f in d["families"] for w in f["words"]]
for _d in LONG:
    if _d["kind"] == "unit":
        _d["items"] = [w[0] for f in _d["families"] for w in f["words"]]
    elif _d["kind"] == "review":
        _d["items"] = [w[0] for x in LONG if x["kind"] == "unit" and x["units"][0] in _d["units"] for f in x["families"] for w in f["words"]]
    else:
        _d["items"] = list("aeiou") + ["long"]

# ── LV1 4권 이중자음 ── Phonics Monster 4 앞쪽(원장 2026-11-02, 학습 달 5~6달 그대로):
#   Before You Start(장모음 복습) → Unit 1 bl fl gl sl → Unit 2 br cr dr gr → Unit 3 ch sh → Unit 4 th wh → Unit 5 hard/soft c, g → Review.
#   조각 태그: :La…:Le 긴 소리, :Vow·:Var·:Ver·:Voo 이중모음 소리(dv-), :sh :ch :th :ng 이중자 소리(dg-), :k :s :j :z :i :o :u :f :l 그 글자 소리, * 묵음 e.
BOOK4 = "LV1 4권"
BOOK4_NAME = "이중자음"
DIGRAPH_SND = {"sh": ("ʃ", "쉬"), "ch": ("tʃ", "취"), "th": ("θ", "쓰"), "ng": ("ŋ", "응")}
DV_SND = {"oo": ("ʊ", "우"), "ow": ("aʊ", "아우"), "oi": ("ɔɪ", "오이"), "aw": ("ɔ", "오-"),
          "ar": ("ɑɹ", "아ㄹ"), "or": ("ɔɹ", "오ㄹ"), "er": ("ɝ", "얼"), "ear": ("ɪɹ", "이얼")}


def _f4(name, pat, ws):
    return {"name": name, "pat": pat, "words": [list(w) for w in ws]}


_U4 = {
    1: [_f4("bl", "bl", [("black", "검은색", "⬛", "b|l|a|ck:k"), ("blade", "칼날", "🔪", "b|l|a:La|d|e*"), ("blue", "파란색", "🔵", "b|l|ue:Lu")]),
        _f4("fl", "fl", [("flag", "깃발", "🚩", "f|l|a|g"), ("flame", "불꽃", "🔥", "f|l|a:La|m|e*"), ("flute", "플루트", "🪈", "f|l|u:Lu|t|e*")]),
        _f4("gl", "gl", [("globe", "지구본", "🌍", "g|l|o:Lo|b|e*"), ("glass", "유리컵", "🥛", "g|l|a|ss:s"), ("glue", "풀", "🧴", "g|l|ue:Lu")]),
        _f4("sl", "sl", [("slide", "미끄럼틀", "🛝", "s|l|i:Li|d|e*"), ("sled", "썰매", "🛷", "s|l|e|d"), ("sleep", "자다", "😴", "s|l|ee:Le|p")])],
    2: [_f4("br", "br", [("brick", "벽돌", "🧱", "b|r|i|ck:k"), ("bride", "신부", "👰", "b|r|i:Li|d|e*"), ("brave", "용감한", "🦸", "b|r|a:La|v|e*")]),
        _f4("cr", "cr", [("crab", "게", "🦀", "c|r|a|b"), ("cross", "십자 모양", "➕", "c|r|o|ss:s"), ("crow", "까마귀", "🐦‍⬛", "c|r|ow:Lo")]),
        _f4("dr", "dr", [("dress", "드레스", "👗", "d|r|e|ss:s"), ("drum", "북", "🥁", "d|r|u|m"), ("dragon", "용", "🐉", "d|r|a|g|o:u|n")]),
        _f4("gr", "gr", [("grape", "포도", "🍇", "g|r|a:La|p|e*"), ("grass", "풀밭", "🌿", "g|r|a|ss:s"), ("green", "초록색", "🟢", "g|r|ee:Le|n")])],
    3: [_f4("ch", "ch", [("chin", "턱", "🧔", "ch:ch|i|n"), ("chip", "감자칩", "🍟", "ch:ch|i|p"), ("chop", "자르다", "🪓", "ch:ch|o|p"),
                         ("lunch", "점심", "🍱", "l|u|n|ch:ch"), ("ostrich", "타조", "🦤", "o|s|t|r|i|ch:ch"), ("watch", "손목시계", "⌚", "w|a:o|tch:ch")]),
        _f4("sh", "sh", [("ship", "배", "🚢", "sh:sh|i|p"), ("shape", "모양", "🔷", "sh:sh|a:La|p|e*"), ("shark", "상어", "🦈", "sh:sh|ar:Var|k"),
                         ("brush", "솔", "🪥", "b|r|u|sh:sh"), ("fish", "물고기", "🐟", "f|i|sh:sh"), ("wash", "씻다", "🧼", "w|a:o|sh:sh")])],
    4: [_f4("th", "th", [("thick", "두꺼운", "📗", "th:th|i|ck:k"), ("thin", "얇은", "🥢", "th:th|i|n"), ("three", "셋", "3️⃣", "th:th|r|ee:Le"),
                         ("bath", "목욕", "🛁", "b|a|th:th"), ("teeth", "이빨", "🦷", "t|ee:Le|th:th"), ("mouth", "입", "👄", "m|ou:Vow|th:th")]),
        _f4("wh", "wh", [("white", "흰색", "⚪", "wh:w|i:Li|t|e*"), ("whale", "고래", "🐳", "wh:w|a:La|l|e*"), ("wheel", "바퀴", "🛞", "wh:w|ee:Le|l"),
                         ("whip", "채찍", "🪢", "wh:w|i|p"), ("whisk", "거품기", "🥄", "wh:w|i|s|k"), ("whisper", "속삭이다", "🤫", "wh:w|i|s|p|er:Ver")])],
    5: [_f4("hard c", "c", [("candy", "사탕", "🍬", "c|a|n|d|y:Le"), ("cut", "자르다", "✂️", "c|u|t"), ("cold", "추운", "🥶", "c|o:Lo|l|d")]),
        _f4("soft c", "c", [("city", "도시", "🏙️", "c:s|i|t|y:Le"), ("face", "얼굴", "🙂", "f|a:La|c:s|e*"), ("bicycle", "자전거", "🚲", "b|i:Li|c:s|y:i|c|l|e*")]),
        _f4("hard g", "g", [("gum", "껌", "🫧", "g|u|m"), ("gorilla", "고릴라", "🦍", "g|o|r|i|ll:l|a:u"), ("alligator", "악어", "🐊", "a|ll:l|i|g|a:La|t|or:Vor")]),
        _f4("soft g", "g", [("giraffe", "기린", "🦒", "g:j|i|r|a|ff:f|e*"), ("gym", "체육관", "🏋️", "g:j|y:i|m"), ("cage", "새장", "🔲", "c|a:La|g:j|e*")])],
}
_S4 = {
    1: [["The flag is blue.", "깃발이 파래요.", "🚩🔵"], ["I sleep on the sled.", "나는 썰매 위에서 자요.", "😴🛷"]],
    2: [["The crab has a drum.", "게가 북을 가졌어요.", "🦀🥁"], ["The grass is green.", "풀밭이 초록색이에요.", "🌿🟢"]],
    3: [["I see a fish and a ship.", "나는 물고기와 배를 봐요.", "🐟🚢"], ["I eat lunch and chips.", "나는 점심과 감자칩을 먹어요.", "🍱🍟"]],
    4: [["I see three whales.", "나는 고래 세 마리를 봐요.", "3️⃣🐳"], ["My teeth are white.", "내 이는 하얘요.", "🦷⚪"]],
    5: [["The city is big.", "도시가 커요.", "🏙️"], ["I see a giraffe at the zoo.", "나는 동물원에서 기린을 봐요.", "🦒"]],
}
_PLAN4 = [("unit", "Before You Start", "장모음 복습", [0]), ("unit", "Unit 1", "bl · fl · gl · sl", [1]), ("unit", "Unit 2", "br · cr · dr · gr", [2]),
          ("unit", "Unit 3", "ch · sh", [3]), ("unit", "Unit 4", "th · wh", [4]), ("unit", "Unit 5", "hard/soft c · g", [5]),
          ("review", "Review", "Unit 1~5", [1, 2, 3, 4, 5])]
CONS = []
for _i, (_kind, _name, _label, _units) in enumerate(_PLAN4):
    _d = {"day": _i + 1, "kind": _kind, "name": _name, "label": _label, "units": _units, "families": [], "sents": [], "vowel": ""}
    if _kind == "unit" and _units[0] == 0:
        # 장모음 복습: 3권 Unit 1·3·6·8 의 첫 가족(-ake·-ice·-ole·-ube)
        _src = [x for x in LONG if x["kind"] == "unit"]
        _d.update(nomeet=True, kind="unit",
                  families=[dict(next(x for x in _src if x["units"][0] == u)["families"][0]) for u in (1, 3, 6, 8)],
                  sents=[x for u in (1, 4) for x in next(y for y in _src if y["units"][0] == u)["sents"][:1]])
    elif _kind == "unit":
        _d.update(families=_U4[_units[0]], vowel=_U4[_units[0]][0]["pat"],
                  sents=[{"id": f"c{_units[0]}{j + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for j, x in enumerate(_S4[_units[0]])])
    CONS.append(_d)
CONS_WORDS = [w for d in CONS for f in d["families"] for w in f["words"]]
for _d in CONS:
    if _d["kind"] == "review":
        _d["items"] = [w[0] for x in CONS if x["kind"] == "unit" and x["units"][0] in _d["units"] for f in x["families"] for w in f["words"]]
    else:
        _d["items"] = [w[0] for f in _d["families"] for w in f["words"]]

# ── LV1 5권 이중모음 ── Phonics Monster 4 뒤쪽(원장 2026-11-02, 학습 달 7~8달 그대로):
#   Unit 6 ai ay → Unit 7 ea ee → Unit 8 oa ow → Unit 9 ou ow → Unit 10 long/short oo → Review.
BOOK5 = "LV1 5권"
BOOK5_NAME = "이중모음"
_U5 = {
    6: [_f4("ai", "ai", [("mail", "편지", "📬", "m|ai:La|l"), ("snail", "달팽이", "🐌", "s|n|ai:La|l"), ("rain", "비", "🌧️", "r|ai:La|n"),
                         ("tail", "꼬리", "🐿️", "t|ai:La|l"), ("train", "기차", "🚆", "t|r|ai:La|n"), ("wait", "기다리다", "⏳", "w|ai:La|t")]),
        _f4("ay", "ay", [("hay", "건초", "🌾", "h|ay:La"), ("crayon", "크레용", "🖍️", "c|r|ay:La|o:u|n"), ("gray", "회색", "🩶", "g|r|ay:La"),
                         ("clay", "찰흙", "🟫", "c|l|ay:La"), ("spray", "뿌리다", "💨", "s|p|r|ay:La"), ("play", "놀다", "⚽", "p|l|ay:La")])],
    7: [_f4("ea", "ea", [("eat", "먹다", "🍽️", "ea:Le|t"), ("beach", "해변", "🏖️", "b|ea:Le|ch:ch"), ("sea", "바다", "🌊", "s|ea:Le"),
                         ("meat", "고기", "🥩", "m|ea:Le|t"), ("leaf", "나뭇잎", "🍃", "l|ea:Le|f"), ("clean", "깨끗한", "🧹", "c|l|ea:Le|n")]),
        _f4("ee", "ee", [("bee", "벌", "🐝", "b|ee:Le"), ("sheep", "양", "🐑", "sh:sh|ee:Le|p"), ("seed", "씨앗", "🌱", "s|ee:Le|d"),
                         ("tree", "나무", "🌳", "t|r|ee:Le"), ("feet", "발", "🦶", "f|ee:Le|t"), ("green", "초록색", "🟢", "g|r|ee:Le|n")])],
    8: [_f4("oa", "oa", [("boat", "배", "⛵", "b|oa:Lo|t"), ("toast", "토스트", "🍞", "t|oa:Lo|s|t"), ("soap", "비누", "🧼", "s|oa:Lo|p"),
                         ("coat", "코트", "🧥", "c|oa:Lo|t"), ("goat", "염소", "🐐", "g|oa:Lo|t"), ("road", "길", "🛣️", "r|oa:Lo|d")]),
        _f4("ow (오우)", "ow", [("bowl", "그릇", "🥣", "b|ow:Lo|l"), ("crow", "까마귀", "🐦‍⬛", "c|r|ow:Lo"), ("snow", "눈", "❄️", "s|n|ow:Lo"),
                               ("blow", "불다", "🌬️", "b|l|ow:Lo"), ("window", "창문", "🪟", "w|i|n|d|ow:Lo"), ("yellow", "노란색", "🟡", "y|e|ll:l|ow:Lo")])],
    9: [_f4("ou", "ou", [("house", "집", "🏠", "h|ou:Vow|s|e*"), ("couch", "소파", "🛋️", "c|ou:Vow|ch:ch"), ("cloud", "구름", "☁️", "c|l|ou:Vow|d"),
                         ("mouse", "생쥐", "🐭", "m|ou:Vow|s|e*"), ("blouse", "블라우스", "👚", "b|l|ou:Vow|s|e*"), ("count", "세다", "🔢", "c|ou:Vow|n|t")]),
        _f4("ow (아우)", "ow", [("owl", "부엉이", "🦉", "ow:Vow|l"), ("brown", "갈색", "🟤", "b|r|ow:Vow|n"), ("cow", "소", "🐄", "c|ow:Vow"),
                               ("clown", "광대", "🤡", "c|l|ow:Vow|n"), ("crown", "왕관", "👑", "c|r|ow:Vow|n"), ("down", "아래로", "⬇️", "d|ow:Vow|n")])],
    10: [_f4("oo (긴)", "oo", [("moon", "달", "🌙", "m|oo:Lu|n"), ("spoon", "숟가락", "🥄", "s|p|oo:Lu|n"), ("food", "음식", "🍱", "f|oo:Lu|d"),
                              ("zoo", "동물원", "🦒🐘", "z|oo:Lu"), ("moose", "무스", "🫎", "m|oo:Lu|s|e*"), ("school", "학교", "🏫", "s|ch:k|oo:Lu|l")]),
         _f4("oo (짧은)", "oo", [("book", "책", "📕", "b|oo:Voo|k"), ("foot", "발", "🦶", "f|oo:Voo|t"), ("cook", "요리하다", "👨‍🍳", "c|oo:Voo|k"),
                                ("wood", "나무(목재)", "🪵", "w|oo:Voo|d"), ("hook", "갈고리", "🪝", "h|oo:Voo|k"), ("cookie", "쿠키", "🍪", "c|oo:Voo|k|ie:Le")])],
}
_SAY5 = {"ai": ("lv-a", "에이"), "ay": ("lv-a", "에이"), "ea": ("lv-e", "이-"), "ee": ("lv-e", "이-"), "oa": ("lv-o", "오우"),
         "ow (오우)": ("lv-o", "오우"), "ou": ("dv-ow", "아우"), "ow (아우)": ("dv-ow", "아우"), "oo (긴)": ("lv-u", "우-"), "oo (짧은)": ("dv-oo", "우")}
for _fs in _U5.values():
    for _f in _fs:
        _f["say"], _f["sayko"] = _SAY5[_f["name"]]
_S5 = {
    6: [["The snail is in the rain.", "달팽이가 비를 맞아요.", "🐌🌧️"], ["I play with clay.", "나는 찰흙으로 놀아요.", "⚽🟫"]],
    7: [["I eat meat at the beach.", "나는 해변에서 고기를 먹어요.", "🥩🏖️"], ["The bee is on the tree.", "벌이 나무 위에 있어요.", "🐝🌳"]],
    8: [["The goat has a coat.", "염소가 코트를 입었어요.", "🐐🧥"], ["I see snow on the road.", "나는 길 위의 눈을 봐요.", "❄️🛣️"]],
    9: [["A mouse is in the house.", "생쥐가 집 안에 있어요.", "🐭🏠"], ["The clown has a crown.", "광대가 왕관을 썼어요.", "🤡👑"]],
    10: [["I eat food with a spoon.", "나는 숟가락으로 음식을 먹어요.", "🍱🥄"], ["I look at my book.", "나는 내 책을 봐요.", "📕"]],
}
_PLAN5 = [("unit", "Unit 6", "ai · ay", [6]), ("unit", "Unit 7", "ea · ee", [7]), ("unit", "Unit 8", "oa · ow", [8]),
          ("unit", "Unit 9", "ou · ow", [9]), ("unit", "Unit 10", "long/short oo", [10]), ("review", "Review", "Unit 6~10", [6, 7, 8, 9, 10])]
DIPH = []
for _i, (_kind, _name, _label, _units) in enumerate(_PLAN5):
    _d = {"day": _i + 1, "kind": _kind, "name": _name, "label": _label, "units": _units, "families": [], "sents": [], "vowel": ""}
    if _kind == "unit":
        _d.update(families=_U5[_units[0]], vowel=_U5[_units[0]][0]["pat"],
                  sents=[{"id": f"v{_units[0]}{j + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for j, x in enumerate(_S5[_units[0]])])
    DIPH.append(_d)
DIPH_WORDS = [w for d in DIPH for f in d["families"] for w in f["words"]]
for _d in DIPH:
    if _d["kind"] == "review":
        _d["items"] = [w[0] for x in DIPH if x["kind"] == "unit" and x["units"][0] in _d["units"] for f in x["families"] for w in f["words"]]
    else:
        _d["items"] = [w[0] for f in _d["families"] for w in f["words"]]

# ── LV1 6권 총복습 ── Phonics Monster ASAP 목차(원장 2026-11-02): Unit 0 Single Letters → 단모음(Unit 1~6) → Teacher e(7)
#   → 장모음(8~12) → Speed Race → 블렌드·이중자(14~17) → Bossy r(18) → 모음 팀·이중모음(20~22) → Check-up → Phonics Master.
#   학습 달(9~10달)은 그대로. 앞 권 가족은 (책, Day, 가족 번호)로 가져오고, 교재에만 있는 소리(sm·mp·nk·kn·ck·ng, ar·or·er·ir·ur,
#   ie·igh·y, oi·oy)는 여기서 새로 만든다.
BOOK6 = "LV1 6권"
BOOK6_NAME = "총복습"
_SRC = {"s": SHORT, "l": LONG, "c": CONS, "d": DIPH}


def _f6(name, pat, ws, say=None, sayko=None):
    f = _f4(name, pat, ws)
    if say:
        f["say"], f["sayko"] = say, sayko
    return f


_N6 = {
    "sm": _f6("sm", "sm", [("smile", "미소", "😊", "s|m|i:Li|l|e*"), ("smell", "냄새 맡다", "👃", "s|m|e|ll:l"), ("smoke", "연기", "💨", "s|m|o:Lo|k|e*")]),
    "mp": _f6("mp", "mp", [("lamp", "램프", "🪔", "l|a|m|p"), ("camp", "캠프", "🏕️", "c|a|m|p"), ("jump", "뛰다", "🦘", "j|u|m|p")]),
    "nk": _f6("nk", "nk", [("pink", "분홍색", "🩷", "p|i|n:ng|k"), ("sink", "싱크대", "🚰", "s|i|n:ng|k"), ("bank", "은행", "🏦", "b|a|n:ng|k")],
              "dg-ng", "응 + ㅋ"),
    "kn": _f6("kn", "kn", [("knee", "무릎", "🦵", "k*|n|ee:Le"), ("knife", "칼", "🔪", "k*|n|i:Li|f|e*"), ("knot", "매듭", "🪢", "k*|n|o|t")],
              "snd-n", "k 는 소리 없이 ㄴ"),
    "ck": _f6("ck", "ck", [("duck", "오리", "🦆", "d|u|ck:k"), ("sock", "양말", "🧦", "s|o|ck:k"), ("clock", "시계", "⏰", "c|l|o|ck:k")]),
    "ng": _f6("ng", "ng", [("ring", "반지", "💍", "r|i|ng:ng"), ("king", "왕", "🤴", "k|i|ng:ng"), ("sing", "노래하다", "🎤", "s|i|ng:ng")]),
    "ar": _f6("ar", "ar", [("car", "자동차", "🚗", "c|ar:Var"), ("star", "별", "⭐", "s|t|ar:Var"), ("park", "공원", "🏞️", "p|ar:Var|k")],
              "dv-ar", "아ㄹ"),
    "or": _f6("or", "or", [("fork", "포크", "🍴", "f|or:Vor|k"), ("corn", "옥수수", "🌽", "c|or:Vor|n"), ("horse", "말", "🐎", "h|or:Vor|s|e*")],
              "dv-or", "오ㄹ"),
    "er": _f6("er", "er", [("tiger", "호랑이", "🐯", "t|i:Li|g|er:Ver"), ("sister", "언니·누나·여동생", "👧", "s|i|s|t|er:Ver")], "dv-er", "얼"),
    "ir": _f6("ir", "ir", [("bird", "새", "🐦", "b|ir:Ver|d"), ("girl", "소녀", "👧", "g|ir:Ver|l")], "dv-er", "얼"),
    "ur": _f6("ur", "ur", [("nurse", "간호사", "👩‍⚕️", "n|ur:Ver|s|e*"), ("turn", "돌다", "🔄", "t|ur:Ver|n")], "dv-er", "얼"),
    "ie": _f6("ie", "ie", [("pie", "파이", "🥧", "p|ie:Li"), ("tie", "넥타이", "👔", "t|ie:Li")], "lv-i", "아이"),
    "igh": _f6("igh", "igh", [("night", "밤", "🌃", "n|igh:Li|t"), ("light", "불빛", "💡", "l|igh:Li|t"), ("right", "오른쪽", "➡️", "r|igh:Li|t")],
               "lv-i", "아이"),
    "y": _f6("y (아이)", "y", [("fly", "날다", "🪰", "f|l|y:Li"), ("cry", "울다", "😢", "c|r|y:Li"), ("sky", "하늘", "🌌", "s|k|y:Li")], "lv-i", "아이"),
    "oi": _f6("oi", "oi", [("coin", "동전", "🪙", "c|oi:Voi|n"), ("soil", "흙", "🪴", "s|oi:Voi|l"), ("oil", "기름", "🛢️", "oi:Voi|l")],
              "dv-oi", "오이"),
    "oy": _f6("oy", "oy", [("boy", "소년", "👦", "b|oy:Voi"), ("toy", "장난감", "🧸", "t|oy:Voi"), ("joy", "기쁨", "😄", "j|oy:Voi")],
              "dv-oi", "오이"),
}
_S6 = {
    7: [["I have a kit and a kite.", "나는 도구 상자와 연이 있어요.", "🧰🪁"]],
    14: [["I jump and smile.", "나는 뛰고 웃어요.", "🦘😊"], ["I see a pink lamp.", "나는 분홍 램프를 봐요.", "🩷🪔"]],
    15: [["The king has a ring.", "왕이 반지를 가졌어요.", "🤴💍"], ["The duck is on my knee.", "오리가 내 무릎 위에 있어요.", "🦆🦵"]],
    18: [["I see a star in the park.", "나는 공원에서 별을 봐요.", "⭐🏞️"], ["The girl has a bird.", "소녀가 새를 가졌어요.", "👧🐦"]],
    21: [["I eat pie at night.", "나는 밤에 파이를 먹어요.", "🥧🌃"], ["I can fly in the sky.", "나는 하늘을 날 수 있어요.", "🪰🌌"]],
    22: [["The boy has a toy.", "소년이 장난감을 가졌어요.", "👦🧸"], ["I see a coin in the soil.", "나는 흙 속에서 동전을 봐요.", "🪙🪴"]],
}
# (종류, 이름, 설명, Unit 번호(이 책 안), 가족들). 가족 = (책, Day, 번호) 또는 새 소리 이름. meet=새 소리 만나기
_PLAN6 = [
    ("zero", "Unit 0", "Single Letters", [], []),
    ("unit", "Unit 1~3", "짧은 a · e · i", [1], [("s", 2, 0), ("s", 12, 1), ("s", 5, 0)]),
    ("unit", "Unit 4~5", "짧은 o · u", [4], [("s", 13, 1), ("s", 9, 1), ("s", 3, 2)]),
    ("review", "Unit 6", "Review · Story · 단모음", [1, 4], []),
    ("unit", "Unit 7", "Teacher e", [7], [("l", 10, 0), ("l", 10, 1), ("l", 10, 2)]),
    ("unit", "Unit 8~10", "긴 a · i · o", [8], [("l", 3, 0), ("l", 5, 2), ("l", 8, 1)]),
    ("unit", "Unit 11~12", "긴 u · e", [11], [("l", 9, 0), ("l", 9, 1), ("d", 2, 1)]),
    ("game", "Speed Race", "Unit 7~12", [7, 8, 11], []),
    ("unit", "Unit 14", "sm · mp · nk", [14], ["sm", "mp", "nk"]),
    ("unit", "Unit 15", "kn · ck · ng", [15], ["kn", "ck", "ng"]),
    ("unit", "Unit 17", "ch · sh · th · wh", [17], [("c", 4, 0), ("c", 4, 1), ("c", 5, 0), ("c", 5, 1)]),
    ("unit", "Unit 18", "Bossy r · ar or er ir ur", [18], ["ar", "or", "er", "ir", "ur"]),
    ("unit", "Unit 20", "ai · ay · ea · ee", [20], [("d", 1, 0), ("d", 1, 1), ("d", 2, 0), ("d", 2, 1)]),
    ("unit", "Unit 21", "ie · igh · y · oa · ow", [21], ["ie", "igh", "y", ("d", 3, 0), ("d", 3, 1)]),
    ("unit", "Unit 22", "ou · ow · oi · oy", [22], [("d", 4, 0), ("d", 4, 1), "oi", "oy"]),
    ("review", "Check-up", "Bingo · Unit 14~22", [14, 15, 17, 18, 20, 21, 22], []),
    ("read", "Phonics Master", "Can You Read Them All? · Sight Words to Know", [], []),
]
READ6 = ["cat", "pen", "cake", "kite", "ship", "star", "rain", "boat", "coin", "night"]
SIGHT6 = ["said", "look", "come", "here", "play", "what"]
REV = []
for _i, (_kind, _name, _label, _units, _parts) in enumerate(_PLAN6):
    _fams, _sents, _new = [], [], False
    for _p in _parts:
        if isinstance(_p, str):
            _new = True
            _fams.append(_N6[_p])
            continue
        _b, _day, _fi = _p
        _d = next(x for x in _SRC[_b] if x["day"] == _day)
        _f = dict(_d["families"][_fi])
        _f["words"] = _f["words"][:4]
        if _b == "s":
            _f["name"] = f"{_d['vowel']} {_f['name']}"
        _fams.append(_f)
        _sents += [x for x in _d["sents"] if any(w[0].lower() in x["en"].lower().replace(".", "").split() for w in _f["words"])][:2]
    if _units and _units[0] in _S6:
        _sents = [{"id": f"r{_units[0]}{j + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for j, x in enumerate(_S6[_units[0]])] + _sents
    _uniq = []
    for x in _sents:
        if x["id"] not in [y["id"] for y in _uniq]:
            _uniq.append(x)
    _d6 = {"day": _i + 1, "kind": _kind, "name": _name, "label": _label, "units": _units, "vowel": "",
           "families": _fams, "sents": _uniq[:4], "meet": _new, "nomeet": _parts[:1] == [("l", 10, 0)]}
    REV.append(_d6)
REV_WORDS = [w for d in REV for f in d["families"] for w in f["words"]]
for _d in REV:
    if _d["kind"] == "unit":
        _d["items"] = [w[0] for f in _d["families"] for w in f["words"]]
    elif _d["kind"] in ("review", "game"):
        _d["items"] = [w[0] for x in REV if x["kind"] == "unit" and x["units"][0] in _d["units"] for f in x["families"] for w in f["words"]]
    elif _d["kind"] == "read":
        _d["items"] = READ6 + SIGHT6
        _d["readWords"], _d["sightWords"] = READ6, SIGHT6
    else:
        _d["items"] = list("abcdefghijklmnopqrstuvwxyz")

# ── LV1 사이트워즈 ── Dolch 315(초급 92 + 1·2·3학년 128 + 명사 95), 대개 4개씩 79세트. 원장 2026-10-30:
#   3개월차(장모음과 함께) 시작 → 10개월차 마무리, 한 달 약 10세트(주 2~3세트, 원장 11/02 "최소 300개"). 문장은 그 세트·앞 세트 단어 + 파닉스 단어로만.
BOOKS = "LV1 사이트워즈"
SIGHT = [
    (["I", "나"], ["see", "보다"], ["a", "하나의"], ["the", "그"]),
    (["can", "~할 수 있다"], ["go", "가다"], ["up", "위로"], ["down", "아래로"]),
    (["and", "그리고"], ["big", "큰"], ["little", "작은"], ["my", "나의"]),
    (["is", "~이다"], ["it", "그것"], ["in", "~ 안에"], ["to", "~로"]),
    (["red", "빨간"], ["blue", "파란"], ["yellow", "노란"], ["here", "여기"]),
    (["come", "오다"], ["look", "보다"], ["play", "놀다"], ["run", "달리다"]),
    (["me", "나를"], ["help", "돕다"], ["find", "찾다"], ["where", "어디"]),
    (["one", "하나"], ["two", "둘"], ["three", "셋"], ["jump", "뛰다"]),
    (["we", "우리"], ["you", "너"], ["not", "아니다"], ["said", "말했다"]),
    (["make", "만들다"], ["funny", "웃긴"], ["away", "멀리"], ["for", "~를 위해"]),
    (["he", "그(남자)"], ["she", "그녀"], ["they", "그들"], ["was", "~였다"]),
    (["am", "~이다"], ["are", "~이다"], ["at", "~에"], ["be", "~이 되다"]),
    (["all", "모두"], ["ate", "먹었다"], ["eat", "먹다"], ["good", "좋은"]),
    (["have", "가지다"], ["like", "좋아하다"], ["want", "원하다"], ["do", "하다"]),
    (["did", "했다"], ["get", "얻다"], ["saw", "보았다"], ["went", "갔다"]),
    (["black", "검은"], ["brown", "갈색의"], ["white", "흰"], ["pretty", "예쁜"]),
    (["this", "이것"], ["that", "저것"], ["there", "저기"], ["what", "무엇"]),
    (["no", "아니요"], ["yes", "네"], ["please", "부탁해요"], ["so", "아주"]),
    (["new", "새로운"], ["our", "우리의"], ["out", "밖으로"], ["now", "지금"]),
    (["on", "~ 위에"], ["under", "~ 아래에"], ["into", "~ 안으로"], ["with", "~와 함께"]),
    (["ran", "달렸다"], ["ride", "타다"], ["came", "왔다"], ["soon", "곧"]),
    (["four", "넷"], ["too", "~도"], ["must", "~해야 한다"], ["but", "그러나"]),
    (["well", "잘"], ["will", "~할 것이다"], ["who", "누구"], ["say", "말하다"]),
]
SIGHT_SENTS = [
    [["I see a cat.", "나는 고양이를 봐요.", "🙋🐱"], ["I see the sun.", "나는 해를 봐요.", "🙋☀️"]],
    [["I can go up.", "나는 위로 갈 수 있어요.", "🙋⬆️"], ["The cat can go down.", "고양이가 아래로 갈 수 있어요.", "🐱⬇️"]],
    [["A big dog and a little cat.", "큰 개와 작은 고양이.", "🐶🐱"], ["I see my big dog.", "나는 내 큰 개를 봐요.", "🙋🐶"]],
    [["It is in the box.", "그것은 상자 안에 있어요.", "📦"], ["I go to bed.", "나는 자러 가요.", "🛏️"]],
    [["Here is a red hat.", "여기 빨간 모자가 있어요.", "🎩🔴"], ["I see blue and yellow.", "나는 파랑과 노랑을 봐요.", "🔵🟡"]],
    [["Come and play.", "와서 같이 놀자.", "⚽"], ["Look, I can run.", "봐, 나 달릴 수 있어.", "🏃"]],
    [["Help me find my cap.", "내 모자 찾는 것 좀 도와줘.", "🧢🔍"], ["Where is my dog?", "내 개는 어디 있어요?", "🐶❓"]],
    [["I can jump one, two, three.", "하나, 둘, 셋 뛸 수 있어요.", "🦘"], ["I see two cats.", "나는 고양이 두 마리를 봐요.", "🐱🐱"]],
    [["We can play.", "우리는 놀 수 있어요.", "🧒🧒"], ["It is not red.", "그것은 빨갛지 않아요.", "❌🔴"]],
    [["Make a funny hat.", "웃긴 모자를 만들어요.", "🎩😂"], ["It is for you.", "이건 너를 위한 거야.", "🎁"]],
    [["He and she can run.", "그와 그녀는 달릴 수 있어요.", "🏃‍♂️🏃‍♀️"], ["The cat was in the box.", "고양이가 상자 안에 있었어요.", "🐱📦"]],
    [["I am big.", "나는 커요.", "💪"], ["We are at home.", "우리는 집에 있어요.", "🏠"]],
    [["We all eat cake.", "우리 모두 케이크를 먹어요.", "🎂"], ["The dog ate it.", "개가 그걸 먹었어요.", "🐶"]],
    [["I like my cat.", "나는 내 고양이가 좋아요.", "🐱❤️"], ["I want to have a dog.", "나는 개를 갖고 싶어요.", "🐶"]],
    [["I saw a fox.", "나는 여우를 봤어요.", "🦊"], ["We went to the sea.", "우리는 바다에 갔어요.", "🌊"]],
    [["I see a black cat.", "나는 검은 고양이를 봐요.", "🐈‍⬛"], ["The white rose is pretty.", "흰 장미가 예뻐요.", "🌹"]],
    [["What is this?", "이건 뭐예요?", "❓"], ["That is my bike.", "저건 내 자전거예요.", "🚲"]],
    [["Yes, please.", "네, 주세요.", "🙋"], ["No, it is so hot.", "아니요, 너무 뜨거워요.", "🔥"]],
    [["This is our new home.", "여기가 우리 새 집이에요.", "🏠✨"], ["Come out now.", "지금 밖으로 나와요.", "🚪"]],
    [["The cat is under the bed.", "고양이가 침대 아래에 있어요.", "🐱🛏️"], ["Jump into the box with me.", "나랑 같이 상자 안으로 뛰어요.", "📦"]],
    [["I ride my bike.", "나는 자전거를 타요.", "🚲"], ["The dog ran to me.", "개가 나에게 달려왔어요.", "🐶"]],
    [["I have four pens.", "나는 펜이 네 개 있어요.", "🖊️"], ["I must go too.", "나도 가야 해요.", "🏃"]],
    [["Who will play?", "누가 놀 거예요?", "⚽❓"], ["I can say it well.", "나는 그걸 잘 말할 수 있어요.", "🗣️"]],
]
# 원장 2026-11-02 "사이트워즈는 최소 300개" → Dolch 전체 315(기능어 220 + 명사 95). 24세트부터 1·2·3학년 기능어 + 명사.
SIGHT += [
    (["has", "가지고 있다"], ["his", "그의"], ["her", "그녀의"], ["ball", "공"]),
    (["him", "그를"], ["give", "주다"], ["of", "~의"], ["apple", "사과"]),
    (["an", "하나의(모음 앞)"], ["some", "조금"], ["just", "그냥·딱"], ["milk", "우유"]),
    (["from", "~에게서"], ["going", "가는 중"], ["mother", "엄마"], ["father", "아빠"]),
    (["open", "열다"], ["door", "문"], ["stop", "멈추다"], ["walk", "걷다"]),
    (["how", "어떻게·얼마나"], ["old", "나이 든·오래된"], ["as", "~만큼"], ["baby", "아기"]),
    (["know", "알다"], ["think", "생각하다"], ["when", "언제"], ["time", "시간"]),
    (["put", "놓다"], ["round", "둥근"], ["over", "~ 위로 넘어"], ["table", "탁자"]),
    (["thank", "고마워하다"], ["take", "가져가다"], ["them", "그들을"], ["cake", "케이크"]),
    (["then", "그 다음에"], ["were", "~였다(복수)"], ["after", "~ 뒤에"], ["morning", "아침"]),
    (["let", "~하게 하다"], ["live", "살다"], ["may", "~해도 된다"], ["house", "집"]),
    (["could", "~할 수 있었다"], ["every", "모든·매"], ["fly", "날다"], ["bird", "새"]),
    (["ask", "묻다"], ["by", "~ 옆에"], ["had", "가지고 있었다"], ["man", "남자"]),
    (["once", "옛날에·한 번"], ["any", "조금이라도"], ["again", "다시"], ["rabbit", "토끼"]),
    (["your", "너의"], ["very", "아주"], ["cold", "차가운"], ["water", "물"]),
    (["sit", "앉다"], ["chair", "의자"], ["sleep", "자다"], ["bed", "침대"]),
    (["these", "이것들"], ["those", "저것들"], ["shoe", "신발"], ["green", "초록색"]),
    (["sing", "노래하다"], ["song", "노래"], ["read", "읽다"], ["us", "우리를"]),
    (["first", "첫 번째"], ["best", "가장 좋은"], ["five", "다섯"], ["fish", "물고기"]),
    (["buy", "사다"], ["many", "많은"], ["toy", "장난감"], ["does", "하다(그가)"]),
    (["call", "부르다"], ["their", "그들의"], ["dog", "개"], ["wash", "씻다"]),
    (["always", "항상"], ["around", "주위에"], ["tree", "나무"], ["goes", "간다(그가)"]),
    (["because", "왜냐하면"], ["why", "왜"], ["been", "~였던"], ["sun", "해"]),
    (["before", "~ 전에"], ["made", "만들었다"], ["bread", "빵"], ["work", "일하다"]),
    (["both", "둘 다"], ["gave", "주었다"], ["girl", "소녀"], ["boy", "소년"]),
    (["don't", "~하지 마"], ["fast", "빠른"], ["car", "자동차"], ["pull", "당기다"]),
    (["found", "찾았다"], ["its", "그것의"], ["cat", "고양이"], ["off", "떨어져"]),
    (["or", "또는"], ["which", "어느"], ["wish", "바라다"], ["would", "~하겠다"]),
    (["right", "오른쪽·맞는"], ["tell", "말해 주다"], ["use", "쓰다"], ["hand", "손"]),
    (["write", "쓰다"], ["letter", "편지"], ["upon", "~ 위에"], ["name", "이름"]),
    (["draw", "그리다"], ["picture", "그림"], ["paper", "종이"], ["pick", "줍다·고르다"]),
    (["today", "오늘"], ["birthday", "생일"], ["party", "파티"], ["eight", "여덟"]),
    (["six", "여섯"], ["seven", "일곱"], ["ten", "열"], ["egg", "달걀"]),
    (["laugh", "웃다"], ["kind", "친절한"], ["together", "함께"], ["children", "아이들"]),
    (["carry", "나르다"], ["bring", "가져오다"], ["box", "상자"], ["hold", "잡다"]),
    (["clean", "깨끗이 하다"], ["floor", "바닥"], ["window", "창문"], ["done", "다 한"]),
    (["drink", "마시다"], ["much", "많이"], ["full", "배부른·가득한"], ["chicken", "닭"]),
    (["grow", "자라다"], ["seed", "씨앗"], ["garden", "정원"], ["flower", "꽃"]),
    (["fall", "넘어지다"], ["hurt", "다치다"], ["leg", "다리"], ["head", "머리"]),
    (["hot", "뜨거운"], ["warm", "따뜻한"], ["fire", "불"], ["if", "만약"]),
    (["far", "먼"], ["long", "긴"], ["street", "거리"], ["way", "길·방향"]),
    (["keep", "간직하다"], ["own", "자기 자신의"], ["myself", "나 스스로"], ["money", "돈"]),
    (["show", "보여 주다"], ["small", "작은"], ["bear", "곰"], ["try", "해 보다"]),
    (["start", "시작하다"], ["game", "게임"], ["never", "절대 ~않다"], ["only", "오직"]),
    (["better", "더 좋은"], ["shall", "~할까요"], ["got", "얻었다"], ["cut", "베인 상처·자르다"]),
    (["light", "불빛"], ["night", "밤"], ["about", "~에 대해"], ["thing", "것·물건"]),
    (["farm", "농장"], ["farmer", "농부"], ["cow", "소"], ["pig", "돼지"]),
    (["horse", "말"], ["sheep", "양"], ["duck", "오리"], ["grass", "풀"]),
    (["brother", "형·오빠·남동생"], ["sister", "언니·누나·여동생"], ["home", "집"], ["school", "학교"]),
    (["coat", "코트"], ["snow", "눈"], ["Christmas", "크리스마스"], ["Santa", "산타"]),
    (["rain", "비"], ["day", "날"], ["back", "뒤로·돌아와"], ["goodbye", "안녕(헤어질 때)"]),
    (["eye", "눈(얼굴)"], ["feet", "발들"], ["kitty", "아기 고양이"], ["ring", "반지·울리다"]),
    (["boat", "배"], ["hill", "언덕"], ["ground", "땅"], ["stick", "막대기"]),
    (["robin", "울새"], ["squirrel", "다람쥐"], ["wood", "숲"], ["top", "꼭대기"]),
    (["bell", "종"], ["watch", "손목시계"], ["men", "남자들"]),
    (["corn", "옥수수"], ["doll", "인형"], ["nest", "둥지"], ["wind", "바람"]),
]
SIGHT_SENTS += [
    [["He has a ball.", "그는 공을 가지고 있어요.", "👦⚽"], ["She has her ball.", "그녀는 자기 공을 가지고 있어요.", "👧⚽"]],
    [["Give him the apple.", "그에게 사과를 주세요.", "🍎"], ["I have a box of apples.", "나는 사과 한 상자가 있어요.", "📦🍎"]],
    [["I want some milk.", "나는 우유를 조금 원해요.", "🥛"], ["I have an apple.", "나는 사과가 하나 있어요.", "🍎"]],
    [["I am going to my mother.", "나는 엄마한테 가는 중이에요.", "👩"], ["It is from my father.", "그건 아빠가 준 거예요.", "👨🎁"]],
    [["Open the door.", "문을 열어요.", "🚪"], ["Stop and walk.", "멈추고 걸어요.", "🛑🚶"]],
    [["How old is the baby?", "아기는 몇 살이에요?", "👶❓"], ["I am as big as you.", "나는 너만큼 커요.", "🧒🧒"]],
    [["I know the time.", "나는 시간을 알아요.", "⏰"], ["When can we go? I think now.", "언제 갈 수 있어요? 지금인 것 같아요.", "🤔"]],
    [["Put it on the table.", "그것을 탁자 위에 놓아요.", "🪑"], ["The ball is round.", "공은 둥글어요.", "⚽"]],
    [["Thank you for the cake.", "케이크 고마워요.", "🎂"], ["Take them with you.", "그것들을 가지고 가요.", "🎒"]],
    [["We were up in the morning.", "우리는 아침에 일어나 있었어요.", "🌅"], ["We play after we eat.", "우리는 먹고 나서 놀아요.", "🍽️⚽"]],
    [["I live in a little house.", "나는 작은 집에 살아요.", "🏠"], ["May I come in?", "들어가도 돼요?", "🚪"]],
    [["The bird could fly.", "그 새는 날 수 있었어요.", "🐦"], ["I see a bird every morning.", "나는 매일 아침 새를 봐요.", "🐦"]],
    [["Ask the man.", "그 남자에게 물어봐요.", "👨❓"], ["The man had a dog by him.", "그 남자 옆에 개가 있었어요.", "👨🐶"]],
    [["Once there was a rabbit.", "옛날에 토끼가 있었어요.", "🐇"], ["Look again.", "다시 봐요.", "👀"]],
    [["Your water is very cold.", "네 물은 아주 차가워요.", "🥶💧"], ["Is it cold?", "그거 차가워요?", "❄️"]],
    [["Sit on the chair.", "의자에 앉아요.", "🪑"], ["I sleep in my bed.", "나는 내 침대에서 자요.", "🛏️"]],
    [["These shoes are green.", "이 신발들은 초록색이에요.", "👟🟢"], ["Those are my shoes.", "저것들이 내 신발이에요.", "👟"]],
    [["Sing a song with us.", "우리랑 같이 노래해요.", "🎤"], ["Read it to us.", "우리에게 그걸 읽어 줘요.", "📖"]],
    [["I have five fish.", "나는 물고기가 다섯 마리 있어요.", "🐟"], ["I was first!", "내가 일등이었어요!", "🥇"]],
    [["I want to buy a toy.", "나는 장난감을 사고 싶어요.", "🧸"], ["Does he have many toys?", "그는 장난감이 많아요?", "🧸❓"]],
    [["Call their dog.", "그들의 개를 불러요.", "🐶"], ["Wash the dog.", "개를 씻겨요.", "🐶🫧"]],
    [["The dog goes around the tree.", "개가 나무 주위를 돌아요.", "🐶🌳"], ["I always play.", "나는 항상 놀아요.", "⚽"]],
    [["Why do you like the sun?", "너는 왜 해가 좋아요?", "☀️❓"], ["Because it is pretty.", "예쁘니까요.", "☀️"]],
    [["I made bread.", "나는 빵을 만들었어요.", "🍞"], ["We work before we play.", "우리는 놀기 전에 일해요.", "🧹⚽"]],
    [["The boy and the girl play.", "소년과 소녀가 놀아요.", "👦👧"], ["I gave a toy to both.", "나는 둘 다에게 장난감을 주었어요.", "🧸"]],
    [["The car is fast.", "자동차가 빨라요.", "🚗💨"], ["Don't pull it.", "그거 당기지 마요.", "🙅"]],
    [["I found a cat.", "나는 고양이를 찾았어요.", "🐱"], ["The cat is off its bed.", "고양이가 자기 침대에서 내려왔어요.", "🐱🛏️"]],
    [["Which one would you like?", "어느 것이 좋아요?", "🤔"], ["Is it red or blue?", "그건 빨강이에요, 파랑이에요?", "🔴🔵"]],
    [["Use your right hand.", "오른손을 써요.", "✋"], ["Tell me.", "나에게 말해 줘요.", "🗣️"]],
    [["Write your name.", "네 이름을 써요.", "✍️"], ["Once upon a time, a cat had a letter.", "옛날 옛적에 고양이에게 편지가 있었어요.", "🐱💌"]],
    [["Draw a picture.", "그림을 그려요.", "🖍️"], ["Pick up the paper.", "종이를 주워요.", "📄"]],
    [["Today is my birthday.", "오늘은 내 생일이에요.", "🎂"], ["I am eight. Come to my party!", "나는 여덟 살이에요. 내 파티에 와요!", "🎉"]],
    [["I have ten eggs.", "나는 달걀이 열 개 있어요.", "🥚"], ["Six, seven, eight!", "여섯, 일곱, 여덟!", "🔢"]],
    [["The children laugh together.", "아이들이 함께 웃어요.", "😂"], ["Be kind.", "친절하게 대해요.", "💛"]],
    [["Bring the box.", "상자를 가져와요.", "📦"], ["Can you carry it? Hold it.", "그거 나를 수 있어요? 잡아요.", "💪"]],
    [["Clean the floor.", "바닥을 깨끗이 해요.", "🧹"], ["Look out the window. I am done!", "창밖을 봐요. 다 했어요!", "🪟"]],
    [["Drink your milk.", "우유를 마셔요.", "🥛"], ["I ate too much chicken. I am full.", "나는 닭고기를 너무 많이 먹었어요. 배불러요.", "🍗"]],
    [["A seed can grow.", "씨앗은 자랄 수 있어요.", "🌱"], ["I see a flower in the garden.", "나는 정원에서 꽃을 봐요.", "🌷"]],
    [["I fall and hurt my leg.", "나는 넘어져서 다리를 다쳐요.", "🦵"], ["My head is big.", "내 머리는 커요.", "🙆"]],
    [["The fire is hot.", "불이 뜨거워요.", "🔥"], ["If it is cold, I like it warm.", "추우면 나는 따뜻한 게 좋아요.", "🧣"]],
    [["The street is long.", "그 거리는 길어요.", "🛣️"], ["Is it far? Go this way.", "멀어요? 이쪽으로 가요.", "➡️"]],
    [["I keep my own money.", "나는 내 돈을 간직해요.", "💰"], ["I can do it myself.", "나는 그걸 스스로 할 수 있어요.", "💪"]],
    [["Show me the small bear.", "작은 곰을 보여 줘요.", "🧸"], ["Try it!", "해 봐요!", "👍"]],
    [["Start the game.", "게임을 시작해요.", "🎮"], ["I only want one.", "나는 하나만 원해요.", "☝️"]],
    [["Shall we go?", "우리 갈까요?", "🚶"], ["I got a cut. It is better now.", "베였어요. 이제 좀 나아요.", "🩹"]],
    [["I see the light at night.", "나는 밤에 불빛을 봐요.", "💡🌃"], ["What is that thing?", "저 물건은 뭐예요?", "❓"]],
    [["The farmer has a cow.", "농부는 소가 있어요.", "👨‍🌾🐄"], ["I see a pig on the farm.", "나는 농장에서 돼지를 봐요.", "🐷"]],
    [["The sheep eat grass.", "양들이 풀을 먹어요.", "🐑🌿"], ["I see a duck and a horse.", "나는 오리와 말을 봐요.", "🦆🐎"]],
    [["My brother goes to school.", "우리 형은 학교에 가요.", "🏫"], ["My sister is at home.", "우리 언니는 집에 있어요.", "🏠"]],
    [["Santa has a red coat.", "산타는 빨간 코트를 입어요.", "🎅"], ["I see snow at Christmas.", "크리스마스에 눈을 봐요.", "❄️🎄"]],
    [["I like the rain.", "나는 비가 좋아요.", "🌧️"], ["Goodbye! Come back some day.", "안녕! 언젠가 다시 와요.", "👋"]],
    [["The kitty has big eyes.", "아기 고양이는 눈이 커요.", "🐱👀"], ["I have two feet.", "나는 발이 두 개 있어요.", "🦶🦶"]],
    [["Run up the hill.", "언덕 위로 달려요.", "⛰️"], ["Put the stick on the ground.", "막대기를 땅에 놓아요.", "🪵"]],
    [["A robin is on top of the tree.", "울새가 나무 꼭대기에 있어요.", "🐦🌳"], ["The squirrel is in the wood.", "다람쥐가 숲에 있어요.", "🐿️🌲"]],
    [["The men ring the bell.", "남자들이 종을 울려요.", "🔔"], ["Look at my watch.", "내 손목시계를 봐요.", "⌚"]],
    [["The bird is in the nest.", "새가 둥지에 있어요.", "🪺"], ["My doll and I eat corn in the wind.", "인형이랑 나는 바람 속에서 옥수수를 먹어요.", "🌬️🌽🪆"]],
]
SIGHT_DAYS = [{"day": i + 1, "words": [list(w) for w in ws],
               "sents": [{"id": f"w{i + 1}{j + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for j, x in enumerate(SIGHT_SENTS[i])]}
              for i, ws in enumerate(SIGHT)]
SIGHT_WORDS = [w for d in SIGHT_DAYS for w in d["words"]]


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
    for d in SHORT:
        for x in d["sents"]:
            t[f"sent-{x['id']}"] = f'<prosody rate="-20%">{x["en"]}</prosody>'
    for w in LONG_WORDS:
        t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for d in LONG:
        for x in d["sents"]:
            t[f"sent-{x['id']}"] = f'<prosody rate="-20%">{x["en"]}</prosody>'
    slow = lambda x: f'<prosody rate="-25%">{x}</prosody>'
    for k, (ipa, _ko) in LONG_SND.items():
        t[f"lv-{k}"] = slow(_ph(ipa, "a"))
    for d in [x for x in LONG if x["kind"] == "unit" and not x.get("nomeet")]:   # 긴 소리 노래: "Long A. A says eɪ, eɪ, bake!"
        v, ipa = d["vowel"], LONG_SND[d["snd"]][0]
        key = d["families"][0]["words"][0][0]
        t[f"lchant-{v}"] = (slow(f"Long {v.upper()}.") + '<break time="600ms"/>' + slow(f"{v.upper()} says") +
                            '<break time="700ms"/>' + slow(_ph(ipa, v)) + '<break time="600ms"/>' + slow(_ph(ipa, v)) +
                            '<break time="700ms"/>' + slow(f"{key}!"))
    for w in CONS_WORDS:
        t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for d in CONS:
        for x in d["sents"]:
            t[f"sent-{x['id']}"] = f'<prosody rate="-20%">{x["en"]}</prosody>'
    for k, (ipa, _ko) in DIGRAPH_SND.items():
        t[f"dg-{k}"] = f'<prosody rate="-25%">{_ph(ipa, k)}</prosody>'
    for w in SIGHT_WORDS:
        t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for d in SIGHT_DAYS:
        for x in d["sents"]:
            t[f"sent-{x['id']}"] = f'<prosody rate="-20%">{x["en"]}</prosody>'
    for w in DIPH_WORDS:
        t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for d in DIPH:
        for x in d["sents"]:
            t[f"sent-{x['id']}"] = f'<prosody rate="-20%">{x["en"]}</prosody>'
    for w in REV_WORDS:
        t[f"word-{w[0]}"] = f'<prosody rate="-10%">{w[0]}</prosody>'
    for d in REV:
        for x in d["sents"]:
            t[f"sent-{x['id']}"] = f'<prosody rate="-20%">{x["en"]}</prosody>'
    for k, (ipa, _ko) in DV_SND.items():
        t[f"dv-{k}"] = f'<prosody rate="-25%">{_ph(ipa, k)}</prosody>'
    # wind 는 혼자 두면 '와인드(감다)'로 읽힐 수 있다 → 바람(윈드)으로 못 박는다
    t["word-wind"] = f'<prosody rate="-10%">{_ph("wɪnd", "wind")}</prosody>'
    for i, ok in enumerate(["Great job!", "Good try!"]):
        t[f"fb-{i}"] = ok
    return t


AUDIO = _audio_table()


def _templates():
    """보관함 원본: Day 1~9 + 진급시험. id 를 고정해 두어 몇 번 떠도 한 벌만 생긴다."""
    rows = []
    for d in DAYS:
        rows.append({"id": f"phx-lv1-1-d{d['day']:02d}", "title": f"{BOOK} {BOOK_NAME} Day {d['day']} ({d['name']}: {d['label']})",
                     "book": BOOK, "type": "phonics", "phonicsDay": d["day"], "items": d["items"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-1-exam", "title": f"{BOOK} {BOOK_NAME} 진급시험", "book": BOOK,
                 "type": "exam", "kind": "phonics", "items": _ORDER, "meanings": [], "passScore": 70,
                 "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [], "exampleAudio": [],
                 "recordMode": "each", "published": False})
    for d in SHORT:
        fam = " / ".join(f["name"] for f in d["families"])
        rows.append({"id": f"phx-lv1-2-d{d['day']:02d}",
                     "title": f"{BOOK2} {BOOK2_NAME} Day {d['day']} ({d['name']}: {d['label']}{' · ' + fam if fam else ''})",
                     "book": BOOK2, "type": "phonics", "phonicsDay": d["day"],
                     "items": d["items"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    for d in LONG:
        fam = " / ".join(f["name"] for f in d["families"])
        rows.append({"id": f"phx-lv1-3-d{d['day']:02d}",
                     "title": f"{BOOK3} {BOOK3_NAME} Day {d['day']} ({d['name']}: {d['label']}{' · ' + fam if fam else ''})",
                     "book": BOOK3, "type": "phonics", "phonicsDay": d["day"],
                     "items": d["items"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-3-exam", "title": f"{BOOK3} {BOOK3_NAME} 진급시험", "book": BOOK3,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in LONG_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                 "exampleAudio": [], "recordMode": "each", "published": False})
    for d in CONS:
        rows.append({"id": f"phx-lv1-4-d{d['day']:02d}", "title": f"{BOOK4} {BOOK4_NAME} Day {d['day']} ({d['name']}: {d['label']})",
                     "book": BOOK4, "type": "phonics", "phonicsDay": d["day"],
                     "items": d["items"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-4-exam", "title": f"{BOOK4} {BOOK4_NAME} 진급시험", "book": BOOK4,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in CONS_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                 "exampleAudio": [], "recordMode": "each", "published": False})
    for d in SIGHT_DAYS:
        rows.append({"id": f"phx-lv1-s-d{d['day']:02d}", "book": BOOKS, "type": "phonics", "phonicsDay": d["day"],
                     "title": f"{BOOKS} Day {d['day']} ({' · '.join(w[0] for w in d['words'])})",
                     "items": [w[0] for w in d["words"]],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-s-exam", "title": f"{BOOKS} 마무리 시험", "book": BOOKS,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in SIGHT_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                 "exampleAudio": [], "recordMode": "each", "published": False})
    for d in DIPH:
        rows.append({"id": f"phx-lv1-5-d{d['day']:02d}", "title": f"{BOOK5} {BOOK5_NAME} Day {d['day']} ({d['name']}: {d['label']})",
                     "book": BOOK5, "type": "phonics", "phonicsDay": d["day"],
                     "items": d["items"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-5-exam", "title": f"{BOOK5} {BOOK5_NAME} 진급시험", "book": BOOK5,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in DIPH_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                 "exampleAudio": [], "recordMode": "each", "published": False})
    for d in REV:
        rows.append({"id": f"phx-lv1-6-d{d['day']:02d}", "title": f"{BOOK6} {BOOK6_NAME} Day {d['day']} ({d['name']}: {d['label']})",
                     "book": BOOK6, "type": "phonics", "phonicsDay": d["day"],
                     "items": d["items"],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-6-exam", "title": f"LV1 파닉스 졸업 시험", "book": BOOK6,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in REV_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
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


# 소리 하나(snd-·lv-)는 크기를 맞춘다(원장 2026-10-30 "day 에서 ㄷ 소리가 너무 작아").
#   실측: 모음 '에이' 최대 -6dB 인데 ㄷ -21·ㅂ -26·ㄱ -26·ㅋ -25dB — 떼어 낸 자음은 4~8배 작게 나온다.
#   모양은 그대로 두고 가장 큰 소리를 -2dB 로 끌어올린다(+24dB 까지). NORM_TAG 를 바꾸면 다시 만들어진다.
NORM_TAG = "|peak3-mean-17x2"


def _needs_norm(aid):
    return aid.startswith(("snd-", "lv-", "dg-", "dv-"))   # dg-(sh·ch·th·ng): th 가 -40dB 로 거의 안 들렸다


def _normalize(data: bytes) -> bytes:
    """낱소리(snd·lv·dg·dv) 크기를 '소리 나는 부분의 평균'으로 맞춘다.
    최고점(-2dB)만 맞추던 때는 기차 칸 'ㅋ · 에이 · ㅋ' 가 칸마다 크게·작게 들렸다(원장 2026-11-02) —
    터지는 자음(b·g·k)은 순간 최고점만 높아 평균이 -24~-32, 모음·m·n 은 -11~-15 로 21dB 차이.
    평균을 -17dB 로 올리고 리미터로 찢어짐을 막는다. 리미터가 깎은 만큼 한 번 더."""
    import re as _re, subprocess, tempfile, os as _os
    src = dst = None
    TARGET = -17.0

    def mean_of(path):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                            "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_threshold=-45dB,volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=30)
        m = _re.search(r"mean_volume: (-?[0-9.]+) dB", r.stderr or "")
        return float(m.group(1)) if m else None

    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(data); src = f.name
        cur, out = src, None
        # 0) 최고점부터 -3dB 로 — th·h·v 원본은 최고점 -40dB 라 무음 자르기(-45dB)에 통째로 잘려 평균을 못 쟀다
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", src, "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=30)
        m = _re.search(r"max_volume: (-?[0-9.]+) dB", r.stderr or "")
        if m and float(m.group(1)) < -3.5:
            dst = f"{src}.p.mp3"
            r = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", src, "-af", f"volume={min(45.0, -3.0 - float(m.group(1))):.1f}dB",
                                "-codec:a", "libmp3lame", "-b:a", "64k", dst], capture_output=True, timeout=30)
            if r.returncode == 0:
                cur = out = dst
        for k in range(2):
            mv = mean_of(cur)
            if mv is None:
                break
            gain = max(-12.0, min(40.0, TARGET - mv))   # th(θ)·h 는 크게 올려야 한다
            if abs(gain) <= 0.7:
                break
            dst = f"{src}.{k}.mp3"
            r = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", cur, "-af",
                                f"volume={gain:.1f}dB,alimiter=limit=0.89:attack=2:release=30:level=false",
                                "-codec:a", "libmp3lame", "-b:a", "64k", dst], capture_output=True, timeout=30)
            if r.returncode != 0:
                break
            if out and out != src:
                try: _os.remove(out)
                except OSError: pass
            cur = out = dst
        if not out:
            return data
        with open(out, "rb") as f:
            return f.read()
    except Exception as e:
        print("[phonics] 음량 맞추기 실패(원본 사용):", e)
        return data
    finally:
        for x in (src, dst, f"{src}.p.mp3" if src else None, f"{src}.0.mp3" if src else None):
            if x:
                try: _os.unlink(x)
                except Exception: pass


def make_router(*, data_dir: Path, azure_key, azure_region, run_assessment,
                lock, load_db, save_db, load_db_ro, load_student_subs, load_exam, exam_report):
    r = APIRouter()
    audio_dir = Path(data_dir) / "phonics" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 보관함 원본 넣기(없는 것만). 실패해도 서버는 떠야 한다.
    try:
        with lock:
            db = load_db()
            have = {a.get("id"): a for a in db["assignments"]}
            new = [a for a in _templates() if a["id"] not in have]
            # 아직 아무에게도 안 나간 원본은 내용(제목·단어)을 지금 데이터로 맞춘다(단어를 바꿨을 때 — 10/30 top→hop)
            fixed = 0
            for t in _templates():
                o = have.get(t["id"])
                if o and o.get("published") is False and not o.get("assignedIds") and                         (o.get("items") != t["items"] or o.get("title") != t["title"]):
                    o["items"], o["title"] = t["items"], t["title"]; fixed += 1
            if new or fixed:
                db["assignments"].extend(new)
                save_db(db)
                print(f"[phonics] 보관함 파닉스 원본 새로 {len(new)}개 · 고침 {fixed}개")
    except Exception as e:
        print("[phonics] 보관함 원본 넣기 실패:", e)

    def _path(aid):
        # 대본을 고치면 이름이 바뀌어 새로 만든다
        h = hashlib.sha1((VOICE + AUDIO[aid] + (NORM_TAG if _needs_norm(aid) else "")).encode("utf-8")).hexdigest()[:10]
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
        ver = hashlib.sha1((VOICE + NORM_TAG + json.dumps(AUDIO, sort_keys=True)).encode("utf-8")).hexdigest()[:8]
        return {"letters": LETTERS, "days": DAYS, "book": BOOK, "bookName": BOOK_NAME, "audioVer": ver,
                "short": {"book": BOOK2, "bookName": BOOK2_NAME, "days": SHORT, "vowelKey": VOWEL_KEY},
                "long": {"book": BOOK3, "bookName": BOOK3_NAME, "days": LONG,
                         "snd": {k: v[1] for k, v in LONG_SND.items()}},
                "cons": {"book": BOOK4, "bookName": BOOK4_NAME, "days": CONS,
                         "snd": {k: v[1] for k, v in LONG_SND.items()},
                         "dg": {k: v[1] for k, v in DIGRAPH_SND.items()},
                         "dv": {k: v[1] for k, v in DV_SND.items()}},
                "sight": {"book": BOOKS, "bookName": "사이트워즈", "days": SIGHT_DAYS},
                "rev": {"book": BOOK6, "bookName": BOOK6_NAME, "days": REV,
                        "snd": {k: v[1] for k, v in LONG_SND.items()},
                        "dg": {k: v[1] for k, v in DIGRAPH_SND.items()},
                        "dv": {k: v[1] for k, v in DV_SND.items()}},
                "diph": {"book": BOOK5, "bookName": BOOK5_NAME, "days": DIPH,
                         "snd": {k: v[1] for k, v in LONG_SND.items()},
                         "dg": {k: v[1] for k, v in DIGRAPH_SND.items()},
                         "dv": {k: v[1] for k, v in DV_SND.items()}}}

    @r.get("/api/phonics/audio/{aid}.mp3")
    def audio(aid: str):
        if aid not in AUDIO:
            raise HTTPException(404, "없는 소리예요.")
        p = _path(aid)
        if not p.exists():
            tmp = p.with_suffix(".part")
            data = _synth(aid)
            tmp.write_bytes(_normalize(data) if _needs_norm(aid) else data)
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
        ALLB = (BOOK, BOOK2, BOOK3, BOOK4, BOOK5, BOOK6, BOOKS)
        books = sorted({a.get("book") for a in db["assignments"] if a.get("book") in ALLB and mine(a)})
        book = book if book in ALLB else ([b for b in books if b != BOOKS] or books or [BOOK])[-1]
        rows = [a for a in db["assignments"] if a.get("book") == book and mine(a)]
        if book == BOOKS:
            keys = [w[0] for w in SIGHT_WORDS]
            groups = [{"name": f"세트 {d['day']}", "vowel": "", "keys": [w[0] for w in d["words"]]} for d in SIGHT_DAYS]
            info = {w[0]: {"ko": w[1], "emoji": ""} for w in SIGHT_WORDS}
        elif book in (BOOK2, BOOK3, BOOK4, BOOK5, BOOK6):
            DD, WW = {BOOK2: (SHORT, SHORT_WORDS), BOOK3: (LONG, LONG_WORDS), BOOK4: (CONS, CONS_WORDS),
                      BOOK5: (DIPH, DIPH_WORDS), BOOK6: (REV, REV_WORDS)}[book]
            keys = [w[0] for w in WW]
            groups = [{"name": (f"{d['vowel']}  {f['name']}" if book == BOOK2 else f"{d['label']}  {f['name']}" if book == BOOK3 else f['name']),
                       "vowel": d["vowel"], "keys": [w[0] for w in f["words"]]}
                      for d in DD for f in d["families"]]
            info = {w[0]: {"ko": w[1], "emoji": w[2]} for w in WW}
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
                             "chart": ph.get("chart"),   # 복습 소리표 녹음 {url, at, n, mode, sec}
                             "sents": ph.get("sents") or {}})   # 문장 읽기 {id: {en, score, url, at}}

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
                "book": book, "bookName": {BOOK2: BOOK2_NAME, BOOK3: BOOK3_NAME, BOOK4: BOOK4_NAME, BOOK5: BOOK5_NAME, BOOK6: BOOK6_NAME, BOOKS: "사이트워즈"}.get(book, BOOK_NAME), "books": books,
                "days": day_rows, "letters": letters, "groups": groups, "info": info,
                "areas": areas, "exam": exam_out}

    return r
