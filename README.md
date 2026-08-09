# 통역 졸업시험 관리 툴 V1

한국어↔일본어 동시통역 연습, 셀프피드백, 언어쌍, 복습, 통계를 한곳에서 관리하는 개인용 로컬 앱입니다. 데이터는 외부로 전송되지 않고 앱 폴더의 `interpretation_study.db`에 저장됩니다.

## 설치 (Mac)

터미널을 열고 이 폴더로 이동한 뒤 아래 명령을 차례로 실행하세요.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## 실행

```bash
source .venv/bin/activate
streamlit run app.py
```

브라우저가 자동으로 열립니다. 열리지 않으면 터미널에 표시되는 `Local URL`을 클릭하세요. 종료는 터미널에서 `Control + C`입니다.

## 화면

- **대시보드**: 큰 글씨의 시험 D-day, 방향별 동시통역·순차통역과 섀도잉 기본 루틴, 시역 횟수를 포함한 월~일 실천표, 최근 공부 메모, 주간 목표와 진행률
- **연습**: 동시통역·순차통역·시역·섀도잉 유형, 방향별 연습시간, 자료 제목과 URL, 난이도, 오류 횟수와 메모 기록
- **언어쌍**: 한일 언어쌍 저장, 검색, 유형·숙지도 필터
- **리뷰**: KO→JA와 JA→KO가 무작위로 바뀌는 플래시카드 복습과 3단계 자기평가. 낮은 평가·오래 미복습한 카드 우선 출제
- **Study Notes**: 공부 메모 작성, 태그, 검색과 모아보기
- **Statistics**: 방향별 누적 시간, 오류 유형, 주간 추이, 언어쌍 누적
- **공부 자료**: 목록에서 제목을 눌러 읽는 게시판. 제목·본문 검색, 한일/일한 및 순차/동시 필터, 텍스트 서식과 YouTube 임베드 지원
- **스크립트 피드백**: 문장별 대조 분석과 누락·오역·어색한 표현·퍼포먼스 구간의 색상 하이라이트 및 횟수 그래프
- **TTS**: 한국어 기사체를 -ㅂ니다/-습니다체로, 일본어 だ・である체를 です・ます調로 바꾼 뒤 기준 속도에 맞춰 생성. 음질이 늘어지지 않도록 브라우저의 사후 속도 보정은 작은 범위로 제한

시험일 초기값은 2026년 12월 1일이며 Dashboard에서 변경할 수 있습니다. 데이터 백업은 앱 종료 후 `interpretation_study.db` 파일을 복사하면 됩니다.

## Supabase 연결 준비

`supabase_schema.sql`을 Supabase SQL Editor에서 실행한 뒤 `.streamlit/secrets.toml.example`을
`.streamlit/secrets.toml`로 복사하고 프로젝트 URL과 Secret key를 입력하세요. 실제 secrets 파일은
GitHub이나 채팅에 공유하지 마세요. 현재 V1은 계속 SQLite를 사용하며, 온라인 저장소 전환 버전에서
이 설정을 사용합니다. Supabase 연결은 Python 기본 REST 기능을 사용하므로 별도의 Supabase 패키지를 설치할 필요가 없습니다.

## 문장별 AI 스크립트 피드백

Streamlit Cloud의 앱 설정에서 **Secrets**를 열고 기존 Supabase 설정 아래에 다음 항목을 추가하세요.

```toml
OPENAI_API_KEY = "sk-..."
```

API 키는 앱 코드나 GitHub에 올리지 마세요. 스크립트 피드백을 실행하면 원문과 실제 통역문이 분석을 위해 OpenAI API로 전송되며, API 사용량에 따른 비용이 발생할 수 있습니다. 분석 결과만 앱의 기존 `script_feedbacks` 기록에 저장됩니다.

고유명사·전문용어 추출에서 기사 URL을 사용하면 앱이 공개된 기사 페이지의 본문을 불러온 뒤 OpenAI API로 전송해 분석합니다. 로그인·유료벽·자바스크립트 전용 페이지처럼 자동 수집이 허용되지 않거나 본문을 확인할 수 없는 기사는 직접 붙여넣기를 사용하세요.

TTS 메뉴는 입력한 텍스트를 OpenAI Audio API로 전송해 AI 음성을 생성합니다. 음성 생성에는 API 사용량에 따른 비용이 발생할 수 있습니다.

공부 자료 게시판을 이미 사용하는 기존 Supabase 프로젝트에서는 먼저 `supabase_update_v7.sql`을 실행한 상태인지 확인하고, 이번 게시판 분류 기능을 위한 `supabase_update_v8.sql`을 SQL Editor에서 한 번 실행하세요. 새 프로젝트라면 최신 `supabase_schema.sql`만 실행하면 됩니다. 배포할 때 `study_material_editor/index.html` 폴더도 `app.py`와 같은 저장소 구조로 함께 올려야 합니다.
