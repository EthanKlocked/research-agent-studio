# Research Agent Studio

리서치 워크플로우를 구성하고 실제 실행 이벤트를 클라이언트에서 관측하는 로컬 프로토타입입니다. 질문 → 계획 → 읽기 전용 MCP 자료 조회 → 인용 보고서 → 평가 → 필요한 경우 재계획 과정을 실행하고, 단계·모델/도구 호출·근거·보고서 revision을 대시보드에서 확인합니다. 기본은 오프라인 Apple 예제이며, 명시적으로 설정한 실제 모델 모드에서는 Exa 일반 웹 검색을 추가할 수 있습니다. 공개 데이터 기반 독립 구현으로 특정 기업과 제휴하지 않으며 투자 자문 또는 최신 정보 서비스가 아닙니다.

![리서치 워크플로우와 보고서 화면](docs/viewport-1440.png)

## 빠른 시작

요구 환경: Python 3.12, Node.js 22, npm, uv. 최초 설치에는 패키지 레지스트리 네트워크 접근이 필요합니다. Docker·외부 데이터베이스·별도 MCP 설치는 기본 실행에 필요 없습니다. 선택형 LiteLLM gateway 검증/실행에는 Docker Desktop과 Compose v2가 추가로 필요합니다.

먼저 저장소를 clone하고 해당 디렉터리로 이동합니다.

```text
git clone https://github.com/EthanKlocked/research-agent-studio.git
cd research-agent-studio
```

### Windows · PowerShell

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1 -TestMode
```

PowerShell 스크립트는 로컬 개발 환경에서 정적 계약 테스트를 했습니다. 별도 **Windows PowerShell 5.1 / Python 3.12.14 환경의 실행 결과가 보고**되었지만, 당시 커밋·로컬 수정 여부가 확인되지 않아 **현재 커밋의 Windows 검증 완료를 의미하지는 않습니다**. 발견된 인코딩·테스트 호환성 문제와 확인 범위는 [검증 문서](docs/verification.md)를 참고하세요. 실행 정책 때문에 스크립트가 차단되면 시스템 정책을 바꾸지 말고 아래 명령을 직접 실행할 수 있습니다.

```powershell
uv sync --locked --extra dev
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
$previousTestMode = [Environment]::GetEnvironmentVariable('RESEARCH_TEST_MODE', 'Process')
try {
    $env:RESEARCH_TEST_MODE = "1"
    uv run --locked --extra dev python -m uvicorn backend.api:app --host 127.0.0.1 --port 8765
} finally {
    [Environment]::SetEnvironmentVariable('RESEARCH_TEST_MODE', $previousTestMode, 'Process')
}
```

### macOS / Linux · Bash

```bash
bash scripts/setup.sh
bash scripts/start.sh --test
```

실제 설치·실행·브라우저 검증은 macOS에서 수행했습니다.

브라우저: **http://127.0.0.1:8765**. 종료: 실행한 터미널에서 **Ctrl+C**. 하나의 API 서버가 빌드된 프론트를 제공합니다. 하나의 Uvicorn worker만 사용하세요.

테스트 질문:

> Apple FY2024 4분기 실적과 주요 위험요인을 근거와 함께 정리해 주세요.

`재조사 후 개선` 시나리오를 선택하고 리서치를 시작합니다. 실제 LangGraph와 LangChain Agent, 실제 MCP stdio 자식 프로세스, 실제 API/SSE를 실행합니다. **모델 응답은 결정적 fixture이며 자료는 오프라인 고정 데이터입니다. 실제 모델·Exa·Apple 공개자료 네트워크 호출은 없습니다.** 이는 임의 질문에 대한 지능 검증이 아니라 고정 Apple 사례의 제어 흐름 시연입니다. 타이머로 단계를 흉내 내지 않습니다. 테스트 실행은 빠르게 끝날 수 있으며 작업 타임라인에서 실제 노드·도구·분기 이벤트를 확인할 수 있습니다.

## 모델 연결

`.env.example`의 모델 설정 값은 모두 비어 있습니다. 로컬 `.env` 또는 프로세스 환경변수로만 아래 이름에 값을 넣습니다. 프로세스 환경변수가 `.env`보다 우선합니다.

- `LLM_PROVIDER`: 구현된 adapter는 `openai` 또는 `openai-compatible`.
- `LLM_MODEL`: 사용하는 모델 식별자.
- `LLM_BASE_URL`: 해당 provider의 chat-completions API base URL. 원격은 HTTPS, HTTP는 loopback만 허용합니다.
- `LLM_API_KEY`: 로컬에서만 주입하는 키.
- `LLM_MAX_OUTPUT_TOKENS`: 선택 설정. 비워 두면 8192, 허용 범위 1–65536. 모델이 허용하는 한도 내에서 지정하세요. thinking을 포함하는 provider에서는 답변에 쓸 수 있는 토큰이 줄어들 수 있으며, 한도 증가는 비용·지연을 늘릴 수 있습니다.
- `RESEARCH_TEST_MODE`: 안전 기본값 `0`. `--test` 또는 PowerShell `-TestMode` 시작 옵션은 이 값을 `1`로 설정하여 별도 테스트 모드를 허용합니다.

모델·endpoint·키의 실제 예시 값은 제공하지 않습니다. `.env`를 Git에 넣지 마세요. 키를 브라우저 변수·localStorage에 넣지 마세요. 인증 없는 로컬 호환 서버도 클라이언트 프로토콜상 네 필드가 필요하므로 운영자가 비밀이 아닌 placeholder key를 정할 수 있습니다.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
# 로컬 편집기로 .env를 설정한 다음:
.\scripts\start.ps1
```

macOS / Linux:

```bash
cp .env.example .env
# 로컬 편집기로 .env를 설정한 다음:
bash scripts/start.sh
```

이전에 직접 설정한 `RESEARCH_TEST_MODE=1`이 현재 터미널에 남아 있다면 제거하세요.

설정 미완료/형식 오류이면 실제 모델 실행을 막습니다. `configured`는 **설정 형식 충족**이지 인증 성공을 뜻하지 않습니다. `--test`와 실제 모델 설정을 함께 쓸 때는 화면에서 실행 모드를 명시적으로 선택합니다. 실제 모델 오류가 나도 테스트 모델로 대체하지 않습니다. LangSmith tracing과 모델 HTTP 환경 proxy 사용은 비활성화합니다.

### Gemini 호환 범위

사용자 제공 API 테스트 보고 기준으로 **Gemini는 2.5 계열까지 확인됨**입니다. 정확한 모델별 전체 성공이나 보고서 품질을 보증하지 않으며, 이번 수정본의 실제 연결은 재검증이 필요합니다. 초기 Windows 테스트 모드 브라우저 흐름은 로컬 수정본에서 확인되었습니다. 초기 실제 모델 확인은 API-only였으며, 이후 `5a3c325`에서 실제 모델 브라우저 실행 1회가 timeout으로 끝났고 오류 분류 표시는 정상이었다는 사용자 보고가 있습니다.

**Gemini 3.x는 현재 미지원**입니다. 현재 OpenAI-compatible 어댑터는 도구 호출의 `thought_signature` 왕복 전달을 지원하지 않아 후속 요청에서 400 오류가 날 수 있습니다. Gemini 전용 어댑터는 포함하지 않습니다.

### 사용자 설정 후 live smoke

1. 테스트 옵션 없이 시작하고 화면에서 실제 모델 모드를 확인합니다.
2. 위 질문을 실행합니다. 또는 별도 터미널에서:

```bash
curl --fail-with-body -sS http://127.0.0.1:8765/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"question":"Apple FY2024 4분기 실적과 주요 위험요인을 근거와 함께 정리해 주세요.","mode":"live","scenario":"pass"}'
```

3. 반환된 `run_id`로 snapshot `/api/runs/<run_id>`와 SSE `/api/runs/<run_id>/events`를 확인합니다. UI는 이 API를 사용합니다.
4. MCP 조회 근거와 인용을 열어 분기·연간 수치, GAAP/비GAAP, 위험의 불확실성 표현을 검토합니다. 첫 평가에서 통과해도 정상이며 재조사를 보장하지 않습니다. 실제 `revise`가 나오면 Planner 재진입과 기존 근거 보존을 확인합니다.
5. 실패 경로를 확인하려면 **운영자가 로컬 설정에 잘못된 테스트용 인증값을 직접 사용**하고 오류 종료 및 비밀값 미노출을 확인한 뒤 정상 설정으로 되돌립니다. 실서비스 키를 폐기하거나 변경할 필요는 없습니다. 재조사·한도·도구 오류를 결정적으로 확인하려면 별도 테스트 모드를 이용합니다.

**실제 provider 인증, 선택한 모델의 tool calling/JSON 호환성, 보고서 품질·의미상 사실성, provider 측 취소 효과는 사용자 설정 후 확인 필요합니다. 이 저장소의 키 없는 테스트는 이를 검증하지 않습니다.**

## 선택: LiteLLM Gateway

기존 직접 연결·오프라인 fixture를 유지하면서 **Agent → localhost LiteLLM Proxy → 두 OpenAI-compatible upstream** 경로를 선택할 수 있습니다. 앱과 MCP는 호스트에서 계속 실행하고, `gateway/`의 고정 이미지 Proxy만 Docker Compose로 실행합니다. `research-primary` / `research-secondary` 별칭, 한 번의 fallback, gateway 인증과 deployment별 실제 RPM 제한을 구성합니다. 전 역할은 같은 설정 별칭을 쓰며 MCP 도구는 Proxy를 거치지 않습니다.

[Windows/macOS 설치·키 없는 mock 검증·선택적 실제 연결·종료 및 학습 가이드](docs/gateway.md)를 먼저 읽으세요. 키 없는 통합 테스트는 **실제 LiteLLM + 로컬 mock upstream + 기존 graph/Agent/MCP**를 사용하며 live 모델의 품질·과금·Windows 실행을 검증하지 않습니다. 요청 상관관계·지연·응답 token usage는 안전한 앱 로그로 기록합니다. `gateway/app.env.example`을 호스트 앱 설정에 병합하면 gateway용 timeout 예산과 관측 opt-in을 적용할 수 있습니다. 타임라인에 검증된 `served_by` 별칭 / `fallback`을 표시하고, 알 수 없으면 unknown으로 남깁니다. 명시적 reasoning tokens와 미설명 토큰 차액은 구분하며, 가격은 운영자가 등록한 경우에만 추정합니다. 모르는 usage/가격과 실제 청구액은 `null`입니다. [런타임 피드백 변경 검증](docs/gateway-feedback-verification.md)을 참고하세요. DB/Redis/유료 라이선스는 필수가 아니며 영속 예산/분산 운영은 포함하지 않습니다.

## 선택: Exa 일반 웹 검색

고정 Apple 예제를 넘어 일반 공개 웹을 조사하려면 모델 설정과 별도로 **로컬 `.env` 또는 프로세스 환경변수에만** `SEARCH_PROVIDER=exa`와 `EXA_API_KEY`를 설정하고 서버를 재시작하세요. 키 값은 문서·채팅·브라우저·Git에 넣지 마세요. 두 설정이 모두 있어야 활성화되며 미설정 시 기존 제한된 자료 범위를 사용합니다. Exa 설정은 모델 연결을 대신하지 않습니다.

**무료 크레딧만 사용하려는 운영자 체크리스트:**
- Exa 계정에서 카드 등록 없음, 크레딧 구매 없음, **Auto recharge OFF**를 직접 확인하세요. 이 앱은 계정 결제 설정을 변경하거나 검증하지 않습니다.
- 충전 한도 **0은 무제한(unlimited)**일 수 있으므로 “0원 지출 차단”으로 사용하지 마세요. 자동 충전을 끄는 것과 한도 숫자는 별개입니다.
- 로컬 요청 제한은 **무료 잔액 또는 무료 크레딧만 사용됨을 보장할 수 없습니다**. 실행 전에 계정 잔액·과금 정책을 확인하고, 무료 사용을 보장할 수 없으면 활성화하지 마세요. [Exa 결제·가격 문서](https://exa.ai/docs/reference/admin/pricing)를 확인하세요.

MCP에 `web_search`와 `read_page`가 추가됩니다. 검색은 메타데이터만 반환하며 snippet은 인용 근거가 아닙니다. 검색에서 등록한 실행별 opaque ID만 읽을 수 있고, 성공한 `/contents` 본문 조회만 근거가 됩니다. 임의 URL 입력·직접 fetch 도구는 제공하지 않습니다. 자료의 게시일·기준일이 없으면 미확인으로 표시하며 최신성·완전성을 보장하지 않습니다.

실행별 Exa 저장소 한도는 **검색 요청 6회, 본문 읽기 요청 8회**, 검색당 최대 5개 결과입니다. 캐시는 같은 실행의 재조사에서도 유지됩니다. 이는 다른 Researcher 도구 예산·시간 제한과 별개인 상한으로, 모든 요청이 실행된다는 뜻이 아닙니다. **검색과 contents 읽기는 별도 비용 항목**이며 본문 읽기나 모델 호출도 비용을 발생시킬 수 있습니다. 인증·할당량 실패 시 다른 서비스나 fixture로 자동 대체하지 않습니다.

Planner와 Researcher는 MCP 저장소의 실제 남은 검색/읽기 예산을 받습니다. **로컬 실행별 Exa 예산** 소진만 구조화된 `web_budget_exhausted` 도구 오류로 복구합니다. 소진된 작업은 재시도하지 않고 이미 읽은 근거와 아직 허용된 읽기를 사용합니다. 모델이 계속 재시도해도 역할별 도구 호출 상한은 유지됩니다. 소진을 관측한 실행은 `budget_exhausted`로 끝나며, 근거가 있으면 한계를 명시한 부분 보고서를 제공하고 없으면 보고서를 만들지 않습니다. Evaluator가 pass를 반환해도 전체 조사 성공으로 표시하지 않으며 추가 재계획을 반복하지 않습니다. 제공자 quota/auth/네트워크 오류 및 역할별 도구 한도는 여전히 실패입니다. 잔여 로컬 예산은 계정 잔액이 아닙니다.

**외부 전송:** 실제 모델 모드의 질문·근거는 설정한 모델 제공자에게, Exa 검색어와 읽을 URL은 Exa에게 전송됩니다. 로컬 UI라고 해서 데이터가 장치 안에만 머무는 것은 아닙니다. 개인·기밀 정보를 질문이나 URL에 넣지 마세요. 테스트 모드는 Exa와 Apple 공개자료 옵션이 설정되어도 **오프라인 고정 자료와 fixture 모델만 사용**합니다.

`/api/config`의 `capabilities.general_web`과 `capabilities.search_provider`(`exa` 또는 `null`)는 설정 기반 기능 표시입니다. 연결·인증·잔액 검증 결과가 아닙니다. 화면의 “현재 관측된 도구”는 실행 로그일 뿐 전체 기능 목록이나 웹 검색 사용 가능성의 근거가 아닙니다.

## 클라이언트

- 질문·실행·중단, 검색 기능 설정과 오프라인/실제 모델 구분, 자료 기준일(없으면 미확인), 실행 단계·시간·회차.
- 작업 타임라인: MCP discovery, 모델 요청 시작/완료, 출력 검증·보정, 도구 호출, 분기·종료. 본문 토큰 스트림이나 모델 내부 추론이 아닙니다.
- 보고서·수집 자료·수정 기록 탭과 출처 포커스 이동. 검색 메타데이터와 실제 읽은 근거를 구분합니다.
- 구조화된 계획, 실제 도구 조회, 평가 이슈·후속 조사.
- 보고서 버전 선택, 이전 보고서 비교, 추가된 근거와 출처/구간 확인.
- 작업 타임라인에서 실행 이벤트와 State 변경 필드를 확인합니다. 접이식 개발 상세는 공통 State 필드 안내입니다. 내부 추론·시스템 프롬프트를 노출하는 debugger가 아닙니다.
- SSE 순서/실행 격리, 연결 오류 표시와 snapshot 우선 재동기화. 새로고침 시 sessionStorage의 run ID만 사용해 현재 snapshot을 복원합니다. 기존 상세 이벤트 전체를 복구한다고 주장하지 않습니다.

## 구조와 상태 매핑

```text
frontend/       React + TypeScript / Vite
backend/        FastAPI, 환경 설정, Agent factory, LangGraph, run manager
mcp_server/     검색·구간 조회 전용 stdio 서버
data/           공개 출처에 기반한 짧은 독립 요약과 provenance
tests/          키 없는 단위·통합·실제 MCP 프로토콜 테스트
scripts/        설치·시작·테스트
docs/           설계·QA·화면 캡처
```

상위 State는 question, interpreted_request, plan, evidence, report, revisions, evaluation, feedback, iteration, status, errors를 전달합니다. 각 역할의 내부 메시지는 역할별로 새로 구성하고 검증한 JSON만 상위 State에 반영합니다. Researcher만 허용 도구를 받습니다. 근거는 실제 구간 조회 결과에서만 추가하고 ID로 중복을 제거합니다. 재계획은 근거·평가 피드백을 보존합니다. Checkpointer/DB는 사용하지 않으며 **서버 재시작 시 모든 실행 기록이 사라집니다**.

### 실행 기준 시각과 지원 범위

서버는 실행 시작 시 **UTC 기준 timezone-aware 시각**을 한 번 캡처합니다. `run_context`의 `started_at`, `current_date`, `timezone`은 전 역할과 출력 보정·재조사에 동일하게 전달됩니다. UI에도 실행 기준일/시간대를 표시합니다. “오늘/최근”과 미래 날짜 판단은 이 시각을 기준으로 하도록 지시하며, 모델의 지식 기준일을 사용하지 않습니다. 장시간 실행이 자정을 넘어도 기준은 바뀌지 않습니다. 사용자가 특정 시간대/기간을 요청하면 명시적으로 해석해야 합니다. 근거의 게시일(`published_at`), 자료 기준일(`as_of`), 수집 provenance는 실행 시각과 별개이며 미확인 값을 오늘로 채우지 않습니다. 이는 명시적 입력/프롬프트 계약이며 live 모델의 날짜 판단 정확성을 보장하지 않습니다.

Listener는 자료 범위(`scope`)와 별도로 `request_support`를 분류합니다. 개인 재정에 맞춘 종목 추천·거래 실행 등 리서치 지원 밖의 요청은 설명(`unsupported_reason`)과 함께 **정상 종료 `unsupported`**로 끝납니다. MCP 시작·검색·보고서 작성·평가를 하지 않으며 조사 성공이나 도구 오류가 아닙니다. 사실 기반 시장/기업/공시 비교는 허용하며 키워드 차단을 사용하지 않습니다. 사실 조사와 개인 맞춤 요청이 섞이면 `partial`로 사실 부분을 보존하고 제외 범위를 명시합니다. 필드가 없는 기존 출력/불확실한 분류는 `unknown`으로 계속 진행합니다. 실제 분류 품질은 모델에 의존합니다.

### 재조사 실패 시 이전 보고서

2회차가 실패하면 마지막 평가까지 완료된 보고서와 그 근거를 복원하고 `partial_result`에 보존 회차를 기록합니다. 상태는 `error`이며 **평가 통과가 아닙니다**. 화면에 “이전 보고서 · 추가 조사 실패 · 평가 미통과”와 원래 오류를 함께 표시합니다. 명시적 취소는 취소 상태를 유지합니다.

Evaluator/Reporter에는 활성 데이터셋의 문서 범위 밖 요구를 재조사 사유가 아니라 보고서 한계로 명시하도록 지시합니다. 범위 내 누락과 근거 없는 주장은 여전히 수정 대상입니다. 이는 모델에 대한 지시이며 실제 모델의 준수·의미상 정확성은 별도 검증이 필요합니다.

## 데이터·안전 경계

기본 번들 모드는 Apple FY2024 공개자료를 대상으로 **2024-09-28 기준**, 2024-10-31/11-01 게시 자료의 짧은 독립 요약을 사용합니다. 원문 전체를 재배포하지 않습니다. 번들 자료의 `excerpt`는 원문 직접 인용이 아닌 작성된 사실 요약이며 구간 ID도 요약 데이터셋의 ID입니다. 선택적 공식 자료의 excerpt는 원문에서 추출한 짧은 문단 또는 재무 표의 사실 행이며, 별도 source_kind와 source_locator로 구분합니다. [출처·획득일·재배포 범위](data/README.md)를 확인하세요.

기본 MCP 도구는 `search_documents`, `get_section`이며, Exa를 활성화한 실제 모델 실행에는 `web_search`, `read_page`가 추가됩니다. 고정 데이터셋/ID allowlist와 실행별 웹 ID 등록, 검색 입력·결과·호출수 제한을 적용합니다. 임의 shell/SQL/경로/URL fetch 도구가 없습니다. 문서 지시는 신뢰하지 않으며 프롬프트 경고만으로 injection 방어가 완성되었다고 주장하지 않습니다. 인용 ID 존재 검사는 사실성 보장이 아닙니다.

기본 한도:
- 총 **2회차**: 최초 실행 1회 + 최대 추가 재계획 1회.
- 동시 실행 2개, 메모리 실행 20개, 실행별 최근 이벤트 160개.
- 질문 2,000자, 요청 본문 16,000바이트, 본문 수신 5초.
- 전체 실행 기본 600초(`RUN_TIMEOUT`), 개별 모델 HTTP 요청 기본 60초(`LLM_REQUEST_TIMEOUT`), MCP 작업 10초.
- 역할 전체 제한: `RESEARCHER_TIMEOUT` 180초, `REPORTER_TIMEOUT` 120초, `LISTENER_TIMEOUT`·`PLANNER_TIMEOUT`·`EVALUATOR_TIMEOUT` 각각 60초. 도구 반복과 최대 1회 스키마/인용 보정 재요청도 역할 제한 안에 포함됩니다. 긴 웹 근거를 사용하는 재조사 Reporter를 위해 요청 기본값은 30→60초, Reporter 전체 기본값은 60→120초로 늘렸으며, 근거 손실을 피하려고 excerpt를 추가로 자르지 않습니다. 다른 역할·전체 실행 제한은 유지합니다.
- timeout 환경변수는 초 단위이며 누락·빈 값·공백만 있는 값은 기본값, 유한한 양수부터 최대 7200초까지 허용합니다. 요청·역할·실행 제한은 독립 설정이며 요청 제한을 바꿔도 역할/실행 제한이 자동 증가하지 않습니다. 기존 `.env` 또는 프로세스 환경변수의 명시적 값은 그대로 우선하므로 기본값 변경을 적용하려면 운영자가 해당 override를 직접 수정하거나 제거하고 재시작해야 합니다. 역할/전체 실행의 남은 시간이 우선하므로 Reporter에서도 60초 요청 두 번과 처리 오버헤드를 모두 보장하지 않습니다. 다른 60초 역할은 보정에 남은 시간만 사용할 수 있습니다. 한도를 늘리면 대기 시간과 모델 사용 비용이 늘어날 수 있습니다.
- Researcher 회차별 도구 12회(잘못된 입력도 포함), 입력 수정 기회 최대 2회, 검색 최대 5건. `web_search`와 `search_documents`의 `limit` 생략 시 각 도구의 공유 스키마 기본값(현재 각각 5건)을 입력 요약에 표시합니다. 명시적 `null`·불리언·문자열·범위 밖 값은 기본값으로 바꾸거나 강제 변환하지 않고 유효하지 않은 상한으로 표시합니다.
- 도구 호출/수정 예산과 MCP timeout은 서버 `Settings`에서 관리합니다. 브라우저에서 한도를 변경할 수 없습니다.

모델 출력은 단일 JSON 객체 또는 응답 전체를 감싼 하나의 JSON/무표기 코드펜스만 허용합니다. 앞뒤 설명에서 임의로 JSON을 추출하거나 잘못된 필드를 자동 보정하지 않습니다. Provider별 구조화 출력 지원을 가정해 `response_format`을 일괄 강제하지 않습니다. JSON·역할 스키마 오류는 필드 경로와 오류 유형만 안전하게 전달해 최대 1회 재요청합니다. 같은 역할의 timeout과 도구 예산을 공유하며, 재검증 실패나 인용 오류는 종료합니다. 출력 잘림(`finish_reason=length`)은 재요청하지 않고 출력 한도 초과로 종료합니다. 자동으로 성공 처리하거나 필드를 잘라내지 않습니다.

잘못된 도구 인자·문서/구간 ID는 제한 내에서 안전한 오류 정보를 모델에 돌려주어 수정할 수 있게 합니다. 오류 이후 실제 구간 조회에 성공해야 복구된 것으로 인정하며, 검색만 성공하거나 잘못된 호출을 그대로 남긴 채 답하면 오류로 종료합니다. 금지된 도구, 역할별 도구 예산 소진, MCP 통신 장애, timeout·취소는 복구 대상으로 취급하지 않습니다. 위의 로컬 Exa 실행별 예산 소진만 별도로 처리합니다. UI는 도구 입력 오류를 정상적인 빈 조회와 구분합니다. 검색 결과는 본문 요약 없이 메타데이터만 반환합니다. 검색 결과가 있지만 조회된 구간이나 기존 근거가 없는 경우 `retrieval_incomplete` 오류이며, 정상적인 빈 검색과 구분합니다. 모든 역할은 데이터셋 이름·기준일·문서/구간 범위·게시일을 입력받습니다.

오류는 기존 `status=error`를 유지하며 `[역할/분류]`와 고정된 안내를 표시합니다. 분류는 `output_limit`, `validation`, `retrieval_incomplete`, `timeout`, `tool`, `provider_or_execution`입니다. 혼합 예외에서는 timeout을 도구 오류보다 우선 분류합니다. 서버 로그는 역할·분류와 길이 제한된 허용 예외 클래스 체인만 기록하며 원본 provider 응답·예외 내용·키를 기록하지 않습니다. 자료 없음과 조회 실패를 구분합니다. 취소는 실제 asyncio 실행 중단과 MCP/HTTP 자원 정리를 시도합니다. 연결된 provider가 서버 측 계산을 즉시 멈춘다는 보장은 없습니다. SSE 연결만 끊는 것은 취소가 아닙니다.

Loopback 전용, 동일 출처 요청 검사·host 제한을 적용합니다. 계정 인증, 다중 사용자 권한, 영속 복구, 인터넷 공개 운영은 범위 밖입니다. 외부에 포트를 공개하지 마세요.

## 선택: Apple 공식 공개자료 추가 조회

기본은 번들 자료만 사용하는 오프라인 조회입니다. 로컬 `.env`에 `RESEARCH_PUBLIC_SOURCES=1`을 설정하고 서버를 재시작하면 실제 모델 모드에서 고정된 Apple FY2024 Q4 공식 재무 PDF와 실적 발표 페이지를 추가 조회할 수 있습니다. 테스트 모드는 이 옵션이 켜져 있어도 외부 조회를 비활성화합니다. API 키나 유료 검색 서비스는 필요하지 않습니다. 범용 웹 검색·최신 기업정보 조회가 아닙니다.

PDF 파싱은 **Poppler `pdftotext`**가 추가로 필요합니다. 운영자가 설치한 실행 파일을 PATH에 두거나 `RESEARCH_PDFTOTEXT`에 실행 파일 경로를 지정하세요(Windows는 `pdftotext.exe`). 빈 값은 PATH 탐색을 사용합니다. 이 프로젝트는 Poppler를 자동 설치하지 않으며 Windows의 해당 실행 경로는 아직 직접 검증하지 않았습니다. `pdftotext -v`로 설치 여부를 확인할 수 있습니다.

허용된 두 URL만 접근하며 redirect/proxy는 사용하지 않습니다. MCP 세션별 최대 두 번의 HTTP 시도, 응답 6 MiB, 다운로드 6초, PDF 파싱 2초와 성공/실패 캐시를 적용합니다. 전체 원문은 저장하지 않고 필요한 사실 구간과 출처 URL·게시일·조회 시각·바이트 수·SHA-256을 보존합니다. 캐시는 해당 실행의 MCP 세션 동안만 유지됩니다. 재무 표의 gross margin은 **USD millions 금액이며 비율이 아닙니다**.

실제 공개자료 접근만 확인하는 명령(모델 호출 없음):

```powershell
$env:RESEARCH_PUBLIC_SOURCES = "1"
uv run --locked --extra dev python -m mcp_server.smoke_public_sources
```

[실제 조회 기록과 출처](data/public_source_smoke.md)를 참고하세요. 공개 페이지의 향후 접근 가능성·형식은 보장하지 않습니다. 선택적 공개자료의 일반 조회 실패는 `unavailable`로 구분하고, 다른 실제 근거가 있으면 보고서 한계에 명시합니다. 조회 불가 결과는 인용 근거가 아니며 실제 근거가 전혀 없으면 오류로 종료합니다. 보안 경계 위반·도구 예산 초과·MCP 통신 실패는 계속 치명적 오류입니다.

## 검증

```bash
bash scripts/test.sh
# 개별 실행:
uv run --locked --extra dev python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Windows에서는 `.\scripts\test.ps1`을 사용할 수 있습니다. 검증 범위와 남은 항목은 [검증 문서](docs/verification.md), 상태·이벤트 구조는 [아키텍처](docs/architecture.md)를 확인하세요. Python 의존성은 `uv.lock`, frontend는 `frontend/package-lock.json`으로 고정합니다.

소스 공개와 별개로 호스팅된 서비스는 제공하지 않습니다. 앱은 로컬에서 실행되지만, 실제 모델과 선택적 웹 조회는 설정한 외부 서비스로 요청을 전송합니다.
