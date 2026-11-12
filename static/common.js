// 자동 생성 — tools/split_admin.py. 학생·선생님 화면이 같이 쓴다.

const { useState, useEffect, useRef } = React;

const TAKES = 3;

/* 관리자 비밀번호는 관리자 API 를 여는 열쇠이기도 하다.
   선생님이 로그인할 때 받아 두고, 이후 모든 요청에 x-ht-admin 으로 붙여 보낸다.
   (전교생 명단·백업·과제 지우기 같은 동작은 서버가 이 헤더를 확인한다.)
   sessionStorage 라서 탭을 닫으면 사라진다 — 학생 기기에 남지 않는다. */

let ADMIN_KEY = "";
try { ADMIN_KEY = sessionStorage.getItem("tt_admin") || ""; } catch (e) {}

// 선생님들이 비밀번호를 같이 쓰므로, 누가 했는지는 로그인 때 받은 이름으로 남긴다(2026-11-05).
let ADMIN_WHO = "";
try { ADMIN_WHO = sessionStorage.getItem("tt_who") || ""; } catch (e) {}
function setAdminWho(name) {
  ADMIN_WHO = name || "";
  try { name ? sessionStorage.setItem("tt_who", name) : sessionStorage.removeItem("tt_who"); } catch (e) {}
}

function setAdminKey(pw) {
  ADMIN_KEY = pw || "";
  try { pw ? sessionStorage.setItem("tt_admin", pw) : sessionStorage.removeItem("tt_admin"); } catch (e) {}
}

/* 관리자 화면에는 api() 를 안 거치고 fetch 를 직접 부르는 곳이 여남은 군데 있다
   (과제 삭제·수정 등). 한 곳씩 고치면 빠뜨리기 쉬워서, /api 로 나가는 요청 전부에
   여기서 열쇠를 붙인다. 학생 화면은 ADMIN_KEY 가 비어 있으니 아무것도 붙지 않는다. */

/* 학생 출입증(2026-11-11) — 학생이 로그인하면 서버가 준다. 학생 아이디가 든 주소를 그 학생만 열게.
   sessionStorage 라 탭을 닫으면 사라진다(학생 정보 tt_student 와 같은 수명). */
let STU_KEY = "";
try { STU_KEY = sessionStorage.getItem("tt_stk") || ""; } catch (e) {}
function setStuKey(k) {
  STU_KEY = k || "";
  try { k ? sessionStorage.setItem("tt_stk", k) : sessionStorage.removeItem("tt_stk"); } catch (e) {}
}

const _fetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  try {
    const u = typeof input === "string" ? input : (input && input.url) || "";
    if (ADMIN_KEY && u.indexOf("/api") === 0) {
      init = { ...(init || {}) };
      init.headers = { ...(init.headers || {}), "x-ht-admin": ADMIN_KEY };
      if (ADMIN_WHO) init.headers["x-tt-who"] = encodeURIComponent(ADMIN_WHO);   // 헤더엔 한글을 못 싣는다
    } else if (STU_KEY && u.indexOf("/api") === 0) {
      init = { ...(init || {}) };
      init.headers = { ...(init.headers || {}), "x-tt-stk": STU_KEY };
    }
  } catch (e) {}
  return _fetch(input, init);
};

async function api(path, opts) {
  const res = await fetch("/api" + path, opts);
  if (!res.ok) {
    let msg = "요청에 실패했어요.";
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

const apiGet = (p) => api(p);

const apiPost = (p, body) => api(p, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {})
});

const apiDelete = (p) => api(p, { method: "DELETE" });

const STUDENT_PORTAL = "https://student.happytreeacademy.com/";   // 학생 포털(허브) — 문해숨·수학숨 등

// ---- 웹 푸시 ----

function urlB64ToUint8(base64String) {
  const pad = "=".repeat((4 - base64String.length % 4) % 4);
  const b64 = (base64String + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

const pushSupported = () => ("serviceWorker" in navigator) && ("PushManager" in window) && ("Notification" in window);
async function enablePush(studentId) {
  if (!pushSupported()) throw new Error("이 기기(브라우저)는 알림을 지원하지 않아요. 크롬으로 열거나, 아이폰은 홈 화면에 추가한 뒤 다시 시도해주세요.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("알림이 허용되지 않았어요. 브라우저 설정에서 알림을 허용해주세요.");
  const reg = await navigator.serviceWorker.ready;
  const { publicKey } = await apiGet("/push/key");
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8(publicKey) });
  await apiPost(`/push/subscribe/${studentId}`, sub.toJSON());
  return true;
}
async function disablePush(studentId) {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) { await apiPost(`/push/unsubscribe/${studentId}`, sub.toJSON()); await sub.unsubscribe(); }
  } catch (e) {}
}
// 학생이 학습을 시작하면 실시간 현황판에 알림 (실패해도 무시)

const pingActivity = (sid, kind, title) => apiPost(`/activity/${sid}`, { kind, title }).catch(()=>{});

function normalizeTakes(v) {
  const arr = Array.isArray(v) ? v.slice(0, TAKES) : [];
  while (arr.length < TAKES) arr.push(null);
  return arr;
}

function formatDue(d) {
  if (!d) return null;
  const [y, m, day] = d.split("-").map(Number);
  return `${m}/${day}`;
}
// 교재 이름이 따로 없을 때, 제목 끝의 "Day/Unit/Lesson N"을 떼어 같은 시리즈로 묶는다.

function seriesOf(title) {
  return (title || "").replace(/\s*(?:day|unit|lesson|lec|chapter)\s*\d+\s*$/i, "")
    .replace(/\s*\d+\s*(?:일차|유닛|레슨|과|강|주차|챕터|단원)\s*$/, "").trim() || (title || "");
}
// 제목의 "Day/Unit/Lesson/과 N"에서 숫자만 뽑는다(정렬용). 없으면 null.

// ★마지막 것을 읽는다(원장 2026-10-13 "김시안 Day1만 다 배정"). 교재 이름이 '…_2 Day1-24' 처럼
//   번호를 품고 있으면 첫 것은 교재 이름 속 'Day1' 이라 24개가 전부 Day 1 로 보이고 1,10,11…,2 로 섞였다.
function dayNum(title) {
  const t = title || "";
  const last = (re) => { const all = [...t.matchAll(re)]; return all.length ? all[all.length - 1] : null; };
  const m = last(/(?:day|unit|lesson|lec|chapter)\s*(\d+)/gi)
    || last(/(?:유닛|레슨|단원|챕터)\s*(\d+)/g)
    || last(/(\d+)\s*(?:일차|과|강|주차)/g);
  return m ? parseInt(m[1], 10) : null;
}

function dueStatus(d) {
  if (!d) return null;
  const t = new Date(); t.setHours(0,0,0,0);
  const [y, m, day] = d.split("-").map(Number);
  const due = new Date(y, m - 1, day); due.setHours(0,0,0,0);
  const diff = Math.round((due - t) / 86400000);
  return diff < 0 ? "overdue" : diff === 0 ? "today" : "upcoming";
}

function scoreTone(s) {
  if (s == null) return "b-gray";
  if (s >= 85) return "b-navy";
  if (s >= 60) return "b-gold";
  return "b-danger";
}

function nowStr() {
  const d = new Date();
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

/* 발음이 '로봇 같다'(원장 2026-11-10). 예전엔 목록의 첫 en-US 를 썼는데, 윈도우 크롬은 그게
   옛 Microsoft David/Zira(기계음)이고 더 좋은 목소리가 뒤에 있어도 안 골랐다.
   자연스러운 순서: 엣지 신경망(… Online (Natural)) > Google US English > 애플 고급(Premium/Enhanced·Samantha 등)
   > 그 밖의 en-US > 영국·호주 영어. 옛 기계음(David·Zira·Mark·Hazel·Fred 등)은 맨 뒤. */
function bestEnglishVoice(vs) {
  const en = vs.filter(v => /^en[-_]/i.test(v.lang || ""));
  if (!en.length) return vs[0] || null;
  const score = (v) => {
    const n = (v.name || "") + " " + (v.voiceURI || "");
    let s = 0;
    if (/natural/i.test(n)) s += 100;
    if (/online/i.test(n)) s += 20;
    if (/google/i.test(n)) s += 60;
    if (/premium|enhanced|neural|siri/i.test(n)) s += 50;
    if (/samantha|ava|allison|susan|nicky|joelle|aria|jenny|emma|michelle/i.test(n)) s += 25;
    if (/^en[-_]us/i.test(v.lang)) s += 15;
    if (/david|zira|mark|hazel|george|fred|albert|bad news|bells|boing|bubbles|cellos|whisper|zarvox|trinoids|junior|ralph|kathy|bahh|jester|organ|superstar|wobble|grandma|grandpa|eddy|flo|reed|rocko|sandy|shelley/i.test(n)) s -= 80;
    return s;
  };
  return en.slice().sort((a, b) => score(b) - score(a))[0];
}

function useVoice() {
  const [voice, setVoice] = useState(null);
  useEffect(() => {
    if (!window.speechSynthesis) return;
    const pick = () => {
      const vs = speechSynthesis.getVoices();
      if (!vs.length) return;
      setVoice(bestEnglishVoice(vs));
    };
    pick();
    speechSynthesis.onvoiceschanged = pick;
  }, []);
  return voice;
}

// 낱말 끝소리가 잘리던 것(short→"숄", 원장 10/22). 태블릿 음성엔진은 소리를 다 내보내기 전에
// 재생을 닫아 마지막 자음(t·k·d)을 먹는다. 그래서
//  ① 문장부호로 끝나지 않으면 마침표를 붙여 끝에 쉼을 만든다 — 잘려도 쉼이 잘리고 자음은 남는다.
//  ② cancel() 직후 바로 speak() 하면 안드로이드·iOS 에서 새 소리가 끊기므로, 앞 소리가 있을 때만 끄고 잠깐 기다린다.
//  ③ 크롬은 참조가 없는 utterance 를 재생 중에 치워 소리가 중간에 멎으므로 전역에 붙잡아 둔다.
let _speakT = null;
function speak(text, voice, rate) {
  if (!window.speechSynthesis) return alert("이 브라우저는 음성 재생을 지원하지 않아요.");
  const s = String(text || "").trim();
  if (!s) return;
  const u = new SpeechSynthesisUtterance(/[.!?…]["')\]]*$/.test(s) ? s : s + ".");
  if (voice) u.voice = voice;
  u.lang = "en-US";
  // 0.7 은 늘어져서 오히려 기계음처럼 들렸다. 보통 속도에 가깝게(천천히 듣기 버튼은 따로 0.45 를 넘긴다).
  u.rate = rate || 0.9;
  u.pitch = 1;
  window._ttsUtter = u;
  clearTimeout(_speakT);
  if (speechSynthesis.speaking || speechSynthesis.pending) {
    speechSynthesis.cancel();
    _speakT = setTimeout(() => speechSynthesis.speak(u), 120);
  } else {
    speechSynthesis.speak(u);
  }
}
/* 자연스러운 문장 소리(원장 2026-11-11 "문장 읽어주는 음원이 자연스러웠으면" → 견본 A 선택).
   두 낱말 이상(문장)은 우리 음성 워커(happytree-ttvoice, Workers AI Aura-2 thalia)에서 받는다.
   한 번 만든 소리는 워커에 저장돼 다시 만들지 않고, 새로 만드는 건 하루 무료 한도 안에서만.
   한도를 넘었거나·느리거나·막히면 예전처럼 기기 음성으로 읽는다(소리가 안 나는 일은 없게).
   낱말 하나는 기기 음성 그대로(무료 한도를 문장에 쓰려고). */
const NATURAL_TTS = "https://happytree-ttvoice.white21040.workers.dev/s?t=";
let _curAudio = null;
/* 듣기가 안 나오던 것(원장 2026-11-12 "홍리아 듣고 문제 풀기 게임에서 듣기가 안 나온다").
   자막 맞추기 등은 첫 소리를 손으로 누른 순간이 아니라 카운트다운 뒤 타이머로 튼다. 아이패드·아이폰은
   이렇게 '누르지 않고 튼' 새 Audio 를 막고, 대신 쓰는 기기 음성도 한 번도 손으로 연 적이 없으면 막는다 → 무음.
   그래서 ① 소리 나는 통(Audio)을 하나만 만들어 계속 다시 쓰고 ② 화면을 처음 누를 때 그 통과 기기 음성을
   무음으로 한 번 열어 둔다. 한 번 열린 통은 그 뒤 타이머로 틀어도 막히지 않는다. */
const _SILENT_WAV = "data:audio/wav;base64,UklGRrQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YZABAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA";
let _sharedAudio = null, _soundUnlocked = false, _playTok = 0;
function _getAudio() {
  if (!_sharedAudio) { try { _sharedAudio = new Audio(); _sharedAudio.preload = "auto"; } catch (e) { _sharedAudio = null; } }
  return _sharedAudio;
}
function unlockSound() {
  if (_soundUnlocked) return;
  _soundUnlocked = true;
  const a = _getAudio();
  if (a && (a.paused || a.ended) && !a.src) {   // 이미 무언가 틀고 있으면 건드리지 않는다(그 소리가 끊기니까)
    try {
      a.src = _SILENT_WAV;
      const p = a.play();
      if (p && p.catch) p.catch(e => { if (e && e.name === "NotAllowedError") _soundUnlocked = false; });
    } catch (e) { _soundUnlocked = false; }
  }
  try {
    if (window.speechSynthesis && !speechSynthesis.speaking && !speechSynthesis.pending) {
      const u = new SpeechSynthesisUtterance(" "); u.volume = 0; speechSynthesis.speak(u);
    }
  } catch (e) {}
}
try { ["touchend", "pointerup", "click", "keydown"].forEach(ev => document.addEventListener(ev, unlockSound, true)); } catch (e) {}
function _stopSounds() {
  try { if (_curAudio) _curAudio.pause(); } catch (e) {}
  try { if (window.speechSynthesis && (speechSynthesis.speaking || speechSynthesis.pending)) speechSynthesis.cancel(); } catch (e) {}
}
function _playUrl(url, rate, onFail) {
  _stopSounds();
  const a = _getAudio() || new Audio();
  const tok = ++_playTok;
  _curAudio = a;
  const pr = rate ? Math.max(0.5, Math.min(1.2, rate / 0.9)) : 1;
  const setRate = () => { try { a.preservesPitch = true; a.playbackRate = pr; } catch (e) {} };
  let gone = false;
  const fail = () => { if (gone || tok !== _playTok) return; gone = true; clearTimeout(t); try { a.pause(); } catch (e) {} if (onFail) onFail(); };
  a.onloadedmetadata = () => { if (tok === _playTok) setRate(); };
  a.onplaying = () => { if (tok === _playTok) clearTimeout(t); };
  a.onerror = () => { if (tok === _playTok) fail(); };
  a.src = url;
  setRate();
  const t = setTimeout(() => { if (tok === _playTok && !a.ended && a.currentTime === 0) fail(); }, 6000);   // 6초 안에 소리가 안 나면 기기 음성
  try { const p = a.play(); if (p && p.catch) p.catch(e => { if (!(e && e.name === "AbortError")) fail(); }); } catch (e) { fail(); }
}
function speakNatural(text, voice, rate) {
  const s = String(text || "").replace(/\s+/g, " ").trim();
  if (!s) return;
  if (s.indexOf(" ") < 0 || s.length > 300) return speak(s, voice, rate);
  _playUrl(NATURAL_TTS + encodeURIComponent(s), rate, () => speak(s, voice, rate));
}

// 선생님이 올린 음원(url)이 있으면 그걸, 없으면 문장은 자연스러운 목소리, 낱말은 기기 음성
function playModel(url, text, voice, rate) {
  if (url) { _playUrl(url, null, text ? () => speakNatural(text, voice, rate) : null); return; }
  speakNatural(text, voice, rate);
}

function Badge({ tone, children }) {
  return <span className={"badge " + tone}>{children}</span>;
}

// ---------- Login ----------

function readStats(words) {
  const ws = (words || []).filter(w => w && w.word);
  if (!ws.length) return null;
  const omitted  = ws.filter(w => w.errorType === "Omission");
  const badPron  = ws.filter(w => w.errorType === "Mispronunciation");
  const inserted = ws.filter(w => w.errorType === "Insertion");
  return { ws, omitted, badPron, inserted, refCount: ws.length - inserted.length };
}

function ReadMarks({ words, showScores }) {
  const st = readStats(words);
  if (!st) return null;
  const style = (w) => {
    if (w.errorType === "Omission")
      return { color:"#AAA49A", textDecoration:"line-through" };
    if (w.errorType === "Insertion")
      return { color:"#8A6D0F", borderBottom:"2px dotted #8A6D0F" };
    if (w.errorType === "Mispronunciation")
      return { color:"var(--danger)", fontWeight:700 };
    return { color:"var(--navy)" };
  };
  const bits = [];
  if (st.omitted.length) bits.push(`안 읽은 단어 ${st.omitted.length}개`);
  if (st.badPron.length) bits.push(`발음 주의 ${st.badPron.length}개`);
  if (st.inserted.length) bits.push(`더 말한 단어 ${st.inserted.length}개`);

  return (
    <div style={{ marginTop:8 }}>
      <div style={{ fontSize:11, color:"var(--navy-soft)", marginBottom:3 }}>읽은 결과</div>
      <div style={{ lineHeight:1.8, fontSize:14, wordBreak:"keep-all" }}>
        {st.ws.map((w, i) => (
          <span key={i}>
            <span style={style(w)}
              title={w.accuracy != null ? `정확도 ${Math.round(w.accuracy)}` : ""}>{w.word}</span>
            {i < st.ws.length - 1 ? " " : ""}
          </span>
        ))}
      </div>
      <div className="muted" style={{ marginTop:4, fontSize:11.5 }}>
        {bits.length
          ? `${st.refCount}단어 중 ` + bits.join(" · ")
          : `${st.refCount}단어 모두 또박또박 읽었어요 👍`}
      </div>
      {(st.omitted.length > 0 || st.badPron.length > 0) && (
        <div style={{ marginTop:2, fontSize:10.5, color:"var(--navy-soft)" }}>
          {st.omitted.length > 0 && <span style={{ textDecoration:"line-through", color:"#AAA49A" }}>취소선</span>}
          {st.omitted.length > 0 && <span>=안 읽음</span>}
          {st.omitted.length > 0 && st.badPron.length > 0 && <span> · </span>}
          {st.badPron.length > 0 && <span style={{ color:"var(--danger)", fontWeight:700 }}>빨강</span>}
          {st.badPron.length > 0 && <span>=발음 주의</span>}
        </div>
      )}
      {showScores && st.badPron.length > 0 && (
        <div className="row" style={{ marginTop:5, gap:5, flexWrap:"wrap" }}>
          {st.badPron.filter(w => w.accuracy != null).sort((a,b)=>a.accuracy-b.accuracy).slice(0,8).map((w, wi)=>(
            <span key={wi} style={{ fontSize:11, padding:"2px 8px", borderRadius:999,
              background:"#F3D9D2", color:"var(--danger)", fontWeight:600 }}>
              {w.word} {Math.round(w.accuracy)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// words 가 없는 옛 기록용. 정렬된 값이라는 걸 반드시 같이 알린다.

function AlignedFallback({ recognized }) {
  if (!recognized) return null;
  return (
    <div style={{ marginTop:8 }}>
      <div className="muted">정렬된 인식값: "{recognized}"</div>
      <div style={{ fontSize:10.5, color:"var(--navy-soft)", marginTop:2 }}>
        ※ 참조문장에 맞춰 정렬된 값이라 실제 발음과 다를 수 있어요. 녹음을 직접 들어보세요.
      </div>
    </div>
  );
}

/* 단어익힘·문장익힘 한 판에 나오는 몫(원장 2026-10-16 "30개를 4단계 다 하는 건 너무 많다").
   단계마다 따로 무작위로 뽑으니 4단계를 다 돌면 대부분의 단어가 한 번은 나온다. */
const STUDY_RATIO = 0.6;
function studyCount(n) { return Math.min(n, Math.max(1, Math.ceil(n * STUDY_RATIO))); }

function shuffleArr(a) {
  const b = a.slice();
  for (let i = b.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [b[i], b[j]] = [b[j], b[i]];
  }
  return b;
}

// ---------- 문장익힘 (뜻 확인 · 문장 배열) ----------

const BATTLE_OPT = [
  { c: "#D94A3D", s: "▲" }, { c: "#2E6FB0", s: "●" },
  { c: "#C9A227", s: "■" }, { c: "#3E8E63", s: "◆" },
];

const BALLOON_COLORS = ["#E4572E","#F4A259","#4C9F70","#2E6FB0","#9B5DE5","#F15BB5","#00BBF9","#FF66C4"];

function wsUrl(code, qs) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/battle/${code}?${qs}`;
}
