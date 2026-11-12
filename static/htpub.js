/* ★학부모 포털로 성적표 내보내기(htpub, 2026-11-12) — 트리톡(낭독·단어) 선생님 화면 admin.html
   관리자(admin.happytreeacademy.com)가 이 화면을 보이지 않는 iframe(admin.html?htpub=1)으로 열고
   window.name 에 HT_TEACHER_SSO(이름·개인번호)를 실어 준다. 여기서 그 번호로 선생님 로그인(/api/login/teacher)을 하고,
   학생·달마다 {htpub:'render'} 를 받으면 선생님 「📊 성적표」와 같은 ReportSheet(admin.js)로 그 달 성적표를 그려
   정적 HTML+CSS 로 돌려준다. 서버에는 아무것도 쓰지 않는다(읽기: /api/students, /api/report 만).
   유치부는 점수·평균·그래프·약한 단어를 뺀다(학원법 유아 평가 금지). */
(function(){
  var qs = location.search || '';
  if(!/[?&]htpub=1(&|$)/.test(qs) || window.parent === window) return;
  var ADMIN = 'https://admin.happytreeacademy.com';
  var KIND = 'talk';
  var TITLE = '트리톡 영어 성적표';
  function originOk(o){ o = String(o || ''); return o === ADMIN || o.indexOf('http://localhost:') === 0 || o.indexOf('http://127.0.0.1:') === 0; }

  /* SSO 는 읽자마자 지운다(주소에도 안 실린다) */
  var sso = null;
  try{
    var raw = String(window.name || ''); window.name = '';
    if(raw.indexOf('HT_TEACHER_SSO:') === 0){
      var d0 = JSON.parse(decodeURIComponent(escape(atob(raw.slice(15)))));
      if(d0 && d0.name && d0.pw && +d0.exp >= Date.now()) sso = {name:String(d0.name), pw:String(d0.pw)};
    }
  }catch(e){ sso = null; }

  /* 숨은 iframe 이라 창이 뜨면 안 된다 */
  try{ window.alert = function(){}; window.confirm = function(){ return false; }; window.print = function(){}; }catch(e){}

  var state = 'wait', failMsg = '', queue = [], TOKEN = '', STUDENTS = [];
  function post(msg, origin){ try{ window.parent.postMessage(msg, origin || ADMIN); }catch(e){} }
  function readyMsg(){ return state === 'ok' ? {htpub:'ready', kind:KIND} : {htpub:'ready', kind:KIND, ok:false, msg:failMsg}; }
  function parentOrigin(){ try{ var a = document.referrer ? new URL(document.referrer).origin : ''; return originOk(a) ? a : ADMIN; }catch(e){ return ADMIN; } }
  function announce(){ var o = parentOrigin(); post(readyMsg(), o); if(o !== ADMIN) post(readyMsg(), ADMIN); }
  function flush(){ queue.splice(0).forEach(function(q){ handle(q.d, q.o); }); }
  function fail(m){ if(state !== 'wait') return; state = 'fail'; failMsg = m; announce(); flush(); }
  function succeed(){ if(state !== 'wait') return; state = 'ok'; announce(); flush(); }

  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function getJson(path){
    return fetch(path, {headers:{'x-ht-admin': TOKEN}}).then(function(r){
      if(!r.ok) return r.json().catch(function(){ return {}; }).then(function(j){ throw new Error(j.detail || ('HTTP ' + r.status)); });
      return r.json();
    });
  }

  /* ① 선생님 로그인 — 서버가 잠에서 깨는 중이면(502/503/네트워크) 몇 번 더 */
  function login(){
    if(!sso) return Promise.reject(new Error('선생님 로그인 안 됨(SSO 없음·만료)'));
    var tries = 0;
    function once(){
      return fetch('/api/login/teacher', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name: sso.name, tail: sso.pw})}).then(function(r){
        return r.json().catch(function(){ return {}; }).then(function(j){
          if(r.ok && j.ok && j.token){ TOKEN = j.token; sso = null; return; }
          if((r.status >= 500 || r.status === 0) && ++tries < 4) return sleep(2500 * tries).then(once);
          throw new Error('선생님 로그인 실패: ' + (j.detail || ('HTTP ' + r.status)));
        });
      }, function(err){ if(++tries < 4) return sleep(2500 * tries).then(once); throw new Error('서버 연결 실패'); });
    }
    return once();
  }
  /* ② 성적표 그리는 함수(admin.js — Babel 로 늦게 컴파일된다)가 생길 때까지 */
  function waitRenderer(){
    var t0 = Date.now();
    return new Promise(function(res, rej){
      (function tick(){
        if(typeof ReportSheet === 'function' && window.React && window.ReactDOM) return res();
        if(Date.now() - t0 > 60000) return rej(new Error('성적표 화면을 불러오지 못했어요'));
        setTimeout(tick, 200);
      })();
    });
  }
  function boot(){
    Promise.all([login(), waitRenderer()]).then(function(){
      return getJson('/api/students');
    }).then(function(rows){ STUDENTS = Array.isArray(rows) ? rows : []; succeed(); })
      .catch(function(e){ fail(String(e && e.message || e)); });
  }

  /* ③ 정적으로 만들기 */
  function abs(u){ try{ return new URL(u, location.href).href; }catch(e){ return u; } }
  function absCssUrls(t, base){
    return String(t || '').replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g, function(m, q, u){
      if(/^(data:|https?:|blob:|#)/i.test(u)) return m; try{ return 'url("' + new URL(u, base || location.href).href + '")'; }catch(e){ return m; } });
  }
  function staticize(box){
    Array.prototype.forEach.call(box.querySelectorAll('canvas'), function(c){
      try{ var img = document.createElement('img'); img.src = c.toDataURL('image/png'); img.style.cssText = c.style.cssText; img.width = c.width; img.height = c.height; c.parentNode.replaceChild(img, c); }catch(e){ c.remove(); }
    });
    Array.prototype.forEach.call(box.querySelectorAll('script,button,select,input,textarea,iframe,noscript,audio,video,.noprint,.no-htpub'), function(el){ el.remove(); });
    Array.prototype.forEach.call([box].concat(Array.prototype.slice.call(box.querySelectorAll('*'))), function(el){
      Array.prototype.slice.call(el.attributes).forEach(function(a){ if(/^on/i.test(a.name)) el.removeAttribute(a.name); });
      ['src', 'href', 'poster'].forEach(function(k){ var v = el.getAttribute(k); if(!v) return;
        if(/^javascript:/i.test(v)) el.removeAttribute(k); else if(!/^(data:|https?:|#)/i.test(v)) el.setAttribute(k, abs(v)); });
      var st = el.getAttribute('style'); if(st && /url\(/i.test(st)) el.setAttribute('style', absCssUrls(st));
    });
  }
  function allCss(){
    var out = [];
    Array.prototype.forEach.call(document.styleSheets, function(sh){
      var rules = null; try{ rules = sh.cssRules; }catch(e){ rules = null; }
      if(!rules){ if(sh.href) out.push('@import url("' + sh.href + '");'); return; }
      var base = sh.href || location.href;
      Array.prototype.forEach.call(rules, function(r){ out.push(absCssUrls(r.cssText, base)); });
    });
    return out;
  }

  function lastDay(ym){ var y = +ym.slice(0, 4), m = +ym.slice(5, 7); return ym + '-' + String(new Date(y, m, 0).getDate()).padStart(2, '0'); }
  function isKinder(st){ return !!(st && (st.kinder || /유치|7세/.test(String(st.cls || '') + ' ' + String(st.className || '')))); }

  /* 이번 달이면 오늘까지만(2026-11-12) — 달 끝까지 잡으면 아직 마감 안 된 과제가 '미제출'로 세어져
     제출률이 낮게·그래프가 0으로 떨어져 보였다(김의진 11월 36%). 지난 달은 말일까지 */
  function endDay(ym){
    var t = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
    return t.slice(0, 7) === ym ? t : lastDay(ym);
  }
  function render(d){
    var stid = String(d.stid || ''), ym = String(d.ym || ''), nm = String(d.name || '');
    if(!stid || !/^\d{4}-\d{2}$/.test(ym)) return Promise.resolve({ok:false, msg:'stid·ym 이 필요해요'});
    /* 트리톡 학생 아이디 = 해피트리 학생 아이디(공용 학생계정으로 로그인). 없으면 이름이 하나뿐일 때만 */
    var st = STUDENTS.filter(function(s){ return String(s.id) === stid; })[0];
    if(!st && nm){ var byName = STUDENTS.filter(function(s){ return String(s.name || '') === nm; }); if(byName.length === 1) st = byName[0]; }
    if(!st) return Promise.resolve({ok:true, empty:true});
    return getJson('/api/report/' + encodeURIComponent(st.id) + '?start=' + ym + '-01&end=' + endDay(ym)).then(function(rep){
      var hasVocab = rep.vocab && rep.vocab.studiedSets > 0;
      if(!rep.totalAssigned && !hasVocab) return {ok:true, empty:true};
      var kin = isKinder(st);
      var note = kin ? ((rep.student && rep.student.name || nm) + ' 학생은 이번 달 과제 ' + rep.totalAssigned + '개 중 ' + rep.submittedCount + '개를 해냈어요.') : (rep.summary || '');
      var host = document.createElement('div');
      host.style.cssText = 'position:absolute;left:-10000px;top:0;width:820px';
      document.body.appendChild(host);
      var root = ReactDOM.createRoot(host);
      try{
        ReactDOM.flushSync(function(){ root.render(React.createElement(ReportSheet, {rep:rep, note:note, noScores:kin})); });
        var box = host.firstElementChild;
        if(!box) return {ok:false, msg:'성적표를 그리지 못했어요'};
        box = box.cloneNode(true);
        box.style.maxWidth = '860px'; box.style.margin = '0 auto'; box.style.boxSizing = 'border-box';
        staticize(box);
        var html = box.outerHTML, css = allCss().join('\n');
        if(html.length > 550000) return {ok:false, msg:'성적표가 너무 커요(' + Math.round(html.length / 1024) + 'KB)'};
        if(css.length > 850000) css = css.slice(0, 850000);
        return {ok:true, empty:false, html:html, css:css, title:TITLE};
      } finally { try{ root.unmount(); }catch(e){} try{ host.remove(); }catch(e){} }
    });
  }

  var chain = Promise.resolve();   /* 한 번에 하나씩 */
  function handle(d, origin){
    chain = chain.then(function(){
      if(state !== 'ok') return {ok:false, msg:failMsg || '준비 안 됨'};
      return render(d).catch(function(e){ return {ok:false, msg:'그리기 오류: ' + (e && e.message || e)}; });
    }).then(function(res){ res.htpub = 'done'; res.reqId = d.reqId; post(res, origin); });
  }
  window.addEventListener('message', function(e){
    if(!originOk(e.origin)) return;
    var d = e.data; if(!d || d.htpub !== 'render') return;
    if(state === 'wait'){ queue.push({d:d, o:e.origin}); return; }
    handle(d, e.origin);
  });

  boot();
})();
