# 해피트리 낭독 숙제 (통합 버전)

앱 화면 + 데이터 저장 + Azure 발음평가가 하나의 서버에서 모두 돌아가요.
학생들에게는 주소 하나만 알려주면 됩니다.

## 기존 Render 서비스에 올리기

이미 만들어두신 `happytree-speech` 서비스를 그대로 쓰면 돼요.

### 1. GitHub 저장소 파일 교체

기존 `happytree-speech` 저장소에 이 폴더의 파일들을 올립니다.

- `app.py` — 기존 것을 **덮어쓰기**
- `requirements.txt` — 기존 것을 덮어쓰기 (내용 동일)
- `Dockerfile` — 기존 것을 덮어쓰기 (내용 동일)
- `static/index.html` — **새로 추가** (static 폴더를 만들고 그 안에 넣기)

GitHub 웹에서 하는 방법:
1. 저장소 페이지 → `app.py` 클릭 → 연필 아이콘(Edit) → 전체 선택 후 새 내용 붙여넣기 → Commit
2. 저장소 페이지 → `Add file` → `Create new file` → 파일명 칸에 `static/index.html` 이라고 입력
   (슬래시를 넣으면 폴더가 자동으로 만들어져요) → 내용 붙여넣기 → Commit

### 2. Render에 디스크 추가 (중요 — 데이터 보존)

유료 플랜이므로 디스크를 붙일 수 있어요. 이걸 해야 재배포해도 데이터가 남아요.

1. Render 대시보드 → `happytree-speech` 서비스 클릭
2. 왼쪽 메뉴 **Disks** → **Add Disk**
3. Name: `data` (아무거나)
4. **Mount Path: `/data`**  ← 반드시 이 값
5. Size: 1 GB (녹음 파일 저장용, 나중에 늘릴 수 있어요)
6. Save

### 3. 환경변수 확인

Environment 탭에 아래 값들이 있는지 확인하세요.

| Key | Value |
|---|---|
| `AZURE_SPEECH_KEY` | Azure에서 복사한 KEY 1 |
| `AZURE_SPEECH_REGION` | 예: `eastus` |
| `ADMIN_PASSCODE` | 원하는 관리자 비밀번호 (없으면 기본값 `happytree`) |

`ADMIN_PASSCODE`는 새로 추가하시길 권해요. 기본값 그대로 두면 주소를 아는
사람이 관리자 화면에 들어올 수 있어요.

### 4. 배포 후 확인

- `https://happytree-speech.onrender.com/api/health` 접속
  → `{"ok":true,"azure_key_set":true,...}` 가 뜨면 정상
- `https://happytree-speech.onrender.com` 접속
  → 로그인 화면이 뜨면 완료

## 사용법

**선생님**: 로그인 화면 → "선생님" 탭 → 관리자 비밀번호 입력

- 학생관리: 이름/반 입력 후 아이디 발급 (기존 학원 아이디·비밀번호 그대로 입력 가능)
- 과제관리: 제목·마감일·유형 선택, 목록은 직접 입력하거나 엑셀/PDF 업로드
  배정 대상은 전체 / 반별 / 개별 중 선택
- 제출확인: 학생별 녹음 재생(1~3회차), 발음평가 점수 확인, 코멘트 작성
- 설정: 백업 파일 내려받기 / 복원

**학생**: 같은 주소 접속 → "학생" 탭 → 발급받은 아이디·비밀번호로 로그인
→ 과제 선택 → 🔊 버튼으로 원어민 발음 듣기 → 1회/2회/3회 각각 녹음 → 제출

## 참고

- 녹음은 **HTTPS 주소**에서만 동작해요. Render 주소는 HTTPS라 문제없어요.
- 학생이 처음 녹음 버튼을 누르면 브라우저가 마이크 권한을 물어봐요. "허용"을 눌러야 해요.
- 발음평가는 Azure Free F0 요금제 기준 월 사용량 한도가 있어요.
  초과하면 점수 없이 녹음/제출만 정상 동작합니다.
- 설정 탭에서 백업 파일을 정기적으로 내려받아 두시길 권해요.
