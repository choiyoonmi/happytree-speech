// 단어익힘 게임판 (2026-11-10 원장 "게임하듯이" → 같은 날 "여러 게임을 랜덤하게, 매일 지루하지 않게").
// 단계마다 게임 묶음(GAME_POOLS)이 있고, 오늘의 게임은 (날짜·학생·단어장·단계)로 정해진다 —
// 같은 날 다시 들어와도 같은 게임, 다음 날엔 바뀐다. 시작 화면 '🎲 다른 게임'으로 바꿔 할 수도 있다.
//   카드 암기(flash)  : 🧠 메모리 카드 · 🔗 짝 잇기
//   뜻 고르기(choice) : 🌧️ 단어 비 · 🔨 두더지 잡기 · 🎈 풍선 터뜨리기
//   스펠링(spell)     : 🚀 스펠링 슈터 · 🧩 글자 블록 · 🌳 나무 지키기
//   미니 테스트(test) : ⏱️ 스피드 퀴즈 · 🏁 단어 레이스
// 서버에 남는 건 예전과 똑같이 (맞은 개수, 문제 수) — 단계 키·완료 규칙·최고점 규칙은 그대로다.
// 게임 점수(포인트·콤보)는 재미용이라 이 기기에만 '내 최고 기록'으로 남긴다.
// 유치부(isKin)는 점수·콤보·승패를 안 보이고 천천히 한다(유아 평가 금지).
// common.js 다음, student.js 앞에 불러온다.

const GAME_CSS = `
@keyframes gmPop { 0%{transform:translate(-50%,0) scale(1);opacity:1} 100%{transform:translate(-50%,0) scale(1.9);opacity:0} }
@keyframes gmShake { 0%,100%{margin-left:0} 20%{margin-left:-9px} 40%{margin-left:9px} 60%{margin-left:-6px} 80%{margin-left:6px} }
@keyframes gmFloatUp { 0%{transform:translate(-50%,0);opacity:1} 100%{transform:translate(-50%,-46px);opacity:0} }
@keyframes gmTwinkle { 0%,100%{opacity:.25} 50%{opacity:.9} }
@keyframes gmBlink { 0%,100%{border-bottom-color:#E4C766} 50%{border-bottom-color:transparent} }
@keyframes gmGlow { 0%,100%{box-shadow:0 0 0 0 rgba(228,199,102,.0)} 50%{box-shadow:0 0 0 8px rgba(228,199,102,.55)} }
@keyframes gmBurst { 0%{transform:scale(.3);opacity:1} 100%{transform:scale(1.6);opacity:0} }
@keyframes gmCount { 0%{transform:scale(1.8);opacity:0} 30%{transform:scale(1);opacity:1} 100%{transform:scale(.9);opacity:.9} }
@keyframes gmMoleUp { 0%{transform:translateY(100%)} 100%{transform:translateY(0)} }
@keyframes gmFall { 0%{transform:translateY(0) rotate(0)} 100%{transform:translateY(120px) rotate(90deg);opacity:0} }
@keyframes gmFlipIn { 0%{transform:rotateY(90deg)} 100%{transform:rotateY(0)} }
@keyframes gmFade { 0%{opacity:1;transform:scale(1)} 100%{opacity:.25;transform:scale(.94)} }
.gm-sky{position:relative;overflow:hidden;border-radius:16px;background:linear-gradient(180deg,#14223A 0%,#1B2E4C 55%,#2E4A75 100%);user-select:none;-webkit-user-select:none;touch-action:manipulation}
.gm-star{position:absolute;width:3px;height:3px;border-radius:50%;background:#fff;animation:gmTwinkle 2.4s infinite}
.gm-ground{position:absolute;left:0;right:0;bottom:0;height:34px;background:linear-gradient(180deg,#3E8E63,#2E6B4A);display:flex;align-items:flex-end;justify-content:space-around;font-size:22px;line-height:1;padding-bottom:4px}
.gm-hud{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;font-weight:800;color:var(--navy)}
.gm-pill{background:#fff;border:1px solid var(--line);border-radius:999px;padding:4px 11px;font-size:13px}
`;
(function () {
  try { const s = document.createElement("style"); s.textContent = GAME_CSS; document.head.appendChild(s); } catch (e) {}
})();

// ---- 효과음(파일 없이 Web Audio로 만든다) ----
const GameSfx = (() => {
  let ctx = null, muted = false;
  try { muted = localStorage.getItem("tt_game_mute") === "1"; } catch (e) {}
  const get = () => {
    if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { ctx = null; } }
    return ctx;
  };
  const tone = (f, dur, type, vol, slide) => {
    if (muted) return;
    const c = get(); if (!c) return;
    try {
      const t = c.currentTime, o = c.createOscillator(), g = c.createGain();
      o.type = type || "sine"; o.frequency.setValueAtTime(f, t);
      if (slide) o.frequency.exponentialRampToValueAtTime(slide, t + dur);
      g.gain.setValueAtTime(vol || 0.15, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g).connect(c.destination); o.start(t); o.stop(t + dur + 0.02);
    } catch (e) {}
  };
  return {
    unlock() { const c = get(); if (c && c.state === "suspended") { try { c.resume(); } catch (e) {} } },
    isMuted() { return muted; },
    toggle() { muted = !muted; try { localStorage.setItem("tt_game_mute", muted ? "1" : "0"); } catch (e) {} return muted; },
    good() { tone(660, .12, "triangle", .18); setTimeout(() => tone(990, .18, "triangle", .18), 90); },
    bad() { tone(220, .28, "sawtooth", .09, 110); },
    shot() { tone(1100, .08, "square", .05, 320); },
    pop() { tone(480, .09, "sine", .16, 1300); },
    tick() { tone(740, .07, "sine", .12); },
    win() { [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => tone(f, .2, "triangle", .16), i * 110)); },
  };
})();

// 이 기기에 남기는 '내 최고 기록'(게임 포인트). 막혀 있어도 게임은 그대로 돈다.
function gameBest(key) { try { return Number(localStorage.getItem("tt_gbest_" + key) || 0) || 0; } catch (e) { return 0; } }
function setGameBest(key, v) { try { localStorage.setItem("tt_gbest_" + key, String(v)); } catch (e) {} }

function MuteBtn() {
  const [m, setM] = useState(GameSfx.isMuted());
  return <button className="gm-pill" onClick={() => setM(GameSfx.toggle())} style={{ cursor: "pointer" }}>{m ? "🔇" : "🔊"}</button>;
}

// 시작 화면 — 버튼을 한 번 눌러야 소리(AudioContext)가 열린다
function GameReady({ icon, name, how, onStart, onBack, onClassic, onShuffle, best, today }) {
  return <>
    <button onClick={onBack} style={{ background: "none", color: "var(--navy)", fontWeight: 700, marginBottom: 10 }}>‹ 모드 선택</button>
    <div className="gm-sky" style={{ padding: "34px 20px 60px", textAlign: "center", color: "#fff" }}>
      {[[12, 18], [80, 30], [30, 70], [65, 12], [90, 60], [45, 40]].map(([x, y], k) =>
        <span key={k} className="gm-star" style={{ left: x + "%", top: y + "%", animationDelay: (k * .4) + "s" }} />)}
      {today && <div style={{ fontSize: 12, fontWeight: 800, color: "#1B2E4C", background: "#E4C766", display: "inline-block", padding: "3px 12px", borderRadius: 999, marginBottom: 12 }}>✨ 오늘의 게임</div>}
      <div style={{ fontSize: 60, lineHeight: 1 }}>{icon}</div>
      <div style={{ fontSize: 26, fontWeight: 900, marginTop: 10, color: "#E4C766" }}>{name}</div>
      <div style={{ fontSize: 14, marginTop: 10, lineHeight: 1.7, opacity: .92, wordBreak: "keep-all" }}>{how}</div>
      {best > 0 && !isKin() && <div style={{ marginTop: 12, fontSize: 13, color: "#E4C766", fontWeight: 700 }}>🏆 내 최고 기록 {best.toLocaleString()}점</div>}
      <div className="gm-ground">🌳<span>🌱</span>🌳<span>🌱</span>🌳</div>
    </div>
    <button className="btn full" style={{ marginTop: 12, fontSize: 18, padding: "14px 16px", background: "#C9A227", color: "#1B2E4C", fontWeight: 900 }}
      onClick={() => { GameSfx.unlock(); onStart(); }}>▶ 게임 시작</button>
    {onShuffle && <button className="btn-ghost" style={{ width: "100%", marginTop: 8 }} onClick={onShuffle}>🎲 다른 게임 하기</button>}
    {onClassic && <button onClick={onClassic} style={{ display: "block", margin: "12px auto 0", background: "none", color: "var(--navy-soft)", fontSize: 13, textDecoration: "underline" }}>
      게임 말고 차분하게 풀기 ›</button>}
  </>;
}

function GameCountdown({ onDone }) {
  const [n, setN] = useState(3);
  useEffect(() => {
    GameSfx.tick();
    const t = setTimeout(() => { if (n <= 1) onDone(); else setN(n - 1); }, 650);
    return () => clearTimeout(t);
  }, [n]);
  return <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 5, background: "rgba(10,18,32,.45)" }}>
    <div key={n} style={{ fontSize: 86, fontWeight: 900, color: "#E4C766", animation: "gmCount .65s ease-out" }}>{n}</div>
  </div>;
}

/* 결과 화면. stats = 알약에 넣을 글자들, stars = 0~3(없으면 안 보임), headline = 점수 아래 한 줄 */
function GameResult({ icon, label, title, points, stars, stats, headline, isNewBest, best, wrong, onAgain, onBack, wrongLabel }) {
  const kin = isKin();
  useEffect(() => { GameSfx.win(); }, []);
  return <>
    <div className="gm-sky" style={{ padding: "26px 18px 56px", textAlign: "center", color: "#fff" }}>
      <div style={{ fontSize: 48, lineHeight: 1 }}>{icon}</div>
      <div style={{ fontSize: 21, fontWeight: 900, marginTop: 6, color: "#E4C766" }}>{label} 끝!</div>
      <div style={{ fontSize: 12, opacity: .8, marginTop: 4 }}>{title}</div>
      {kin
        ? <div style={{ fontSize: 22, fontWeight: 800, marginTop: 14 }}>🌟 끝까지 다 했어요!</div>
        : <>
          {stars != null && <div style={{ fontSize: 34, marginTop: 10, letterSpacing: 4 }}>{"⭐".repeat(stars)}<span style={{ opacity: .25 }}>{"⭐".repeat(3 - stars)}</span></div>}
          <div style={{ fontSize: 44, fontWeight: 900, marginTop: 4 }}>{(points || 0).toLocaleString()}<span style={{ fontSize: 18 }}>점</span></div>
          {headline && <div style={{ fontSize: 16, fontWeight: 900, marginTop: 2 }}>{headline}</div>}
          {isNewBest ? <div style={{ fontSize: 15, fontWeight: 900, color: "#E4C766", marginTop: 2 }}>🏆 새 기록!</div>
            : best > 0 ? <div style={{ fontSize: 12, opacity: .8, marginTop: 2 }}>내 최고 {best.toLocaleString()}점</div> : null}
          <div style={{ display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 8, marginTop: 12, fontSize: 13 }}>
            {(stats || []).map((t, k) => <span key={k} className="gm-pill" style={{ color: "var(--navy)" }}>{t}</span>)}
          </div>
        </>}
      <div className="gm-ground">🌳<span>🌱</span>🌳<span>🌱</span>🌳</div>
    </div>
    {wrong && wrong.length > 0 && <>
      <div style={{ fontWeight: 700, color: "var(--navy)", margin: "14px 4px 8px", fontSize: 14 }}>{wrongLabel || "한 번 더 볼 단어"} {kin ? "" : wrong.length + "개"}</div>
      {wrong.map((p, k) => (
        <div key={k} className="card" style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", gap: 10 }}>
          <b style={{ color: "var(--navy)" }}>{p.word}</b><span className="muted" style={{ textAlign: "right" }}>{p.kor}</span>
        </div>
      ))}
    </>}
    <div className="row" style={{ gap: 8, marginTop: 14 }}>
      <button className="btn-ghost" style={{ flex: 1 }} onClick={onBack}>모드 선택으로</button>
      <button className="btn" style={{ flex: 1, background: "#C9A227", color: "#1B2E4C", fontWeight: 800 }} onClick={onAgain}>🔁 한 판 더</button>
    </div>
  </>;
}
const starsOf = (c, t) => { const p = t ? c / t : 0; return p >= .9 ? 3 : p >= .6 ? 2 : 1; };
// 판이 끝날 때: 기기 최고 기록 비교·저장
function gameFinal(bestKey, points) {
  const best = gameBest(bestKey), isNew = !isKin() && points > best;
  if (isNew) setGameBest(bestKey, points);
  return { isNew, best };
}
const sayWord = (p, voice) => { try { playModel(p.audio, p.word, voice); } catch (e) {} };

// 오답 보기: 뜻이 같은 단어는 빼고(정답이 둘 되면 안 된다), 서로도 겹치지 않게
function gameDistractors(pairs, q, n) {
  const seen = new Set([String(q.kor).trim()]);
  const out = [];
  for (const p of shuffleArr(pairs)) {
    const k = String(p.kor).trim();
    if (p === q || seen.has(k)) continue;
    seen.add(k); out.push(p.kor);
    if (out.length >= n) break;
  }
  return out;
}

const RAIN_COLORS = ["#D94A3D", "#2E6FB0", "#B8901C", "#3E8E63"];

// ================= 🌧️ 단어 비 =================
function WordRainPlay({ pairs, title, voice, onBack, onDone, limit, label, uid, onAgain }) {
  const kin = isKin();
  const bestKey = "rain_" + (uid || "");
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q =>
    ({ ...q, options: shuffleArr([q.kor, ...gameDistractors(pairs, q, 3)]) })));
  const [phase, setPhase] = useState("count");   // count | play | result
  const [i, setI] = useState(0);
  const [status, setStatus] = useState("fall");  // fall | hit | wrong | miss
  const [picked, setPicked] = useState(null);
  const [points, setPoints] = useState(0);
  const [combo, setCombo] = useState(0);
  const [gain, setGain] = useState(null);        // {v, key} 떠오르는 +점수
  const [final, setFinal] = useState(null);
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [] });
  const prog = useRef(0);
  const wordEl = useRef(null);
  const skyEl = useRef(null);
  const SKY_H = 300;
  const q = qs[i];
  const level = Math.floor(st.current.correct / 4) + 1;
  const dur = kin ? 12 : Math.max(3.6, 8 - (level - 1) * 0.7);   // 한 단어가 땅까지 오는 초

  const placeWord = () => {
    const el = wordEl.current; if (!el) return;
    const h = el.offsetHeight || 50;
    el.style.top = (8 + prog.current * (SKY_H - 34 - h - 8)) + "px";
  };

  // 새 단어: 맨 위에서 시작 + 발음 들려주기
  useEffect(() => {
    if (phase !== "play" || !q) return;
    prog.current = 0; placeWord();
    try { playModel(q.audio, q.word, voice); } catch (e) {}
  }, [i, phase]);

  // 떨어지기
  useEffect(() => {
    if (phase !== "play" || status !== "fall") return;
    let raf, last = null;
    const loop = (t) => {
      if (last != null) prog.current += Math.min(0.05, (t - last) / 1000) / dur;
      last = t;
      if (prog.current >= 1) { prog.current = 1; placeWord(); miss(); return; }
      placeWord();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [phase, status, i]);

  const next = (delay) => setTimeout(() => {
    if (i + 1 >= qs.length) {
      const s = st.current, best = gameBest(bestKey), isNew = !kin && s.points > best;
      if (isNew) setGameBest(bestKey, s.points);
      setFinal({ isNew, best });
      setPhase("result");
      onDone(s.correct, qs.length);
    } else { setI(i + 1); setPicked(null); setStatus("fall"); }
  }, delay);

  const lose = () => {
    st.current.combo = 0; setCombo(0);
    st.current.wrong.push(q);
    GameSfx.bad();
  };
  const miss = () => { setStatus("miss"); lose(); next(1300); };

  const choose = (opt) => {
    if (status !== "fall") return;
    setPicked(opt);
    if (opt === q.kor) {
      const s = st.current;
      s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo);
      const v = 100 + Math.round((1 - prog.current) * 100) + (s.combo - 1) * 20;
      s.points += v;
      setPoints(s.points); setCombo(s.combo); setGain({ v, key: i });
      setStatus("hit"); GameSfx.good();
      next(700);
    } else { setStatus("wrong"); lose(); next(1300); }
  };

  if (phase === "result") return <GameResult icon="🌧️" label={label || "단어 비"} title={title} points={st.current.points}
    stars={starsOf(st.current.correct, qs.length)} stats={[`✅ ${st.current.correct}/${qs.length}`, `🔥 최대 콤보 ${st.current.maxCombo}`]}
    isNewBest={final.isNew} best={final.best} wrong={st.current.wrong} onAgain={onAgain} onBack={onBack} />;

  const wordStyle = {
    position: "absolute", left: "50%", transform: "translate(-50%,0)", top: 8, zIndex: 2,
    background: status === "hit" ? "#E4C766" : status === "fall" ? "#fff" : "#F6E1DC",
    color: "#1B2E4C", padding: "10px 22px", borderRadius: 999, fontSize: 26, fontWeight: 900,
    boxShadow: "0 0 18px rgba(255,255,255,.45)", whiteSpace: "nowrap", maxWidth: "92%", overflow: "hidden", textOverflow: "ellipsis",
    animation: status === "hit" ? "gmPop .6s ease-out forwards" : (status === "wrong" || status === "miss") ? "gmShake .45s" : "none",
  };
  return <>
    <div className="gm-hud">
      <button onClick={onBack} style={{ background: "none", color: "var(--navy)", fontWeight: 700 }}>‹ 그만하기</button>
      <div className="row" style={{ gap: 6 }}>
        <span className="gm-pill">{i + 1}/{qs.length}</span>
        {!kin && <span className="gm-pill">⚡ Lv.{level}</span>}
        {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{points.toLocaleString()}점</span>}
        <MuteBtn />
      </div>
    </div>
    <div className="gm-sky" ref={skyEl} style={{ height: SKY_H }}>
      {[[8, 14], [22, 46], [40, 10], [58, 34], [74, 18], [90, 44], [14, 70], [84, 72]].map(([x, y], k) =>
        <span key={k} className="gm-star" style={{ left: x + "%", top: y + "%", animationDelay: (k * .3) + "s" }} />)}
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      {phase === "play" && q && <div ref={wordEl} key={"w" + i} style={wordStyle}>{q.word}</div>}
      {status === "hit" && gain && <div key={"g" + gain.key} style={{ position: "absolute", left: "50%", top: 40, color: "#E4C766", fontWeight: 900, fontSize: 22, animation: "gmFloatUp .8s ease-out forwards", zIndex: 3 }}>
        {kin ? "✨ 팡!" : `+${gain.v}`}</div>}
      {!kin && combo >= 2 && status === "hit" && <div style={{ position: "absolute", right: 12, top: 10, color: "#FF9F43", fontWeight: 900, fontSize: 18, zIndex: 3 }}>🔥 {combo} 콤보!</div>}
      {(status === "wrong" || status === "miss") && <div style={{ position: "absolute", left: 0, right: 0, bottom: 44, textAlign: "center", zIndex: 3 }}>
        <span style={{ background: "rgba(0,0,0,.55)", color: "#fff", padding: "6px 14px", borderRadius: 10, fontSize: 15, fontWeight: 700 }}>
          {status === "miss" ? "앗, 놓쳤어요! " : ""}정답: <span style={{ color: "#E4C766" }}>{q.kor}</span></span>
      </div>}
      <div className="gm-ground">🌳<span>🌱</span>🌳<span>🌱</span>🌳<span>🌱</span>🌳</div>
    </div>
    <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      {(q ? q.options : []).map((opt, k) => {
        let bg = RAIN_COLORS[k % 4], op = 1, ring = "none";
        if (status !== "fall") {
          if (opt === q.kor) ring = "0 0 0 4px #E4C766";
          else if (opt === picked) { bg = "#7A7A7A"; }
          else op = .45;
        }
        return <button key={k} onPointerDown={(e) => { e.preventDefault(); choose(opt); }} disabled={phase !== "play" || status !== "fall"}
          style={{ minHeight: 62, padding: "10px 10px", borderRadius: 14, background: bg, color: "#fff", fontSize: 15.5, fontWeight: 800, opacity: op, boxShadow: ring,
            wordBreak: "keep-all", lineHeight: 1.35, transition: "opacity .2s", border: "none" }}>{opt}</button>;
      })}
    </div>
  </>;
}

// ================= 🚀 스펠링 슈터 =================
const IS_LETTER = /[a-z]/i;
const BUB = 48;          // 글자 공 지름(px)
const SHOOT_H = 300;     // 하늘 높이
const CANNON_Y = SHOOT_H - 26;

function SpellShooterPlay({ pairs, title, voice, onBack, onDone, label, uid, onAgain }) {
  const kin = isKin();
  const bestKey = "shoot_" + (uid || "");
  const [qs] = useState(() => shuffleArr(pairs.filter(p => IS_LETTER.test(p.word))).slice(0, studyCount(pairs.length)));
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [pos, setPos] = useState(0);              // 다음에 쏠 글자 자리(글자 아닌 것은 건너뜀)
  const [miss, setMiss] = useState(0);            // 이 단어에서 틀린 횟수
  const [wordState, setWordState] = useState("go"); // go | done | gaveup
  const [bubbles, setBubbles] = useState([]);     // [{id,ch}] — 위치는 ref 에서 움직인다
  const [laser, setLaser] = useState(null);
  const [angle, setAngle] = useState(0);
  const [bursts, setBursts] = useState([]);
  const [flashBad, setFlashBad] = useState(0);
  const [points, setPoints] = useState(0);
  const [final, setFinal] = useState(null);
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [] });
  const phys = useRef({});        // id → {x,y,vx,vy}
  const els = useRef({});         // id → element
  const skyEl = useRef(null);
  const nextId = useRef(1);
  const q = qs[i];
  const chars = q ? Array.from(q.word) : [];
  const skipNon = (p) => { while (p < chars.length && !IS_LETTER.test(chars[p])) p++; return p; };
  const curPos = skipNon(pos);
  const needCh = curPos < chars.length ? chars[curPos].toLowerCase() : null;
  const hint = miss >= 3;

  const W = () => (skyEl.current && skyEl.current.offsetWidth) || 340;

  // 화면에 띄울 글자 공 고르기: 다음 글자는 꼭 하나, 나머지는 남은 글자와 헷갈리는 글자 섞어서
  const makeBubbles = (p) => {
    const rest = chars.slice(p).filter(c => IS_LETTER.test(c)).map(c => c.toLowerCase());
    if (!rest.length) return [];
    const target = Math.min(8, Math.max(5, new Set(rest).size + 2));
    const list = [rest[0]];
    const later = shuffleArr(rest.slice(1));
    while (list.length < target && later.length && list.length < target - 2) list.push(later.pop());
    const ABC = "abcdefghijklmnopqrstuvwxyz";
    while (list.length < target) {
      const c = ABC[Math.floor(Math.random() * 26)];
      if (c !== rest[0] || Math.random() < .2) list.push(c);
    }
    const w = W();
    const sp = kin ? 26 : 42 + Math.min(30, st.current.correct * 3);
    const out = [];
    shuffleArr(list).forEach((ch) => {
      const id = nextId.current++;
      const a = Math.random() * Math.PI * 2, v = sp * (.6 + Math.random() * .6);
      phys.current[id] = { x: 6 + Math.random() * (w - BUB - 12), y: 6 + Math.random() * (SHOOT_H - BUB - 90), vx: Math.cos(a) * v, vy: Math.sin(a) * v };
      out.push({ id, ch });
    });
    return out;
  };

  const resetWord = () => {
    phys.current = {}; els.current = {};
    setPos(0); setMiss(0); setWordState("go");
    setBubbles(makeBubbles(skipNon(0)));
  };
  useEffect(() => {
    if (phase !== "play" || !q) return;
    resetWord();
    try { playModel(q.audio, q.word, voice); } catch (e) {}
  }, [i, phase]);

  // 글자 공 떠다니기(벽에 튕김)
  useEffect(() => {
    if (phase !== "play") return;
    let raf, last = null;
    const loop = (t) => {
      const dt = last == null ? 0 : Math.min(0.05, (t - last) / 1000); last = t;
      const w = W(), maxY = SHOOT_H - BUB - 70;
      for (const id in phys.current) {
        const b = phys.current[id];
        b.x += b.vx * dt; b.y += b.vy * dt;
        if (b.x < 2) { b.x = 2; b.vx = Math.abs(b.vx); }
        if (b.x > w - BUB - 2) { b.x = w - BUB - 2; b.vx = -Math.abs(b.vx); }
        if (b.y < 2) { b.y = 2; b.vy = Math.abs(b.vy); }
        if (b.y > maxY) { b.y = maxY; b.vy = -Math.abs(b.vy); }
        const el = els.current[id];
        if (el) el.style.transform = `translate(${b.x}px,${b.y}px)`;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [phase]);

  const finishGame = () => {
    const s = st.current, best = gameBest(bestKey), isNew = !kin && s.points > best;
    if (isNew) setGameBest(bestKey, s.points);
    setFinal({ isNew, best }); setPhase("result");
    onDone(s.correct, qs.length);
  };
  const goNext = (delay) => setTimeout(() => { if (i + 1 >= qs.length) finishGame(); else setI(i + 1); }, delay);

  const wordDone = (missCount) => {
    const s = st.current;
    setWordState("done"); GameSfx.good();
    try { playModel(q.audio, q.word, voice); } catch (e) {}
    const letters = chars.filter(c => IS_LETTER.test(c)).length;
    if (missCount === 0) { s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo); }
    else { s.combo = 0; s.wrong.push(q); }
    const v = letters * 15 + (missCount === 0 ? 100 + (s.combo - 1) * 30 : Math.max(0, 40 - missCount * 10));
    s.points += v; setPoints(s.points);
    phys.current = {}; setBubbles([]);
    goNext(1100);
  };

  const shoot = (b) => {
    if (wordState !== "go" || !b) return;
    const p = phys.current[b.id];
    if (p) {
      const cx = W() / 2, tx = p.x + BUB / 2, ty = p.y + BUB / 2;
      setLaser({ x1: cx, y1: CANNON_Y, x2: tx, y2: ty, k: Date.now() });
      setAngle(Math.atan2(tx - cx, CANNON_Y - ty) * 180 / Math.PI);
      setBursts(bs => [...bs.slice(-4), { x: tx, y: ty, k: b.id, ok: b.ch === needCh }]);
      setTimeout(() => setLaser(null), 140);
    }
    GameSfx.shot();
    delete phys.current[b.id]; delete els.current[b.id];
    if (b.ch === needCh) {
      GameSfx.pop();
      const np = skipNon(curPos + 1);
      setPos(np);
      if (np >= chars.length) { wordDone(miss); return; }
      // 남은 공 중에 다음 글자가 없으면 새로 채운다
      setBubbles(bs => {
        const left = bs.filter(x => x.id !== b.id);
        const nextCh = chars[np].toLowerCase();
        if (left.some(x => x.ch === nextCh) && left.length >= 4) return left;
        left.forEach(x => { delete phys.current[x.id]; delete els.current[x.id]; });
        return makeBubbles(np);
      });
    } else {
      GameSfx.bad();
      setMiss(m => m + 1); setFlashBad(k => k + 1);
      st.current.combo = 0;
      setBubbles(bs => {
        const left = bs.filter(x => x.id !== b.id);
        return left.length >= 3 ? left : (left.forEach(x => { delete phys.current[x.id]; }), makeBubbles(curPos));
      });
    }
  };
  const shootRef = useRef(shoot); shootRef.current = shoot;
  const goRef = useRef(true); goRef.current = wordState === "go";
  const bubRef = useRef(bubbles); bubRef.current = bubbles;

  // 키보드로도 쏠 수 있게(노트북·키보드 태블릿)
  useEffect(() => {
    if (phase !== "play") return;
    const onKey = (e) => {
      const k = (e.key || "").toLowerCase();
      if (k.length !== 1 || !IS_LETTER.test(k)) return;
      e.preventDefault();
      if (!goRef.current) return;
      const b = bubRef.current.find(x => x.ch === k);
      if (b) shootRef.current(b);
      else { GameSfx.bad(); setMiss(m => m + 1); setFlashBad(n => n + 1); st.current.combo = 0; }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  const giveUp = () => {
    if (wordState !== "go") return;
    setWordState("gaveup"); GameSfx.bad();
    st.current.combo = 0; st.current.wrong.push(q);
    setPos(chars.length);
    phys.current = {}; setBubbles([]);
    try { playModel(q.audio, q.word, voice); } catch (e) {}
    goNext(2200);
  };

  if (phase === "result") return <GameResult icon="🚀" label={label || "스펠링 슈터"} title={title} points={st.current.points}
    stars={starsOf(st.current.correct, qs.length)} stats={[`✅ ${st.current.correct}/${qs.length}`, `🔥 최대 콤보 ${st.current.maxCombo}`]}
    isNewBest={final.isNew} best={final.best} wrong={st.current.wrong} onAgain={onAgain} onBack={onBack} />;

  const w = W();
  return <>
    <div className="gm-hud">
      <button onClick={onBack} style={{ background: "none", color: "var(--navy)", fontWeight: 700 }}>‹ 그만하기</button>
      <div className="row" style={{ gap: 6 }}>
        <span className="gm-pill">{Math.min(i + 1, qs.length)}/{qs.length}</span>
        {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{points.toLocaleString()}점</span>}
        {!kin && st.current.combo >= 2 && <span className="gm-pill" style={{ color: "#E06A1B" }}>🔥{st.current.combo}</span>}
        <MuteBtn />
      </div>
    </div>
    {/* 뜻 + 칸 */}
    <div className="card" style={{ padding: "12px 14px", textAlign: "center", marginBottom: 8 }}>
      <div style={{ fontSize: 19, fontWeight: 800, color: "var(--navy)", wordBreak: "keep-all" }}>{q ? q.kor : ""}</div>
      <div key={"fb" + flashBad} style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 4, marginTop: 10, animation: flashBad ? "gmShake .35s" : "none" }}>
        {chars.map((c, k) => {
          const letter = IS_LETTER.test(c);
          if (!letter) return <span key={k} style={{ width: c === " " ? 12 : "auto", fontSize: 22, fontWeight: 800, color: "var(--navy)" }}>{c === " " ? "" : c}</span>;
          const shown = k < curPos || wordState !== "go";
          const isNext = k === curPos && wordState === "go";
          return <span key={k} style={{ minWidth: 24, padding: "0 2px", fontSize: 24, fontWeight: 900, lineHeight: "32px",
            color: wordState === "gaveup" ? "var(--danger)" : "#2E7D5B", borderBottom: "3px solid " + (shown ? "#8FC7AA" : "#C8C1AE"),
            animation: isNext ? "gmBlink 1s infinite" : "none" }}>{shown ? c : ""}</span>;
        })}
      </div>
      {wordState === "gaveup" && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>이렇게 써요! 한 번 더 볼 단어에 넣어 둘게요</div>}
      {wordState === "done" && <div style={{ fontSize: 14, fontWeight: 800, color: "#2E7D5B", marginTop: 6 }}>{miss === 0 && !kin ? "🎯 한 번에 성공!" : "✅ 완성!"}</div>}
    </div>
    <div className="gm-sky" ref={skyEl} style={{ height: SHOOT_H }}>
      {[[8, 14], [22, 46], [40, 10], [58, 34], [74, 18], [90, 44]].map(([x, y], k) =>
        <span key={k} className="gm-star" style={{ left: x + "%", top: y + "%", animationDelay: (k * .3) + "s" }} />)}
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      {bubbles.map(b => {
        const p = phys.current[b.id] || { x: 0, y: 0 };
        const glow = hint && b.ch === needCh;
        return <button key={b.id} ref={el => { if (el) els.current[b.id] = el; }}
          onPointerDown={(e) => { e.preventDefault(); shoot(b); }}
          style={{ position: "absolute", left: 0, top: 0, width: BUB, height: BUB, borderRadius: "50%", transform: `translate(${p.x}px,${p.y}px)`,
            background: "radial-gradient(circle at 35% 30%,#FFFFFF,#CFE0F7 60%,#8FB2E0)", color: "#1B2E4C", fontSize: 24, fontWeight: 900,
            border: "2px solid rgba(255,255,255,.8)", boxShadow: "0 3px 10px rgba(0,0,0,.35)", padding: 0, zIndex: 2,
            animation: glow ? "gmGlow 1s infinite" : "none" }}>{b.ch}</button>;
      })}
      {bursts.map(bu => <span key={"b" + bu.k} style={{ position: "absolute", left: bu.x - 28, top: bu.y - 28, width: 56, height: 56, borderRadius: "50%",
        border: "4px solid " + (bu.ok ? "#E4C766" : "#D94A3D"), animation: "gmBurst .4s ease-out forwards", pointerEvents: "none", zIndex: 3 }} />)}
      <svg width="100%" height={SHOOT_H} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none", zIndex: 3 }}>
        {laser && <line x1={laser.x1} y1={laser.y1} x2={laser.x2} y2={laser.y2} stroke="#FF5A5A" strokeWidth="4" strokeLinecap="round" />}
      </svg>
      {/* 대포 */}
      <div style={{ position: "absolute", left: w / 2 - 6, top: CANNON_Y - 38, width: 12, height: 40, background: "#E4C766", borderRadius: 6,
        transformOrigin: "50% 100%", transform: `rotate(${angle}deg)`, transition: "transform .08s", zIndex: 4 }} />
      <div style={{ position: "absolute", left: w / 2 - 22, top: CANNON_Y - 12, width: 44, height: 30, background: "#C9A227", borderRadius: "22px 22px 6px 6px", zIndex: 4,
        boxShadow: "0 -2px 0 #F2DC8C inset" }} />
      <div className="gm-ground" style={{ height: 22 }} />
      {phase === "play" && wordState === "go" && <button onClick={giveUp}
        style={{ position: "absolute", right: 8, bottom: 26, zIndex: 5, background: "rgba(255,255,255,.18)", color: "#fff", fontSize: 12, padding: "5px 10px", borderRadius: 999, border: "1px solid rgba(255,255,255,.35)" }}>
        모르겠어요 🙋</button>}
      {hint && wordState === "go" && <div style={{ position: "absolute", left: 10, bottom: 28, zIndex: 5, color: "#E4C766", fontSize: 12, fontWeight: 700 }}>💡 반짝이는 글자를 쏴 봐요</div>}
    </div>
  </>;
}

// 보드 나누기: n개를 한 판 최대 size개로, 마지막 판이 1개만 남지 않게 고르게
function splitBoards(arr, size) {
  const k = Math.max(1, Math.ceil(arr.length / size)), per = Math.ceil(arr.length / k), out = [];
  for (let i = 0; i < arr.length; i += per) out.push(arr.slice(i, i + per));
  return out;
}
const textSize = (t, big, small) => String(t || "").length > 9 ? small : big;

function GameHud({ onBack, children }) {
  return <div className="gm-hud">
    <button onClick={onBack} style={{ background: "none", color: "var(--navy)", fontWeight: 700 }}>‹ 그만하기</button>
    <div className="row" style={{ gap: 6 }}>{children}<MuteBtn /></div>
  </div>;
}

// ================= 🧠 메모리 카드 (카드 암기) =================
// 판을 시작하면 카드를 잠깐 다 보여 주고(외우기) 뒤집는다. 영어 카드를 열면 발음이 나온다.
function MemoryPlay({ pairs, title, voice, onBack, onDone, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const [boards] = useState(() => splitBoards(shuffleArr(pairs).slice(0, Math.max(2, studyCount(pairs.length))), 6));
  const [b, setB] = useState(0);
  const [cards, setCards] = useState([]);
  const [peek, setPeek] = useState(true);
  const [phase, setPhase] = useState("play");
  const [, force] = useState(0);
  const st = useRef({ points: 0, misses: 0, moves: 0, combo: 0, maxCombo: 0, t0: Date.now(), sel: [], busy: false, final: null, sec: 0 });
  const total = boards.reduce((a, x) => a + x.length, 0);

  useEffect(() => {
    const words = boards[b] || [];
    setCards(shuffleArr(words.flatMap((p, pi) => [
      { key: pi + "e", pi, side: "en", text: p.word, p, open: true, done: false },
      { key: pi + "k", pi, side: "ko", text: p.kor, p, open: true, done: false },
    ])));
    setPeek(true); st.current.sel = []; st.current.busy = false;
    const t = setTimeout(() => { setPeek(false); setCards(cs => cs.map(c => ({ ...c, open: false }))); }, kin ? 5000 : 1800 + words.length * 350);
    return () => clearTimeout(t);
  }, [b]);

  const flip = (idx) => {
    const s = st.current, c = cards[idx];
    if (peek || s.busy || !c || c.open || c.done) return;
    if (c.side === "en") sayWord(c.p, voice);
    const next = cards.map((x, k) => k === idx ? { ...x, open: true } : x);
    setCards(next);
    s.sel = [...s.sel, idx];
    if (s.sel.length < 2) return;
    const [a, z] = s.sel; s.sel = []; s.moves++;
    const A = next[a], Z = next[z];
    if (A.pi === Z.pi && A.side !== Z.side) {
      s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo); s.points += 100 + (s.combo - 1) * 20;
      GameSfx.good();
      const done = next.map((x, k) => (k === a || k === z) ? { ...x, done: true } : x);
      setCards(done); force(n => n + 1);
      if (done.every(x => x.done)) {
        s.busy = true;
        setTimeout(() => {
          if (b + 1 < boards.length) setB(b + 1);
          else {
            s.sec = Math.round((Date.now() - s.t0) / 1000);
            s.points += Math.max(0, total * 30 - s.sec * 2);
            s.final = gameFinal(bestKey, s.points);
            setPhase("result"); onDone(total, total);
          }
        }, 700);
      }
    } else {
      s.misses++; s.combo = 0; s.busy = true; GameSfx.bad(); force(n => n + 1);
      setTimeout(() => { setCards(cs => cs.map((x, k) => (k === a || k === z) ? { ...x, open: false } : x)); s.busy = false; }, 900);
    }
  };

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={s.misses <= total * .5 ? 3 : s.misses <= total * 1.5 ? 2 : 1}
    stats={[`🃏 ${total}쌍`, `🎯 ${s.moves}번 뒤집기`, `⏱ ${s.sec}초`]} isNewBest={s.final.isNew} best={s.final.best} wrong={[]} onAgain={onAgain} onBack={onBack} />;
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">판 {b + 1}/{boards.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
    </GameHud>
    <div style={{ textAlign: "center", fontSize: 13, fontWeight: 700, color: peek ? "#B8901C" : "var(--navy-soft)", marginBottom: 8 }}>
      {peek ? "👀 잘 봐 두세요! 곧 카드가 뒤집혀요" : "영어 카드와 뜻 카드 짝을 찾아요"}</div>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
      {cards.map((c, k) => {
        const show = c.open || c.done;
        return <button key={c.key + "_" + b} onPointerDown={(e) => { e.preventDefault(); flip(k); }}
          style={{ minHeight: 86, borderRadius: 14, border: "none", padding: 6, wordBreak: "keep-all", lineHeight: 1.25,
            background: !show ? "linear-gradient(135deg,#2E4A75,#1B2E4C)" : c.done ? "#E3F1E9" : c.side === "en" ? "#fff" : "#FFF6DA",
            color: c.done ? "#2E7D5B" : "#1B2E4C", fontWeight: 800, fontSize: show ? textSize(c.text, c.side === "en" ? 19 : 15, 13) : 30,
            boxShadow: "0 3px 8px rgba(0,0,0,.15)", outline: c.done ? "2px solid #8FC7AA" : c.side === "ko" && show ? "2px solid #E4C766" : "none",
            animation: show && !c.done ? "gmFlipIn .2s" : c.done ? "gmFade .5s forwards" : "none" }}>
          {show ? c.text : "🌳"}</button>;
      })}
    </div>
  </>;
}

// ================= 🔗 짝 잇기 (카드 암기) =================
function MatchPlay({ pairs, title, voice, onBack, onDone, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const [boards] = useState(() => splitBoards(shuffleArr(pairs).slice(0, Math.max(2, studyCount(pairs.length))), 5));
  const [b, setB] = useState(0);
  const [cols, setCols] = useState({ L: [], R: [] });
  const [selL, setSelL] = useState(null);
  const [selR, setSelR] = useState(null);
  const [done, setDone] = useState({});
  const [bad, setBad] = useState(null);
  const [phase, setPhase] = useState("play");
  const st = useRef({ points: 0, misses: 0, combo: 0, maxCombo: 0, t0: Date.now(), final: null, sec: 0 });
  const total = boards.reduce((a, x) => a + x.length, 0);

  useEffect(() => {
    const w = (boards[b] || []).map((p, i) => ({ ...p, id: i }));
    setCols({ L: shuffleArr(w), R: shuffleArr(w) }); setDone({}); setSelL(null); setSelR(null);
  }, [b]);

  const check = (l, r) => {
    const s = st.current;
    if (l == null || r == null) return;
    if (l === r) {
      s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo); s.points += 100 + (s.combo - 1) * 20; GameSfx.good();
      const nd = { ...done, [l]: true }; setDone(nd); setSelL(null); setSelR(null);
      if (Object.keys(nd).length >= cols.L.length) setTimeout(() => {
        if (b + 1 < boards.length) setB(b + 1);
        else {
          s.sec = Math.round((Date.now() - s.t0) / 1000);
          s.points += Math.max(0, total * 25 - s.sec * 2);
          s.final = gameFinal(bestKey, s.points); setPhase("result"); onDone(total, total);
        }
      }, 600);
    } else {
      s.misses++; s.combo = 0; GameSfx.bad(); setBad({ l, r });
      setTimeout(() => { setSelL(null); setSelR(null); setBad(null); }, 450);
    }
  };
  const tapL = (p) => { if (done[p.id] || bad) return; sayWord(p, voice); setSelL(p.id); check(p.id, selR); };
  const tapR = (p) => { if (done[p.id] || bad) return; setSelR(p.id); check(selL, p.id); };

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={s.misses === 0 ? 3 : s.misses <= total * .5 ? 2 : 1}
    stats={[`🔗 ${total}쌍`, `❌ ${s.misses}번 헷갈림`, `⏱ ${s.sec}초`]} isNewBest={s.final.isNew} best={s.final.best} wrong={[]} onAgain={onAgain} onBack={onBack} />;
  const cell = (p, side) => {
    const sel = side === "L" ? selL === p.id : selR === p.id;
    const isBad = bad && (side === "L" ? bad.l === p.id : bad.r === p.id);
    const ok = done[p.id];
    return <button key={side + p.id + "_" + b} onPointerDown={(e) => { e.preventDefault(); side === "L" ? tapL(p) : tapR(p); }}
      style={{ minHeight: 56, borderRadius: 12, padding: "8px 8px", fontWeight: 800, wordBreak: "keep-all", lineHeight: 1.3,
        fontSize: side === "L" ? textSize(p.word, 18, 14) : 14.5,
        background: ok ? "#E3F1E9" : isBad ? "#F6E1DC" : sel ? "#E4C766" : side === "L" ? "#fff" : "#FFF6DA",
        color: ok ? "#2E7D5B" : "#1B2E4C", border: "2px solid " + (ok ? "#8FC7AA" : sel ? "#C9A227" : "var(--line)"),
        animation: isBad ? "gmShake .4s" : ok ? "gmFade .5s forwards" : "none" }}>{side === "L" ? p.word : p.kor}</button>;
  };
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">판 {b + 1}/{boards.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
    </GameHud>
    <div style={{ textAlign: "center", fontSize: 13, fontWeight: 700, color: "var(--navy-soft)", marginBottom: 8 }}>왼쪽 영어와 오른쪽 뜻을 하나씩 눌러 짝을 이어요</div>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      <div style={{ display: "grid", gap: 8, alignContent: "start" }}>{cols.L.map(p => cell(p, "L"))}</div>
      <div style={{ display: "grid", gap: 8, alignContent: "start" }}>{cols.R.map(p => cell(p, "R"))}</div>
    </div>
  </>;
}

// 뜻 고르기 문제 묶음(두더지·풍선 공통)
function useChoiceQs(pairs, limit) {
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q =>
    ({ ...q, options: shuffleArr([q.kor, ...gameDistractors(pairs, q, 3)]) })));
  return qs;
}
function WordBanner({ q, voice }) {
  return <div className="card" style={{ padding: "12px 14px", textAlign: "center", marginBottom: 8, display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
    <div style={{ fontSize: textSize(q && q.word, 28, 22), fontWeight: 900, color: "var(--navy)" }}>{q ? q.word : ""}</div>
    {q && <button onPointerDown={(e) => { e.preventDefault(); sayWord(q, voice); }} style={{ background: "none", fontSize: 20 }}>🔊</button>}
  </div>;
}
const EMPTY6 = [null, null, null, null, null, null];

// ================= 🔨 두더지 잡기 (뜻 고르기) =================
// 구멍 6개에서 두더지가 뜻 팻말을 들고 올라온다. 맞는 뜻의 두더지를 잡는다. 세 번 올라오는 동안 못 잡으면 놓침.
function MolePlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const qs = useChoiceQs(pairs, limit);
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [holes, setHoles] = useState(EMPTY6);
  const [wave, setWave] = useState(0);
  const [status, setStatus] = useState("go");
  const [hitHole, setHitHole] = useState(null);
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [], final: null, wave: 0 });
  const q = qs[i];
  const UP = kin ? 3200 : Math.max(1500, 2300 - st.current.correct * 60);

  useEffect(() => { if (phase === "play" && q) sayWord(q, voice); }, [i, phase]);

  useEffect(() => {
    if (phase !== "play" || status !== "go" || !q) return;
    let alive = true, t;
    const show = (n) => {
      if (!alive) return;
      if (n >= 3) { setHoles(EMPTY6); lose("miss"); return; }
      st.current.wave = n; setWave(n);
      const spots = shuffleArr([0, 1, 2, 3, 4, 5]).slice(0, q.options.length);
      const h = EMPTY6.slice();
      spots.forEach((sp, k) => { h[sp] = q.options[k]; });
      setHoles(h);
      t = setTimeout(() => { if (!alive) return; setHoles(EMPTY6); t = setTimeout(() => show(n + 1), 280); }, UP);
    };
    show(0);
    return () => { alive = false; clearTimeout(t); };
  }, [phase, status, i]);

  const next = (delay) => setTimeout(() => {
    if (i + 1 >= qs.length) { const s = st.current; s.final = gameFinal(bestKey, s.points); setPhase("result"); onDone(s.correct, qs.length); }
    else { setI(i + 1); setStatus("go"); setHitHole(null); setHoles(EMPTY6); }
  }, delay);
  const lose = (why) => { const s = st.current; s.combo = 0; s.wrong.push(q); GameSfx.bad(); setStatus(why); next(1300); };
  const whack = (k) => {
    if (status !== "go" || holes[k] == null) return;
    setHitHole(k);
    if (holes[k] === q.kor) {
      const s = st.current; s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo);
      s.points += 100 + (2 - s.wave) * 50 + (s.combo - 1) * 20;
      GameSfx.good(); setStatus("hit"); next(700);
    } else lose("wrong");
  };

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={starsOf(s.correct, qs.length)} stats={[`✅ ${s.correct}/${qs.length}`, `🔥 최대 콤보 ${s.maxCombo}`]}
    isNewBest={s.final.isNew} best={s.final.best} wrong={s.wrong} onAgain={onAgain} onBack={onBack} />;
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">{i + 1}/{qs.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
    </GameHud>
    <WordBanner q={q} voice={voice} />
    <div className="gm-sky" style={{ padding: "18px 10px 46px", background: "linear-gradient(180deg,#9BD3F0 0%,#CDEBC0 60%,#7FBF6A 100%)" }}>
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "14px 10px" }}>
        {holes.map((opt, k) => {
          const isHit = hitHole === k;
          return <div key={k} style={{ position: "relative", height: 112, overflow: "hidden" }}>
            <div style={{ position: "absolute", left: "6%", right: "6%", bottom: 0, height: 26, borderRadius: "50%", background: "#4A3220", zIndex: 1 }} />
            {opt != null && <button key={"m" + i + "_" + wave + "_" + k} onPointerDown={(e) => { e.preventDefault(); whack(k); }}
              style={{ position: "absolute", left: "4%", right: "4%", bottom: 10, height: 98, border: "none", background: "none", padding: 0, zIndex: 2,
                animation: "gmMoleUp .22s ease-out", display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div style={{ fontSize: 34, lineHeight: 1 }}>{isHit ? (opt === q.kor ? "😵" : "😝") : "🐹"}</div>
              <div style={{ marginTop: 2, background: isHit ? (opt === q.kor ? "#E4C766" : "#F6E1DC") : "#FFF8E6", color: "#1B2E4C", border: "2px solid #8A5A2B", borderRadius: 8,
                fontSize: 13, fontWeight: 800, padding: "3px 4px", width: "100%", lineHeight: 1.25, wordBreak: "keep-all" }}>{opt}</div>
            </button>}
          </div>;
        })}
      </div>
      {(status === "wrong" || status === "miss") && <div style={{ position: "absolute", left: 0, right: 0, bottom: 8, textAlign: "center", zIndex: 3 }}>
        <span style={{ background: "rgba(0,0,0,.6)", color: "#fff", padding: "6px 14px", borderRadius: 10, fontSize: 15, fontWeight: 700 }}>
          {status === "miss" ? "앗, 놓쳤어요! " : ""}정답: <span style={{ color: "#E4C766" }}>{q.kor}</span></span></div>}
      {status === "go" && phase === "play" && <div style={{ position: "absolute", left: 10, bottom: 10, fontSize: 12, fontWeight: 800, color: "#1B2E4C" }}>
        {"🔨".repeat(3 - wave)}</div>}
    </div>
  </>;
}

// ================= 🎈 풍선 터뜨리기 (뜻 고르기) =================
function BalloonPlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const qs = useChoiceQs(pairs, limit);
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [status, setStatus] = useState("go");
  const [popped, setPopped] = useState(null);
  const [lift, setLift] = useState(0);         // 몇 번째 떠오름(두 번 다 날아가면 놓침)
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [], final: null });
  const bal = useRef([]);
  const els = useRef([]);
  const H = 330;
  const q = qs[i];
  const COLORS = ["#E8584A", "#3D86D0", "#E2A922", "#4BAA74"];

  useEffect(() => { if (phase === "play" && q) sayWord(q, voice); }, [i, phase]);

  useEffect(() => {
    if (phase !== "play" || status !== "go" || !q) return;
    const base = kin ? 11 : Math.max(5, 8.5 - st.current.correct * 0.25);
    bal.current = q.options.map(() => ({ prog: -Math.random() * 0.25, dur: base * (0.85 + Math.random() * 0.35) }));
    let raf, last = null;
    const loop = (t) => {
      const dt = last == null ? 0 : Math.min(0.05, (t - last) / 1000); last = t;
      let allGone = true;
      bal.current.forEach((b, k) => {
        b.prog += dt / b.dur;
        if (b.prog < 1) allGone = false;
        const el = els.current[k];
        if (el) el.style.transform = `translateY(${-Math.max(0, b.prog) * (H + 120)}px)`;
      });
      if (allGone) {
        if (lift >= 1) lose("miss"); else setLift(l => l + 1);
        return;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [phase, status, i, lift]);

  const next = (delay) => setTimeout(() => {
    if (i + 1 >= qs.length) { const s = st.current; s.final = gameFinal(bestKey, s.points); setPhase("result"); onDone(s.correct, qs.length); }
    else { setI(i + 1); setStatus("go"); setPopped(null); setLift(0); }
  }, delay);
  const lose = (why) => { const s = st.current; s.combo = 0; s.wrong.push(q); GameSfx.bad(); setStatus(why); next(1300); };
  const pop = (k) => {
    if (status !== "go") return;
    setPopped(k);
    if (q.options[k] === q.kor) {
      const s = st.current; s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo);
      const pr = Math.max(0, (bal.current[k] || {}).prog || 0);
      s.points += 100 + Math.round((1 - Math.min(1, pr)) * 80) + (lift === 0 ? 30 : 0) + (s.combo - 1) * 20;
      GameSfx.pop(); GameSfx.good(); setStatus("hit"); next(700);
    } else lose("wrong");
  };

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={starsOf(s.correct, qs.length)} stats={[`✅ ${s.correct}/${qs.length}`, `🔥 최대 콤보 ${s.maxCombo}`]}
    isNewBest={s.final.isNew} best={s.final.best} wrong={s.wrong} onAgain={onAgain} onBack={onBack} />;
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">{i + 1}/{qs.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
    </GameHud>
    <WordBanner q={q} voice={voice} />
    <div className="gm-sky" style={{ height: H, background: "linear-gradient(180deg,#7EC8F2 0%,#BFE6FA 70%,#E9F7FF 100%)" }}>
      {[[10, 12], [62, 8], [35, 30]].map(([x, y], k) => <span key={k} style={{ position: "absolute", left: x + "%", top: y + "%", fontSize: 30, opacity: .8 }}>☁️</span>)}
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      {phase === "play" && q && q.options.map((opt, k) => {
        const isPop = popped === k, right = opt === q.kor, reveal = status !== "go";
        return <div key={"b" + i + "_" + lift + "_" + k} ref={el => { els.current[k] = el; }}
          style={{ position: "absolute", left: (2 + k * 24.5) + "%", width: "23%", bottom: -110, zIndex: 2, opacity: reveal && !right && !isPop ? .35 : 1 }}>
          <button onPointerDown={(e) => { e.preventDefault(); pop(k); }}
            style={{ width: "100%", height: 96, borderRadius: "50% 50% 46% 46%", border: "none", padding: "4px 5px", background: isPop ? "transparent" : COLORS[k],
              color: "#fff", fontWeight: 900, fontSize: 13, lineHeight: 1.2, wordBreak: "keep-all",
              boxShadow: isPop ? "none" : (reveal && right ? "0 0 0 4px #1B2E4C, " : "") + "inset -8px -10px 0 rgba(0,0,0,.12)",
              textShadow: "0 1px 2px rgba(0,0,0,.35)" }}>{isPop ? <span style={{ fontSize: 40 }}>{right ? "💥" : "💨"}</span> : opt}</button>
          {!isPop && <div style={{ width: 2, height: 30, background: "#7A8899", margin: "0 auto" }} />}
        </div>;
      })}
      {(status === "wrong" || status === "miss") && <div style={{ position: "absolute", left: 0, right: 0, top: 12, textAlign: "center", zIndex: 3 }}>
        <span style={{ background: "rgba(0,0,0,.6)", color: "#fff", padding: "6px 14px", borderRadius: 10, fontSize: 15, fontWeight: 700 }}>
          {status === "miss" ? "풍선이 날아갔어요! " : ""}정답: <span style={{ color: "#E4C766" }}>{q.kor}</span></span></div>}
      {lift === 1 && status === "go" && <div style={{ position: "absolute", left: 10, top: 10, fontSize: 12, fontWeight: 800, color: "#1B2E4C", zIndex: 3 }}>한 번 더 올라와요!</div>}
    </div>
  </>;
}

// 스펠링 공통: 문제 고르기·뜻 카드
function useSpellQs(pairs) {
  const [qs] = useState(() => shuffleArr(pairs.filter(p => IS_LETTER.test(p.word))).slice(0, studyCount(pairs.length)));
  return qs;
}
function MeaningCard({ q, children }) {
  return <div className="card" style={{ padding: "12px 14px", textAlign: "center", marginBottom: 8 }}>
    <div style={{ fontSize: 19, fontWeight: 800, color: "var(--navy)", wordBreak: "keep-all" }}>{q ? q.kor : ""}</div>
    {children}
  </div>;
}

// ================= 🧩 글자 블록 (스펠링) =================
// 섞인 글자 블록을 칸에 채운다. 다 채우면 채점, 틀린 칸만 블록으로 돌아간다. 세 번 틀리면 정답 보여 주기.
function BlocksPlay({ pairs, title, voice, onBack, onDone, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const qs = useSpellQs(pairs);
  const [i, setI] = useState(0);
  const [tiles, setTiles] = useState([]);   // [{id, ch, used}]
  const [slots, setSlots] = useState([]);   // 자리마다 tile id / null / 'fixed'(글자 아닌 자리)
  const [tries, setTries] = useState(0);
  const [state, setState] = useState("go"); // go | ok | fail
  const [shake, setShake] = useState(0);
  const [phase, setPhase] = useState("play");
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [], final: null });
  const q = qs[i];
  const chars = q ? Array.from(q.word) : [];

  useEffect(() => {
    if (!q) return;
    const letters = chars.filter(c => IS_LETTER.test(c)).map(c => c.toLowerCase());
    const extra = letters.length <= 7 ? 2 : letters.length <= 11 ? 1 : 0;
    const ABC = "abcdefghijklmnopqrstuvwxyz", ex = [];
    for (let k = 0; k < extra; k++) ex.push(ABC[Math.floor(Math.random() * 26)]);
    setTiles(shuffleArr([...letters, ...ex]).map((ch, id) => ({ id, ch, used: false })));
    setSlots(chars.map(c => IS_LETTER.test(c) ? null : "fixed"));
    setTries(0); setState("go");
    sayWord(q, voice);
  }, [i]);

  const finishWord = (ok, nTries) => {
    const s = st.current;
    if (ok && nTries === 0) { s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo); }
    else { s.combo = 0; s.wrong.push(q); }
    const letters = chars.filter(c => IS_LETTER.test(c)).length;
    s.points += ok ? letters * 15 + (nTries === 0 ? 100 + (s.combo - 1) * 30 : Math.max(0, 40 - nTries * 10)) : 0;
    setState(ok ? "ok" : "fail");
    if (ok) GameSfx.good(); else GameSfx.bad();
    sayWord(q, voice);
    setTimeout(() => {
      if (i + 1 >= qs.length) { s.final = gameFinal(bestKey, s.points); setPhase("result"); onDone(s.correct, qs.length); }
      else setI(i + 1);
    }, ok ? 1100 : 2200);
  };

  const place = (t) => {
    if (state !== "go" || t.used) return;
    const k = slots.findIndex(x => x === null);
    if (k < 0) return;
    GameSfx.tick();
    const ns = slots.slice(); ns[k] = t.id;
    const nt = tiles.map(x => x.id === t.id ? { ...x, used: true } : x);
    setSlots(ns); setTiles(nt);
    if (ns.includes(null)) return;
    const wrongIdx = ns.map((id, j) => id === "fixed" ? -1 : (nt.find(x => x.id === id).ch !== chars[j].toLowerCase() ? j : -1)).filter(j => j >= 0);
    if (!wrongIdx.length) { finishWord(true, tries); return; }
    const nTries = tries + 1; setTries(nTries); setShake(n => n + 1); GameSfx.bad();
    if (nTries >= 3) { setTimeout(() => finishWord(false, nTries), 400); return; }
    setTimeout(() => {
      const back = new Set(wrongIdx.map(j => ns[j]));
      setSlots(ns.map((id, j) => wrongIdx.includes(j) ? null : id));
      setTiles(nt.map(x => back.has(x.id) ? { ...x, used: false } : x));
    }, 500);
  };
  const unplace = (j) => {
    if (state !== "go" || slots[j] == null || slots[j] === "fixed") return;
    const id = slots[j];
    setSlots(slots.map((x, k) => k === j ? null : x));
    setTiles(tiles.map(x => x.id === id ? { ...x, used: false } : x));
  };
  const resetAll = () => {
    if (state !== "go") return;
    setSlots(chars.map(c => IS_LETTER.test(c) ? null : "fixed"));
    setTiles(tiles.map(x => ({ ...x, used: false })));
  };

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={starsOf(s.correct, qs.length)} stats={[`✅ 한 번에 ${s.correct}/${qs.length}`, `🔥 최대 콤보 ${s.maxCombo}`]}
    isNewBest={s.final.isNew} best={s.final.best} wrong={s.wrong} onAgain={onAgain} onBack={onBack} />;
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">{i + 1}/{qs.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
      {state === "go" && <span className="gm-pill">{"❤️".repeat(3 - tries)}</span>}
    </GameHud>
    <MeaningCard q={q}>
      <div key={"sh" + shake} style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 5, marginTop: 12, animation: shake ? "gmShake .35s" : "none" }}>
        {chars.map((c, j) => {
          if (slots[j] === "fixed") return <span key={j} style={{ width: c === " " ? 12 : "auto", fontSize: 24, fontWeight: 900, color: "var(--navy)", alignSelf: "center" }}>{c === " " ? "" : c}</span>;
          const id = slots[j], t = id != null ? tiles.find(x => x.id === id) : null;
          const show = state === "fail" ? c : t ? t.ch : "";
          return <button key={j} onPointerDown={(e) => { e.preventDefault(); unplace(j); }}
            style={{ width: 38, height: 44, borderRadius: 9, fontSize: 22, fontWeight: 900, padding: 0,
              background: state === "ok" ? "#E3F1E9" : state === "fail" ? "#FBEFEC" : t ? "#FFF6DA" : "#F3F0E7",
              color: state === "fail" ? "var(--danger)" : "#1B2E4C", border: "2px " + (t || state !== "go" ? "solid #C9A227" : "dashed #C8C1AE") }}>{show}</button>;
        })}
      </div>
      {state === "ok" && <div style={{ fontSize: 14, fontWeight: 800, color: "#2E7D5B", marginTop: 8 }}>{tries === 0 && !kin ? "🎯 한 번에 성공!" : "✅ 완성!"}</div>}
      {state === "fail" && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>이렇게 써요! 한 번 더 볼 단어에 넣어 둘게요</div>}
    </MeaningCard>
    <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, padding: "16px 8px", background: "#F3EEE0", borderRadius: 16, minHeight: 80 }}>
      {tiles.map(t => <button key={t.id + "_" + i} onPointerDown={(e) => { e.preventDefault(); place(t); }} disabled={t.used || state !== "go"}
        style={{ width: 50, height: 54, borderRadius: 12, fontSize: 26, fontWeight: 900, padding: 0, border: "none",
          background: t.used ? "transparent" : "linear-gradient(180deg,#FFD978,#E4B33A)", color: "#1B2E4C",
          boxShadow: t.used ? "inset 0 0 0 2px #E2DACA" : "0 4px 0 #B8901C" }}>{t.used ? "" : t.ch}</button>)}
    </div>
    {state === "go" && <button onClick={resetAll} className="btn-ghost" style={{ width: "100%", marginTop: 10 }}>↺ 다시 놓기</button>}
  </>;
}

// ================= 🌳 나무 지키기 (스펠링) =================
// 뜻을 보고 들어갈 글자를 하나씩 고른다. 없는 글자를 고르면 사과가 하나 떨어진다. 사과가 다 떨어지기 전에 완성!
function TreePlay({ pairs, title, voice, onBack, onDone, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const qs = useSpellQs(pairs);
  const LIVES = kin ? 9 : 6;
  const [i, setI] = useState(0);
  const [guessed, setGuessed] = useState({});
  const [miss, setMiss] = useState(0);
  const [state, setState] = useState("go");
  const [phase, setPhase] = useState("play");
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [], final: null });
  const q = qs[i];
  const chars = q ? Array.from(q.word) : [];
  const need = new Set(chars.filter(c => IS_LETTER.test(c)).map(c => c.toLowerCase()));

  useEffect(() => { if (q) { setGuessed({}); setMiss(0); setState("go"); sayWord(q, voice); } }, [i]);

  const end = (ok, misses) => {
    const s = st.current;
    if (ok && misses <= 2) { s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo); }
    else { s.combo = 0; s.wrong.push(q); }
    s.points += ok ? 60 + (LIVES - misses) * 25 + (misses <= 2 ? (s.combo - 1) * 25 : 0) : 0;
    setState(ok ? "ok" : "fail"); if (ok) GameSfx.good(); else GameSfx.bad();
    sayWord(q, voice);
    setTimeout(() => {
      if (i + 1 >= qs.length) { s.final = gameFinal(bestKey, s.points); setPhase("result"); onDone(s.correct, qs.length); }
      else setI(i + 1);
    }, ok ? 1100 : 2200);
  };
  const guess = (ch) => {
    if (state !== "go" || guessed[ch]) return;
    const g = { ...guessed, [ch]: true }; setGuessed(g);
    if (need.has(ch)) {
      GameSfx.pop();
      if ([...need].every(c => g[c])) end(true, miss);
    } else {
      GameSfx.bad(); const m = miss + 1; setMiss(m);
      if (m >= LIVES) end(false, m);
    }
  };
  const guessRef = useRef(guess); guessRef.current = guess;
  useEffect(() => {
    const onKey = (e) => { const k = (e.key || "").toLowerCase(); if (k.length === 1 && /[a-z]/.test(k)) { e.preventDefault(); guessRef.current(k); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={starsOf(s.correct, qs.length)} stats={[`✅ ${s.correct}/${qs.length}`, `🔥 최대 콤보 ${s.maxCombo}`]}
    isNewBest={s.final.isNew} best={s.final.best} wrong={s.wrong} onAgain={onAgain} onBack={onBack} />;
  const APPLE_POS = [[30, 22], [52, 14], [68, 28], [40, 40], [60, 44], [22, 42], [78, 44], [46, 26], [34, 8]];
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">{i + 1}/{qs.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
    </GameHud>
    <div style={{ display: "flex", gap: 10, alignItems: "stretch" }}>
      <div className="gm-sky" style={{ width: 120, flex: "0 0 120px", height: 150, background: "linear-gradient(180deg,#BFE6FA,#E9F7FF)" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 4, textAlign: "center", fontSize: 92, lineHeight: 1 }}>🌳</div>
        {Array.from({ length: LIVES }, (_, k) => { const [x, y] = APPLE_POS[k % APPLE_POS.length], on = k < LIVES - miss;
          return <span key={k + "_" + i} style={{ position: "absolute", left: x + "%", top: y + "%", fontSize: 17, zIndex: 2, animation: on ? "none" : "gmFall .7s forwards" }}>🍎</span>; })}
        <div className="gm-ground" style={{ height: 18 }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <MeaningCard q={q}>
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 4, marginTop: 10 }}>
            {chars.map((c, k) => {
              if (!IS_LETTER.test(c)) return <span key={k} style={{ width: c === " " ? 10 : "auto", fontSize: 22, fontWeight: 900 }}>{c === " " ? "" : c}</span>;
              const got = guessed[c.toLowerCase()], show = got || state === "fail";
              return <span key={k} style={{ minWidth: 20, fontSize: 22, fontWeight: 900, lineHeight: "30px", borderBottom: "3px solid #C8C1AE",
                color: state === "fail" && !got ? "var(--danger)" : "#2E7D5B" }}>{show ? c : ""}</span>;
            })}
          </div>
          {state === "ok" && <div style={{ fontSize: 14, fontWeight: 800, color: "#2E7D5B", marginTop: 6 }}>🍎 나무를 지켰어요!</div>}
          {state === "fail" && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>이렇게 써요! 한 번 더 볼 단어에 넣어 둘게요</div>}
        </MeaningCard>
      </div>
    </div>
    <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
      {["qwertyuiop", "asdfghjkl", "zxcvbnm"].map((row, r) => <div key={r} style={{ display: "flex", justifyContent: "center", gap: 4 }}>
        {Array.from(row).map(ch => {
          const used = guessed[ch], good = used && need.has(ch);
          return <button key={ch} onPointerDown={(e) => { e.preventDefault(); guess(ch); }} disabled={!!used || state !== "go"}
            style={{ flex: "0 1 34px", minWidth: 0, height: 46, borderRadius: 8, fontSize: 19, fontWeight: 800, padding: 0, border: "none",
              background: !used ? "#fff" : good ? "#BFE0CC" : "#E8E3D6", color: !used ? "#1B2E4C" : good ? "#2E7D5B" : "#AAA49A",
              boxShadow: used ? "none" : "0 2px 0 #C8C1AE" }}>{ch}</button>;
        })}
      </div>)}
    </div>
    {state === "go" && <button className="btn-ghost" style={{ width: "100%", marginTop: 10 }} onClick={() => { if (state === "go") end(false, LIVES); }}>모르겠어요 🙋</button>}
  </>;
}

// ================= ⏱️ 스피드 퀴즈 · 🏁 단어 레이스 (미니 테스트) =================
// 문제 종류를 섞는다: 영어→뜻, 뜻→영어, 듣고→뜻. 문제마다 제한 시간. 레이스는 컴퓨터 차와 경주한다.
function QuizRacePlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain, skin }) {
  const kin = isKin();
  const race = skin === "race" && !kin;
  const T = kin ? 25 : 10;   // 한 문제 제한 시간(초)
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q => {
    const type = ["meaning", "english", "listen"][Math.floor(Math.random() * 3)];
    if (type === "english") {
      const seen = new Set([q.word.toLowerCase()]), opts = [];
      for (const p of shuffleArr(pairs)) {
        const k = p.word.toLowerCase();
        if (!seen.has(k) && String(p.kor).trim() !== String(q.kor).trim()) { seen.add(k); opts.push(p.word); }
        if (opts.length >= 3) break;
      }
      return { ...q, type, answer: q.word, options: shuffleArr([q.word, ...opts]) };
    }
    return { ...q, type, answer: q.kor, options: shuffleArr([q.kor, ...gameDistractors(pairs, q, 3)]) };
  }));
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState(null);
  const [status, setStatus] = useState("go");
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [], final: null, t0: 0, won: null });
  const barEl = useRef(null);
  const rivalEl = useRef(null);
  const left = useRef(T);
  const q = qs[i];
  const RIVAL_SEC = qs.length * T * 0.5;   // 컴퓨터 차가 결승선까지 걸리는 시간

  useEffect(() => { if (phase === "play" && q && q.type !== "english") sayWord(q, voice); }, [i, phase]);

  useEffect(() => {
    if (phase !== "play") return;
    if (!st.current.t0) st.current.t0 = performance.now();
    let raf, last = null;
    const loop = (t) => {
      const dt = last == null ? 0 : Math.min(0.05, (t - last) / 1000); last = t;
      if (status === "go") {
        left.current -= dt;
        if (barEl.current) barEl.current.style.width = Math.max(0, left.current / T * 100) + "%";
        if (left.current <= 0) { choose(null); return; }
      }
      if (race && rivalEl.current) {
        const r = Math.min(1, (performance.now() - st.current.t0) / 1000 / RIVAL_SEC);
        rivalEl.current.style.left = (r * 86) + "%";
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [phase, status, i]);

  const choose = (opt) => {
    if (status !== "go") return;
    setPicked(opt);
    const s = st.current, ok = opt === q.answer;
    if (ok) {
      s.correct++; s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo);
      s.points += 100 + Math.round(Math.max(0, left.current) * 12) + (s.combo - 1) * 15;
      GameSfx.good(); setStatus("ok");
    } else { s.combo = 0; s.wrong.push(q); GameSfx.bad(); setStatus(opt == null ? "timeout" : "no"); }
    setTimeout(() => {
      if (i + 1 >= qs.length) {
        if (race) { const el = (performance.now() - s.t0) / 1000; s.won = el < RIVAL_SEC && s.correct >= qs.length * .6; if (s.won) s.points += 300; }
        s.final = gameFinal(bestKey, s.points); setPhase("result"); onDone(s.correct, qs.length);
      } else { left.current = T; setI(i + 1); setPicked(null); setStatus("go"); }
    }, ok ? 600 : 1300);
  };

  const s = st.current;
  if (phase === "result") return <GameResult icon={icon} label={label} title={title} points={s.points}
    stars={starsOf(s.correct, qs.length)} headline={race ? (s.won ? "🏁 레이스 우승!" : "🚙 아깝게 졌어요, 한 판 더!") : null}
    stats={[`✅ ${s.correct}/${qs.length}`, `🔥 최대 콤보 ${s.maxCombo}`]}
    isNewBest={s.final.isNew} best={s.final.best} wrong={s.wrong} onAgain={onAgain} onBack={onBack} />;
  const prompt = !q ? "" : q.type === "english" ? q.kor : q.type === "listen" ? null : q.word;
  return <>
    <GameHud onBack={onBack}>
      <span className="gm-pill">{i + 1}/{qs.length}</span>
      {!kin && <span className="gm-pill" style={{ color: "#B8901C" }}>{s.points.toLocaleString()}점</span>}
      {!kin && s.combo >= 2 && <span className="gm-pill" style={{ color: "#E06A1B" }}>🔥{s.combo}</span>}
    </GameHud>
    {race && <div className="gm-sky" style={{ height: 78, marginBottom: 8, background: "#5B6470" }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 38, borderTop: "3px dashed #F2DC8C" }} />
      <div style={{ position: "absolute", right: 8, top: 0, bottom: 0, width: 10, background: "repeating-linear-gradient(0deg,#fff 0 8px,#222 8px 16px)" }} />
      <div style={{ position: "absolute", left: ((s.correct / qs.length) * 86) + "%", top: 4, fontSize: 28, transition: "left .4s" }}><span style={{ display: "inline-block", transform: "scaleX(-1)" }}>🚗</span></div>
      <div ref={rivalEl} style={{ position: "absolute", left: 0, top: 42, fontSize: 28, opacity: .85 }}><span style={{ display: "inline-block", transform: "scaleX(-1)" }}>🚙</span></div>
      <div style={{ position: "absolute", right: 22, top: 4, fontSize: 10, color: "#fff", fontWeight: 800 }}>나</div>
      <div style={{ position: "absolute", right: 22, top: 44, fontSize: 10, color: "#fff", fontWeight: 800 }}>컴퓨터</div>
    </div>}
    {phase === "count" ? <div className="gm-sky" style={{ height: 170 }}><GameCountdown onDone={() => setPhase("play")} /></div> : <>
      <div className="card" style={{ padding: "16px 14px", textAlign: "center" }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: "var(--navy-soft)", marginBottom: 6 }}>
          {q.type === "meaning" ? "뜻을 골라요" : q.type === "english" ? "영어 단어를 골라요" : "🎧 듣고 뜻을 골라요"}</div>
        {prompt != null
          ? <div style={{ fontSize: q.type === "english" ? 21 : textSize(prompt, 28, 22), fontWeight: 900, color: "var(--navy)", wordBreak: "keep-all" }}>{prompt}</div>
          : <button onPointerDown={(e) => { e.preventDefault(); sayWord(q, voice); }} style={{ fontSize: 38, background: "#FFF6DA", borderRadius: 999, width: 76, height: 76, border: "2px solid #E4C766" }}>🔊</button>}
        {(status === "no" || status === "timeout") && <div style={{ marginTop: 8, fontSize: 14, fontWeight: 800, color: "var(--danger)" }}>
          {status === "timeout" ? "⏰ 시간이 다 됐어요! " : ""}정답: {q.type === "listen" ? `${q.word} = ${q.kor}` : q.answer}</div>}
        {status === "ok" && q.type === "listen" && <div style={{ marginTop: 8, fontSize: 14, fontWeight: 800, color: "#2E7D5B" }}>{q.word} = {q.kor}</div>}
        <div style={{ height: 8, background: "#EDE7D8", borderRadius: 99, marginTop: 12, overflow: "hidden" }}>
          <div ref={barEl} style={{ height: "100%", width: "100%", background: "linear-gradient(90deg,#E06A1B,#E4C766)", borderRadius: 99 }} />
        </div>
      </div>
      <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {q.options.map((opt, k) => {
          let bg = RAIN_COLORS[k % 4], op = 1, ring = "none";
          if (status !== "go") { if (opt === q.answer) ring = "0 0 0 4px #1B2E4C"; else if (opt === picked) bg = "#7A7A7A"; else op = .45; }
          return <button key={i + "_" + k} onPointerDown={(e) => { e.preventDefault(); choose(opt); }} disabled={status !== "go"}
            style={{ minHeight: 62, padding: "10px", borderRadius: 14, background: bg, color: "#fff", fontSize: q.type === "english" ? 18 : 15.5, fontWeight: 800, opacity: op,
              boxShadow: ring, wordBreak: "keep-all", lineHeight: 1.35, border: "none" }}>{opt}</button>;
        })}
      </div>
    </>}
  </>;
}

// ================= 게임 묶음 · 오늘의 게임 =================
const GAME_POOLS = {
  flash: [
    { id: "memory", icon: "🧠", name: "메모리 카드", short: "같은 짝 카드 찾기", Comp: MemoryPlay,
      how: <>카드를 잠깐 보여 준 뒤 뒤집어요.<br />영어 카드와 <b>뜻 카드</b>의 짝을 찾아 뒤집어요.<br />적게 뒤집을수록, 빨리 찾을수록 점수가 커져요.</> },
    { id: "match", icon: "🔗", name: "짝 잇기", short: "영어와 뜻 이어 주기", Comp: MatchPlay,
      how: <>왼쪽엔 영어, 오른쪽엔 뜻이 섞여 있어요.<br />하나씩 눌러 <b>짝을 이어요</b>.<br />헷갈리지 않고 빨리 이을수록 점수가 커져요.</> },
  ],
  choice: [
    { id: "rain", icon: "🌧️", name: "단어 비", short: "떨어지는 단어 터뜨리기", Comp: WordRainPlay,
      how: <>하늘에서 영어 단어가 떨어져요!<br />땅에 닿기 전에 <b>알맞은 뜻</b>을 눌러 팡! 터뜨려요.<br />빨리 맞힐수록, 연속으로 맞힐수록 점수가 커져요.</> },
    { id: "mole", icon: "🔨", name: "두더지 잡기", short: "맞는 뜻 두더지 잡기", Comp: MolePlay,
      how: <>두더지들이 뜻 팻말을 들고 올라와요.<br />위 영어 단어의 <b>뜻을 든 두더지</b>를 콩! 잡아요.<br />세 번 올라오는 동안 잡아야 해요.</> },
    { id: "balloon", icon: "🎈", name: "풍선 터뜨리기", short: "맞는 뜻 풍선 터뜨리기", Comp: BalloonPlay,
      how: <>뜻이 적힌 풍선들이 하늘로 날아가요.<br />위 영어 단어의 <b>뜻 풍선</b>을 눌러 터뜨려요.<br />높이 날아가기 전에 터뜨릴수록 점수가 커져요.</> },
  ],
  spell: [
    { id: "shoot", icon: "🚀", name: "스펠링 슈터", short: "글자를 순서대로 쏘기", Comp: SpellShooterPlay,
      how: <>한글 뜻을 보고, 떠다니는 <b>글자를 순서대로</b> 쏴요!<br />단어가 완성되면 다음 단어로 넘어가요.<br />키보드가 있으면 글자를 눌러도 쏴져요. 한 번에 맞히면 보너스!</> },
    { id: "blocks", icon: "🧩", name: "글자 블록", short: "섞인 블록으로 단어 만들기", Comp: BlocksPlay,
      how: <>섞여 있는 글자 블록을 눌러<br />빈칸에 <b>차례대로 채워</b> 단어를 만들어요.<br />기회는 세 번! 한 번에 맞히면 보너스!</> },
    { id: "tree", icon: "🌳", name: "나무 지키기", short: "글자 맞혀 사과 지키기", Comp: TreePlay,
      how: <>뜻을 보고 단어에 들어갈 <b>글자를 골라요</b>.<br />없는 글자를 고르면 사과가 하나 떨어져요.<br />사과가 다 떨어지기 전에 단어를 완성해요!</> },
  ],
  test: [
    { id: "speed", icon: "⏱️", name: "스피드 퀴즈", short: "시간 안에 섞어 풀기", Comp: QuizRacePlay, skin: "speed",
      how: <>뜻 고르기 · 영어 고르기 · 듣고 고르기가 섞여 나와요.<br />문제마다 <b>제한 시간</b>이 있어요.<br />빨리 맞힐수록 점수가 커져요. 맞힌 개수는 기록에 남아요!</> },
    { id: "race", icon: "🏁", name: "단어 레이스", short: "컴퓨터 차와 경주", Comp: QuizRacePlay, skin: "race", noKin: true,
      how: <>맞힐 때마다 내 차가 앞으로 가요.<br />컴퓨터 차보다 <b>먼저 결승선</b>에 들어가요!<br />문제는 섞여 나오고, 맞힌 개수는 기록에 남아요.</> },
  ],
};
function gamePool(stage) { return (GAME_POOLS[stage] || []).filter(g => !(g.noKin && isKin())); }
function _ymd() { const d = new Date(); return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate(); }
// 오늘의 게임: 같은 날·같은 아이·같은 단어장·같은 단계면 늘 같은 게임, 날이 바뀌면 바뀐다
function todayGameIndex(stage, uid, aid) {
  const pool = gamePool(stage);
  if (!pool.length) return 0;
  const key = _ymd() + "|" + (uid || "") + "|" + (aid || "") + "|" + stage;
  let h = 5381;
  for (let k = 0; k < key.length; k++) h = ((h * 33) ^ key.charCodeAt(k)) >>> 0;
  return h % pool.length;
}
function todayGame(stage, uid, aid) { return gamePool(stage)[todayGameIndex(stage, uid, aid)]; }

function GameStage({ stage, pairs, title, voice, uid, aid, limit, onBack, onDone, onClassic }) {
  const pool = gamePool(stage);
  const start = todayGameIndex(stage, uid, aid);
  const [idx, setIdx] = useState(start);
  const [playing, setPlaying] = useState(false);
  const [round, setRound] = useState(0);
  const g = pool[idx % pool.length];
  const bestKey = g.id + "_" + (uid || "");
  if (!playing) return <GameReady icon={g.icon} name={g.name} how={g.how} best={gameBest(bestKey)} today={idx === start}
    onStart={() => setPlaying(true)} onBack={onBack} onClassic={onClassic}
    onShuffle={pool.length > 1 ? () => setIdx(n => (n + 1) % pool.length) : null} />;
  const C = g.Comp;
  return <C key={g.id + round} pairs={pairs} title={title} voice={voice} uid={uid} bestKey={bestKey} label={g.name} icon={g.icon} skin={g.skin}
    limit={limit} onBack={onBack} onDone={onDone} onAgain={() => setRound(r => r + 1)} />;
}
