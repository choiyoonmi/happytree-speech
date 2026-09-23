// 자동 생성 — tools/split_admin.py. 학생 화면.

function Recorder({ index, text, meaning, take, round, onSaved, voice, audioUrl, label, bgScore, aid, sid, mode }) {
  const [rec, setRec] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const mrRef = useRef(null); const chunksRef = useRef([]);

  const start = async () => {
    setErr("");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setErr("이 브라우저는 녹음을 지원하지 않아요.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mrRef.current = mr;
      mr.ondataavailable = e => { if (e.data && e.data.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || "audio/webm" });
        stream.getTracks().forEach(t => t.stop());
        try {
          const fd = new FormData();
          fd.append("audio", blob, "take.webm");
          const up = await fetch("/api/audio", { method: "POST", body: fd });
          const upJson = await up.json();

          // 백그라운드 채점(통문장처럼 오래 걸리는 것): 녹음은 '채점 중'으로 즉시 저장하고
          // 서버에 채점을 맡긴 뒤 바로 끝낸다. 학생은 기다리지 않고, 점수는 뒤에서 채워진다.
          if (bgScore) {
            onSaved(index, round, { audio: upJson.url, score: null, scoring: true });
            try {
              const sf = new FormData();
              sf.append("audio", blob, "take.webm");
              sf.append("text", text);
              sf.append("round", String(round));
              sf.append("mode", mode || "whole");
              sf.append("index", String(index));
              fetch(`/api/score-take/${aid}/${sid}`, { method: "POST", body: sf }).catch(()=>{});
            } catch (e) {}
            setBusy(false);
            return;
          }

          let score = null, recognized = null, detail = null, words = null, durationMs = null, assessError = null, assessDebug = null;
          // 채점이 몰려서(502) 실패하면 저장된 녹음으로 잠깐 쉬었다 다시 채점 요청(최대 3회).
          // 순간 몰림은 이 사이 대부분 풀려 결국 점수가 나온다. 200 응답(점수 있음/무음·NoMatch 등
          // '진짜 인식 실패')이면 재시도하지 않는다(헛대기 방지).
          const ASSESS_TRIES = 3;
          for (let attempt = 0; attempt < ASSESS_TRIES; attempt++) {
            try {
              const fd2 = new FormData();
              fd2.append("audio", blob, "take.webm");
              fd2.append("text", text);
              const as = await fetch("/api/assess", { method: "POST", body: fd2 });
              if (as.ok) {
                const d = await as.json();
                durationMs = d.audio && d.audio.durationMs != null ? Math.round(d.audio.durationMs) : null;
                recognized = d.recognizedText || null;
                score = d.pronScore != null ? Math.round(d.pronScore) : null;
                words = d.words || null;
                detail = {
                  accuracy: d.accuracyScore != null ? Math.round(d.accuracyScore) : null,
                  fluency: d.fluencyScore != null ? Math.round(d.fluencyScore) : null,
                  completeness: d.completenessScore != null ? Math.round(d.completenessScore) : null,
                };
                assessError = null; assessDebug = null;
                if (score == null) {
                  assessError = d.note || "인식되지 않았어요. 다시 녹음해볼까요?";
                  assessDebug = [
                    d.status ? `상태 ${d.status}` : null,
                    d.audio ? `길이 ${(d.audio.durationMs/1000).toFixed(1)}초` : null,
                    d.audio && d.audio.dBFS != null ? `음량 ${d.audio.dBFS}dB` : null,
                    d.recognizedText ? `정렬된 인식값 "${d.recognizedText}"` : null,
                  ].filter(Boolean).join(" · ");
                }
                break;   // 200 = 서버가 판정 끝냄 → 재시도 안 함
              } else {
                let m = `발음평가 오류 (${as.status})`;
                try { const j = await as.json(); if (j.detail) m = j.detail; } catch (e) {}
                assessError = m;
                if (attempt < ASSESS_TRIES - 1) { await new Promise(r => setTimeout(r, 1500 * (attempt + 1))); continue; }
              }
            } catch (e) {
              assessError = "발음평가 서버에 연결하지 못했어요.";
              if (attempt < ASSESS_TRIES - 1) { await new Promise(r => setTimeout(r, 1500 * (attempt + 1))); continue; }
            }
          }

          onSaved(index, round, { audio: upJson.url, recognized, score, detail, words, durationMs, assessError, assessDebug });
        } catch (e) {
          setErr("업로드에 실패했어요. 인터넷 연결을 확인해주세요.");
        }
        setBusy(false);
      };
      mr.start();
      setRec(true);
    } catch (e) {
      setErr("마이크 접근이 거부되었어요. 주소창 왼쪽 자물쇠 아이콘에서 마이크를 허용해주세요.");
    }
  };

  const stop = () => {
    if (mrRef.current && rec) { setBusy(true); mrRef.current.stop(); setRec(false); }
  };

  return (
    <div className="card" style={ take ? { borderLeft:"4px solid var(--gold)" } : {} }>
      <div style={{ display:"flex", justifyContent:"space-between", gap:10 }}>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontSize:11, fontWeight:700, color:"var(--gold)" }}>
            {label || (index+1)}{take ? " · 완료" : ""}
          </div>
          <div style={{ fontSize:20, fontWeight:600, wordBreak:"break-word", lineHeight:1.5, whiteSpace:"pre-line" }}>{text}</div>
          {meaning && (
            <div style={{ fontSize:15, color:"var(--navy-soft)", marginTop:4, fontWeight:500 }}>{meaning}</div>
          )}
        </div>
        <div style={{ display:"flex", flexDirection:"column", gap:6, flexShrink:0 }}>
          <button onClick={()=>playModel(audioUrl, text, voice, 0.7)}
            style={{ background:"var(--cream-deep)", color:"var(--navy)", borderRadius:9, padding:"8px 12px", fontSize:13, fontWeight:600, whiteSpace:"nowrap" }}>
            {audioUrl ? "🔊 선생님 발음" : "🔊 듣기"}
          </button>
          <button onClick={()=> audioUrl ? playModel(audioUrl, text, voice) : speak(text, voice, 0.45)}
            style={{ background:"#fff", color:"var(--navy)", border:"1px solid var(--line)", borderRadius:9, padding:"7px 12px", fontSize:12, whiteSpace:"nowrap" }}>
            {audioUrl ? "🔁 다시" : "🐢 천천히"}
          </button>
        </div>
      </div>

      <div className="row" style={{ marginTop:12 }}>
        {!rec ? (
          <button className={take ? "btn-ghost" : "btn"} onClick={start} disabled={busy}>
            🎤 {busy ? "처리 중..." : take ? "다시 녹음" : "녹음 시작"}
          </button>
        ) : (
          <button className="btn-danger" onClick={stop}>■ 녹음 중지</button>
        )}
        {take && <audio controls src={take.audio} />}
      </div>

      {busy && !rec && (
        <div style={{ marginTop:10, background:"var(--cream)", borderRadius:9, padding:"9px 12px",
          fontSize:12.5, color:"var(--navy)", display:"flex", alignItems:"center", gap:8 }}>
          <span className="spin" style={{ width:14, height:14, borderWidth:2, flexShrink:0 }} />
          <span>발음 채점 중이에요… <b>통문장은 길면 1분까지</b> 걸려요. 화면을 닫지 말고 잠깐 기다려 주세요!</span>
        </div>
      )}

      {take && take.score != null && (
        <div style={{ marginTop:12, background:"var(--cream)", borderRadius:10, padding:12 }}>
          <div style={{ display:"flex", alignItems:"center", gap:14 }}>
            <div style={{ textAlign:"center", minWidth:70 }}>
              <div style={{ fontSize:30, fontWeight:800, lineHeight:1,
                color: take.score>=85 ? "#2E7D5B" : take.score>=60 ? "#8A6D0F" : "var(--danger)" }}>
                {take.score}
              </div>
              <div style={{ fontSize:10, color:"var(--navy-soft)", marginTop:2 }}>종합 점수</div>
            </div>
            {take.detail && (
              <div style={{ flex:1, display:"flex", gap:6 }}>
                {[["정확도",take.detail.accuracy],["유창성",take.detail.fluency],["완성도",take.detail.completeness]].map(([l,v])=>(
                  <div key={l} style={{ flex:1, textAlign:"center" }}>
                    <div style={{ fontSize:16, fontWeight:700, color:"var(--navy)" }}>{v != null ? v : "-"}</div>
                    <div style={{ fontSize:10, color:"var(--navy-soft)" }}>{l}</div>
                    <div style={{ height:4, background:"#E3DCC8", borderRadius:2, marginTop:3, overflow:"hidden" }}>
                      <div style={{ width:`${v||0}%`, height:"100%", background:"var(--gold)" }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          {take.words && take.words.length > 0
            ? <ReadMarks words={take.words} />
            : <AlignedFallback recognized={take.recognized} />}
        </div>
      )}
      {take && take.score == null && take.scoring && (
        <div style={{ marginTop:10, background:"var(--cream)", borderRadius:9, padding:"9px 12px",
          fontSize:12.5, color:"var(--navy)", display:"flex", alignItems:"center", gap:8 }}>
          <span className="spin" style={{ width:14, height:14, borderWidth:2, flexShrink:0 }} />
          <span>채점 중이에요 ⏳ 통문장은 조금 걸려요 — <b>다음 걸 계속하셔도</b> 점수는 자동으로 떠요!</span>
        </div>
      )}
      {take && take.score == null && !take.scoring && take.assessError && (
        <div style={{ marginTop:10, fontSize:12, color:"var(--danger)" }}>⚠ {take.assessError}</div>
      )}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// ---------- Student ----------

function PushBell({ studentId }) {
  const [state, setState] = useState("checking");   // checking | on | off | unsupported
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!pushSupported()) { setState("unsupported"); return; }
    (async () => {
      try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        setState(sub && Notification.permission === "granted" ? "on" : "off");
      } catch (e) { setState("off"); }
    })();
  }, []);
  const turnOn = async () => {
    setBusy(true);
    try {
      await enablePush(studentId);
      setState("on");
      try { await apiPost(`/push/test/${studentId}`); } catch (e) {}   // 바로 테스트 알림
      alert("알림을 켰어요! 🔔 방금 테스트 알림을 보냈으니 확인해보세요. 숙제 있는 날 폰으로 알려줄게요.");
    }
    catch (e) { alert(e.message); }
    setBusy(false);
  };
  const turnOff = async () => { setBusy(true); try { await disablePush(studentId); setState("off"); } catch (e) {} setBusy(false); };
  if (state === "checking") return null;
  if (state === "unsupported") return (
    <div className="card" style={{ padding:"10px 14px", background:"var(--cream)" }}>
      <div className="muted" style={{ fontSize:12 }}>🔔 숙제 알림을 받으려면 <b>크롬</b>으로 열거나, 아이폰은 <b>공유 → 홈 화면에 추가</b> 후 그 아이콘으로 들어와 주세요.</div>
    </div>
  );
  return (
    <div className="card" style={{ display:"flex", alignItems:"center", justifyContent:"space-between", gap:10, padding:"12px 14px" }}>
      <div style={{ minWidth:0 }}>
        <div style={{ fontWeight:700, fontSize:14 }}>🔔 숙제 알림</div>
        <div className="muted" style={{ fontSize:12, marginTop:2 }}>
          {state==="on" ? "켜짐 — 숙제 있는 날 폰으로 알려줘요." : "켜두면 숙제 있는 날 폰으로 알려줘요!"}
        </div>
      </div>
      {state==="on"
        ? <button className="btn-ghost" style={{ fontSize:12, padding:"7px 12px", flexShrink:0 }} onClick={turnOff} disabled={busy}>{busy?"...":"끄기"}</button>
        : <button className="btn" style={{ fontSize:13, padding:"8px 14px", flexShrink:0 }} onClick={turnOn} disabled={busy}>{busy?"켜는 중...":"알림 켜기"}</button>}
    </div>
  );
}

function StudentView({ student, onLogout }) {
  const voice = useVoice();
  const [assignments, setAssignments] = useState([]);
  const [statusMap, setStatusMap] = useState({});
  const [open, setOpen] = useState(null);
  const [sub, setSub] = useState(null);
  const [round, setRound] = useState(0);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const [saveMsg, setSaveMsg] = useState("");
  const [done, setDone] = useState(false);
  const [openVocab, setOpenVocab] = useState(null);
  const [openSentence, setOpenSentence] = useState(null);
  const [openExam, setOpenExam] = useState(null);
  const [vocabProgress, setVocabProgress] = useState({});

  const mine = assignments.filter(a =>
    a.published !== false &&
    ((!a.assignedIds || !a.assignedIds.length) || a.assignedIds.includes(student.id)));

  const reloadVocab = () => apiGet(`/vocab/${student.id}`).then(setVocabProgress).catch(()=>{});

  useEffect(() => {
    reloadVocab();
    (async () => {
      // 과제 목록 + 제출상태를 각각 1번씩만 호출 (과제마다 따로 부르지 않음 → 접속 로딩 대폭 단축)
      // ?student= 를 붙이는 이유: 서버가 '이 학생이 속한 학원'의 과제만 골라 주기 위해서다.
      // 학생은 관리자 열쇠가 없어서 이게 없으면 해피트리 과제만 보인다.
      const [list, subs] = await Promise.all([
        apiGet(`/assignments?student=${encodeURIComponent(student.id)}`),
        apiGet(`/student-submissions/${student.id}`).catch(() => ({})),
      ]);
      setAssignments(list);
      const map = {};
      list.forEach(a => {
        const s = subs[a.id];
        map[a.id] = (s && s.status) ? s.status : "none";
      });
      setStatusMap(map);
      setLoading(false);
    })();
  }, []);

  const openA = async (a) => {
    // 재학습(완료한 과제 다시 열기): 완료 메시지 — 점수는 더 오르지 않음(다른 앱과 동일)
    const _st = statusMap[a.id];
    if ((_st === "submitted" || _st === "reviewed") &&
        !confirm("✅ 이 학습을 완료했어요!\n\n다시 하면 복습이에요. 점수는 더 오르지 않아요.\n복습할까요?")) return;
    setOpen(a);
    pingActivity(student.id, "record", a.title);
    const s = await apiGet(`/submission/${a.id}/${student.id}`);
    const items = a.items.map((_, i) => normalizeTakes((s.items || [])[i]));
    const n = a.rounds || 3;
    const isWhole = a.type === "sentence" && a.recordMode === "whole";
    const whole = Array.from({ length: n }, (_, k) => (s.whole || [])[k] || null);
    setSub({ items, whole, comment: s.comment || "", status: s.status || "none" });
    let r = 0;
    if (isWhole) {
      for (let k = 0; k < n; k++) { if (whole[k]) r = Math.min(k + 1, n - 1); else { r = k; break; } }
    } else {
      for (let k = 0; k < n; k++) { if (items.every(it => it[k])) r = Math.min(k + 1, n - 1); else { r = k; break; } }
    }
    setRound(r);
  };

  // 백그라운드 채점 대기: '채점 중'인 take 가 있으면 8초마다 제출을 다시 받아 점수가 채워졌는지 확인.
  const hasScoringTake = !!sub && (
    (sub.whole || []).some(t => t && t.scoring) ||
    (sub.items || []).some(row => (row || []).some(t => t && t.scoring)));
  useEffect(() => {
    if (!open || !hasScoringTake) return;
    const id = setInterval(async () => {
      try {
        const s = await apiGet(`/submission/${open.id}/${student.id}`);
        const n = open.rounds || 3;
        setSub(prev => {
          if (!prev) return prev;
          const whole = Array.from({ length: n }, (_, k) => (s.whole || [])[k] || prev.whole[k] || null);
          const items = (prev.items || []).map((_, i) => normalizeTakes((s.items || [])[i]));
          return { ...prev, whole, items };
        });
      } catch (e) {}
    }, 8000);
    return () => clearInterval(id);
  }, [open, hasScoringTake]);

  const onSaved = (idx, take, val) => {
    setSub(prev => {
      const items = prev.items.map(x => x.slice());
      items[idx][take] = val;
      const next = { ...prev, items };
      // 녹음할 때마다 서버에 바로 저장 (제출 전이라도 유실되지 않도록)
      apiPost(`/submission/${open.id}/${student.id}`, { items })
        .then(() => setSaveMsg("자동 저장됨"))
        .catch(() => setSaveMsg("자동 저장 실패 — 인터넷 연결을 확인해주세요"));
      setTimeout(()=>setSaveMsg(""), 2500);
      return next;
    });
  };

  // 통문장 말하기 모드: 회차별 통문장 녹음 저장
  const onSavedWhole = (roundIdx, val) => {
    setSub(prev => {
      const whole = (prev.whole || []).slice();
      whole[roundIdx] = val;
      const next = { ...prev, whole };
      apiPost(`/submission/${open.id}/${student.id}`, { whole })
        .then(() => setSaveMsg("자동 저장됨"))
        .catch(() => setSaveMsg("자동 저장 실패 — 인터넷 연결을 확인해주세요"));
      setTimeout(()=>setSaveMsg(""), 2500);
      return next;
    });
  };

  const submit = async () => {
    const isWhole = open.type==="sentence" && open.recordMode==="whole";
    const parts = [];
    for (let r = 0; r < (open.rounds || 3); r++) {
      if (isWhole) { if (!(sub.whole||[])[r]) parts.push(`${r+1}회차`); }
      else { const miss = sub.items.filter(it => !it[r]).length; if (miss) parts.push(`${r+1}회차 ${miss}개`); }
    }
    if (parts.length && !confirm(`아직 녹음하지 않은 ${isWhole ? "회차" : "항목"}가 있어요 (${parts.join(", ")}). 그래도 제출할까요?`)) return;
    setMsg("제출 중...");
    try {
      await apiPost(`/submission/${open.id}/${student.id}`,
        isWhole
          ? { whole: sub.whole, status: "submitted", submittedAt: nowStr() }
          : { items: sub.items, status: "submitted", submittedAt: nowStr() });
      setStatusMap(m => ({ ...m, [open.id]: "submitted" }));
      setMsg("");
      setDone(true);
    } catch (e) { setMsg("제출 실패: " + e.message); }
  };

  if (loading) return <div className="center"><div className="spin" /></div>;

  if (open && sub) {
    return (
      <div className="wrap">
        <div className="hdr">
          <div className="row" style={{ gap:12 }}>
            <button onClick={()=>{ setOpen(null); setSub(null); }} style={{ background:"none", color:"var(--cream)", fontSize:22 }}>‹</button>
            <div>
              <div style={{ fontWeight:700, fontSize:15 }}>{open.title}</div>
              <div style={{ fontSize:11, color:"var(--gold-soft)" }}>
                {open.type==="word"?"단어":"문장"} {open.items.length}개 · {open.rounds || 3}회 녹음{open.dueDate ? ` · 마감 ${formatDue(open.dueDate)}` : ""}
              </div>
            </div>
          </div>
        </div>
        <div className="body" style={{ paddingBottom:100 }}>
          {sub.status === "reviewed" && sub.comment && (
            <div className="card" style={{ background:"#F3E4B8" }}>
              <div style={{ fontSize:11, fontWeight:700, color:"#8A6D0F", marginBottom:4 }}>선생님 코멘트</div>
              <div style={{ fontSize:14 }}>{sub.comment}</div>
            </div>
          )}

          {(open.rounds || 3) > 1 && (
            <div className="card" style={{ padding:12 }}>
              <div className="label" style={{ marginBottom:8 }}>몇 회차를 녹음할까요?</div>
              <div className="seg" style={{ marginTop:0 }}>
                {Array.from({length: open.rounds || 3}, (_,r) => {
                  const isWhole = open.type==="sentence" && open.recordMode==="whole";
                  const label = isWhole
                    ? `${r+1}회차 (${(sub.whole||[])[r] ? "완료" : "미완료"})`
                    : `${r+1}회차 (${sub.items.filter(it => it[r]).length}/${sub.items.length})`;
                  return (
                    <button key={r} className={round===r ? "on" : ""} onClick={()=>setRound(r)}>{label}</button>
                  );
                })}
              </div>
            </div>
          )}

          {open.type==="sentence" && open.recordMode==="whole" ? (
            <>
              <div className="card" style={{ background:"var(--cream)", padding:12 }}>
                <div style={{ fontSize:11, fontWeight:700, color:"var(--navy-soft)", marginBottom:6 }}>📖 통문장 — 처음부터 끝까지 한 번에 읽어요</div>
                <div style={{ fontSize:15, lineHeight:1.7, color:"var(--navy)" }}>
                  {open.items.map((t,i)=>(<div key={i}>{i+1}. {t}</div>))}
                </div>
              </div>
              <Recorder key={`whole-${round}`} index={0} label="통문장 말하기"
                text={open.items.join("\n")}
                take={(sub.whole||[])[round]} round={round}
                onSaved={(_,r,v)=>onSavedWhole(r,v)} voice={voice}
                bgScore={true} aid={open.id} sid={student.id} mode="whole" />
            </>
          ) : (
            open.items.map((t,i) => (
              <Recorder key={`${round}-${i}`} index={i} text={t} meaning={(open.meanings||[])[i]}
                take={sub.items[i][round]} round={round} onSaved={onSaved} voice={voice}
                audioUrl={(open.exampleAudio||[])[i]} />
            ))
          )}
        </div>
        <div style={{ position:"fixed", bottom:0, left:0, right:0, padding:14, background:"var(--cream)", borderTop:"1px solid var(--line)" }}>
          <div style={{ maxWidth:640, margin:"0 auto" }}>
            {msg && <div style={{ textAlign:"center", fontSize:12, fontWeight:700, color:"var(--navy)", marginBottom:8 }}>{msg}</div>}
            {!msg && saveMsg && <div style={{ textAlign:"center", fontSize:11, color:"var(--navy-soft)", marginBottom:8 }}>{saveMsg}</div>}
            <button className="btn full" onClick={submit}>제출하기</button>
          </div>
        </div>

        {done && (
          <div onClick={()=>{ setDone(false); setOpen(null); setSub(null); }}
            style={{ position:"fixed", inset:0, background:"rgba(27,46,76,0.75)", zIndex:100,
              display:"flex", alignItems:"center", justifyContent:"center", padding:24 }}>
            <div style={{ background:"#fff", borderRadius:20, padding:"36px 28px", textAlign:"center",
              maxWidth:340, width:"100%", boxShadow:"0 20px 60px rgba(0,0,0,0.3)" }}>
              <div style={{ fontSize:56, lineHeight:1, marginBottom:14 }}>🎉</div>
              <div style={{ fontSize:28, fontWeight:800, color:"var(--navy)", marginBottom:8 }}>제출 완료!</div>
              <div style={{ fontSize:15, color:"var(--navy-soft)", lineHeight:1.6, marginBottom:22 }}>
                {student.name} 학생, 오늘도 잘했어요.<br/>선생님이 확인하고 알려줄게요.
              </div>
              <button className="btn full" onClick={()=>{ setDone(false); setOpen(null); setSub(null); }}>
                확인
              </button>
              <a href={STUDENT_PORTAL} className="btn full" style={{ display:"block", marginTop:10, background:"var(--navy)", color:"#fff", textDecoration:"none" }}>
                🏠 학생 메인으로 — 다른 학습 하러 가기
              </a>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (openVocab) {
    return (
      <div className="wrap">
        <div className="hdr">
          <div className="row" style={{ gap:12 }}>
            <button onClick={()=>{ setOpenVocab(null); reloadVocab(); }} style={{ background:"none", color:"var(--cream)", fontSize:22 }}>‹</button>
            <div>
              <div style={{ fontWeight:700, fontSize:15 }}>{openVocab.title}</div>
              <div style={{ fontSize:11, color:"var(--gold-soft)" }}>단어 자습 · {openVocab.items.length}단어</div>
            </div>
          </div>
        </div>
        <div className="body">
          <VocabSetStudy assignment={openVocab} student={student} voice={voice}
            onClose={()=>{ setOpenVocab(null); reloadVocab(); }} />
        </div>
      </div>
    );
  }

  if (openSentence) {
    return (
      <div className="wrap">
        <div className="hdr">
          <div className="row" style={{ gap:12 }}>
            <button onClick={()=>{ setOpenSentence(null); reloadVocab(); }} style={{ background:"none", color:"var(--cream)", fontSize:22 }}>‹</button>
            <div>
              <div style={{ fontWeight:700, fontSize:15 }}>{openSentence.title}</div>
              <div style={{ fontSize:11, color:"var(--gold-soft)" }}>문장 자습 · {openSentence.items.length}문장</div>
            </div>
          </div>
        </div>
        <div className="body">
          <SentenceStudy assignment={openSentence} student={student} voice={voice}
            onClose={()=>{ setOpenSentence(null); reloadVocab(); }} />
        </div>
      </div>
    );
  }

  if (openExam) {
    return (
      <div className="wrap">
        <div className="hdr">
          <div className="row" style={{ gap:12 }}>
            <button onClick={()=>{ setOpenExam(null); }} style={{ background:"none", color:"var(--cream)", fontSize:22 }}>‹</button>
            <div>
              <div style={{ fontWeight:700, fontSize:15 }}>{openExam.title}</div>
              <div style={{ fontSize:11, color:"var(--gold-soft)" }}>권말 진급 시험</div>
            </div>
          </div>
        </div>
        <div className="body">
          <ExamPlay assignment={openExam} student={student}
            onClose={()=>{ setOpenExam(null); }} />
        </div>
      </div>
    );
  }

  return (
    <div className="wrap">
      <div className="hdr">
        <div>
          <div style={{ fontSize:11, color:"var(--gold-soft)" }}>반갑습니다</div>
          <h1>{student.name} 학생</h1>
        </div>
        <button onClick={onLogout} style={{ background:"none", color:"var(--cream)", fontSize:13 }}>로그아웃</button>
      </div>
      <div className="body">
        <a href={STUDENT_PORTAL}
          style={{ display:"flex", alignItems:"center", justifyContent:"space-between", gap:10, textDecoration:"none",
            background:"var(--navy)", color:"#fff", borderRadius:14, padding:"12px 16px", marginBottom:12 }}>
          <span style={{ fontWeight:800, fontSize:15 }}>🏠 학생 홈으로 돌아가기</span>
          <span style={{ fontSize:12, color:"var(--gold-soft)", fontWeight:700 }}>문해숨 · 수학숨 숙제 →</span>
        </a>
        <div style={{ marginBottom:12 }}><PushBell studentId={student.id} /></div>
        <StudentHome mine={mine} statusMap={statusMap} vocabProgress={vocabProgress}
          onOpenRecord={openA} onOpenVocab={setOpenVocab} onOpenSentence={setOpenSentence} onOpenExam={setOpenExam} />
      </div>
    </div>
  );
}

// ---------- 학생 홈: 달력 + [녹음 숙제 / 단어 자습] 두 탭 (같은 달력 공유) ----------

function StudentHome({ mine, statusMap, vocabProgress, onOpenRecord, onOpenVocab, onOpenSentence, onOpenExam }) {
  const today = new Date();
  const [ym, setYm] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [tab, setTab] = useState("record");
  const [picked, setPicked] = useState(() =>
    `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-${String(today.getDate()).padStart(2,"0")}`);

  const isVocab = tab === "vocab";
  const isSentence = tab === "sentence";
  const isStudy = isVocab || isSentence;
  const studyLabel = isSentence ? "문장 자습" : "단어 자습";
  const source = isVocab
    ? mine.filter(a => a.type === "exam" ? (a.poolSize || (a.items||[]).length) : ((a.type || "word") === "word" && (a.items || []).length))
    : isSentence
      ? mine.filter(a => a.type === "sentence" && (a.items || []).length)
      : mine.filter(a => a.type !== "exam");

  const byDate = {};
  const noDate = [];
  source.forEach(a => {
    if (a.dueDate) (byDate[a.dueDate] = byDate[a.dueDate] || []).push(a);
    else noDate.push(a);
  });
  const dayCmp = (x, y) => {
    const dx = dayNum(x.title), dy = dayNum(y.title);
    if (dx != null && dy != null && dx !== dy) return dx - dy;
    return (x.title || "").localeCompare(y.title || "");
  };
  Object.keys(byDate).forEach(k => byDate[k].sort(dayCmp));
  noDate.sort(dayCmp);

  // 자습 완료 기준: 단계의 50% 이상 완료 (단어 4단계 중 2개↑, 문장 2단계 중 1개↑)
  const studyDone = (a) => {
    const rec = vocabProgress[a.id];
    if (!rec || !rec.byMode) return false;
    const stages = a.type === "sentence" ? ["smeaning", "unscramble"] : ["flash", "choice", "spell", "test"];
    const done = stages.filter(s => rec.byMode[s]).length;
    return done / stages.length >= 0.5;
  };

  // 달력 완료 배지: 전체 과제 기준으로 그날 완료한 활동 표시 (탭과 무관하게 한눈에)
  const allByDate = {};
  mine.forEach(a => { if (a.dueDate) (allByDate[a.dueDate] = allByDate[a.dueDate] || []).push(a); });
  const dayBadges = (k) => {
    const list = allByDate[k] || [];
    const seen = {};
    list.forEach(a => {
      const L = a.type === "sentence" ? "문" : "단";
      const st = statusMap[a.id] || "none";
      if (st === "submitted" || st === "reviewed") seen[L + "R"] = { label: L, kind: "rec" };
      if (studyDone(a)) seen[L + "S"] = { label: L, kind: "study" };
    });
    return ["단R", "문R", "단S", "문S"].filter(x => seen[x]).map(x => seen[x]);
  };

  const first = new Date(ym.y, ym.m, 1);
  const daysInMonth = new Date(ym.y, ym.m + 1, 0).getDate();
  const startDow = first.getDay();
  const cells = [];
  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const key = (d) => `${ym.y}-${String(ym.m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
  const todayKey = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-${String(today.getDate()).padStart(2,"0")}`;

  const move = (delta) => {
    let m = ym.m + delta, y = ym.y;
    if (m < 0) { m = 11; y--; }
    if (m > 11) { m = 0; y++; }
    setYm({ y, m });
  };

  const doneOf = (a) => isStudy
    ? studyDone(a)
    : (statusMap[a.id] || "none") !== "none";

  /* ★미리 학습 창: 과제 날짜는 마감일이라 미리 해도 되지만, 마감 3일 전부터만 열린다
     (원장 2026-09-23 — 한 달치를 몰아 해 버리는 것을 막기 위해). 열리는 날(openFrom)은
     서버가 과제마다 넣어 준다 — 그래야 화면과 서버 판단이 어긋나지 않는다.
     마감이 지난 과제는 계속 열려 있다(밀린 거 따라잡기). */
  const lockedOf = (a) => !!(a.openFrom && todayKey < a.openFrom);
  const openLabel = (a) => `${+a.openFrom.slice(5,7)}월 ${+a.openFrom.slice(8,10)}일`;

  const dayState = (d) => {
    const list = byDate[key(d)] || [];
    if (!list.length) return null;
    if (list.every(doneOf)) return "done";
    if (key(d) < todayKey) return "late";
    if (list.every(lockedOf)) return "soon";     // 아직 안 열린 날 — '해야 할 일'로 보이면 안 된다
    return "todo";
  };

  const pickedList = byDate[picked] || [];

  const recordCard = (a) => {
    const st = statusMap[a.id] || "none";
    return (
      <button key={a.id} onClick={()=>onOpenRecord(a)} className="card"
        style={{ display:"flex", width:"100%", textAlign:"left", justifyContent:"space-between", alignItems:"center", gap:10 }}>
        <div style={{ minWidth:0 }}>
          <div className="row" style={{ marginBottom:5 }}>
            <Badge tone={a.type==="word"?"b-navy":"b-gold"}>{a.type==="word"?"단어":"문장"}</Badge>
            <span className="muted">{a.items.length}개 · {a.rounds||3}회</span>
          </div>
          <div style={{ fontWeight:700, fontSize:15 }}>{a.title}</div>
        </div>
        <Badge tone={st==="none"?"b-gray":st==="submitted"?"b-gold":"b-navy"}>
          {st==="none"?"미제출":st==="submitted"?"제출완료":"확인완료"}
        </Badge>
      </button>
    );
  };
  const vocabCard = (a) => {
    const rec = vocabProgress[a.id];
    return (
      <button key={a.id} onClick={()=>onOpenVocab(a)} className="card"
        style={{ display:"flex", width:"100%", textAlign:"left", justifyContent:"space-between", alignItems:"center", gap:10 }}>
        <div style={{ minWidth:0 }}>
          <div className="row" style={{ marginBottom:5 }}>
            <Badge tone="b-navy">단어</Badge>
            <span className="muted">{a.items.length}단어</span>
          </div>
          <div style={{ fontWeight:700, fontSize:15 }}>{a.title}</div>
        </div>
        <Badge tone={rec ? "b-navy" : "b-gray"}>{rec ? `최고 ${rec.best}점` : "시작 전"}</Badge>
      </button>
    );
  };
  const sentenceCard = (a) => {
    const rec = vocabProgress[a.id];
    return (
      <button key={a.id} onClick={()=>onOpenSentence(a)} className="card"
        style={{ display:"flex", width:"100%", textAlign:"left", justifyContent:"space-between", alignItems:"center", gap:10 }}>
        <div style={{ minWidth:0 }}>
          <div className="row" style={{ marginBottom:5 }}>
            <Badge tone="b-gold">문장</Badge>
            <span className="muted">{a.items.length}문장</span>
          </div>
          <div style={{ fontWeight:700, fontSize:15 }}>{a.title}</div>
        </div>
        <Badge tone={rec ? "b-navy" : "b-gray"}>{rec && rec.best!=null ? `최고 ${rec.best}점` : rec ? "학습중" : "시작 전"}</Badge>
      </button>
    );
  };
  const examCard = (a) => {
    const rec = vocabProgress; // placeholder unused
    return (
      <button key={a.id} onClick={()=>onOpenExam(a)} className="card"
        style={{ display:"flex", width:"100%", textAlign:"left", justifyContent:"space-between", alignItems:"center", gap:10,
          border:"1.5px solid var(--gold)", background:"var(--cream-deep, #fbf6ea)" }}>
        <div style={{ minWidth:0 }}>
          <div className="row" style={{ marginBottom:5 }}>
            <Badge tone="b-gold">진급시험</Badge>
            <span className="muted">{a.poolSize || a.items.length}단어 · 40문항</span>
          </div>
          <div style={{ fontWeight:800, fontSize:15, color:"var(--navy)" }}>🎯 {a.title}</div>
        </div>
        <span style={{ color:"var(--navy)", fontSize:20 }}>›</span>
      </button>
    );
  };
  const vocabOrExam = (a) => a.type === "exam" ? examCard(a) : vocabCard(a);
  /* 아직 안 열린 과제 — 누를 수 없게 하고 언제부터 되는지 알려 준다. */
  const lockedCard = (a) => (
    <div key={a.id} className="card"
      style={{ display:"flex", width:"100%", justifyContent:"space-between", alignItems:"center", gap:10,
        opacity:.62, background:"#F4F6F8" }}>
      <div style={{ minWidth:0 }}>
        <div className="row" style={{ marginBottom:5 }}>
          <Badge tone="b-gray">{a.type==="sentence"?"문장":"단어"}</Badge>   {/* 진급시험은 이 창을 안 타서 여기 안 온다 */}
          <span className="muted">{openLabel(a)}부터 열려요</span>
        </div>
        <div style={{ fontWeight:700, fontSize:15 }}>{a.title}</div>
      </div>
      <span style={{ fontSize:20 }}>🔒</span>
    </div>
  );
  const baseCard = isVocab ? vocabOrExam : isSentence ? sentenceCard : recordCard;
  const card = (a) => lockedOf(a) ? lockedCard(a) : baseCard(a);

  return (
    <>
      <div className="seg" style={{ marginBottom:12 }}>
        <button className={tab==="record" ? "on" : ""} onClick={()=>setTab("record")}>📅 녹음</button>
        <button className={tab==="vocab" ? "on" : ""} onClick={()=>setTab("vocab")}>📚 단어</button>
        <button className={tab==="sentence" ? "on" : ""} onClick={()=>setTab("sentence")}>📝 문장</button>
      </div>

      <div className="card" style={{ padding:14 }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:12 }}>
          <button onClick={()=>move(-1)} style={{ background:"none", fontSize:22, color:"var(--navy)", padding:"0 10px" }}>‹</button>
          <div style={{ fontWeight:800, fontSize:17, color:"var(--navy)" }}>{ym.y}년 {ym.m+1}월</div>
          <button onClick={()=>move(1)} style={{ background:"none", fontSize:22, color:"var(--navy)", padding:"0 10px" }}>›</button>
        </div>

        <div style={{ display:"grid", gridTemplateColumns:"repeat(7,1fr)", gap:4, marginBottom:6 }}>
          {["일","월","화","수","목","금","토"].map((n,i) => (
            <div key={n} style={{ textAlign:"center", fontSize:11, fontWeight:700,
              color: i===0 ? "var(--danger)" : i===6 ? "#3B6FA0" : "var(--navy-soft)" }}>{n}</div>
          ))}
        </div>

        <div style={{ display:"grid", gridTemplateColumns:"repeat(7,1fr)", gap:4 }}>
          {cells.map((d,i) => {
            if (!d) return <div key={"e"+i} />;
            const k = key(d);
            const st = dayState(d);
            const isToday = k === todayKey;
            const isPicked = k === picked;
            const bs = dayBadges(k);
            const hasBadges = bs.length > 0;
            const colors = { done:"#2E7D5B", todo:"var(--gold)", late:"var(--danger)", soon:"#B9C4CE" };
            return (
              <button key={k} onClick={()=>setPicked(k)}
                style={{ minHeight:54, padding:"5px 0", borderRadius:10, position:"relative",
                  background: isPicked ? "var(--navy)" : hasBadges ? "#E7F1EA" : isToday ? "var(--cream-deep)" : "transparent",
                  border: isPicked ? "none" : hasBadges ? "1px solid #BFE0CC" : isToday ? "1px solid var(--gold)" : "1px solid transparent",
                  color: isPicked ? "#fff" : "var(--ink)",
                  fontSize:15, fontWeight: (st || hasBadges) ? 700 : 400,
                  display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:3 }}>
                {d}
                {(() => {
                  const showDot = st && st !== "done" && !bs.length;
                  return <>
                    {bs.length > 0 && (
                      <div style={{ display:"flex", flexWrap:"wrap", gap:3, justifyContent:"center", maxWidth:"100%" }}>
                        {bs.map((b,bi) => (
                          <span key={bi} style={{ fontSize:12, fontWeight:800, lineHeight:1.15, padding:"1px 5px", borderRadius:5,
                            background: b.kind==="rec" ? (isPicked ? "#9FB0CC" : "var(--navy)") : "var(--good)",
                            color:"#fff", border: isPicked ? "1px solid rgba(255,255,255,.6)" : "none" }}>{b.label}</span>
                        ))}
                      </div>
                    )}
                    {showDot && <span style={{ width:6, height:6, borderRadius:"50%", background: isPicked ? "#fff" : colors[st] }} />}
                  </>;
                })()}
              </button>
            );
          })}
        </div>

        <div style={{ marginTop:12, display:"flex", flexDirection:"column", gap:6, alignItems:"center" }}>
          <div className="row" style={{ gap:10, justifyContent:"center", flexWrap:"wrap" }}>
            <span style={{ fontSize:11, color:"var(--navy-soft)", display:"inline-flex", alignItems:"center", gap:4 }}>
              <span style={{ fontSize:11, fontWeight:800, color:"#fff", background:"var(--navy)", borderRadius:4, padding:"1px 4px" }}>단</span>
              <span style={{ fontSize:11, fontWeight:800, color:"#fff", background:"var(--navy)", borderRadius:4, padding:"1px 4px" }}>문</span>
              🎤 녹음 완료
            </span>
            <span style={{ fontSize:11, color:"var(--navy-soft)", display:"inline-flex", alignItems:"center", gap:4 }}>
              <span style={{ fontSize:11, fontWeight:800, color:"#fff", background:"var(--good)", borderRadius:4, padding:"1px 4px" }}>단</span>
              <span style={{ fontSize:11, fontWeight:800, color:"#fff", background:"var(--good)", borderRadius:4, padding:"1px 4px" }}>문</span>
              📚 자습 완료
            </span>
          </div>
          <div className="row" style={{ gap:12, justifyContent:"center" }}>
            {[["var(--gold)", isStudy?"할 수 있어요":"해야 해요"],["var(--danger)","기한 지남"]].map(([c,l]) => (
              <span key={l} style={{ fontSize:11, color:"var(--navy-soft)", display:"inline-flex", alignItems:"center", gap:4 }}>
                <span style={{ width:7, height:7, borderRadius:"50%", background:c, display:"inline-block" }} />{l}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div style={{ fontWeight:700, color:"var(--navy)", margin:"14px 4px 8px", fontSize:14 }}>
        {picked.slice(5).replace("-","월 ")}일 {isStudy ? studyLabel : "숙제"}
      </div>
      {!pickedList.length && (
        <div className="card" style={{ textAlign:"center", padding:24 }}>
          <span className="muted">이 날은 {isStudy ? studyLabel+"이" : "숙제가"} 없어요 🎈</span>
        </div>
      )}
      {/* 과제 날짜는 '마감일'이라 미리 해도 되지만, 마감 3일 전부터만 열린다(lockedOf).
         그보다 먼 건 자물쇠로 보여주고, 서버(_too_early)도 같은 기준으로 막는다. */}
      {pickedList.map(card)}

      {noDate.length > 0 && (
        <>
          <div style={{ fontWeight:700, color:"var(--navy)", margin:"18px 4px 8px", fontSize:14 }}>날짜 없는 {isStudy ? (isSentence?"문장":"단어장") : "숙제"}</div>
          {noDate.map(card)}
        </>
      )}
    </>
  );
}

// ---------- Admin: students ----------

function SentenceStudy({ assignment, student, voice, onClose }) {
  const cur = assignment;
  const [mode, setMode] = useState(null);
  const [rec, setRec] = useState(null);
  const [savedMsg, setSavedMsg] = useState("");
  const reload = () => apiGet(`/vocab/${student.id}`).then(d => setRec(d[cur.id] || null)).catch(()=>{});
  useEffect(() => { reload(); }, []);
  const pairs = cur.items.map((w, i) => ({ text: w, kor: (cur.meanings && cur.meanings[i]) || "" }));
  const back = () => setMode(null);
  const persist = async (body) => {
    try { const r = await apiPost(`/vocab/${cur.id}/${student.id}`, body); setRec(r); setSavedMsg("저장됐어요 ✓"); setTimeout(()=>setSavedMsg(""), 1600); }
    catch (e) { reload(); }
  };
  if (mode === "meaning") return <SentenceFlash pairs={pairs} title={cur.title} voice={voice} onBack={back} onDone={()=>persist({ mode:"smeaning" })} />;
  if (mode === "scramble") return <Unscramble pairs={pairs} title={cur.title} voice={voice} onBack={back} onDone={(c,t)=>persist({ mode:"unscramble", correct:c, total:t })} />;

  const bm = (rec && rec.byMode) || {};
  const modes = [
    ["meaning", "smeaning", "🃏 뜻 확인하기", "문장을 넘기며 한글 뜻을 확인해요 (발음 자동재생)"],
    ["scramble", "unscramble", "🧩 문장 배열", "섞인 단어를 순서대로 배열해요 · 점수 기록"],
  ];
  return <>
    <div className="muted" style={{ marginBottom:12 }}>{pairs.length}문장{rec && rec.best!=null ? ` · 배열 최고 ${rec.best}점` : ""}</div>
    {modes.map(([id, mk, label, desc]) => (
      <button key={id} className="card" onClick={()=>setMode(id)}
        style={{ display:"flex", width:"100%", textAlign:"left", justifyContent:"space-between", alignItems:"center", gap:10 }}>
        <div><div style={{ fontWeight:700, fontSize:15 }}>{bm[mk] ? "✅ " : ""}{label}</div>
          <div className="muted" style={{ marginTop:2 }}>{desc}{mk==="unscramble" && bm.unscramble && bm.unscramble.best!=null ? ` · 최고 ${bm.unscramble.best}점` : ""}</div></div>
        <span style={{ color:"var(--navy-soft)", fontSize:20 }}>›</span>
      </button>
    ))}
    {savedMsg && (
      <div style={{ position:"fixed", left:0, right:0, bottom:24, display:"flex", justifyContent:"center", pointerEvents:"none", zIndex:90 }}>
        <div style={{ background:"var(--navy)", color:"#fff", padding:"8px 16px", borderRadius:999, fontSize:13, fontWeight:700 }}>{savedMsg}</div>
      </div>
    )}
  </>;
}

function SentenceFlash({ pairs, title, voice, onBack, onDone }) {
  const [order] = useState(() => shuffleArr(pairs));
  const [i, setI] = useState(0);
  const [flip, setFlip] = useState(false);
  const doneRef = useRef(false);
  const p = order[i];
  useEffect(() => {
    if (p) speak(p.text, voice, 0.85);
    if (i === order.length - 1 && !doneRef.current) { doneRef.current = true; onDone && onDone(); }
  }, [i]);
  const move = (d) => { setFlip(false); setI(x => Math.max(0, Math.min(order.length - 1, x + d))); };
  return <>
    <button onClick={onBack} style={{ background:"none", color:"var(--navy)", fontWeight:700, marginBottom:10 }}>‹ 모드 선택</button>
    <div className="muted" style={{ marginBottom:8 }}>{title} · {i+1}/{order.length}</div>
    <button onClick={()=>setFlip(f=>!f)} className="card"
      style={{ width:"100%", minHeight:200, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:12, padding:"22px 18px" }}>
      <div style={{ fontSize: flip ? 19 : 21, fontWeight:800, color:"var(--navy)", lineHeight:1.5, textAlign:"center" }}>{flip ? p.kor : p.text}</div>
      <div className="muted">{flip ? "영어 보기" : "뜻 보기"} (탭)</div>
    </button>
    <button className="btn-ghost" style={{ width:"100%", marginTop:8 }} onClick={()=>speak(p.text, voice, 0.7)}>🔊 다시 듣기</button>
    <div className="row" style={{ gap:8, marginTop:8 }}>
      <button className="btn-ghost" style={{ flex:1 }} onClick={()=>move(-1)} disabled={i===0}>이전</button>
      <button className="btn" style={{ flex:1 }} onClick={()=>move(1)} disabled={i===order.length-1}>다음</button>
    </div>
  </>;
}

function Unscramble({ pairs, title, voice, onBack, onDone }) {
  const [order] = useState(() => shuffleArr(pairs.filter(p => (p.text||"").trim().split(/\s+/).length >= 2)));
  const [i, setI] = useState(0);
  const [tokens, setTokens] = useState([]);
  const [bank, setBank] = useState([]);
  const [picked, setPicked] = useState([]);
  const [checked, setChecked] = useState(null);
  const scoreRef = useRef(0);
  const [scoreView, setScoreView] = useState(0);
  const p = order[i];
  useEffect(() => {
    const w = p ? p.text.trim().split(/\s+/) : [];
    setTokens(w); setBank(shuffleArr(w.map((_, k) => k))); setPicked([]); setChecked(null);
  }, [i]);

  if (!order.length) return <>
    <button onClick={onBack} style={{ background:"none", color:"var(--navy)", fontWeight:700, marginBottom:10 }}>‹ 모드 선택</button>
    <div className="card" style={{ textAlign:"center", padding:24 }}><span className="muted">단어가 2개 이상인 문장이 없어 배열할 게 없어요.</span></div>
  </>;

  const remaining = bank.filter(k => !picked.includes(k));
  const target = tokens.join(" ");
  const answer = picked.map(k => tokens[k]).join(" ");
  const pick = (k) => { if (!checked) setPicked(prev => [...prev, k]); };
  const undo = () => { if (!checked) setPicked(prev => prev.slice(0, -1)); };
  const check = () => {
    const ok = answer === target;
    setChecked(ok ? "right" : "wrong");
    if (ok) { scoreRef.current += 1; setScoreView(scoreRef.current); }
    speak(p.text, voice, 0.85);
  };
  const next = () => {
    if (i >= order.length - 1) { onDone && onDone(scoreRef.current, order.length); onBack(); }
    else setI(i + 1);
  };

  return <>
    <button onClick={onBack} style={{ background:"none", color:"var(--navy)", fontWeight:700, marginBottom:10 }}>‹ 모드 선택</button>
    <div className="row" style={{ justifyContent:"space-between", marginBottom:8 }}>
      <span className="muted">{title} · {i+1}/{order.length}</span>
      <span style={{ fontWeight:700, color:"var(--navy)", fontSize:13 }}>맞힘 {scoreView}</span>
    </div>
    <div className="card" style={{ background:"var(--cream)", padding:"12px 14px", marginBottom:10 }}>
      <div style={{ fontSize:11, fontWeight:700, color:"var(--navy-soft)", marginBottom:4 }}>이 뜻이 되도록 단어를 순서대로 놓아요</div>
      <div style={{ fontSize:16, fontWeight:700, color:"var(--navy)", lineHeight:1.5 }}>{p.kor || "(뜻 없음)"}</div>
    </div>
    <div className="card" style={{ minHeight:66, display:"flex", flexWrap:"wrap", gap:6, alignItems:"flex-start",
      borderColor: checked==="right" ? "var(--good)" : checked==="wrong" ? "var(--danger)" : "var(--line)" }}>
      {picked.length ? picked.map((k, idx) => (
        <span key={idx} style={{ padding:"7px 11px", borderRadius:10, background:"var(--navy)", color:"#fff", fontWeight:700, fontSize:15 }}>{tokens[k]}</span>
      )) : <span className="muted" style={{ alignSelf:"center", fontSize:13 }}>아래 단어를 눌러 문장을 만들어요</span>}
    </div>
    {checked === "wrong" && (
      <div style={{ marginTop:8, fontSize:14, color:"var(--danger)", fontWeight:700 }}>아쉬워요! 정답: <span style={{ color:"var(--navy)" }}>{target}</span></div>
    )}
    {checked === "right" && (
      <div style={{ marginTop:8, fontSize:15, color:"var(--good)", fontWeight:800 }}>정답이에요! 🎉</div>
    )}
    {!checked && (
      <div className="row" style={{ flexWrap:"wrap", gap:8, marginTop:12 }}>
        {remaining.map((k) => (
          <button key={k} onClick={()=>pick(k)}
            style={{ padding:"9px 13px", borderRadius:11, border:"1px solid var(--navy)", background:"#fff", color:"var(--navy)", fontWeight:700, fontSize:16 }}>{tokens[k]}</button>
        ))}
      </div>
    )}
    <div className="row" style={{ gap:8, marginTop:16 }}>
      {!checked ? <>
        <button className="btn-ghost" style={{ flex:1 }} onClick={undo} disabled={!picked.length}>되돌리기</button>
        <button className="btn" style={{ flex:2 }} onClick={check} disabled={remaining.length>0}>확인</button>
      </> : (
        <button className="btn full" onClick={next}>{i >= order.length-1 ? "끝내기" : "다음 문장 →"}</button>
      )}
    </div>
  </>;
}

// ---------- 단어 자습 ----------

function VocabSetStudy({ assignment, student, voice, onClose }) {
  const cur = assignment;
  const [mode, setMode] = useState(null);
  const [rec, setRec] = useState(null);
  const [savedMsg, setSavedMsg] = useState("");
  const [doneMsg, setDoneMsg] = useState(false);   // 4단계 완료 축하 메시지

  const reloadProgress = () => apiGet(`/vocab/${student.id}`).then(d => setRec(d[cur.id] || null)).catch(()=>{});
  useEffect(() => { reloadProgress(); }, []);

  const pairs = cur.items.map((w, i) => ({ word: w, kor: (cur.meanings && cur.meanings[i]) || "", audio: (cur.exampleAudio && cur.exampleAudio[i]) || null }));

  const backToModes = () => { setMode(null); };
  // 결과 저장 후, 이번 저장으로 4단계가 처음 완성되면 완료 메시지
  const persist = async (body) => {
    const wasComplete = !!(rec && rec.complete);
    try {
      const r = await apiPost(`/vocab/${cur.id}/${student.id}`, body);
      setRec(r);
      setSavedMsg("저장됐어요 ✓"); setTimeout(()=>setSavedMsg(""), 1800);
      if (r.complete && !wasComplete) setDoneMsg(true);
    } catch (e) { reloadProgress(); }
  };
  const saveResult = (correct, total) => persist({ mode, correct, total });
  const saveFlash = () => persist({ mode: "flash" });

  if (mode === "flash") return <Flashcards pairs={pairs} title={cur.title} label="카드 암기" voice={voice} onBack={backToModes} onDone={saveFlash} />;
  if (mode === "choice") return <ChoiceQuiz pairs={pairs} title={cur.title} label="뜻 고르기" onBack={backToModes} onDone={saveResult} />;
  if (mode === "spell") return <SpellQuiz pairs={pairs} title={cur.title} label="스펠링" onBack={backToModes} onDone={saveResult} />;
  if (mode === "test") return <ChoiceQuiz pairs={pairs} title={cur.title} label="미니 테스트" onBack={backToModes} onDone={saveResult} limit={Math.min(20, pairs.length)} />;

  const bm = (rec && rec.byMode) || {};
  const doneCount = ["flash","choice","spell","test"].filter(k => bm[k]).length;
  const modes = [
    ["flash", "🃏 카드 암기", "단어와 뜻을 넘기며 외워요 (발음 자동재생)"],
    ["choice", "✅ 뜻 고르기", "4개 중 맞는 뜻 고르기"],
    ["spell", "⌨️ 스펠링", "뜻을 보고 영어 단어 쓰기"],
    ["test", "📝 미니 테스트", "섞어서 시험 · 점수 기록"],
  ];
  return <>
    <div className="muted" style={{ marginBottom:6 }}>{pairs.length}단어{rec ? ` · 최고 ${rec.best}점 · ${rec.attempts}회` : ""}</div>
    <div style={{ marginBottom:12, fontSize:13, fontWeight:700, color: doneCount===4 ? "var(--good)" : "var(--navy-soft)" }}>
      진행 {doneCount}/4 단계 {doneCount===4 ? "· 완료 ✅" : ""}
    </div>
    {modes.map(([id, label, desc]) => (
      <button key={id} className="card" onClick={()=>{ pingActivity(student.id, id, cur.title); setMode(id); }}
        style={{ display:"flex", width:"100%", textAlign:"left", justifyContent:"space-between", alignItems:"center", gap:10 }}>
        <div><div style={{ fontWeight:700, fontSize:15 }}>{bm[id] ? "✅ " : ""}{label}</div>
          <div className="muted" style={{ marginTop:2 }}>{desc}{bm[id] && bm[id].best!=null ? ` · 최고 ${bm[id].best}점` : (bm[id] ? " · 완료" : "")}</div></div>
        <span style={{ color:"var(--navy-soft)", fontSize:20 }}>›</span>
      </button>
    ))}
    {savedMsg && !doneMsg && (
      <div style={{ position:"fixed", left:0, right:0, bottom:24, display:"flex", justifyContent:"center", pointerEvents:"none", zIndex:90 }}>
        <div style={{ background:"var(--navy)", color:"#fff", padding:"8px 16px", borderRadius:999, fontSize:13, fontWeight:700, boxShadow:"0 6px 20px rgba(0,0,0,.2)" }}>{savedMsg}</div>
      </div>
    )}
    {doneMsg && (
      <div onClick={()=>setDoneMsg(false)} style={{ position:"fixed", inset:0, display:"flex", alignItems:"center", justifyContent:"center", zIndex:100, background:"rgba(0,0,0,.3)" }}>
        <div style={{ background:"#fff", borderRadius:20, padding:"34px 30px", textAlign:"center", maxWidth:320, boxShadow:"0 12px 40px rgba(0,0,0,.3)" }}>
          <div style={{ fontSize:56 }}>🎉</div>
          <div style={{ fontSize:22, fontWeight:800, color:"var(--navy)", marginTop:8 }}>자습 4단계 완료!</div>
          <div className="muted" style={{ marginTop:8, fontSize:14 }}>카드암기·뜻고르기·스펠링·미니테스트를 모두 마쳤어요. 기록이 저장됐어요. 정말 잘했어요! 👏</div>
          <button className="btn full" style={{ marginTop:16 }} onClick={()=>setDoneMsg(false)}>확인</button>
          <a href={STUDENT_PORTAL} className="btn full" style={{ display:"block", marginTop:10, background:"var(--navy)", color:"#fff", textDecoration:"none" }}>🏠 학생 메인으로 — 다른 학습 하러 가기</a>
        </div>
      </div>
    )}
  </>;
}

function Flashcards({ pairs, title, voice, onBack, onDone, label }) {
  const [order] = useState(() => shuffleArr(pairs));
  const [i, setI] = useState(0);
  const [flip, setFlip] = useState(false);
  const [done, setDone] = useState(false);
  const doneRef = useRef(false);
  const p = order[i];
  useEffect(() => {
    if (!done && p) playModel(p.audio, p.word, voice);   // 카드가 바뀌면 발음 자동재생(선생님 음원 우선)
  }, [i, done]);
  const finish = () => { if (!doneRef.current) { doneRef.current = true; onDone && onDone(); } setDone(true); };  // 마지막 카드까지 보면 '완료' 기록
  const move = (d) => { setFlip(false); setI(x => Math.max(0, Math.min(order.length - 1, x + d))); };
  if (done) return <>
    <div className="card" style={{ textAlign:"center", padding:24, background:"var(--green-bg,#E7F1EA)", borderColor:"var(--green-line,#BFE0CC)" }}>
      <div style={{ fontSize:44, lineHeight:1 }}>🎉</div>
      <div style={{ fontSize:20, fontWeight:800, color:"var(--good,#2E7D5B)", marginTop:6 }}>{label ? label + " 완료!" : "완료!"}</div>
      <div style={{ fontSize:12, color:"var(--navy-soft)", marginTop:6 }}>{title}</div>
      <div className="muted" style={{ marginTop:8 }}>{order.length}개 카드를 모두 봤어요</div>
    </div>
    <button className="btn full" style={{ marginTop:14 }} onClick={onBack}>모드 선택으로</button>
  </>;
  const last = i === order.length - 1;
  return <>
    <button onClick={onBack} style={{ background:"none", color:"var(--navy)", fontWeight:700, marginBottom:10 }}>‹ 모드 선택</button>
    <div className="muted" style={{ marginBottom:8 }}>{title} · {i+1}/{order.length}</div>
    <button onClick={()=>setFlip(f=>!f)} className="card"
      style={{ width:"100%", minHeight:180, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:10 }}>
      <div style={{ fontSize:26, fontWeight:800, color:"var(--navy)" }}>{flip ? p.kor : p.word}</div>
      <div className="muted">{flip ? "영어 보기" : "뜻 보기"} (탭)</div>
    </button>
    <button className="btn-ghost" style={{ width:"100%", marginTop:8 }} onClick={()=>playModel(p.audio, p.word, voice)}>🔊 다시 듣기{p.audio ? " (선생님)" : ""}</button>
    <div className="row" style={{ gap:8, marginTop:8 }}>
      <button className="btn-ghost" style={{ flex:1 }} onClick={()=>move(-1)} disabled={i===0}>이전</button>
      {last
        ? <button className="btn" style={{ flex:1 }} onClick={finish}>완료</button>
        : <button className="btn" style={{ flex:1 }} onClick={()=>move(1)}>다음</button>}
    </div>
  </>;
}

function ChoiceQuiz({ pairs, title, onBack, onDone, limit, label }) {
  const [qs] = useState(() => shuffleArr(pairs).slice(0, limit || pairs.length).map(q => {
    const others = shuffleArr(pairs.filter(p => p !== q)).slice(0, 3).map(p => p.kor);
    return { ...q, options: shuffleArr([q.kor, ...others]) };
  }));
  const [i, setI] = useState(0);
  const [score, setScore] = useState(0);
  const [picked, setPicked] = useState(null);
  const [wrong, setWrong] = useState([]);
  const [phase, setPhase] = useState("q");
  const q = qs[i];

  const choose = (opt) => {
    if (picked != null) return;
    setPicked(opt);
    const ok = opt === q.kor;
    const ns = score + (ok ? 1 : 0);
    if (!ok) setWrong(w => [...w, q]);
    setTimeout(() => {
      setScore(ns);
      if (i + 1 >= qs.length) { setPhase("result"); onDone(ns, qs.length); }
      else { setI(i + 1); setPicked(null); }
    }, 620);
  };

  if (phase === "result") return <QuizResult title={title} label={label} score={score} total={qs.length} wrong={wrong} onBack={onBack} />;

  return <>
    <button onClick={onBack} style={{ background:"none", color:"var(--navy)", fontWeight:700, marginBottom:10 }}>‹ 모드 선택</button>
    <div className="muted" style={{ marginBottom:8 }}>{title} · {i+1}/{qs.length} · 맞음 {score}</div>
    <div className="card" style={{ padding:22, textAlign:"center" }}>
      <div style={{ fontSize:24, fontWeight:800, color:"var(--navy)" }}>{q.word}</div>
    </div>
    <div style={{ marginTop:10, display:"grid", gap:8 }}>
      {q.options.map((opt, k) => {
        let bg = "#fff", col = "var(--navy)", bd = "var(--line)";
        if (picked != null) {
          if (opt === q.kor) { bg = "#E3F1E9"; col = "#2E7D5B"; bd = "#8FC7AA"; }
          else if (opt === picked) { bg = "#F6E1DC"; col = "var(--danger)"; bd = "#E8C4BC"; }
        }
        return <button key={k} onClick={()=>choose(opt)} disabled={picked != null}
          style={{ textAlign:"left", padding:"12px 14px", borderRadius:10, border:`1px solid ${bd}`, background:bg, color:col, fontSize:15, fontWeight:600 }}>{opt}</button>;
      })}
    </div>
  </>;
}

function SpellQuiz({ pairs, title, onBack, onDone, label }) {
  const [qs] = useState(() => shuffleArr(pairs));
  const [i, setI] = useState(0);
  const [val, setVal] = useState("");
  const [score, setScore] = useState(0);
  const [checked, setChecked] = useState(null); // null | "ok" | "no"
  const [wrong, setWrong] = useState([]);
  const [phase, setPhase] = useState("q");
  const q = qs[i];
  const norm = (s) => (s || "").trim().toLowerCase();

  const check = () => {
    if (checked != null) return;
    const ok = norm(val) === norm(q.word) && norm(val) !== "";
    setChecked(ok ? "ok" : "no");
    if (!ok) setWrong(w => [...w, q]);
    const ns = score + (ok ? 1 : 0);
    setTimeout(() => {
      setScore(ns);
      if (i + 1 >= qs.length) { setPhase("result"); onDone(ns, qs.length); }
      else { setI(i + 1); setVal(""); setChecked(null); }
    }, 850);
  };

  if (phase === "result") return <QuizResult title={title} label={label} score={score} total={qs.length} wrong={wrong} onBack={onBack} />;

  return <>
    <button onClick={onBack} style={{ background:"none", color:"var(--navy)", fontWeight:700, marginBottom:10 }}>‹ 모드 선택</button>
    <div className="muted" style={{ marginBottom:8 }}>{title} · {i+1}/{qs.length} · 맞음 {score}</div>
    <div className="card" style={{ padding:22, textAlign:"center" }}>
      <div style={{ fontSize:20, fontWeight:800, color:"var(--navy)" }}>{q.kor}</div>
      <div className="muted" style={{ marginTop:4 }}>영어로 쓰기</div>
    </div>
    <input className="field" value={val} onChange={e=>setVal(e.target.value)}
      onKeyDown={e=>{ if (e.key === "Enter") check(); }} placeholder="정답 입력" disabled={checked != null}
      style={{ marginTop:10, borderColor: checked==="ok" ? "#8FC7AA" : checked==="no" ? "#E8C4BC" : undefined }} />
    {checked === "no" && <div style={{ marginTop:6, color:"var(--danger)", fontSize:13 }}>정답: <b>{q.word}</b></div>}
    <button className="btn full" style={{ marginTop:10 }} onClick={check} disabled={checked != null}>확인</button>
  </>;
}

function QuizResult({ title, score, total, wrong, onBack, label }) {
  const pct = total ? Math.round(score * 100 / total) : 0;
  return <>
    <div className="card" style={{ textAlign:"center", padding:24, background:"var(--green-bg,#E7F1EA)", borderColor:"var(--green-line,#BFE0CC)" }}>
      <div style={{ fontSize:44, lineHeight:1 }}>🎉</div>
      <div style={{ fontSize:20, fontWeight:800, color:"var(--good,#2E7D5B)", marginTop:6 }}>{label ? label + " 완료!" : "완료!"}</div>
      <div style={{ fontSize:12, color:"var(--navy-soft)", marginTop:6 }}>{title}</div>
      <div style={{ fontSize:40, fontWeight:800, color:"var(--navy)", marginTop:6 }}>{pct}점</div>
      <div className="muted" style={{ marginTop:2 }}>{total}문제 중 {score}개 정답</div>
    </div>
    {wrong.length > 0 && <>
      <div style={{ fontWeight:700, color:"var(--navy)", margin:"14px 4px 8px", fontSize:14 }}>틀린 단어 {wrong.length}개</div>
      {wrong.map((p, k) => (
        <div key={k} className="card" style={{ display:"flex", justifyContent:"space-between", padding:"10px 14px" }}>
          <b style={{ color:"var(--navy)" }}>{p.word}</b><span className="muted">{p.kor}</span>
        </div>
      ))}
    </>}
    <button className="btn full" style={{ marginTop:14 }} onClick={onBack}>모드 선택으로</button>
  </>;
}

// ---------- 권말 진급 시험 (온라인 자동채점 + 성적표) ----------

function ExamPlay({ assignment, student, onClose }) {
  // 목록 응답엔 시험 문제은행이 빠져 있으니(로그인 경량화), 응시할 때만 전체를 받아온다.
  const [full, setFull] = useState((assignment.items && assignment.items.length) ? assignment : null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (full) return;
    apiGet(`/assignment/${assignment.id}`).then(setFull).catch(() => setErr("시험을 불러오지 못했어요. 다시 시도해 주세요."));
  }, []);
  if (err) return <div className="card">{err}<button className="btn full" style={{ marginTop: 12 }} onClick={onClose}>돌아가기</button></div>;
  if (!full) return <div className="card" style={{ textAlign: "center", padding: 30 }}><div className="muted">시험 불러오는 중…</div></div>;
  return <ExamQuiz assignment={full} student={student} onClose={onClose} />;
}

function ExamQuiz({ assignment, student, onClose }) {
  const a = assignment;
  const pool = (a.items || []).map((w, i) => ({
    en: String(w || ""), ko: String((a.meanings && a.meanings[i]) || ""),
    ex: String((a.examples && a.examples[i]) || ""), exKo: String((a.exampleKo && a.exampleKo[i]) || "")
  })).filter(p => p.en && p.ko);
  const pass = a.passScore || 70;
  const NQ = Math.min(40, pool.length);
  /* ★저학년은 타이핑 대신 **알파벳 타일**을 눌러 철자를 세운다(원장 요청 2026-09-08).
     초2·초3에게 영어 자판은 문제가 아니라 장벽이다 — 철자를 아는지 묻는 자리에서
     자판을 못 찾아 틀리면 무엇을 잰 것인지 알 수 없다.
       초2(LV2) : 그 낱말의 글자만큼만 준다(5). 차례를 아는지 묻는다.
       초3(LV3) : 딴 글자 2개를 섞는다(7). 어떤 글자가 드는지도 알아야 한다.
       초4(LV4) : 딴 글자 4개(9). 타일에서 자판으로 곧장 건너뛰면 계단이 너무 급하다.
       LV5 이상 : 자판으로 친다.
     과제에 spellMode·spellDecoys 가 있으면 그대로 따르고, 없으면 책 이름의 LV로 어림잡는다. */
  const lvNo = (() => { const m = String(a.book || "").match(/LV\s*(\d+)/i); return m ? +m[1] : null; })();
  const tileMode = a.spellMode === "tiles" || (a.spellMode == null && lvNo != null && lvNo <= 4);
  const nDecoy = (typeof a.spellDecoys === "number") ? a.spellDecoys
               : (lvNo === 3 ? 2 : lvNo === 4 ? 4 : 0);
  const ALPHA = "abcdefghijklmnopqrstuvwxyz".split("");
  const tilesOf = (en) => {
    const have = new Set(en.toLowerCase().split(""));
    const decoy = shuffleArr(ALPHA.filter(c => !have.has(c))).slice(0, Math.max(0, nDecoy));
    return shuffleArr(en.split("").concat(decoy));   /* 딴 글자는 그 낱말에 없는 것만 — 헷갈리라고 넣는 게 아니다 */
  };
  const norm = s => String(s || "").trim().toLowerCase().replace(/\s+/g, " ");
  const cloze = (ex, en) => {
    if (!ex) return null;
    const re = new RegExp("\\b" + en.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i");
    if (!re.test(ex)) return null;
    return ex.replace(re, "______");
  };
  const [qs] = useState(() => {
    const sh = shuffleArr(pool).slice(0, NQ);
    const types = ["choice", "write", "clozeChoice", "clozeWrite"];
    return sh.map((p, idx) => {
      let t = types[idx % 4];
      const cz = cloze(p.ex, p.en);
      if ((t === "clozeChoice" || t === "clozeWrite") && !cz) t = (idx % 2 ? "write" : "choice");
      if (t === "choice") {
        const opts = shuffleArr([p.ko, ...shuffleArr(pool.filter(x => x.ko !== p.ko)).slice(0, 3).map(x => x.ko)]);
        return { type: "choice", prompt: p.en, answer: p.ko, options: opts, p };
      }
      if (t === "write") return { type: "write", prompt: p.ko, answer: p.en, tiles: tilesOf(p.en), p };
      if (t === "clozeChoice") {
        const opts = shuffleArr([p.en, ...shuffleArr(pool.filter(x => x.en !== p.en)).slice(0, 3).map(x => x.en)]);
        return { type: "clozeChoice", prompt: cz, sub: p.exKo, answer: p.en, options: opts, p };
      }
      return { type: "clozeWrite", prompt: cz, sub: p.exKo, answer: p.en, tiles: tilesOf(p.en), p };
    });
  });
  const t0 = useRef(Date.now());
  const [i, setI] = useState(0);
  const [val, setVal] = useState("");
  const [picked, setPicked] = useState(null);
  const [correct, setCorrect] = useState(0);
  const [byType, setByType] = useState({ choice: [0, 0], write: [0, 0], clozeChoice: [0, 0], clozeWrite: [0, 0] });
  const [phase, setPhase] = useState("q");
  const [report, setReport] = useState(null);
  const [wrong, setWrong] = useState([]);
  const [used, setUsed] = useState([]);
  const q = qs[i];
  const isChoice = q && (q.type === "choice" || q.type === "clozeChoice");
  const useTiles = tileMode && q && !isChoice && (q.tiles || []).length > 0;
  const tapTile = (k) => {
    if (picked != null) return;
    const u = [...used, k]; setUsed(u); setVal(u.map(j => q.tiles[j]).join(""));
  };
  const undoTile = () => {
    if (picked != null) return;
    const u = used.slice(0, -1); setUsed(u); setVal(u.map(j => q.tiles[j]).join(""));
  };

  useEffect(() => { pingActivity(student.id, "test", a.title); }, []);

  const finish = async (nc, bt) => {
    setPhase("submitting");
    const seconds = Math.round((Date.now() - t0.current) / 1000);
    const byTypeScore = {};
    Object.keys(bt).forEach(k => { byTypeScore[k] = bt[k][1] ? Math.round(bt[k][0] * 100 / bt[k][1]) : null; });
    try {
      await apiPost(`/exam/${a.id}/${student.id}`, { correct: nc, total: qs.length, seconds, byType: byTypeScore });
      const rep = await apiGet(`/exam-report/${a.id}/${student.id}`);
      setReport(rep);
    } catch (e) { setReport({ score: Math.round(nc * 100 / qs.length), error: true }); }
    setPhase("done");
  };
  const advance = (ok) => {
    const bt = { ...byType }; bt[q.type] = [bt[q.type][0] + (ok ? 1 : 0), bt[q.type][1] + 1]; setByType(bt);
    const nc = correct + (ok ? 1 : 0); setCorrect(nc);
    if (!ok) setWrong(w => [...w, q]);
    setTimeout(() => {
      if (i + 1 >= qs.length) finish(nc, bt);
      else { setI(i + 1); setVal(""); setPicked(null); setUsed([]); }
    }, isChoice ? 480 : 260);
  };
  const choose = (opt) => { if (picked != null) return; setPicked(opt); advance(opt === q.answer); };
  const submitWrite = () => { if (picked != null) return; const ok = norm(val) === norm(q.answer) && norm(val) !== ""; setPicked(ok ? "ok" : "no"); advance(ok); };

  if (pool.length < 4) return <div className="card">시험 문항이 부족해요. 선생님께 문의해 주세요.<button className="btn full" style={{ marginTop: 12 }} onClick={onClose}>돌아가기</button></div>;
  if (phase === "submitting") return <div className="card" style={{ textAlign: "center", padding: 30 }}><div className="muted">채점 중…</div></div>;
  if (phase === "done") return <ExamReport report={report} title={a.title} pass={pass} wrong={wrong} onClose={onClose} />;

  const typeLabel = { choice: "뜻 고르기", write: "단어 쓰기", clozeChoice: "예문 빈칸 고르기", clozeWrite: "예문 빈칸 쓰기" }[q.type];
  const isCloze = q.type === "clozeChoice" || q.type === "clozeWrite";
  return <>
    <div className="muted" style={{ marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
      <span>{i + 1}/{qs.length} · {typeLabel}</span><span>맞음 {correct}</span>
    </div>
    <div style={{ height: 6, borderRadius: 4, background: "var(--line,#e5e2d8)", marginBottom: 12, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${Math.round(i / qs.length * 100)}%`, background: "var(--gold)" }} />
    </div>
    <div className="card" style={{ padding: 20, textAlign: "center" }}>
      <div style={{ fontSize: isCloze ? 17 : 23, fontWeight: 800, color: "var(--navy)", lineHeight: 1.5 }}>{q.prompt}</div>
      {q.sub && <div className="muted" style={{ marginTop: 6, fontSize: 13 }}>{q.sub}</div>}
      {q.type === "write" && <div className="muted" style={{ marginTop: 6 }}>영어로 쓰기</div>}
    </div>
    {isChoice ? (
      <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
        {q.options.map((opt, k) => {
          let bg = "#fff", col = "var(--navy)", bd = "var(--line)";
          if (picked != null) { if (opt === q.answer) { bg = "#E3F1E9"; col = "#2E7D5B"; bd = "#8FC7AA"; } else if (opt === picked) { bg = "#F6E1DC"; col = "var(--danger)"; bd = "#E8C4BC"; } }
          return <button key={k} onClick={() => choose(opt)} disabled={picked != null}
            style={{ textAlign: "left", padding: "12px 14px", borderRadius: 10, border: `1px solid ${bd}`, background: bg, color: col, fontSize: 15, fontWeight: 600 }}>{opt}</button>;
        })}
      </div>
    ) : (
      <>
        {useTiles ? (
          <>
            {/* 세운 철자 — 빈 칸이 몇 개 남았는지 눈에 보이게 한다 */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12, minHeight: 44 }}>
              {q.answer.split("").map((_, k) => (
                <span key={k} style={{
                  width: 34, height: 42, display: "flex", alignItems: "center", justifyContent: "center",
                  borderBottom: `2px solid ${picked === "ok" ? "#8FC7AA" : picked === "no" ? "#E8C4BC" : "var(--line, #ddd)"}`,
                  fontSize: 22, fontWeight: 700, fontFamily: "Georgia, serif"
                }}>{val[k] || ""}</span>))}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 14 }}>
              {q.tiles.map((c, k) => (
                <button key={k} onClick={() => tapTile(k)} disabled={picked != null || used.includes(k)}
                  style={{
                    width: 42, height: 46, borderRadius: 10, fontSize: 20, fontWeight: 700,
                    fontFamily: "Georgia, serif",
                    border: "1px solid var(--line, #ddd)",
                    background: used.includes(k) ? "transparent" : "#fff",
                    color: used.includes(k) ? "transparent" : "inherit"
                  }}>{c}</button>))}
            </div>
            {picked === "no" && <div style={{ marginTop: 8, color: "var(--danger)", fontSize: 13 }}>정답: <b>{q.answer}</b></div>}
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button className="btn" style={{ flex: "0 0 96px" }} onClick={undoTile}
                disabled={picked != null || !used.length}>← 지우기</button>
              <button className="btn" style={{ flex: 1 }} onClick={submitWrite}
                disabled={picked != null || !val}>확인</button>
            </div>
          </>
        ) : (
          <>
            <input className="field" value={val} onChange={e => setVal(e.target.value)} autoFocus
              onKeyDown={e => { if (e.key === "Enter") submitWrite(); }} placeholder="영어 단어 입력" disabled={picked != null}
              style={{ marginTop: 10, borderColor: picked === "ok" ? "#8FC7AA" : picked === "no" ? "#E8C4BC" : undefined }} />
            {picked === "no" && <div style={{ marginTop: 6, color: "var(--danger)", fontSize: 13 }}>정답: <b>{q.answer}</b></div>}
            <button className="btn full" style={{ marginTop: 10 }} onClick={submitWrite} disabled={picked != null}>확인</button>
          </>
        )}
      </>
    )}
  </>;
}

function ExamReport({ report, title, pass, wrong, onClose }) {
  const r = report;
  if (!r) return <div className="card">결과를 불러오지 못했어요.<button className="btn full" style={{ marginTop: 12 }} onClick={onClose}>돌아가기</button></div>;
  const passed = r.pass != null ? r.pass : (r.score >= pass);
  const metric = (label, obj, isTime) => {
    if (!obj || obj.top == null) return (
      <div className="card" style={{ padding: 14 }}>
        <div className="muted" style={{ fontSize: 11, fontWeight: 700 }}>{label}</div>
        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--navy-soft)", marginTop: 6 }}>표본 부족</div>
      </div>);
    return (
      <div className="card" style={{ padding: 14 }}>
        <div className="muted" style={{ fontSize: 11, fontWeight: 700 }}>{label}</div>
        <div style={{ fontSize: 22, fontWeight: 800, color: "var(--navy)", marginTop: 2 }}>상위 {obj.top}%</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{obj.n}명 중 · 평균 {isTime ? (obj.avgText || "-") : (obj.avg + "점")}</div>
      </div>);
  };
  return <>
    <div className="card" style={{ textAlign: "center", padding: 22, background: passed ? "var(--green-bg,#E7F1EA)" : "#FBECEB", borderColor: passed ? "#BFE0CC" : "#E8C4BC" }}>
      <div style={{ fontSize: 13, color: "var(--navy-soft)", fontWeight: 700 }}>{title} · 권말 진급 시험</div>
      <div style={{ fontSize: 46, fontWeight: 800, color: "var(--navy)", marginTop: 4 }}>{r.score}<span style={{ fontSize: 18, color: "var(--navy-soft)" }}>점</span></div>
      <div style={{ marginTop: 6 }}>
        <span style={{ display: "inline-block", padding: "4px 14px", borderRadius: 999, fontWeight: 800, fontSize: 14, background: passed ? "var(--good,#2E7D5B)" : "var(--danger)", color: "#fff" }}>{passed ? "진급 통과 🎉" : "재응시 권장"}</span>
      </div>
      {(r.secondsText || r.band) && <div className="muted" style={{ marginTop: 8, fontSize: 13 }}>{r.secondsText ? `소요 시간 ${r.secondsText}` : ""}{r.band ? ` · ${r.band}등급` : ""}</div>}
    </div>
    {!r.error && <>
      <div style={{ fontWeight: 700, color: "var(--navy)", margin: "14px 4px 8px", fontSize: 14 }}>📊 내 위치 · 점수</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {metric("전체(전 학년)", r.score_all, false)}
        {metric("같은 학년" + (r.grade ? ` (${r.grade})` : ""), r.score_grade, false)}
      </div>
      <div style={{ fontWeight: 700, color: "var(--navy)", margin: "14px 4px 8px", fontSize: 14 }}>⏱️ 내 위치 · 시간 (빠를수록 상위)</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {metric("전체(전 학년)", r.time_all, true)}
        {metric("같은 학년" + (r.grade ? ` (${r.grade})` : ""), r.time_grade, true)}
      </div>
    </>}
    {wrong && wrong.length > 0 && <>
      <div style={{ fontWeight: 700, color: "var(--navy)", margin: "14px 4px 8px", fontSize: 14 }}>틀린 단어 {wrong.length}개</div>
      {wrong.slice(0, 40).map((q, k) => (
        <div key={k} className="card" style={{ display: "flex", justifyContent: "space-between", padding: "9px 13px" }}>
          <b style={{ color: "var(--navy)" }}>{q.p.en}</b><span className="muted">{q.p.ko}</span>
        </div>
      ))}
    </>}
    <button className="btn full" style={{ marginTop: 14 }} onClick={onClose}>완료</button>
  </>;
}

// ---------- Admin: 학습 현황 (실시간 현황판 + 학생별 자습 점수) ----------

function makeBattleMusic() {
  let ctx = null, timer = null, muted = false, step = 0;
  const seq = [0,7,12,7,4,7,12,16,14,12,7,4,5,9,12,7];
  const base = 261.63;
  const freq = (n) => base * Math.pow(2, n / 12);
  const tick = () => {
    if (!ctx || muted) { step++; return; }
    const t = ctx.currentTime;
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "triangle"; o.frequency.value = freq(seq[step % seq.length]);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.13, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.19);
    o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + 0.2);
    if (step % 4 === 0) {
      const b = ctx.createOscillator(), bg = ctx.createGain();
      b.type = "sine"; b.frequency.value = freq(seq[step % seq.length] - 24);
      bg.gain.setValueAtTime(0.0001, t);
      bg.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      bg.gain.exponentialRampToValueAtTime(0.0001, t + 0.34);
      b.connect(bg).connect(ctx.destination); b.start(t); b.stop(t + 0.36);
    }
    step++;
  };
  return {
    start() { if (ctx) return; try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; } step = 0; timer = setInterval(tick, 175); },
    stop() { if (timer) clearInterval(timer); timer = null; if (ctx) { try { ctx.close(); } catch (e) {} ctx = null; } },
    toggle() { muted = !muted; return muted; },
  };
}

function BattlePlayer({ initialCode, onExit }) {
  const [code, setCode] = useState((initialCode || "").toUpperCase());
  const [name, setName] = useState("");
  const [phase, setPhase] = useState("join");   // join|connecting|lobby|question|answered|reveal|end|closed
  const [err, setErr] = useState("");
  const [q, setQ] = useState(null);
  const [picked, setPicked] = useState(null);
  const [result, setResult] = useState(null);
  const [reveal, setReveal] = useState(null);
  const [board, setBoard] = useState([]);
  const [score, setScore] = useState(0);
  const [tleft, setTleft] = useState(0);
  const [muted, setMuted] = useState(false);
  const wsRef = useRef(null);
  const musicRef = useRef(null);

  useEffect(() => () => {
    if (wsRef.current) { try { wsRef.current.close(); } catch (e) {} }
    if (musicRef.current) musicRef.current.stop();
  }, []);

  useEffect(() => {
    if (phase !== "question" || tleft <= 0) return;
    const t = setTimeout(() => setTleft(x => x - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, tleft]);

  const handle = (m) => {
    if (m.type === "error") { setErr(m.msg); setPhase("join"); }
    else if (m.type === "joined") { setPhase("lobby"); if (musicRef.current) musicRef.current.start(); }
    else if (m.type === "starting") { setPhase("lobby"); }
    else if (m.type === "question") { setQ(m); setPicked(null); setResult(null); setTleft(m.duration); setPhase("question"); }
    else if (m.type === "answered") { setResult(m); setScore(m.score); setPhase("answered"); }
    else if (m.type === "reveal") { setReveal(m); setPhase("reveal"); }
    else if (m.type === "standings") { setBoard(m.board || []); setPhase("standings"); }
    else if (m.type === "end") { setBoard(m.board || []); setPhase("end"); if (musicRef.current) musicRef.current.stop(); }
  };

  const join = () => {
    const c = code.trim().toUpperCase(), nm = name.trim();
    if (c.length < 4 || !nm) { setErr("코드와 이름을 모두 입력해주세요."); return; }
    setErr(""); setPhase("connecting");
    if (!musicRef.current) musicRef.current = makeBattleMusic();
    let ws;
    try { ws = new WebSocket(wsUrl(c, "role=player&name=" + encodeURIComponent(nm))); }
    catch (e) { setErr("연결 실패"); setPhase("join"); return; }
    wsRef.current = ws;
    ws.onmessage = (ev) => { try { handle(JSON.parse(ev.data)); } catch (e) {} };
    ws.onerror = () => { setErr("연결에 실패했어요. 코드를 확인해주세요."); setPhase("join"); };
    ws.onclose = () => { setPhase(p => (p === "end" || p === "join") ? p : "closed"); };
  };

  const answer = (i) => {
    if (picked != null || phase !== "question") return;
    setPicked(i);
    try { wsRef.current.send(JSON.stringify({ type: "answer", choice: i })); } catch (e) {}
  };
  const toggleMute = () => { if (musicRef.current) setMuted(musicRef.current.toggle()); };

  if (phase === "join") {
    return <div className="wrap" style={{ display:"flex", alignItems:"center", justifyContent:"center", padding:20 }}>
      <div style={{ width:"100%", maxWidth:360 }}>
        <div style={{ textAlign:"center", marginBottom:24 }}>
          <div style={{ fontSize:30, fontWeight:800, color:"var(--navy)" }}>🎮 단어 배틀</div>
          <div className="muted" style={{ marginTop:6 }}>코드와 이름을 입력하고 참가해요</div>
        </div>
        <div className="card">
          <label className="label">접속 코드 (숫자 4자리)</label>
          <input className="field" value={code} onChange={e=>setCode(e.target.value.replace(/[^0-9]/g,"").slice(0,4))}
            inputMode="numeric" placeholder="예: 1234" style={{ letterSpacing:6, fontWeight:800, fontSize:20, textAlign:"center" }} />
          <div style={{ height:10 }} />
          <label className="label">내 이름</label>
          <input className="field" value={name} onChange={e=>setName(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&join()} placeholder="이름" />
          {err && <div className="err">{err}</div>}
          <div style={{ height:14 }} />
          <button className="btn full" onClick={join}>참가하기</button>
        </div>
        <button onClick={onExit} style={{ width:"100%", marginTop:12, background:"none", color:"var(--navy-soft)", fontSize:13 }}>‹ 처음으로</button>
      </div>
    </div>;
  }
  if (phase === "connecting") return <div className="center"><div className="spin" /></div>;
  if (phase === "closed") {
    return <div className="wrap"><div className="body" style={{ textAlign:"center", paddingTop:60 }}>
      <div style={{ fontSize:22, fontWeight:800, color:"var(--navy)", marginBottom:8 }}>배틀이 종료됐어요</div>
      <div className="muted" style={{ marginBottom:20 }}>연결이 끊겼거나 배틀이 끝났어요.</div>
      <button className="btn" onClick={onExit}>처음으로</button>
    </div></div>;
  }

  const myRank = board.findIndex(b => b.name === name);
  const musicBtn = <button onClick={toggleMute} style={{ position:"absolute", top:14, right:14, background:"rgba(255,255,255,.25)", color:"#fff", borderRadius:20, padding:"6px 12px", fontSize:13, fontWeight:700 }}>{muted ? "🔇" : "🔊"}</button>;
  const wrapStyle = { minHeight:"100vh", background:"linear-gradient(160deg,#1B2E4C,#3C5075)", color:"#fff", padding:20, position:"relative" };

  if (phase === "lobby") {
    return <div style={wrapStyle}>{musicBtn}
      <div style={{ textAlign:"center", paddingTop:80 }}>
        <div style={{ fontSize:20, fontWeight:700, marginBottom:10 }}>🎈 {name}님, 준비 완료!</div>
        <div style={{ opacity:.85 }}>선생님이 시작하면 바로 문제가 나와요.</div>
        <div className="spin" style={{ marginTop:24, borderTopColor:"#fff" }} />
      </div>
    </div>;
  }
  if (phase === "question") {
    return <div style={wrapStyle}>{musicBtn}
      <div style={{ textAlign:"center", marginTop:36 }}>
        <div style={{ opacity:.8, fontSize:13 }}>{q.index + 1} / {q.total} · 남은 시간 {tleft}s</div>
        <div style={{ height:6, background:"rgba(255,255,255,.2)", borderRadius:4, margin:"8px 0 20px" }}>
          <div style={{ height:"100%", width:`${Math.max(0, tleft / q.duration * 100)}%`, background:"#F4A259", borderRadius:4, transition:"width 1s linear" }} />
        </div>
        <div style={{ fontSize:22, fontWeight:800, lineHeight:1.4, minHeight:70, padding:"0 6px" }}>{q.prompt}</div>
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10, marginTop:24 }}>
        {q.options.map((opt, i) => (
          <button key={i} onClick={()=>answer(i)} disabled={picked != null}
            style={{ background: BATTLE_OPT[i].c, color:"#fff", borderRadius:14, padding:"18px 10px", fontWeight:800,
              opacity: picked != null && picked !== i ? 0.5 : 1, minHeight:96, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:6 }}>
            <div style={{ fontSize:18, opacity:.85 }}>{BATTLE_OPT[i].s}</div>
            <div style={{ fontSize:24, lineHeight:1.25 }}>{opt}</div>
          </button>
        ))}
      </div>
      {picked != null && <div style={{ textAlign:"center", marginTop:18, fontSize:15, opacity:.9 }}>답을 제출했어요! 결과를 기다려요…</div>}
    </div>;
  }
  if (phase === "answered") {
    return <div style={{ ...wrapStyle, display:"flex", alignItems:"center", justifyContent:"center", textAlign:"center" }}>{musicBtn}
      <div>
        <div style={{ fontSize:64 }}>{result.correct ? "🎉" : "😅"}</div>
        <div style={{ fontSize:26, fontWeight:800, marginTop:8 }}>{result.correct ? "정답!" : "아쉬워요"}</div>
        <div style={{ marginTop:8, opacity:.9 }}>내 점수 {result.score}점</div>
        <div style={{ marginTop:16, opacity:.7, fontSize:13 }}>다음 문제를 기다려요…</div>
      </div>
    </div>;
  }
  if (phase === "reveal") {
    return <div style={{ ...wrapStyle, display:"flex", alignItems:"center", justifyContent:"center", textAlign:"center" }}>{musicBtn}
      <div>
        <div style={{ opacity:.8, fontSize:14, marginBottom:8 }}>정답</div>
        <div style={{ fontSize:34, fontWeight:800, color:"#F4D06F" }}>{reveal.answer}</div>
      </div>
    </div>;
  }
  if (phase === "standings") {
    return <div style={wrapStyle}>{musicBtn}
      <div style={{ textAlign:"center", marginTop:34, fontSize:22, fontWeight:800 }}>🏅 중간 순위</div>
      <div style={{ maxWidth:360, margin:"18px auto 0" }}>
        {board.slice(0, 10).map((b, i) => (
          <div key={i} style={{ display:"flex", justifyContent:"space-between", padding:"10px 12px", borderRadius:10,
            background: b.name === name ? "rgba(244,162,89,.35)" : "rgba(255,255,255,.1)", marginBottom:6, fontWeight: b.name === name ? 800 : 500 }}>
            <span>{i + 1}. {b.name}</span><span>{b.score}점</span>
          </div>
        ))}
      </div>
    </div>;
  }
  // end
  return <div style={{ ...wrapStyle, textAlign:"center" }}>{musicBtn}
    <div style={{ fontSize:30, fontWeight:800, marginTop:40 }}>🏆 배틀 종료!</div>
    {myRank >= 0 && <div style={{ marginTop:8, fontSize:17 }}>{name}님 최종 {myRank + 1}등 · {board[myRank].score}점</div>}
    <div style={{ maxWidth:360, margin:"24px auto 0" }}>
      {board.slice(0, 10).map((b, i) => (
        <div key={i} style={{ display:"flex", justifyContent:"space-between", padding:"10px 14px", borderRadius:10,
          background: i === 0 ? "rgba(244,208,111,.4)" : b.name === name ? "rgba(244,162,89,.3)" : "rgba(255,255,255,.1)", marginBottom:6, fontWeight: i < 3 ? 800 : 500 }}>
          <span>{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : (i + 1) + "."} {b.name}</span><span>{b.score}점</span>
        </div>
      ))}
    </div>
    <button className="btn" style={{ marginTop:24, background:"#fff", color:"var(--navy)" }} onClick={onExit}>나가기</button>
  </div>;
}

// ---------- 학생 로그인 ----------
// 선생님 화면은 이제 /admin.html 로 따로 나갔다. 여기서는 학생만 받는다.
function Login({ onStudent, onBattle }) {
  const [sid, setSid] = useState(""); const [spw, setSpw] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);

  const go = async () => {
    setErr(""); setBusy(true);
    try {
      const r = await apiPost("/login/student", { id: sid, pw: spw });
      onStudent(r.student);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  return (
    <div className="wrap" style={{ display:"flex", alignItems:"center", justifyContent:"center", padding:20 }}>
      <div style={{ width:"100%", maxWidth:360 }}>
        <a href={STUDENT_PORTAL} style={{ display:"inline-block", marginBottom:14, color:"var(--navy-soft)", fontWeight:700, fontSize:13, textDecoration:"none" }}>‹ 학생 홈</a>
        <div style={{ textAlign:"center", marginBottom:28 }}>
          <div style={{ fontSize:32, fontWeight:800, color:"var(--navy)", letterSpacing:"-0.02em" }}>트리톡</div>
          <div className="muted" style={{ marginTop:6 }}>해피트리 낭독 · 단어 녹음</div>
        </div>
        <div className="card">
          <label className="label">아이디</label>
          <input className="field" value={sid} onChange={e=>setSid(e.target.value)} placeholder="아이디" />
          <div style={{height:10}} />
          <label className="label">비밀번호</label>
          <input className="field" type="password" value={spw} onChange={e=>setSpw(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&go()} placeholder="비밀번호" />
          {err && <div className="err">{err}</div>}
          <div style={{height:14}} />
          <button className="btn full" onClick={go} disabled={busy}>{busy ? "확인 중..." : "로그인"}</button>
        </div>
        <button onClick={onBattle}
          style={{ width:"100%", marginTop:12, padding:"12px", borderRadius:12, fontWeight:800, fontSize:15,
            color:"#fff", background:"linear-gradient(135deg,#9B5DE5,#F15BB5,#F4A259)" }}>
          🎮 단어 배틀 참가하기
        </button>
        <div style={{ textAlign:"center", marginTop:16 }}>
          <a href="/admin.html" className="muted" style={{ fontSize:13, textDecoration:"none" }}>선생님이신가요? →</a>
        </div>
      </div>
    </div>
  );
}

function App() {
  const params = new URLSearchParams(location.search);
  const battleParam = params.get("battle") || "";
  const autoSid = (params.get("sid") || "").trim();
  const [role, setRole] = useState(battleParam ? "battle" : (autoSid ? "autologin" : null));
  const [student, setStudent] = useState(null);

  // ★ 포털에서 넘어온 학생 아이디로 자동 로그인 (?sid=아이디, 아이디=비번). 실패하면 일반 로그인 화면.
  useEffect(() => {
    if (autoSid && role === "autologin") {
      const pw = params.get("spw") || autoSid;
      apiPost("/login/student", { id: autoSid, pw })
        .then(r => { setStudent(r.student); setRole("student"); })
        .catch(() => setRole(null));
    }
  }, []);

  if (role === "autologin") return <div style={{ minHeight: "70vh", display: "flex", alignItems: "center", justifyContent: "center", color: "#7a8a92", fontSize: 15 }}>로그인 중…</div>;
  if (role === "battle") return <BattlePlayer initialCode={battleParam} onExit={()=>setRole(null)} />;
  if (!role) return <Login onStudent={s=>{setStudent(s); setRole("student");}} onBattle={()=>setRole("battle")} />;
  return <StudentView student={student} onLogout={()=>{setRole(null); setStudent(null);}} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
