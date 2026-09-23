// 자동 생성 — tools/split_admin.py. 학생·선생님 화면이 같이 쓴다.

const { useState, useEffect, useRef } = React;

const TAKES = 3;

/* 관리자 비밀번호는 관리자 API 를 여는 열쇠이기도 하다.
   선생님이 로그인할 때 받아 두고, 이후 모든 요청에 x-ht-admin 으로 붙여 보낸다.
   (전교생 명단·백업·과제 지우기 같은 동작은 서버가 이 헤더를 확인한다.)
   sessionStorage 라서 탭을 닫으면 사라진다 — 학생 기기에 남지 않는다. */

let ADMIN_KEY = "";
try { ADMIN_KEY = sessionStorage.getItem("tt_admin") || ""; } catch (e) {}

function setAdminKey(pw) {
  ADMIN_KEY = pw || "";
  try { pw ? sessionStorage.setItem("tt_admin", pw) : sessionStorage.removeItem("tt_admin"); } catch (e) {}
}

/* 관리자 화면에는 api() 를 안 거치고 fetch 를 직접 부르는 곳이 여남은 군데 있다
   (과제 삭제·수정 등). 한 곳씩 고치면 빠뜨리기 쉬워서, /api 로 나가는 요청 전부에
   여기서 열쇠를 붙인다. 학생 화면은 ADMIN_KEY 가 비어 있으니 아무것도 붙지 않는다. */

const _fetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  try {
    const u = typeof input === "string" ? input : (input && input.url) || "";
    if (ADMIN_KEY && u.indexOf("/api") === 0) {
      init = { ...(init || {}) };
      init.headers = { ...(init.headers || {}), "x-ht-admin": ADMIN_KEY };
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

function dayNum(title) {
  const t = title || "";
  const m = /(?:day|unit|lesson|lec|chapter)\s*(\d+)/i.exec(t)
    || /(?:유닛|레슨|단원|챕터)\s*(\d+)/.exec(t)
    || /(\d+)\s*(?:일차|과|강|주차)/.exec(t);
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

function useVoice() {
  const [voice, setVoice] = useState(null);
  useEffect(() => {
    if (!window.speechSynthesis) return;
    const pick = () => {
      const vs = speechSynthesis.getVoices();
      if (!vs.length) return;
      setVoice(vs.find(v => v.lang === "en-US") || vs.find(v => v.lang && v.lang.startsWith("en")) || vs[0]);
    };
    pick();
    speechSynthesis.onvoiceschanged = pick;
  }, []);
  return voice;
}

function speak(text, voice, rate) {
  if (!window.speechSynthesis) return alert("이 브라우저는 음성 재생을 지원하지 않아요.");
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  if (voice) u.voice = voice;
  u.lang = "en-US";
  u.rate = rate || 0.7;
  u.pitch = 1.05;
  speechSynthesis.speak(u);
}
// 선생님이 올린 음원(url)이 있으면 그걸 재생, 없으면 TTS로 읽기

function playModel(url, text, voice, rate) {
  if (url) { try { const a = new Audio(url); a.play(); return; } catch (e) {} }
  speak(text, voice, rate);
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
