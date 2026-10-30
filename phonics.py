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
        {"name": "-op · -ox", "words": [["hop", "깡충 뛰다", "🐇"], ["mop", "대걸레", "🧹"], ["box", "상자", "📦"], ["fox", "여우", "🦊"]]}]},
    {"day": 5, "vowel": "u", "families": [
        {"name": "-un", "words": [["sun", "해", "☀️"], ["run", "달리다", "🏃‍♂️"], ["bun", "빵", "🍞"], ["fun", "재미있는", "🎉"]]},
        {"name": "-ug", "words": [["bug", "벌레", "🐛"], ["hug", "안아 주다", "🤗"], ["mug", "머그컵", "☕"], ["jug", "주전자", "🫖"]]},
        {"name": "-ut · -up", "words": [["nut", "견과", "🥜"], ["cut", "자르다", "✂️"], ["cup", "컵", "🥤"], ["pup", "강아지", "🐕"]]}]},
]
SHORT_WORDS = [w for d in SHORT for f in d["families"] for w in f["words"]]

# 모음별 문장(원장 2026-10-30 "단모음별 문장 만들기 & 녹음 & 퀴즈") — 그날 단어 + 쉬운 낱말만
SENTS = {
    "a": [["The cat has a hat.", "고양이가 모자를 가졌어요.", "🐱🎩"], ["A man has a fan.", "남자가 부채를 가졌어요.", "👨🪭"],
          ["The bat is on the map.", "박쥐가 지도 위에 있어요.", "🦇🗺️"], ["The rat is in the bag.", "쥐가 가방 안에 있어요.", "🐀👜"]],
    "e": [["The hen is on the bed.", "암탉이 침대 위에 있어요.", "🐔🛏️"], ["The jet is red.", "제트기가 빨개요.", "✈️🔴"],
          ["The vet has a pen.", "수의사가 펜을 가졌어요.", "🩺🖊️"], ["Ten men get wet.", "남자 열 명이 젖어요.", "👬💦"]],
    "i": [["The pig is big.", "돼지가 커요.", "🐷🐘"], ["A pig can dig.", "돼지가 땅을 팔 수 있어요.", "🐷⛏️"],
          ["The pin is in the bin.", "핀이 통 안에 있어요.", "📍🗑️"], ["I can fix it.", "나는 그걸 고칠 수 있어요.", "🙋🔧"]],
    "o": [["The fox is in the box.", "여우가 상자 안에 있어요.", "🦊📦"], ["The dog is on the log.", "개가 통나무 위에 있어요.", "🐶🪵"],
          ["The pot is hot.", "냄비가 뜨거워요.", "🍲🔥"], ["I can jog.", "나는 달릴 수 있어요.", "🙋🏃"]],
    "u": [["The bug is in the mug.", "벌레가 컵 안에 있어요.", "🐛☕"], ["The sun is hot.", "해가 뜨거워요.", "☀️🔥"],
          ["A pup can run.", "강아지가 달릴 수 있어요.", "🐕🏃‍♂️"], ["I hug the pup.", "나는 강아지를 안아요.", "🤗🐕"]],
}
for _d in SHORT:
    _d["sents"] = [{"id": f"s{_d['vowel']}{i + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for i, x in enumerate(SENTS[_d["vowel"]])]


# ── LV1 3권 장모음 ── 원장 범위(a-e ai ay / i-e ie igh / o-e oe oa ow / u-e ue ui / ee ea), 같은 긴 소리끼리 하루.
#   단어 [단어, 뜻, 그림, 조각]: 조각 '|' 로 나눔, ':L' = 그날 긴 소리, ':s' = 그 글자 소리, 끝 '*' = 소리 안 나는 e.
#   팀(ai·igh…)은 한 칸, 매직 e 는 회색 칸. snd = 긴 소리 음원 키(lv-<snd>).
BOOK3 = "LV1 3권"
BOOK3_NAME = "장모음"
LONG_SND = {"a": ("eɪ", "에이"), "i": ("aɪ", "아이"), "o": ("oʊ", "오우"), "u": ("uː", "우-"), "yu": ("juː", "유-"), "e": ("iː", "이-")}
LONG = [
    {"day": 1, "vowel": "a", "snd": "a", "families": [
        {"name": "a_e", "pat": "a_e", "words": [["cake", "케이크", "🎂", "c|a:L|k|e*"], ["game", "게임", "🎮", "g|a:L|m|e*"],
                                               ["cape", "망토", "🦸", "c|a:L|p|e*"], ["vase", "꽃병", "🏺", "v|a:L|s|e*"]]},
        {"name": "ai", "pat": "ai", "words": [["rain", "비", "🌧️", "r|ai:L|n"], ["mail", "편지", "📬", "m|ai:L|l"],
                                             ["nail", "손톱", "💅", "n|ai:L|l"], ["paint", "물감", "🎨", "p|ai:L|n|t"]]},
        {"name": "ay", "pat": "ay", "words": [["day", "날", "📅", "d|ay:L"], ["hay", "건초", "🌾", "h|ay:L"],
                                             ["pay", "돈을 내다", "💰", "p|ay:L"], ["say", "말하다", "🗣️", "s|ay:L"]]}]},
    {"day": 2, "vowel": "i", "snd": "i", "families": [
        {"name": "i_e", "pat": "i_e", "words": [["bike", "자전거", "🚲", "b|i:L|k|e*"], ["kite", "연", "🪁", "k|i:L|t|e*"],
                                               ["five", "다섯", "5️⃣", "f|i:L|v|e*"], ["pine", "소나무", "🌲", "p|i:L|n|e*"]]},
        {"name": "ie", "pat": "ie", "words": [["pie", "파이", "🥧", "p|ie:L"], ["tie", "넥타이", "👔", "t|ie:L"],
                                             ["lie", "거짓말하다", "🤥", "l|ie:L"]]},
        {"name": "igh", "pat": "igh", "words": [["night", "밤", "🌙", "n|igh:L|t"], ["light", "불빛", "💡", "l|igh:L|t"],
                                               ["right", "오른쪽", "👉", "r|igh:L|t"], ["high", "높은", "🔝", "h|igh:L"]]}]},
    {"day": 3, "vowel": "o", "snd": "o", "families": [
        {"name": "o_e", "pat": "o_e", "words": [["rose", "장미", "🌹", "r|o:L|s|e*"], ["bone", "뼈다귀", "🦴", "b|o:L|n|e*"],
                                               ["home", "집", "🏠", "h|o:L|m|e*"], ["rope", "밧줄", "🪢", "r|o:L|p|e*"]]},
        {"name": "oe", "pat": "oe", "words": [["toe", "발가락", "🦶", "t|oe:L"], ["doe", "암사슴", "🦌", "d|oe:L"],
                                             ["hoe", "괭이", "⛏️", "h|oe:L"]]},
        {"name": "oa", "pat": "oa", "words": [["boat", "배", "⛵", "b|oa:L|t"], ["goat", "염소", "🐐", "g|oa:L|t"],
                                             ["coat", "코트", "🧥", "c|oa:L|t"], ["soap", "비누", "🧼", "s|oa:L|p"]]},
        {"name": "ow", "pat": "ow", "words": [["bow", "리본", "🎀", "b|ow:L"], ["row", "노를 젓다", "🚣", "r|ow:L"],
                                             ["bowl", "그릇", "🥣", "b|ow:L|l"], ["low", "낮은", "⬇️", "l|ow:L"]]}]},
    {"day": 4, "vowel": "u", "snd": "u", "families": [
        {"name": "u_e", "pat": "u_e", "snd": "yu", "words": [["cube", "정육면체", "🧊", "c|u:L|b|e*"], ["cute", "귀여운", "🥰", "c|u:L|t|e*"],
                                                            ["mule", "노새", "🫏", "m|u:L|l|e*"], ["huge", "아주 큰", "🦣", "h|u:L|g:j|e*"]]},
        {"name": "ue", "pat": "ue", "words": [["blue", "파란색", "🔵", "b|l|ue:L"], ["glue", "풀", "🧴", "g|l|ue:L"],
                                             ["clue", "단서", "🔍", "c|l|ue:L"], ["true", "진짜인", "✔️", "t|r|ue:L"]]},
        {"name": "ui", "pat": "ui", "words": [["suit", "정장", "🤵", "s|ui:L|t"], ["fruit", "과일", "🍎", "f|r|ui:L|t"],
                                             ["juice", "주스", "🧃", "j|ui:L|c:s|e*"]]}]},
    {"day": 5, "vowel": "e", "snd": "e", "families": [
        {"name": "ee", "pat": "ee", "words": [["bee", "벌", "🐝", "b|ee:L"], ["feet", "발", "🦶", "f|ee:L|t"],
                                             ["seed", "씨앗", "🌱", "s|ee:L|d"], ["jeep", "지프차", "🚙", "j|ee:L|p"]]},
        {"name": "ea", "pat": "ea", "words": [["tea", "차", "🍵", "t|ea:L"], ["sea", "바다", "🌊", "s|ea:L"],
                                             ["meat", "고기", "🥩", "m|ea:L|t"], ["bean", "콩", "🫘", "b|ea:L|n"]]}]},
]
LONG_SENTS = {
    1: [["I see the rain.", "나는 비를 봐요.", "🙋🌧️"], ["My cape is in the rain.", "내 망토가 비를 맞아요.", "🦸🌧️"],
        ["I can paint my nail.", "나는 손톱을 칠할 수 있어요.", "🎨💅"], ["I pay for the cake.", "나는 케이크 값을 내요.", "💰🎂"]],
    2: [["I see a kite at night.", "나는 밤에 연을 봐요.", "🪁🌙"], ["The light is on.", "불이 켜져 있어요.", "💡"],
        ["My tie is red.", "내 넥타이는 빨개요.", "👔🔴"], ["I see five pies.", "나는 파이 다섯 개를 봐요.", "5️⃣🥧"]],
    3: [["The goat has a coat.", "염소가 코트를 입었어요.", "🐐🧥"], ["I see a boat.", "나는 배를 봐요.", "🙋⛵"],
        ["My dog has a bone.", "내 개는 뼈다귀가 있어요.", "🐶🦴"], ["The rose is at home.", "장미가 집에 있어요.", "🌹🏠"]],
    4: [["The cube is blue.", "큐브가 파래요.", "🧊🔵"], ["I see a cute mule.", "나는 귀여운 노새를 봐요.", "🥰🫏"],
        ["The glue is on my suit.", "풀이 내 정장에 묻었어요.", "🧴🤵"], ["I get juice and fruit.", "나는 주스와 과일을 받아요.", "🧃🍎"]],
    5: [["I see a bee.", "나는 벌을 봐요.", "🙋🐝"], ["The tea is hot.", "차가 뜨거워요.", "🍵🔥"],
        ["The bee is on the seed.", "벌이 씨앗 위에 있어요.", "🐝🌱"], ["I see the sea.", "나는 바다를 봐요.", "🙋🌊"]],
}
for _d in LONG:
    for _f in _d["families"]:
        _f.setdefault("snd", _d["snd"])
    _d["sents"] = [{"id": f"l{_d['day']}{i + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for i, x in enumerate(LONG_SENTS[_d["day"]])]
LONG_WORDS = [w for d in LONG for f in d["families"] for w in f["words"]]

# ── LV1 4권 이중자음 ── 블렌드(bl·cr·st…)와 이중자(sh·ch·th·wh·ck·ng), 하루 패턴 3개, 7일.
#   조각 태그: :La/:Li/:Lo/:Lu/:Lyu/:Le = 긴 소리, :sh/:ch/:th/:ng = 이중자 소리(dg-), :k/:s/:l/:z/:w = 그 글자 소리,
#   태그 없으면 글자 소리(모음은 짧은 소리), * = 소리 안 나는 e.
BOOK4 = "LV1 4권"
BOOK4_NAME = "이중자음"
DIGRAPH_SND = {"sh": ("ʃ", "쉬"), "ch": ("tʃ", "취"), "th": ("θ", "쓰"), "ng": ("ŋ", "응")}
CONS = [
    {"day": 1, "kind": "l 블렌드", "families": [
        {"name": "bl", "pat": "bl", "words": [["block", "블록", "🧱", "b|l|o|ck:k"], ["black", "검은색", "⬛", "b|l|a|ck:k"],
                                             ["blue", "파란색", "🔵", "b|l|ue:Lu"], ["blow", "불다", "🌬️", "b|l|ow:Lo"]]},
        {"name": "cl", "pat": "cl", "words": [["clap", "박수 치다", "👏", "c|l|a|p"], ["clock", "시계", "🕰️", "c|l|o|ck:k"],
                                             ["clip", "클립", "📎", "c|l|i|p"], ["class", "반", "🏫", "c|l|a|ss:s"]]},
        {"name": "pl", "pat": "pl", "words": [["plug", "플러그", "🔌", "p|l|u|g"], ["plant", "식물", "🪴", "p|l|a|n|t"],
                                             ["plate", "접시", "🍽️", "p|l|a:La|t|e*"], ["play", "놀다", "⚽", "p|l|ay:La"]]}]},
    {"day": 2, "kind": "l 블렌드", "families": [
        {"name": "fl", "pat": "fl", "words": [["flag", "깃발", "🚩", "f|l|a|g"], ["flame", "불꽃", "🔥", "f|l|a:La|m|e*"],
                                             ["flute", "플루트", "🪈", "f|l|u:Lu|t|e*"], ["flip", "뒤집다", "🤸", "f|l|i|p"]]},
        {"name": "gl", "pat": "gl", "words": [["glass", "유리컵", "🥛", "g|l|a|ss:s"], ["globe", "지구본", "🌍", "g|l|o:Lo|b|e*"],
                                             ["glue", "풀", "🧴", "g|l|ue:Lu"], ["glad", "기쁜", "😊", "g|l|a|d"]]},
        {"name": "sl", "pat": "sl", "words": [["sled", "썰매", "🛷", "s|l|e|d"], ["slide", "미끄럼틀", "🛝", "s|l|i:Li|d|e*"],
                                             ["sleep", "자다", "😴", "s|l|ee:Le|p"], ["slug", "민달팽이", "🐌", "s|l|u|g"]]}]},
    {"day": 3, "kind": "r 블렌드", "families": [
        {"name": "br", "pat": "br", "words": [["brick", "벽돌", "🧱", "b|r|i|ck:k"], ["bride", "신부", "👰", "b|r|i:Li|d|e*"],
                                             ["brain", "뇌", "🧠", "b|r|ai:La|n"]]},
        {"name": "cr", "pat": "cr", "words": [["crab", "게", "🦀", "c|r|a|b"], ["crane", "기중기", "🏗️", "c|r|a:La|n|e*"],
                                             ["crow", "까마귀", "🐦‍⬛", "c|r|ow:Lo"], ["crib", "아기 침대", "🛏️", "c|r|i|b"]]},
        {"name": "dr", "pat": "dr", "words": [["drum", "북", "🥁", "d|r|u|m"], ["dress", "드레스", "👗", "d|r|e|ss:s"],
                                             ["drip", "똑똑 떨어지다", "💧", "d|r|i|p"], ["drive", "운전하다", "🚗", "d|r|i:Li|v|e*"]]}]},
    {"day": 4, "kind": "r 블렌드", "families": [
        {"name": "fr", "pat": "fr", "words": [["frog", "개구리", "🐸", "f|r|o|g"], ["fruit", "과일", "🍎", "f|r|ui:Lu|t"],
                                             ["free", "공짜의", "🆓", "f|r|ee:Le"]]},
        {"name": "gr", "pat": "gr", "words": [["grapes", "포도", "🍇", "g|r|a:La|p|e*|s"], ["green", "초록색", "🟢", "g|r|ee:Le|n"],
                                             ["grass", "풀밭", "🌿", "g|r|a|ss:s"], ["grin", "활짝 웃다", "😁", "g|r|i|n"]]},
        {"name": "tr", "pat": "tr", "words": [["tree", "나무", "🌳", "t|r|ee:Le"], ["train", "기차", "🚆", "t|r|ai:La|n"],
                                             ["trip", "여행", "🧳", "t|r|i|p"]]}]},
    {"day": 5, "kind": "s 블렌드", "families": [
        {"name": "st", "pat": "st", "words": [["stop", "멈추다", "🛑", "s|t|o|p"], ["step", "계단", "👣", "s|t|e|p"],
                                             ["stone", "돌", "🪨", "s|t|o:Lo|n|e*"], ["stamp", "우표", "📮", "s|t|a|m|p"]]},
        {"name": "sp", "pat": "sp", "words": [["spin", "돌다", "🌀", "s|p|i|n"], ["spill", "쏟다", "🫗", "s|p|i|ll:l"],
                                             ["spade", "삽", "♠️", "s|p|a:La|d|e*"], ["spot", "점", "🔴", "s|p|o|t"]]},
        {"name": "sn", "pat": "sn", "words": [["snake", "뱀", "🐍", "s|n|a:La|k|e*"], ["snail", "달팽이", "🐌", "s|n|ai:La|l"],
                                             ["snow", "눈", "❄️", "s|n|ow:Lo"]]}]},
    {"day": 6, "kind": "이중자", "families": [
        {"name": "sh", "pat": "sh", "words": [["ship", "배", "🚢", "sh:sh|i|p"], ["shell", "조개껍데기", "🐚", "sh:sh|e|ll:l"],
                                             ["fish", "물고기", "🐟", "f|i|sh:sh"], ["sheep", "양", "🐑", "sh:sh|ee:Le|p"]]},
        {"name": "ch", "pat": "ch", "words": [["chip", "감자칩", "🍟", "ch:ch|i|p"], ["chick", "병아리", "🐥", "ch:ch|i|ck:k"],
                                             ["cheese", "치즈", "🧀", "ch:ch|ee:Le|s:z|e*"], ["beach", "해변", "🏖️", "b|ea:Le|ch:ch"]]},
        {"name": "th", "pat": "th", "words": [["three", "셋", "3️⃣", "th:th|r|ee:Le"], ["bath", "목욕", "🛁", "b|a|th:th"],
                                             ["teeth", "이빨", "🦷", "t|ee:Le|th:th"]]}]},
    {"day": 7, "kind": "이중자", "families": [
        {"name": "wh", "pat": "wh", "words": [["whale", "고래", "🐳", "wh:w|a:La|l|e*"], ["wheel", "바퀴", "🛞", "wh:w|ee:Le|l"],
                                             ["white", "흰색", "⚪", "wh:w|i:Li|t|e*"]]},
        {"name": "ck", "pat": "ck", "words": [["duck", "오리", "🦆", "d|u|ck:k"], ["sock", "양말", "🧦", "s|o|ck:k"],
                                             ["rock", "바위", "🪨", "r|o|ck:k"], ["truck", "트럭", "🚚", "t|r|u|ck:k"]]},
        {"name": "ng", "pat": "ng", "words": [["ring", "반지", "💍", "r|i|ng:ng"], ["king", "왕", "🤴", "k|i|ng:ng"],
                                             ["sing", "노래하다", "🎤", "s|i|ng:ng"], ["wing", "날개", "🪽", "w|i|ng:ng"]]}]},
]
CONS_SENTS = {
    1: [["I clap and play.", "나는 박수 치며 놀아요.", "👏⚽"], ["The clock is black.", "시계가 검은색이에요.", "🕰️⬛"],
        ["I see a blue block.", "나는 파란 블록을 봐요.", "🔵🧱"], ["The plant is on the plate.", "식물이 접시 위에 있어요.", "🪴🍽️"]],
    2: [["The flag is red.", "깃발이 빨개요.", "🚩🔴"], ["I am glad.", "나는 기뻐요.", "😊"],
        ["I see a slug on the sled.", "썰매 위에 민달팽이가 보여요.", "🐌🛷"], ["The glue is in the glass.", "풀이 유리컵 안에 있어요.", "🧴🥛"]],
    3: [["The crab can dig.", "게가 땅을 팔 수 있어요.", "🦀⛏️"], ["I see a crow.", "나는 까마귀를 봐요.", "🙋🐦‍⬛"],
        ["The bride has a dress.", "신부가 드레스를 입었어요.", "👰👗"], ["I hit the drum.", "나는 북을 쳐요.", "🥁"]],
    4: [["The frog is green.", "개구리가 초록색이에요.", "🐸🟢"], ["I see a tree.", "나는 나무를 봐요.", "🙋🌳"],
        ["I get on the train.", "나는 기차를 타요.", "🙋🚆"], ["The grass is green.", "풀밭이 초록색이에요.", "🌿🟢"]],
    5: [["Stop the bus.", "버스를 멈춰요.", "🛑🚌"], ["I see snow.", "나는 눈을 봐요.", "🙋❄️"],
        ["The snail is on the stone.", "달팽이가 돌 위에 있어요.", "🐌🪨"], ["The snake can spin.", "뱀이 빙글빙글 돌 수 있어요.", "🐍🌀"]],
    6: [["I see a fish.", "나는 물고기를 봐요.", "🙋🐟"], ["The sheep is in the bath.", "양이 목욕통 안에 있어요.", "🐑🛁"],
        ["I see three chicks.", "나는 병아리 세 마리를 봐요.", "3️⃣🐥"], ["The chick has a chip.", "병아리가 감자칩을 가졌어요.", "🐥🍟"]],
    7: [["The duck can sing.", "오리가 노래할 수 있어요.", "🦆🎤"], ["The king has a ring.", "왕이 반지를 가졌어요.", "🤴💍"],
        ["I see a whale.", "나는 고래를 봐요.", "🙋🐳"], ["The sock is white.", "양말이 흰색이에요.", "🧦⚪"]],
}
for _d in CONS:
    _d["vowel"] = _d["families"][0]["pat"]
    _d["sents"] = [{"id": f"c{_d['day']}{i + 1}", "en": x[0], "ko": x[1], "pic": x[2]} for i, x in enumerate(CONS_SENTS[_d["day"]])]
CONS_WORDS = [w for d in CONS for f in d["families"] for w in f["words"]]

# ── LV1 사이트워즈 ── Dolch 초급 92(Pre-primer 40 + Primer 52), 4개씩 23세트. 원장 2026-10-30:
#   3개월차(장모음과 함께) 시작 → 10개월차 마무리, 주 1세트. 문장은 그 세트·앞 세트 단어 + 파닉스 단어로만.
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
    for d in LONG:   # 긴 소리 노래: "Long A. A says eɪ, eɪ, cake!"
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
    for d in LONG:
        fam = " / ".join(f["name"] for f in d["families"])
        rows.append({"id": f"phx-lv1-3-d{d['day']:02d}", "title": f"{BOOK3} {BOOK3_NAME} Day {d['day']} (긴 {d['vowel']}: {fam})",
                     "book": BOOK3, "type": "phonics", "phonicsDay": d["day"],
                     "items": [w[0] for f in d["families"] for w in f["words"]],
                     "meanings": [], "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                     "exampleAudio": [], "recordMode": "each", "published": False})
    rows.append({"id": "phx-lv1-3-exam", "title": f"{BOOK3} {BOOK3_NAME} 진급시험", "book": BOOK3,
                 "type": "exam", "kind": "phonics", "items": [w[0] for w in LONG_WORDS], "meanings": [],
                 "passScore": 70, "rounds": 1, "dueDate": None, "assignedIds": [], "assignedClasses": [],
                 "exampleAudio": [], "recordMode": "each", "published": False})
    for d in CONS:
        fam = " / ".join(f["name"] for f in d["families"])
        rows.append({"id": f"phx-lv1-4-d{d['day']:02d}", "title": f"{BOOK4} {BOOK4_NAME} Day {d['day']} ({fam})",
                     "book": BOOK4, "type": "phonics", "phonicsDay": d["day"],
                     "items": [w[0] for f in d["families"] for w in f["words"]],
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
NORM_TAG = "|peak-2"


def _needs_norm(aid):
    return aid.startswith(("snd-", "lv-", "dg-"))   # dg-(sh·ch·th·ng): th 가 -40dB 로 거의 안 들렸다


def _normalize(data: bytes) -> bytes:
    import re as _re, subprocess, tempfile, os as _os
    src = dst = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(data); src = f.name
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", src, "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=30)
        m = _re.search(r"max_volume: (-?[0-9.]+) dB", r.stderr or "")
        if not m:
            return data
        gain = min(40.0, -2.0 - float(m.group(1)))   # th(θ)는 +38dB 가 필요했다
        if gain <= 0.5:
            return data
        dst = src + ".out.mp3"
        r = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", src, "-af", f"volume={gain:.1f}dB",
                            "-codec:a", "libmp3lame", "-b:a", "64k", dst], capture_output=True, timeout=30)
        if r.returncode != 0:
            return data
        with open(dst, "rb") as f:
            return f.read()
    except Exception as e:
        print("[phonics] 음량 맞추기 실패(원본 사용):", e)
        return data
    finally:
        for x in (src, dst):
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
                         "dg": {k: v[1] for k, v in DIGRAPH_SND.items()}},
                "sight": {"book": BOOKS, "bookName": "사이트워즈", "days": SIGHT_DAYS}}

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
        ALLB = (BOOK, BOOK2, BOOK3, BOOK4, BOOKS)
        books = sorted({a.get("book") for a in db["assignments"] if a.get("book") in ALLB and mine(a)})
        book = book if book in ALLB else ([b for b in books if b != BOOKS] or books or [BOOK])[-1]
        rows = [a for a in db["assignments"] if a.get("book") == book and mine(a)]
        if book == BOOKS:
            keys = [w[0] for w in SIGHT_WORDS]
            groups = [{"name": f"세트 {d['day']}", "vowel": "", "keys": [w[0] for w in d["words"]]} for d in SIGHT_DAYS]
            info = {w[0]: {"ko": w[1], "emoji": ""} for w in SIGHT_WORDS}
        elif book in (BOOK2, BOOK3, BOOK4):
            DD, WW = {BOOK2: (SHORT, SHORT_WORDS), BOOK3: (LONG, LONG_WORDS), BOOK4: (CONS, CONS_WORDS)}[book]
            keys = [w[0] for w in WW]
            groups = [{"name": (f"{d['vowel']}  {f['name']}" if book == BOOK2 else f"긴 {d['vowel']}  {f['name']}" if book == BOOK3 else f['name']),
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
                "book": book, "bookName": {BOOK2: BOOK2_NAME, BOOK3: BOOK3_NAME, BOOK4: BOOK4_NAME, BOOKS: "사이트워즈"}.get(book, BOOK_NAME), "books": books,
                "days": day_rows, "letters": letters, "groups": groups, "info": info,
                "areas": areas, "exam": exam_out}

    return r
