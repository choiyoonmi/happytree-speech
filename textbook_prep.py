# -*- coding: utf-8 -*-
"""학교 교과서 대비 세트(원장 2026-11-17 "영어 교과서 표현부터").

남천초 5학년 2학기 영어 평가계획(4회)의 핵심 표현을 트리톡 보관함 원본으로 넣는다.
  7과  지난 여행(과거)        — 9월 3주 읽기·선택형
  10과 아픈 증상 묻고 답하기  — 11월 2주 말하기·실기
  11과 위치 말하고 쓰기        — 11월 4주 쓰기·서답형
  12과 겨울방학 계획(미래)     — 12월 2주 읽기·선택형
교과서 문장을 옮긴 것이 아니라, 같은 의사소통 표현으로 새로 쓴 원고다.

단원마다 단어 과제(단어녹음+단어익힘: 카드·뜻고르기·스펠링·미니테스트) 하나와
문장 과제(문장녹음+문장익힘: 뜻 확인·문장 배열) 하나 → Day 1~8.
id 를 고정해 두어 서버가 몇 번 떠도 한 벌만 생긴다. published False = 보관함에만, 배정은 선생님 몫.
책 이름이 'LV' 로 시작하지 않아 권말 진급시험(_LV_BOOK)은 붙지 않는다.
"""

BOOK = "초5 교과서 대비 2학기"

UNITS = [
    {
        "unit": "7과", "name": "지난 여행(과거)",
        "words": [
            ("went", "갔다 (go의 과거)"), ("visited", "방문했다"), ("saw", "보았다 (see의 과거)"),
            ("ate", "먹었다 (eat의 과거)"), ("bought", "샀다 (buy의 과거)"), ("swam", "수영했다 (swim의 과거)"),
            ("rode", "탔다 (ride의 과거)"), ("took", "찍었다, 가져갔다 (take의 과거)"), ("trip", "여행"),
            ("beach", "해변"), ("museum", "박물관"), ("last weekend", "지난 주말"),
        ],
        "sents": [
            ("Where did you go last weekend?", "지난 주말에 어디에 갔니?"),
            ("I went to Busan with my family.", "나는 가족과 함께 부산에 갔어."),
            ("What did you do there?", "거기서 무엇을 했니?"),
            ("I swam at the beach.", "나는 해변에서 수영했어."),
            ("I visited a history museum.", "나는 역사 박물관을 방문했어."),
            ("I ate fresh fish for dinner.", "나는 저녁으로 싱싱한 생선을 먹었어."),
            ("I rode a bike by the river.", "나는 강가에서 자전거를 탔어."),
            ("I took a lot of pictures.", "나는 사진을 많이 찍었어."),
            ("How was your trip?", "여행은 어땠니?"),
            ("It was great. I had a good time.", "정말 좋았어. 즐거운 시간을 보냈어."),
        ],
    },
    {
        "unit": "10과", "name": "아픈 증상 묻고 답하기",
        "words": [
            ("headache", "두통"), ("stomachache", "복통, 배앓이"), ("toothache", "치통"),
            ("fever", "열"), ("cold", "감기"), ("cough", "기침; 기침하다"), ("sore throat", "목감기, 따가운 목"),
            ("runny nose", "콧물"), ("hurt", "아프다"), ("medicine", "약"), ("rest", "휴식; 쉬다"),
            ("dentist", "치과 의사"),
        ],
        "sents": [
            ("What's wrong?", "어디가 아프니? (무슨 일이니?)"),
            ("I have a headache.", "나는 머리가 아파."),
            ("I have a stomachache.", "나는 배가 아파."),
            ("I have a fever and a runny nose.", "나는 열이 나고 콧물이 나."),
            ("My leg hurts.", "다리가 아파."),
            ("That's too bad.", "그것 참 안됐구나."),
            ("You should take some medicine.", "너는 약을 좀 먹는 게 좋겠어."),
            ("You should get some rest.", "너는 좀 쉬는 게 좋겠어."),
            ("You should go to the dentist.", "너는 치과에 가 보는 게 좋겠어."),
            ("I hope you feel better soon.", "얼른 나아지길 바라."),
        ],
    },
    {
        "unit": "11과", "name": "위치 말하고 쓰기",
        "words": [
            ("library", "도서관"), ("bank", "은행"), ("hospital", "병원"), ("post office", "우체국"),
            ("bakery", "빵집"), ("park", "공원"), ("next to", "~ 옆에"), ("between", "~ 사이에"),
            ("across from", "~ 건너편에"), ("behind", "~ 뒤에"), ("in front of", "~ 앞에"),
            ("corner", "모퉁이"),
        ],
        "sents": [
            ("Where is the library?", "도서관이 어디에 있니?"),
            ("It's next to the bank.", "은행 옆에 있어."),
            ("It's across from the park.", "공원 건너편에 있어."),
            ("It's between the bakery and the hospital.", "빵집과 병원 사이에 있어."),
            ("It's behind the school.", "학교 뒤에 있어."),
            ("It's in front of the post office.", "우체국 앞에 있어."),
            ("Go straight one block.", "한 블록 곧장 가."),
            ("Turn left at the corner.", "모퉁이에서 왼쪽으로 돌아."),
            ("It's on your right.", "네 오른쪽에 있어."),
            ("Excuse me. How can I get to the museum?", "실례합니다. 박물관에 어떻게 가나요?"),
        ],
    },
    {
        "unit": "12과", "name": "겨울방학 계획(미래)",
        "words": [
            ("winter", "겨울"), ("vacation", "방학, 휴가"), ("will", "~할 것이다"), ("plan", "계획; 계획하다"),
            ("ski", "스키를 타다"), ("skate", "스케이트를 타다"), ("snowman", "눈사람"), ("build", "만들다, 짓다"),
            ("learn", "배우다"), ("practice", "연습하다"), ("travel", "여행하다"), ("grandparents", "조부모님"),
        ],
        "sents": [
            ("What will you do this winter?", "이번 겨울에 무엇을 할 거니?"),
            ("I will go skiing with my dad.", "나는 아빠와 스키 타러 갈 거야."),
            ("I will visit my grandparents.", "나는 조부모님 댁을 방문할 거야."),
            ("I will build a big snowman.", "나는 커다란 눈사람을 만들 거야."),
            ("I will learn how to skate.", "나는 스케이트 타는 법을 배울 거야."),
            ("I will practice the piano every day.", "나는 매일 피아노를 연습할 거야."),
            ("I will read ten books this vacation.", "나는 이번 방학에 책 열 권을 읽을 거야."),
            ("What about you?", "너는 어때?"),
            ("That sounds fun.", "재미있겠다."),
            ("Have a great winter vacation!", "멋진 겨울방학 보내!"),
        ],
    },
]


def templates():
    rows, day = [], 0
    for u in UNITS:
        for kind, key, label in (("word", "words", "단어"), ("sentence", "sents", "문장")):
            day += 1
            pairs = u[key]
            rows.append({
                "id": f"tbk-e5-2-d{day:02d}",
                "title": f"{BOOK} Day {day} ({u['unit']} {u['name']} · {label})",
                "book": BOOK, "type": kind,
                "items": [e for e, _ in pairs], "meanings": [k for _, k in pairs],
                "examples": [], "exampleKo": [], "passScore": 70, "rounds": 3,
                "dueDate": None, "assignedIds": [], "assignedClasses": [], "exampleAudio": [],
                "recordMode": "each", "published": False,
            })
    return rows


def seed(*, lock, load_db, save_db):
    """보관함 원본 넣기(없는 것만). 아직 아무에게도 안 나간 원본은 내용을 지금 원고에 맞춘다.
    실패해도 서버는 떠야 한다."""
    try:
        with lock:
            db = load_db()
            have = {a.get("id"): a for a in db["assignments"]}
            new, fixed = [], 0
            for t in templates():
                o = have.get(t["id"])
                if not o:
                    new.append(t)
                elif o.get("published") is False and not o.get("assignedIds") and \
                        (o.get("items") != t["items"] or o.get("meanings") != t["meanings"] or o.get("title") != t["title"]):
                    o["items"], o["meanings"], o["title"] = t["items"], t["meanings"], t["title"]
                    fixed += 1
            if new or fixed:
                db["assignments"].extend(new)
                save_db(db)
                print(f"[textbook] 교과서 대비 원본 새로 {len(new)}개 · 고침 {fixed}개")
    except Exception as e:
        print("[textbook] 교과서 대비 원본 넣기 실패:", e)
