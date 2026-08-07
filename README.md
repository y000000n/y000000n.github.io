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

- **Dashboard**: 방향별 동시통역·순차통역과 섀도잉 기본 루틴, 월~일 실천표, 최근 공부 메모, 시험 D-day, 주간 목표와 진행률
- **연습**: 동시통역·순차통역·시역·섀도잉 유형, 방향별 연습시간, 자료 제목과 URL, 난이도, 오류 횟수와 메모 기록
- **Language Pairs**: 한일 언어쌍 저장, 검색, 유형·숙지도 필터
- **Review**: 플래시카드 복습과 3단계 자기평가. 낮은 평가·오래 미복습한 카드 우선 출제
- **Study Notes**: 공부 메모 작성, 태그, 검색과 모아보기
- **Statistics**: 방향별 누적 시간, 오류 유형, 주간 추이, 언어쌍 누적

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
