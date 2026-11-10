// 단어익힘 게임판 (2026-11-10 원장 "게임하듯이 — 단어가 내려오면 뜻을 고르고, 쏘아서 스펠링을 맞추는").
//   🌧️ 단어 비     = '뜻 고르기' 단계. 떨어지는 단어가 땅에 닿기 전에 뜻을 골라 터뜨린다.
//   🚀 스펠링 슈터 = '스펠링' 단계. 떠다니는 글자를 순서대로 쏴서 단어를 완성한다.
// 서버에 남는 건 예전과 똑같이 (맞은 개수, 문제 수) — 단계 완료·최고점 규칙은 그대로다.
// 게임 점수(포인트·콤보)는 재미용이라 이 기기에만 '내 최고 기록'으로 남긴다.
// 유치부(isKin)는 점수·콤보 숫자를 안 보이고 천천히 떨어진다(유아 평가 금지).
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
function GameReady({ icon, name, how, onStart, onBack, onClassic, best }) {
  return <>
    <button onClick={onBack} style={{ background: "none", color: "var(--navy)", fontWeight: 700, marginBottom: 10 }}>‹ 모드 선택</button>
    <div className="gm-sky" style={{ padding: "34px 20px 60px", textAlign: "center", color: "#fff" }}>
      {[[12, 18], [80, 30], [30, 70], [65, 12], [90, 60], [45, 40]].map(([x, y], k) =>
        <span key={k} className="gm-star" style={{ left: x + "%", top: y + "%", animationDelay: (k * .4) + "s" }} />)}
      <div style={{ fontSize: 60, lineHeight: 1 }}>{icon}</div>
      <div style={{ fontSize: 26, fontWeight: 900, marginTop: 10, color: "#E4C766" }}>{name}</div>
      <div style={{ fontSize: 14, marginTop: 10, lineHeight: 1.7, opacity: .92, wordBreak: "keep-all" }}>{how}</div>
      {best > 0 && !isKin() && <div style={{ marginTop: 12, fontSize: 13, color: "#E4C766", fontWeight: 700 }}>🏆 내 최고 기록 {best.toLocaleString()}점</div>}
      <div className="gm-ground">🌳<span>🌱</span>🌳<span>🌱</span>🌳</div>
    </div>
    <button className="btn full" style={{ marginTop: 12, fontSize: 18, padding: "14px 16px", background: "#C9A227", color: "#1B2E4C", fontWeight: 900 }}
      onClick={() => { GameSfx.unlock(); onStart(); }}>▶ 게임 시작</button>
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

function GameResult({ icon, label, title, points, correct, total, maxCombo, isNewBest, best, wrong, onAgain, onBack }) {
  const kin = isKin();
  useEffect(() => { GameSfx.win(); }, []);
  const pct = total ? Math.round(correct * 100 / total) : 0;
  const stars = pct >= 90 ? 3 : pct >= 60 ? 2 : 1;
  return <>
    <div className="gm-sky" style={{ padding: "26px 18px 56px", textAlign: "center", color: "#fff" }}>
      <div style={{ fontSize: 48, lineHeight: 1 }}>{icon}</div>
      <div style={{ fontSize: 21, fontWeight: 900, marginTop: 6, color: "#E4C766" }}>{label} 끝!</div>
      <div style={{ fontSize: 12, opacity: .8, marginTop: 4 }}>{title}</div>
      {kin
        ? <div style={{ fontSize: 22, fontWeight: 800, marginTop: 14 }}>🌟 끝까지 다 했어요!</div>
        : <>
          <div style={{ fontSize: 34, marginTop: 10, letterSpacing: 4 }}>{"⭐".repeat(stars)}<span style={{ opacity: .25 }}>{"⭐".repeat(3 - stars)}</span></div>
          <div style={{ fontSize: 44, fontWeight: 900, marginTop: 4 }}>{points.toLocaleString()}<span style={{ fontSize: 18 }}>점</span></div>
          {isNewBest ? <div style={{ fontSize: 15, fontWeight: 900, color: "#E4C766", marginTop: 2 }}>🏆 새 기록!</div>
            : best > 0 ? <div style={{ fontSize: 12, opacity: .8, marginTop: 2 }}>내 최고 {best.toLocaleString()}점</div> : null}
          <div style={{ display: "flex", justifyContent: "center", gap: 10, marginTop: 12, fontSize: 13 }}>
            <span className="gm-pill" style={{ color: "var(--navy)" }}>✅ {correct}/{total}</span>
            <span className="gm-pill" style={{ color: "var(--navy)" }}>🔥 최대 콤보 {maxCombo}</span>
          </div>
        </>}
      <div className="gm-ground">🌳<span>🌱</span>🌳<span>🌱</span>🌳</div>
    </div>
    {wrong.length > 0 && <>
      <div style={{ fontWeight: 700, color: "var(--navy)", margin: "14px 4px 8px", fontSize: 14 }}>한 번 더 볼 단어 {kin ? "" : wrong.length + "개"}</div>
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
function WordRainGame(props) {
  const [round, setRound] = useState(0);
  const [stage, setStage] = useState("ready");
  if (stage === "ready") return <GameReady icon="🌧️" name="단어 비" best={gameBest("rain_" + (props.uid || ""))}
    how={<>하늘에서 영어 단어가 떨어져요!<br />땅에 닿기 전에 <b>알맞은 뜻</b>을 눌러 팡! 터뜨려요.<br />빨리 맞힐수록, 연속으로 맞힐수록 점수가 커져요.</>}
    onStart={() => setStage("play")} onBack={props.onBack} onClassic={props.onClassic} />;
  return <WordRainPlay key={round} {...props} onAgain={() => setRound(r => r + 1)} />;
}

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
    correct={st.current.correct} total={qs.length} maxCombo={st.current.maxCombo} isNewBest={final.isNew} best={final.best}
    wrong={st.current.wrong} onAgain={onAgain} onBack={onBack} />;

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
function SpellShooterGame(props) {
  const [round, setRound] = useState(0);
  const [stage, setStage] = useState("ready");
  if (stage === "ready") return <GameReady icon="🚀" name="스펠링 슈터" best={gameBest("shoot_" + (props.uid || ""))}
    how={<>한글 뜻을 보고, 떠다니는 <b>글자를 순서대로</b> 쏴요!<br />단어가 완성되면 다음 단어로 넘어가요.<br />키보드가 있으면 글자를 눌러도 쏴져요. 한 번에 맞히면 보너스!</>}
    onStart={() => setStage("play")} onBack={props.onBack} onClassic={props.onClassic} />;
  return <SpellShooterPlay key={round} {...props} onAgain={() => setRound(r => r + 1)} />;
}

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
    correct={st.current.correct} total={qs.length} maxCombo={st.current.maxCombo} isNewBest={final.isNew} best={final.best}
    wrong={st.current.wrong} onAgain={onAgain} onBack={onBack} />;

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
