# 해피트리 발음평가 백엔드

Azure Speech의 발음평가(Pronunciation Assessment)를 대신 호출해주는 작은 서버예요.
학생이 녹음한 오디오와 목표 텍스트를 받아서 Azure에 요청하고, 점수만 앱으로 돌려줘요.
Azure 키는 이 서버에만 저장되고 브라우저 쪽 코드에는 절대 노출되지 않아요.

## 1. Azure Speech 리소스 만들기 (키 발급)

1. https://portal.azure.com 접속 후 로그인 (계정 없으면 무료로 생성)
2. 상단 검색창에 "Speech" 입력 → **Speech** (Cognitive Services) 선택 → **Create(만들기)**
3. 아래 항목 입력
   - Subscription: 기본값 그대로
   - Resource group: 새로 만들기 (예: happytree-rg)
   - Region: **East US** 또는 **Korea Central** 중 하나 선택 (아래 배포 시 이 지역명을 그대로 씀)
   - Name: 아무 이름 (예: happytree-speech)
   - Pricing tier: **Free F0** 선택 (무료, 월 사용량 제한 있음 — 소규모 학원 사용에는 충분)
4. **Review + create** → **Create** 클릭, 배포 완료까지 1분 정도 대기
5. 배포 완료 후 **리소스로 이동(Go to resource)** 클릭
6. 왼쪽 메뉴에서 **Keys and Endpoint** 클릭
7. **KEY 1** 값 복사 (이게 `AZURE_SPEECH_KEY`), **Location/Region** 값 확인 (이게 `AZURE_SPEECH_REGION`, 예: `eastus`)

## 2. Render에 배포하기

기존에 쓰시던 방식(namcheon-exam-bank, ht-10step)과 동일해요.

1. 이 폴더(`pronunciation-backend`)를 GitHub 새 저장소로 올리기
2. Render 대시보드 → **New** → **Web Service** → 방금 만든 저장소 선택
3. Environment: **Docker** 선택 (Dockerfile 자동 인식)
4. Environment Variables 추가:
   - `AZURE_SPEECH_KEY` = 1번에서 복사한 키
   - `AZURE_SPEECH_REGION` = 1번에서 확인한 지역 (예: `eastus`)
5. Deploy 클릭, 배포 완료되면 `https://xxxx.onrender.com` 같은 주소가 생김
6. 브라우저에서 `https://xxxx.onrender.com/health` 접속해서 `{"ok":true,"azure_key_set":true}` 뜨는지 확인

## 3. 앱에 연결하기

해피트리 낭독 숙제 앱의 관리자 화면 → **설정** 탭에서, 위에서 만든 Render 주소를
`https://xxxx.onrender.com` 형태로 입력하고 저장하면 끝이에요.
이후 학생이 녹음하면 자동으로 이 서버를 거쳐 Azure 발음평가 점수가 표시돼요.

서버 주소가 비어있거나 연결이 안 되면, 앱은 자동으로 브라우저 자체 간이 체크로 대체돼요.
