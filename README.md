# ksasf-pdf-checker

KSASF 발표 페이지에서 새 PDF를 자동으로 찾아 다운로드하고, PDF 내부에서 연구 제목 관련 키워드를 검색한 뒤 Telegram으로 결과를 전송하는 GitHub Actions 프로젝트입니다.

PC가 꺼져 있어도 GitHub Actions가 30분마다 실행합니다.

## 검색 키워드

```text
혹등고래 버블넷
버블넷
Bubble-Net
```

키워드는 `checker.py`의 `KEYWORDS` 목록에서 수정할 수 있습니다.

## 주요 기능

- KSASF 발표 페이지 접속
- 같은 사이트의 공고 상세 페이지를 한 단계 탐색
- PDF 링크 자동 발견
- 새 PDF 또는 교체된 PDF만 처리
- PDF 다운로드 및 GitHub Actions artifact 보관
- `pypdf`를 이용한 PDF 텍스트 추출
- 키워드 대소문자 구분 없이 검색
- 검색 결과와 PDF 원본을 Telegram으로 전송
- 처리한 PDF의 URL과 SHA256을 저장해 중복 알림 방지
- 수동 실행 및 30분 주기 자동 실행 지원

## 프로젝트 구조

```text
ksasf-pdf-checker/
├─ checker.py
├─ requirements.txt
├─ README.md
├─ .gitignore
├─ .github/
│  └─ workflows/
│     └─ check-pdf.yml
└─ data/
   ├─ processed_pdfs.json
   └─ pdfs/
```

## 1. GitHub 저장소 생성

1. GitHub에서 **New repository**를 누릅니다.
2. 저장소 이름을 `ksasf-pdf-checker`로 입력합니다.
3. 저장소를 생성합니다.
4. 이 프로젝트의 파일을 저장소 루트에 업로드합니다.

`checker.py`와 `requirements.txt`가 저장소 최상위에 있어야 합니다.

## 2. Telegram Bot 준비

1. Telegram에서 `BotFather`를 검색합니다.
2. `/newbot`을 보내 봇을 생성합니다.
3. 발급받은 Bot Token을 보관합니다.
4. 새 봇에게 메시지를 한 번 보냅니다.
5. 브라우저에서 다음 주소를 엽니다.

```text
https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
```

6. 응답의 `chat.id` 값을 확인합니다.

## 3. GitHub Secrets 설정

저장소에서 다음 메뉴로 이동합니다.

```text
Settings > Secrets and variables > Actions
```

다음 Repository secret 두 개를 만듭니다.

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

## 4. Actions 활성화 및 테스트

1. 저장소의 **Actions** 탭을 엽니다.
2. 워크플로 실행을 허용합니다.
3. 왼쪽에서 **KSASF PDF Checker**를 선택합니다.
4. **Run workflow**를 눌러 수동 테스트합니다.

정상 동작하면 이후 30분마다 자동 실행됩니다.

## 5. 알림 내용

새 PDF가 발견되면 다음 정보가 Telegram으로 전송됩니다.

```text
📄 KSASF 새 PDF 감지

제목: 발표 PDF 제목
시간: 확인 시각
페이지 수: 10
결과: 검색 키워드 발견
발견 키워드: 혹등고래 버블넷, 버블넷
PDF: PDF 주소
```

다운로드한 PDF 원본도 Telegram 문서로 함께 전송됩니다.

## 중복 알림 방지

처리한 PDF 정보는 다음 파일에 저장됩니다.

```text
data/processed_pdfs.json
```

PDF URL과 파일 SHA256이 같으면 다시 알리지 않습니다. 같은 URL의 PDF가 새 파일로 교체되면 SHA256이 달라지므로 다시 처리합니다.

## PDF 다운로드 위치

실행 중 다운로드한 PDF는 다음 폴더에 저장됩니다.

```text
data/pdfs/
```

Git 저장소가 커지는 것을 막기 위해 PDF는 Git에 커밋하지 않습니다. GitHub Actions 실행 화면의 **Artifacts**에서 30일 동안 받을 수 있습니다.

## 로컬 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="봇 토큰"
$env:TELEGRAM_CHAT_ID="채팅 ID"
python checker.py
```

## 주의사항

- 이미지로 스캔된 PDF는 텍스트가 없어서 검색되지 않을 수 있습니다. OCR은 현재 포함하지 않습니다.
- KSASF 사이트 구조가 변경되면 PDF 링크 탐색 규칙을 조정해야 할 수 있습니다.
- GitHub Actions 예약 실행은 서버 상황에 따라 정확히 30분 간격보다 늦어질 수 있습니다.
