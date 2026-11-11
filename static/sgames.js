// sgames.js — 문장익힘 게임판 (원장 2026-11-11 "문장익힘도 지겹지 않게, 유치하지 않으면서 재미있게")
// 단어익힘(games.js)과 같은 틀: 단계마다 게임 묶음 → '오늘의 게임'이 날마다 바뀌고 🎲 로 바꿀 수 있다.
//   뜻 확인(smeaning)   : 🎬 자막 맞추기 · ⚖️ 번역 판정
//   문장 배열(unscramble): 🔗 덩어리 잇기 · 🔍 오류 탐정 · 🫥 사라지는 문장
// 서버 단계 키·기록(맞은 문장 수/문장 수)·완료 규칙은 그대로다. 단계 수를 늘리지 않았다(숙제량 그대로).
// 새 자료는 필요 없다 — 오답 보기는 같은 숙제의 다른 문장에서 빌려 온다.
// 재미는 캐릭터가 아니라 도전감(시간·연속 정답·내 최고 기록)에서. 유치부(isKin)는 점수·시간 제한 없이.
// games.js 다음, student.js 앞에 불러온다.

const sgNorm = (w) => String(w || "").toLowerCase().replace(/[^a-z0-9']/g, "");
// 낱말 하나를 앞뒤 문장부호와 알맹이로 나눈다: "dog." → {pre:"", core:"dog", post:"."}
function sgTokens(text) {
  return String(text || "").trim().split(/\s+/).filter(Boolean).map(t => {
    const m = t.match(/^([^A-Za-z0-9']*)(.*?)([^A-Za-z0-9']*)$/);
    return { raw: t, pre: m ? m[1] : "", core: m ? m[2] : t, post: m ? m[3] : "" };
  });
}
// 선생님이 만든 음원(자연스러운 사람 목소리·Azure)이 있으면 그걸, 없으면 기기 음성으로 읽는다
const saySent = (p, voice, rate) => { try { playModel(p.audio, p.text, voice, rate || 0.85); } catch (e) {} };
const sgCap = (w, like) => (like && /^[A-Z]/.test(like) && w) ? w[0].toUpperCase() + w.slice(1) : w;

// 다른 문장들의 낱말(오답 보기 재료). 지금 문장에 든 낱말은 뺀다.
function sgForeignWords(pairs, p, minLen) {
  const mine = new Set(sgTokens(p.text).map(t => sgNorm(t.core)));
  const seen = new Set(), out = [];
  for (const o of pairs) {
    if (o === p || o.text === p.text) continue;
    for (const t of sgTokens(o.text)) {
      const k = sgNorm(t.core);
      if (!k || k.length < (minLen || 1) || mine.has(k) || seen.has(k)) continue;
      seen.add(k); out.push(t.core.toLowerCase() === t.core ? t.core : (k === "i" ? "I" : t.core.toLowerCase()));
    }
  }
  return out;
}

// 점수판: 연속 정답(콤보)에 보너스
function useSgScore() {
  const st = useRef({ correct: 0, points: 0, combo: 0, maxCombo: 0, wrong: [] });
  const [, force] = useState(0);
  const hit = (base) => {
    const s = st.current;
    s.combo++; s.maxCombo = Math.max(s.maxCombo, s.combo);
    const add = Math.max(10, Math.round(base)) + (s.combo - 1) * 20;
    s.points += add; force(x => x + 1);
    return add;
  };
  const miss = () => { st.current.combo = 0; force(x => x + 1); };
  return [st, hit, miss];
}

// 줄어드는 시간 막대. seconds 가 0이면(유치부) 멈춰 있다.
function useSgTimer(active, seconds, onEnd, resetKey) {
  const barRef = useRef(null), frac = useRef(0);
  useEffect(() => {
    frac.current = 0;
    if (barRef.current) barRef.current.style.width = "100%";
    if (!active || !seconds) return;
    let raf, start = null, ended = false;
    const loop = (t) => {
      if (start == null) start = t;
      const f = Math.min(1, (t - start) / 1000 / seconds);
      frac.current = f;
      if (barRef.current) {
        barRef.current.style.width = ((1 - f) * 100) + "%";
        barRef.current.style.background = f > .75 ? "#D94A3D" : "#E4C766";
      }
      if (f >= 1) { if (!ended) { ended = true; onEnd(); } return; }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [active, resetKey]);
  return [barRef, frac];
}
function SgBar({ barRef, hidden }) {
  if (hidden) return null;
  return <div style={{ height: 6, background: "rgba(255,255,255,.14)", borderRadius: 3, overflow: "hidden", marginBottom: 12 }}>
    <div ref={barRef} style={{ height: "100%", width: "100%", background: "#E4C766", borderRadius: 3 }} /></div>;
}

function SgHud({ icon, i, n, st, onBack }) {
  const kin = isKin(), s = st.current;
  return <div className="gm-hud">
    <button className="gm-pill" onClick={onBack} style={{ cursor: "pointer" }}>‹ 그만</button>
    <span className="gm-pill">{icon} {Math.min(i + 1, n)}/{n}</span>
    {!kin && <span className="gm-pill">⭐ {s.points.toLocaleString()}</span>}
    {!kin && <span className="gm-pill" style={{ color: s.combo > 1 ? "#C0392B" : "var(--navy-soft)" }}>🔥 {s.combo}</span>}
    <MuteBtn />
  </div>;
}

const sgOpt = (state) => ({
  display: "block", width: "100%", textAlign: "left", padding: "12px 14px", borderRadius: 12, marginTop: 8,
  fontSize: 15, fontWeight: 700, lineHeight: 1.45, wordBreak: "keep-all", cursor: "pointer", transition: "background .15s",
  border: "2px solid " + (state === "right" ? "#5FBF8A" : state === "wrong" ? "#F07A6E" : "rgba(255,255,255,.2)"),
  background: state === "right" ? "#2F7A52" : state === "wrong" ? "#A8392F" : state === "dim" ? "rgba(255,255,255,.03)" : "rgba(255,255,255,.08)",
  color: state === "dim" ? "rgba(255,255,255,.4)" : "#fff",
});
const sgChip = (state) => ({
  display: "inline-block", padding: "8px 12px", borderRadius: 10, fontSize: 17, fontWeight: 800, cursor: "pointer",
  border: "2px solid " + (state === "right" ? "#5FBF8A" : state === "wrong" ? "#F07A6E" : "rgba(255,255,255,.22)"),
  background: state === "right" ? "#2F7A52" : state === "wrong" ? "#A8392F" : "rgba(255,255,255,.08)", color: "#fff",
  animation: state === "wrong" ? "gmShake .35s" : "none",
});
const sgKorBox = (kor, label) => <div style={{ background: "rgba(228,199,102,.12)", border: "1px solid rgba(228,199,102,.35)", borderRadius: 12, padding: "10px 12px", marginBottom: 14 }}>
  <div style={{ fontSize: 11, fontWeight: 800, color: "#E4C766", marginBottom: 3 }}>{label || "뜻"}</div>
  <div style={{ fontSize: 15.5, fontWeight: 700, lineHeight: 1.5, wordBreak: "keep-all" }}>{kor}</div>
</div>;

// 판 끝: 기기 최고 기록 비교 → 서버에 (맞은 수, 문제 수)
function sgEnd(st, bestKey, total, setFinal, setPhase, onDone) {
  setFinal(gameFinal(bestKey, st.current.points));
  setPhase("result");
  onDone && onDone(st.current.correct, total);
}
function SgResult({ icon, label, title, st, total, final, onAgain, onBack, headline }) {
  const s = st.current;
  return <GameResult icon={icon} label={label} title={title} points={s.points} stars={starsOf(s.correct, total)}
    headline={headline} stats={[`✅ ${s.correct}/${total}문장`, `🔥 최대 콤보 ${s.maxCombo}`]}
    isNewBest={final.isNew} best={final.best} wrong={s.wrong} wrongLabel="한 번 더 볼 문장" onAgain={onAgain} onBack={onBack} />;
}

// ================= 🎬 자막 맞추기 =================
// 영어 문장 소리만 듣고, 그 장면에 맞는 한글 자막을 고른다. 고르고 나면 영어 자막이 뜬다.
function SubtitlePlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q =>
    ({ ...q, options: shuffleArr([q.kor, ...gameDistractors(pairs, q, 2)]) })));
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState(null);
  const [final, setFinal] = useState(null);
  const [st, hit, miss] = useSgScore();
  const lock = useRef(false);
  const q = qs[i];
  const [barRef, frac] = useSgTimer(phase === "play" && picked == null, kin ? 0 : 15, () => answer("__time"), phase + "|" + i);

  useEffect(() => {
    if (phase !== "play" || !q) return;
    lock.current = false;
    const t = setTimeout(() => saySent(q, voice), 250);
    return () => clearTimeout(t);
  }, [i, phase]);

  function answer(opt) {
    if (lock.current) return;
    lock.current = true;
    setPicked(opt);
    if (opt === q.kor) { st.current.correct++; hit(100 + (1 - frac.current) * 100); GameSfx.good(); }
    else { miss(); st.current.wrong.push(q); GameSfx.bad(); }
    setTimeout(() => {
      if (i + 1 >= qs.length) sgEnd(st, bestKey, qs.length, setFinal, setPhase, onDone);
      else { setI(i + 1); setPicked(null); }
    }, opt === q.kor ? 1500 : 2300);
  }

  if (phase === "result") return <SgResult icon={icon} label={label} title={title} st={st} total={qs.length} final={final} onAgain={onAgain} onBack={onBack} />;
  const done = picked != null;
  return <>
    <SgHud icon={icon} i={i} n={qs.length} st={st} onBack={onBack} />
    <div className="gm-sky" style={{ padding: "16px 14px 20px", color: "#fff", minHeight: 360 }}>
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      <SgBar barRef={barRef} hidden={kin} />
      <div style={{ background: "#05080F", borderRadius: 12, aspectRatio: "16 / 7", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", padding: "12px 14px", position: "relative", border: "1px solid rgba(255,255,255,.08)" }}>
        <div style={{ position: "absolute", top: 10, left: 12, fontSize: 11, letterSpacing: 2, opacity: .45, fontWeight: 800 }}>● SCENE {i + 1}</div>
        {!done
          ? <button onClick={() => saySent(q, voice)} style={{ position: "absolute", inset: 0, background: "none", color: "#E4C766", fontSize: 15, fontWeight: 800, cursor: "pointer" }}>
              <div style={{ fontSize: 34 }}>🔊</div>잘 듣고 자막을 골라요 · 다시 듣기</button>
          : <div style={{ fontSize: 17, fontWeight: 800, textAlign: "center", lineHeight: 1.45, color: "#FFF6C8", textShadow: "0 2px 4px #000" }}>{q.text}</div>}
      </div>
      <div style={{ fontSize: 12, fontWeight: 800, color: "#E4C766", margin: "14px 2px 0" }}>이 장면의 한글 자막은?</div>
      {q.options.map((o, k) => {
        const state = !done ? "" : o === q.kor ? "right" : o === picked ? "wrong" : "dim";
        return <button key={k} style={sgOpt(state)} onClick={() => answer(o)} disabled={done}>{o}</button>;
      })}
      {picked === "__time" && <div style={{ marginTop: 10, color: "#F07A6E", fontWeight: 800, fontSize: 14 }}>⏰ 시간이 다 됐어요</div>}
    </div>
  </>;
}

// ================= ⚖️ 번역 판정 =================
// 영어 문장과 한글 뜻이 짝으로 나온다. 맞는 번역인지 빠르게 판정한다(절반쯤은 다른 문장의 뜻).
function JudgePlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map((q, k) => {
    const d = gameDistractors(pairs, q, 1)[0];
    let c = null;
    for (let t = 0; t < 4 && !c; t++) c = sgCorrupt(pairs, q);
    const truth = (!d && !c) || (k % 2 === 0 ? Math.random() < .65 : Math.random() < .3);
    // 틀린 짝: 대부분은 영어 낱말 하나만 슬쩍 바꾼 것(꼼꼼히 읽어야 잡힌다), 가끔은 엉뚱한 번역
    const sly = !truth && c && (!d || Math.random() < .7);
    const en = sly ? c.toks.map((t, n) => n === c.at ? t.pre + c.rep + t.post : t.raw).join(" ") : q.text;
    return { ...q, truth, sly, en, shown: truth || sly ? q.kor : d };
  }));
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState(null);   // true | false | "time"
  const [final, setFinal] = useState(null);
  const [st, hit, miss] = useSgScore();
  const lock = useRef(false);
  const q = qs[i];
  const [barRef, frac] = useSgTimer(phase === "play" && picked == null, kin ? 0 : 12, () => answer("time"), phase + "|" + i);

  useEffect(() => {
    if (phase !== "play" || !q) return;
    lock.current = false;
    return undefined;
  }, [i, phase]);

  function answer(v) {
    if (lock.current) return;
    lock.current = true;
    setPicked(v);
    const ok = v === q.truth;
    if (ok) { st.current.correct++; hit(80 + (1 - frac.current) * 120); GameSfx.good(); }
    else { miss(); st.current.wrong.push(q); GameSfx.bad(); }
    setTimeout(() => {
      if (i + 1 >= qs.length) sgEnd(st, bestKey, qs.length, setFinal, setPhase, onDone);
      else { setI(i + 1); setPicked(null); }
    }, ok ? 1200 : 2400);
  }

  if (phase === "result") return <SgResult icon={icon} label={label} title={title} st={st} total={qs.length} final={final} onAgain={onAgain} onBack={onBack} />;
  const done = picked != null, ok = done && picked === q.truth;
  return <>
    <SgHud icon={icon} i={i} n={qs.length} st={st} onBack={onBack} />
    <div className="gm-sky" style={{ padding: "16px 14px 20px", color: "#fff", minHeight: 360 }}>
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      <SgBar barRef={barRef} hidden={kin} />
      <div style={{ background: "rgba(255,255,255,.07)", borderRadius: 14, padding: "16px 14px", border: "1px solid rgba(255,255,255,.12)" }}>
        <div style={{ fontSize: 11, fontWeight: 800, opacity: .6, letterSpacing: 1 }}>ENGLISH</div>
        <div style={{ fontSize: 19, fontWeight: 800, lineHeight: 1.45, marginTop: 4, textDecoration: done && q.sly ? "line-through" : "none", opacity: done && q.sly ? .6 : 1 }}>{q.en}
          {done && <button onClick={() => saySent(q, voice)} style={{ background: "none", color: "#E4C766", fontSize: 16, marginLeft: 6, cursor: "pointer" }}>🔊</button>}</div>
        <div style={{ height: 1, background: "rgba(255,255,255,.12)", margin: "14px 0" }} />
        <div style={{ fontSize: 11, fontWeight: 800, color: "#E4C766", letterSpacing: 1 }}>번역</div>
        <div style={{ fontSize: 16.5, fontWeight: 700, lineHeight: 1.5, marginTop: 4, wordBreak: "keep-all",
          textDecoration: done && !q.truth && !q.sly ? "line-through" : "none", opacity: done && !q.truth && !q.sly ? .6 : 1 }}>{q.shown}</div>
        {done && !q.truth && !q.sly && <div style={{ fontSize: 15, fontWeight: 800, marginTop: 6, color: "#9EE6BC", wordBreak: "keep-all" }}>→ {q.kor}</div>}
        {done && q.sly && <div style={{ fontSize: 17, fontWeight: 800, marginTop: 4, color: "#9EE6BC" }}>→ {q.text}</div>}
      </div>
      <div style={{ fontSize: 12, fontWeight: 800, color: "#E4C766", margin: "16px 2px 8px", textAlign: "center" }}>이 번역, 맞아요?</div>
      <div className="row" style={{ gap: 10 }}>
        {[[true, "⭕ 맞아요"], [false, "❌ 틀려요"]].map(([v, t]) => {
          const state = !done ? "" : v === q.truth ? "right" : v === picked ? "wrong" : "dim";
          return <button key={t} disabled={done} onClick={() => answer(v)} style={{ ...sgOpt(state), marginTop: 0, flex: 1, textAlign: "center", fontSize: 18, padding: "16px 10px" }}>{t}</button>;
        })}
      </div>
      {done && <div style={{ marginTop: 12, textAlign: "center", fontWeight: 800, fontSize: 14, color: ok ? "#9EE6BC" : "#F07A6E" }}>
        {picked === "time" ? "⏰ 시간이 다 됐어요" : ok ? "정확한 판정!" : "아쉬워요!"}</div>}
    </div>
  </>;
}

// ================= 🔗 덩어리 잇기 =================
// 문장을 2~3낱말 덩어리로 끊어, 뜻을 보고 다음에 올 덩어리를 고르며 이어 간다.
// 보기에는 이 문장의 뒷덩어리(순서 함정)와 다른 문장의 덩어리(뜻 함정)가 섞인다.
function sgChunks(text) {
  const w = String(text || "").trim().split(/\s+/).filter(Boolean);
  const size = w.length <= 3 ? 1 : w.length <= 6 ? 2 : 3;
  const out = [];
  for (let k = 0; k < w.length; k += size) out.push(w.slice(k, k + size).join(" "));
  // 끝에 한 낱말만 남으면 앞 덩어리에 붙인다(너무 쉬운 한 칸 방지)
  if (out.length > 2 && size > 1 && out[out.length - 1].split(" ").length === 1) { const last = out.pop(); out[out.length - 1] += " " + last; }
  return out;
}
const sgChunkKey = (c) => String(c).toLowerCase().replace(/[^a-z0-9' ]/g, "").trim();

function ChunkPlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q => ({ ...q, chunks: sgChunks(q.text) })));
  const [foreign] = useState(() => {
    const m = new Map();
    pairs.forEach(p => sgChunks(p.text).forEach((c, n) => {
      // 문장 첫 덩어리는 대문자로 시작하니 소문자로 고쳐 둔다(답이 티 나지 않게). I 로 시작하면 그대로.
      const cc = (n === 0 && !/^I\b/.test(c)) ? c[0].toLowerCase() + c.slice(1) : c;
      const k = sgChunkKey(cc); if (k && !m.has(k)) m.set(k, { c: cc, src: p.text });
    }));
    return [...m.values()];
  });
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [k, setK] = useState(0);
  const [opts, setOpts] = useState([]);
  const [bad, setBad] = useState([]);     // 이번 칸에서 틀린 보기
  const [doneS, setDoneS] = useState(false);
  const [final, setFinal] = useState(null);
  const [st, hit, miss] = useSgScore();
  const perfect = useRef(true), t0 = useRef(Date.now());
  const q = qs[i];

  useEffect(() => { perfect.current = true; t0.current = Date.now(); setK(0); setDoneS(false); }, [i]);
  useEffect(() => {
    if (!q || k >= q.chunks.length) return;
    const right = q.chunks[k], rk = sgChunkKey(right);
    const seen = new Set([rk]), list = [right];
    const add = (c) => { const ck = sgChunkKey(c); if (ck && !seen.has(ck) && list.length < 3) { seen.add(ck); list.push(c); } };
    const later = shuffleArr(q.chunks.slice(k + 1));
    if (later.length) add(later[0]);                                   // 순서 함정 하나
    shuffleArr(foreign.filter(f => f.src !== q.text)).forEach(f => add(f.c));   // 뜻 함정
    later.slice(1).forEach(add);                                       // 그래도 모자라면 뒷덩어리로
    // 첫 칸이면 보기 모두 대문자로 시작, 아니면 뒷덩어리·남의 덩어리는 이미 소문자
    setOpts(shuffleArr(k === 0 ? list.map(c => c[0].toUpperCase() + c.slice(1)) : list));
    setBad([]);
  }, [i, k]);

  const pick = (c) => {
    if (doneS || !q) return;
    if (sgChunkKey(c) === sgChunkKey(q.chunks[k])) {
      GameSfx.pop();
      if (k + 1 >= q.chunks.length) {
        setK(k + 1); setDoneS(true);
        saySent(q, voice);
        const secs = (Date.now() - t0.current) / 1000;
        if (perfect.current) { st.current.correct++; hit(120 + Math.max(0, 120 - secs * 8)); GameSfx.good(); }
        else { miss(); st.current.wrong.push(q); }
        setTimeout(() => {
          if (i + 1 >= qs.length) sgEnd(st, bestKey, qs.length, setFinal, setPhase, onDone);
          else setI(i + 1);
        }, 1700);
      } else setK(k + 1);
    } else {
      perfect.current = false; miss(); GameSfx.bad();
      setBad(b => [...b, c]);
    }
  };

  if (phase === "result") return <SgResult icon={icon} label={label} title={title} st={st} total={qs.length} final={final} onAgain={onAgain} onBack={onBack} />;
  return <>
    <SgHud icon={icon} i={i} n={qs.length} st={st} onBack={onBack} />
    <div className="gm-sky" style={{ padding: "16px 14px 20px", color: "#fff", minHeight: 360 }}>
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      {sgKorBox(q.kor, "이 뜻이 되게 이어요")}
      <div style={{ minHeight: 64, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", padding: "10px", borderRadius: 12,
        background: doneS ? (perfect.current ? "rgba(47,122,82,.35)" : "rgba(168,57,47,.25)") : "rgba(255,255,255,.05)", border: "1px dashed rgba(255,255,255,.25)" }}>
        {q.chunks.slice(0, k).map((c, n) => <span key={n} style={{ padding: "7px 11px", borderRadius: 10, background: "#E4C766", color: "#1B2E4C", fontWeight: 900, fontSize: 16 }}>{c}</span>)}
        {!doneS && <span style={{ padding: "7px 14px", borderRadius: 10, border: "2px dashed #E4C766", color: "#E4C766", fontWeight: 900, animation: "gmBlink 1s infinite" }}>?</span>}
      </div>
      {doneS
        ? <div style={{ marginTop: 14, textAlign: "center", fontWeight: 900, fontSize: 15, color: perfect.current ? "#9EE6BC" : "#F7C9A0" }}>
            {perfect.current ? "한 번에 완성! 🔗" : "완성! 헷갈린 문장은 끝에 다시 보여 줄게요"}</div>
        : <>
          <div style={{ fontSize: 12, fontWeight: 800, color: "#E4C766", margin: "14px 2px 0" }}>다음에 올 덩어리는? ({k + 1}/{q.chunks.length})</div>
          {opts.map((c, n) => {
            const isBad = bad.includes(c);
            return <button key={c + n} disabled={isBad} onClick={() => pick(c)} style={{ ...sgOpt(isBad ? "wrong" : ""), fontSize: 17, animation: isBad ? "gmShake .35s" : "none" }}>{c}</button>;
          })}
        </>}
    </div>
  </>;
}

// ================= 🔍 오류 탐정 =================
// 문장 속 낱말 하나가 몰래 바뀌어 있다. 뜻과 맞지 않는(또는 문법이 틀린) 낱말을 찾아낸다.
// 바꿔치기: 문법 짝(is↔are 등)이 있으면 그걸, 없으면 다른 문장의 낱말. 뜻이 그대로인 짝(a↔the)은 쓰지 않는다.
const SG_SWAP = {
  is: "are", are: "is", was: "were", were: "was", am: "is", do: "does", does: "do", has: "have", have: "has",
  in: "on", on: "in", under: "on", he: "she", she: "he", his: "her", him: "her", this: "that", that: "this",
  these: "those", those: "these", my: "your", your: "my", and: "but", but: "and", big: "small", small: "big",
  up: "down", down: "up", like: "likes", likes: "like", go: "goes", goes: "go", want: "wants", wants: "want",
  can: "can't", "can't": "can", always: "never", never: "always", before: "after", after: "before",
  yesterday: "tomorrow", tomorrow: "yesterday", here: "there", there: "here", open: "close", hot: "cold", cold: "hot",
  happy: "sad", sad: "happy", old: "new", new: "old", long: "short", short: "long", fast: "slow", slow: "fast",
};
function sgCorrupt(pairs, p) {
  const toks = sgTokens(p.text);
  const idx = toks.map((t, k) => k).filter(k => sgNorm(toks[k].core));
  if (!idx.length) return null;
  const foreign = sgForeignWords(pairs, p, 3);
  const swapIdx = idx.filter(k => SG_SWAP[sgNorm(toks[k].core)]);
  const useSwap = swapIdx.length && (Math.random() < .5 || !foreign.length);
  let at, rep;
  if (useSwap) { at = swapIdx[Math.floor(Math.random() * swapIdx.length)]; rep = SG_SWAP[sgNorm(toks[at].core)]; }
  else {
    if (!foreign.length) return null;
    const content = idx.filter(k => sgNorm(toks[k].core).length >= 3);
    const pool = content.length ? content : idx;
    at = pool[Math.floor(Math.random() * pool.length)];
    rep = foreign[Math.floor(Math.random() * foreign.length)];
  }
  if (sgNorm(rep) === sgNorm(toks[at].core)) return null;
  rep = rep === "I" ? "I" : sgCap(rep, toks[at].core);
  return { toks, at, rep };
}

function DetectivePlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const [qs] = useState(() => {
    const out = [];
    for (const q of shuffleArr(pairs)) {
      let c = null;
      for (let t = 0; t < 4 && !c; t++) c = sgCorrupt(pairs, q);
      if (c) out.push({ ...q, ...c });
      if (out.length >= (limit || pairs.length)) break;
    }
    return out;
  });
  const [phase, setPhase] = useState(qs.length ? "count" : "empty");
  const [i, setI] = useState(0);
  const [bad, setBad] = useState([]);
  const [found, setFound] = useState(null);   // "first" | "late"
  const [hint, setHint] = useState(false);
  const [final, setFinal] = useState(null);
  const [st, hit, miss] = useSgScore();
  const t0 = useRef(Date.now());
  const q = qs[i];

  useEffect(() => { t0.current = Date.now(); setBad([]); setFound(null); setHint(false); }, [i]);

  const reveal = (first) => {
    setFound(first ? "first" : "late");
    saySent(q, voice);
    const secs = (Date.now() - t0.current) / 1000;
    if (first) { st.current.correct++; hit((150 + Math.max(0, 120 - secs * 10)) * (hint ? .5 : 1)); GameSfx.good(); }
    else st.current.wrong.push(q);
    setTimeout(() => {
      if (i + 1 >= qs.length) sgEnd(st, bestKey, qs.length, setFinal, setPhase, onDone);
      else setI(i + 1);
    }, 2200);
  };
  const tap = (k) => {
    if (found || bad.includes(k)) return;
    if (k === q.at) { reveal(bad.length === 0); return; }
    miss(); GameSfx.bad();
    const nb = [...bad, k]; setBad(nb);
    if (nb.length >= 2) reveal(false);
  };

  if (phase === "empty") return <>
    <button onClick={onBack} style={{ background: "none", color: "var(--navy)", fontWeight: 700, marginBottom: 10 }}>‹ 모드 선택</button>
    <div className="card" style={{ textAlign: "center", padding: 24 }}><span className="muted">이 숙제 문장으로는 탐정 문제를 만들 수 없어요. 🎲 다른 게임을 골라요.</span></div>
  </>;
  if (phase === "result") return <SgResult icon={icon} label={label} title={title} st={st} total={qs.length} final={final} onAgain={onAgain} onBack={onBack} />;
  return <>
    <SgHud icon={icon} i={i} n={qs.length} st={st} onBack={onBack} />
    <div className="gm-sky" style={{ padding: "16px 14px 20px", color: "#fff", minHeight: 360 }}>
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      {sgKorBox(q.kor, "원래 이런 뜻이었어요")}
      <div style={{ fontSize: 12, fontWeight: 800, color: "#E4C766", margin: "0 2px 10px" }}>
        {found ? (found === "first" ? "🔍 찾았다! 한 번에 잡았어요" : "이 낱말이 바뀌어 있었어요") : "바뀌어 들어온 낱말 하나를 눌러요" + (kin ? "" : ` · 기회 ${2 - bad.length}번`)}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 7, lineHeight: 1 }}>
        {q.toks.map((t, k) => {
          const isAt = k === q.at;
          if (found && isAt) return <span key={k} style={{ ...sgChip("right"), cursor: "default" }}>
            <s style={{ opacity: .6, fontWeight: 600, marginRight: 6 }}>{q.rep}</s>{t.core}{t.post}</span>;
          const state = bad.includes(k) ? "wrong" : "";
          return <button key={k} onClick={() => tap(k)} disabled={!!found || !sgNorm(t.core)} style={sgChip(state)}>
            {t.pre}{isAt ? q.rep : t.core}{t.post}</button>;
        })}
      </div>
      {!found && <button onClick={() => { setHint(true); saySent(q, voice, 0.8); }}
        style={{ marginTop: 18, background: "none", color: hint ? "rgba(255,255,255,.5)" : "#E4C766", fontWeight: 800, fontSize: 13, cursor: "pointer" }}>
        🔊 진짜 문장 듣기 {kin ? "" : hint ? "(이번 문장 점수 절반)" : "· 힌트를 쓰면 점수 절반"}</button>}
    </div>
  </>;
}

// ================= 🫥 사라지는 문장 =================
// 문장을 잠깐 외운다 → 한 낱말이 지워진다 → 채우면 두 낱말이 지워진다 → 세 낱말…
// 다시 보여 주지 않으니 끝까지 버티려면 문장이 머리에 들어가 있어야 한다.
function VanishPlay({ pairs, title, voice, onBack, onDone, limit, label, icon, bestKey, onAgain }) {
  const kin = isKin();
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q => {
    const toks = sgTokens(q.text);
    const order = shuffleArr(toks.map((t, k) => k).filter(k => sgNorm(toks[k].core)));
    const levels = Math.max(1, Math.min(kin ? 2 : 3, order.length));
    return { ...q, toks, order, levels };
  }));
  const [phase, setPhase] = useState("count");
  const [i, setI] = useState(0);
  const [step, setStep] = useState("memo");   // memo | fill | levelup | done
  const [level, setLevel] = useState(1);
  const [filled, setFilled] = useState({});    // 낱말 자리 → "ok" | "miss"
  const [opts, setOpts] = useState([]);
  const [badOpt, setBadOpt] = useState(null);
  const [final, setFinal] = useState(null);
  const [st, hit, miss] = useSgScore();
  const perfect = useRef(true), busy = useRef(false);
  const q = qs[i];
  const blanks = q ? q.order.slice(0, level).slice().sort((a, b) => a - b) : [];
  const cur = blanks.find(k => !filled[k]);
  const memoSec = kin ? 8 : Math.min(9, Math.max(4, (q ? q.toks.length : 6) * 0.6));
  const [barRef] = useSgTimer(phase === "play" && step === "memo", memoSec, () => startFill(), phase + "|" + i + "|" + step);

  useEffect(() => {
    if (phase !== "play" || !q) return;
    perfect.current = true; busy.current = false;
    setStep("memo"); setLevel(1); setFilled({});
    const t = setTimeout(() => saySent(q, voice), 200);
    return () => clearTimeout(t);
  }, [i, phase]);

  // 지금 채울 칸의 보기: 정답 + 같은 문장의 다른 빈칸 낱말 + 다른 문장 낱말
  useEffect(() => {
    if (step !== "fill" || cur == null || !q) return;
    const right = q.toks[cur].core, seen = new Set([sgNorm(right)]), list = [right];
    const others = blanks.filter(k => k !== cur && !filled[k]).map(k => q.toks[k].core)
      .concat(shuffleArr(q.toks.map(t => t.core)), shuffleArr(sgForeignWords(pairs, q, 2)));
    for (const w of others) { const n = sgNorm(w); if (n && !seen.has(n)) { seen.add(n); list.push(w); } if (list.length >= 3) break; }
    // 대문자 하나로 답이 티 나지 않게 보기 모양을 맞춘다(문장 첫 칸이면 모두 대문자로 시작)
    const up = cur === 0 || /^[A-Z]/.test(right);
    const fmt = (w) => w === "I" ? w : up ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w.toLowerCase();
    setOpts(shuffleArr(list.map(fmt))); setBadOpt(null);
  }, [step, cur, level, i]);

  function startFill() { if (step === "memo") setStep("fill"); }

  const pick = (w) => {
    if (busy.current || cur == null) return;
    const ok = sgNorm(w) === sgNorm(q.toks[cur].core);
    const nf = { ...filled, [cur]: ok ? "ok" : "miss" };
    if (ok) { hit(50); GameSfx.pop(); }
    else { perfect.current = false; miss(); GameSfx.bad(); setBadOpt(w); }
    busy.current = true;
    setTimeout(() => {
      busy.current = false;
      setFilled(nf);
      const left = blanks.filter(k => !nf[k]);
      if (left.length) return;
      if (level < q.levels) {
        setStep("levelup");
        setTimeout(() => { setFilled({}); setLevel(level + 1); setStep("fill"); }, 1100);
      } else {
        setStep("done"); saySent(q, voice);
        if (perfect.current) { st.current.correct++; hit(100); GameSfx.good(); }
        else st.current.wrong.push(q);
        setTimeout(() => {
          if (i + 1 >= qs.length) sgEnd(st, bestKey, qs.length, setFinal, setPhase, onDone);
          else setI(i + 1);
        }, 1800);
      }
    }, ok ? 250 : 900);
  };

  if (phase === "result") return <SgResult icon={icon} label={label} title={title} st={st} total={qs.length} final={final} onAgain={onAgain} onBack={onBack} />;
  const showAll = step === "memo" || step === "done";
  return <>
    <SgHud icon={icon} i={i} n={qs.length} st={st} onBack={onBack} />
    <div className="gm-sky" style={{ padding: "16px 14px 20px", color: "#fff", minHeight: 360 }}>
      {phase === "count" && <GameCountdown onDone={() => setPhase("play")} />}
      {sgKorBox(q.kor)}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "0 2px 8px", fontSize: 12, fontWeight: 800, color: "#E4C766" }}>
        <span>{step === "memo" ? "👀 외워요! 곧 사라져요" : step === "done" ? (perfect.current ? "끝까지 버텼어요! 🫥" : "완성! 틀린 문장은 끝에 다시 볼게요")
          : step === "levelup" ? "좋아요! 이제 더 사라져요…" : `빈칸 채우기 · ${level}단계 / ${q.levels}`}</span>
        <span>{"●".repeat(level)}<span style={{ opacity: .3 }}>{"●".repeat(Math.max(0, q.levels - level))}</span></span>
      </div>
      {step === "memo" && <SgBar barRef={barRef} />}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "10px 7px", fontSize: 19, fontWeight: 800, lineHeight: 1.3, minHeight: 60, alignItems: "center",
        padding: "12px", borderRadius: 12, background: "rgba(255,255,255,.05)", border: "1px solid rgba(255,255,255,.12)" }}>
        {q.toks.map((t, k) => {
          const isBlank = !showAll && blanks.includes(k);
          if (!isBlank) return <span key={k}>{t.raw}</span>;
          const f = filled[k];
          if (f) return <span key={k} style={{ color: f === "ok" ? "#9EE6BC" : "#F7A69C", borderBottom: "2px solid currentColor" }}>{t.pre}{t.core}{t.post}</span>;
          return <span key={k}>{t.pre}<span style={{ display: "inline-block", minWidth: Math.max(36, t.core.length * 11), borderBottom: "3px solid " + (k === cur ? "#E4C766" : "rgba(255,255,255,.35)"),
            animation: k === cur ? "gmBlink 1s infinite" : "none" }}>&nbsp;</span>{t.post}</span>;
        })}
      </div>
      {step === "memo" && <button className="btn full" onClick={startFill} style={{ marginTop: 14, background: "#C9A227", color: "#1B2E4C", fontWeight: 900 }}>외웠어요 →</button>}
      {step === "fill" && cur != null && <div className="row" style={{ gap: 8, marginTop: 14, flexWrap: "wrap" }}>
        {opts.map((w, n) => {
          const state = badOpt === w ? "wrong" : (badOpt && sgNorm(w) === sgNorm(q.toks[cur].core)) ? "right" : "";
          return <button key={w + n} onClick={() => pick(w)} style={{ ...sgOpt(state), marginTop: 0, flex: "1 1 30%", textAlign: "center", fontSize: 17 }}>{w}</button>;
        })}
      </div>}
    </div>
  </>;
}

// ================= 문장익힘 게임 묶음 =================
// Comp 은 그릴 때 찾는다(student.js 의 옛 화면이 이 파일보다 늦게 읽혀서).
GAME_POOLS.smeaning = [
  { id: "subtitle", icon: "🎬", name: "자막 맞추기", short: "소리만 듣고 한글 자막 고르기", Comp: SubtitlePlay,
    how: <>장면의 영어 대사가 <b>소리로만</b>나와요.<br />잘 듣고 알맞은 <b>한글 자막</b>을 골라요.<br />빨리, 연속으로 맞힐수록 점수가 커져요.</> },
  { id: "judge", icon: "⚖️", name: "번역 판정", short: "맞는 번역인지 빠르게 판정", Comp: JudgePlay,
    how: <>영어 문장과 번역이 짝으로 나와요.<br />딱 맞으면 <b>⭕</b>, 어긋나면 <b>❌</b>! 낱말 하나만 몰래 바뀐 문장도 있어요.<br />빠르고 정확하게 판정할수록 점수가 커져요.</> },
];
GAME_POOLS.unscramble = [
  { id: "chunk", icon: "🔗", name: "덩어리 잇기", short: "다음에 올 덩어리 골라 잇기", Comp: ChunkPlay,
    how: <>문장이 <b>2~3낱말 덩어리</b>로 쪼개져 있어요.<br />뜻을 보고 다음에 올 덩어리를 골라 이어요.<br />한 번도 안 틀리고 완성해야 맞힌 문장이 돼요.</> },
  { id: "detective", icon: "🔍", name: "오류 탐정", short: "몰래 바뀐 낱말 찾아내기", Comp: DetectivePlay,
    how: <>문장 속 낱말 <b>하나가 몰래 바뀌어</b> 있어요.<br />뜻과 맞지 않거나 문법이 틀린 낱말을 찾아 눌러요.<br />한 번에 잡으면 맞힌 문장! 기회는 두 번이에요.</> },
  { id: "vanish", icon: "🫥", name: "사라지는 문장", short: "지워지는 낱말 채우며 버티기", Comp: VanishPlay,
    how: <>문장을 잠깐 보고 <b>외워요</b>.<br />낱말이 하나, 둘, 셋… 점점 사라져요.<br />빈칸을 채우며 끝까지 버티면 맞힌 문장이 돼요.</> },
];
