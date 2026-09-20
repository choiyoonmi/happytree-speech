# -*- coding: utf-8 -*-
"""index.html 을 학생용/관리자용으로 가른다.

왜: 아이가 트리톡을 열 때마다 관리자 화면 코드까지 받아서 브라우저가 Babel 로
    컴파일하고 있었다. 화면 코드 267KB 중 관리자 전용이 176KB(66%)였고,
    엑셀·PDF·html2canvas 라이브러리도 관리자만 쓰는데 학생이 같이 받았다.

만드는 것
  static/app.css      두 화면이 같이 쓰는 스타일
  static/common.js    공용 도우미·컴포넌트 (양쪽에서 불러 쓴다)
  static/student.js   학생 화면
  static/admin.js     관리자 화면
  static/index.html   학생 진입점 (무거운 라이브러리 없음)
  static/admin.html   관리자 진입점

원본 index.html 은 index.html.bak 으로 남긴다.
학생/관리자 코드가 서로를 참조하지 않는 것은 미리 확인했다(양방향 0건).
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
STATIC = HERE / "static"
SRC = STATIC / "index.html"

STUDENT = {
    "Recorder", "PushBell", "StudentView", "StudentHome", "SentenceStudy", "SentenceFlash",
    "Unscramble", "VocabSetStudy", "Flashcards", "ChoiceQuiz", "SpellQuiz", "QuizResult",
    "ExamPlay", "ExamQuiz", "ExamReport", "makeBattleMusic", "BattlePlayer",
}
ADMIN = {
    "SCHOOL_GRADES", "AdminStudents", "BulkUpload", "AdminAssignments", "AssignmentBrowser",
    "BookDetail", "AdminReview", "StudentReview", "SubmissionDetail", "LineChart",
    "AdminReport", "AdminSettings", "SectionLabel", "PeoplePanel", "HomePanel",
    "SettingsPanel", "AdminView", "ACT_COLS", "AdminDashboard", "BattleHost",
    # 교재 파싱 도우미 — 엑셀/PDF 업로드에서만 쓴다
    "splitMeaning", "SENT_ABBR", "reflowLines", "splitSentences", "splitSentenceMeaning",
    "sentencesOrLines", "parseItemList", "dropRunningHeaders", "joinPdfItems",
}
# Login·App 은 화면마다 다르므로 새로 쓴다
DROP = {"Login", "App", "__ENTRY__"}

ADMIN_LIBS = ("xlsx", "pdf.js", "html2canvas")


def parse():
    src = SRC.read_text(encoding="utf-8").splitlines()
    s0 = next(i for i, l in enumerate(src) if l.strip() == '<script type="text/babel">')
    s1 = next(i for i, l in enumerate(src) if i > s0 and l.strip() == "</script>")
    tops = []
    for i in range(s0 + 1, s1):
        m = (re.match(r"^(function|class) (\w+)", src[i])
             or re.match(r"^(const|let|var) (\w+)\s*=", src[i]))
        if m:
            tops.append((i, m.group(2)))
        elif re.match(r"^ReactDOM\.", src[i]):
            tops.append((i, "__ENTRY__"))
    ends = [tops[j + 1][0] for j in range(len(tops) - 1)] + [s1]
    blocks = {n: "\n".join(src[i:e]).rstrip() for (i, n), e in zip(tops, ends)}
    preamble = "\n".join(src[s0 + 1:tops[0][0]]).strip()
    head = "\n".join(src[:s0])          # <head> … <div id=root>
    tail = "\n".join(src[s1 + 1:])      # </body></html>
    return head, preamble, blocks, [n for _, n in tops], tail


def css_out(head: str):
    m = re.search(r"<style>([\s\S]*?)</style>", head)
    (STATIC / "app.css").write_text(m.group(1).strip() + "\n", encoding="utf-8")
    return head.replace(m.group(0), '<link rel="stylesheet" href="/app.css">')


def strip_libs(head: str) -> str:
    keep = []
    for line in head.splitlines():
        if line.strip().startswith("<script src=") and any(k in line for k in ADMIN_LIBS):
            continue
        keep.append(line)
    return "\n".join(keep)


STUDENT_LOGIN = '''
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
'''

ADMIN_LOGIN = '''
// ---------- 선생님 로그인 ----------
function Login({ onAdmin }) {
  const [apw, setApw] = useState(""); const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const go = async () => {
    setErr(""); setBusy(true);
    try {
      await apiPost("/login/admin", { pw: apw });
      setAdminKey(apw);   // 이후 관리자 API 호출에 열쇠로 쓴다
      onAdmin();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  return (
    <div className="wrap" style={{ display:"flex", alignItems:"center", justifyContent:"center", padding:20 }}>
      <div style={{ width:"100%", maxWidth:360 }}>
        <a href="/" style={{ display:"inline-block", marginBottom:14, color:"var(--navy-soft)", fontWeight:700, fontSize:13, textDecoration:"none" }}>‹ 학생 화면</a>
        <div style={{ textAlign:"center", marginBottom:28 }}>
          <div style={{ fontSize:32, fontWeight:800, color:"var(--navy)", letterSpacing:"-0.02em" }}>트리톡</div>
          <div className="muted" style={{ marginTop:6 }}>선생님 화면</div>
        </div>
        <div className="card">
          <label className="label">관리자 비밀번호</label>
          <input className="field" type="password" value={apw} onChange={e=>setApw(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&go()} placeholder="비밀번호" autoFocus />
          {err && <div className="err">{err}</div>}
          <div style={{height:14}} />
          <button className="btn full" onClick={go} disabled={busy}>{busy ? "확인 중..." : "로그인"}</button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [ok, setOk] = useState(false);
  if (!ok) return <Login onAdmin={()=>setOk(true)} />;
  return <AdminView onLogout={()=>{ setAdminKey(""); setOk(false); }} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
'''

PAGE = '''{head}
<script type="text/babel" src="/common.js"></script>
<script type="text/babel" src="/{main}"></script>
{tail}'''


def main():
    head, preamble, blocks, order, tail = parse()
    if not SRC.with_suffix(".html.bak").exists():
        shutil.copy2(SRC, SRC.with_suffix(".html.bak"))

    head = css_out(head)
    common_names = [n for n in order if n not in STUDENT | ADMIN | DROP]

    # 공용 — preamble 의 pdfjsLib 설정은 관리자 것이라 뺀다
    pre = "\n".join(l for l in preamble.splitlines() if "pdfjsLib" not in l).strip()
    common = ["// 자동 생성 — tools/split_admin.py. 학생·선생님 화면이 같이 쓴다.", pre]
    common += [blocks[n] for n in common_names]
    (STATIC / "common.js").write_text("\n\n".join(common) + "\n", encoding="utf-8")

    stu = ["// 자동 생성 — tools/split_admin.py. 학생 화면."]
    stu += [blocks[n] for n in order if n in STUDENT]
    stu.append(STUDENT_LOGIN.strip())
    (STATIC / "student.js").write_text("\n\n".join(stu) + "\n", encoding="utf-8")

    adm = ["// 자동 생성 — tools/split_admin.py. 선생님 화면.",
           'pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";']
    adm += [blocks[n] for n in order if n in ADMIN]
    adm.append(ADMIN_LOGIN.strip())
    (STATIC / "admin.js").write_text("\n\n".join(adm) + "\n", encoding="utf-8")

    SRC.write_text(PAGE.format(head=strip_libs(head), main="student.js", tail=tail),
                   encoding="utf-8")
    (STATIC / "admin.html").write_text(
        PAGE.format(head=head.replace("<title>트리톡 · 해피트리 낭독</title>",
                                      "<title>트리톡 · 선생님</title>"),
                    main="admin.js", tail=tail), encoding="utf-8")

    print("만든 파일")
    for f in ("app.css", "common.js", "student.js", "admin.js", "index.html", "admin.html"):
        p = STATIC / f
        print(f"  {f:<14}{p.stat().st_size/1024:>8.0f} KB")
    print(f"\n공용 {len(common_names)}개 / 학생 {len([n for n in order if n in STUDENT])}개 "
          f"/ 관리자 {len([n for n in order if n in ADMIN])}개")


if __name__ == "__main__":
    sys.exit(main())
