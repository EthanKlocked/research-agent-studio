# 선택형 LiteLLM Gateway

## 경계와 구성

```text
로컬 React → FastAPI / LangGraph / AgentFactory / ChatOpenAI
                                 ├─ 직접 provider (기존)
                                 └─ localhost:4000 LiteLLM Proxy (선택)
                                      ├─ research-primary → primary endpoint
                                      └─ research-secondary → secondary endpoint
Researcher → 읽기 전용 MCP stdio (Proxy를 거치지 않음)
```

LiteLLM은 추론 엔진이 아니라 모델 접근 게이트웨이입니다. 앱/프론트/MCP는 계속 호스트에서 실행하고 Proxy만 별도 컨테이너로 실행합니다. fixture 모드는 Proxy에 연결하지 않습니다. GPU/vLLM 실행, Kubernetes, Langfuse tracing, 다중 사용자/HA/인터넷 공개 운영은 포함하지 않습니다. 평가·재계획 정책은 변경하지 않았습니다.

- 고정 이미지: `ghcr.io/berriai/litellm:v1.103.2@sha256:f63fb81b831b170ec16851e23c36ac5bf52ef106b271406429524a2ed730bbfd`.
- registry manifest에서 `linux/amd64`, `linux/arm64`를 확인했습니다. macOS Apple Silicon Docker Desktop에서 arm64를 실제 실행했습니다. Windows는 아래 사용자 보고만 있으며, 이 변경의 작성자가 직접 실행하지 않았습니다.
- 공식 [release](https://github.com/BerriAI/litellm/releases/tag/v1.103.2), [배포와 이미지](https://docs.litellm.ai/docs/proxy/deploy), [환경변수/설정](https://docs.litellm.ai/docs/proxy/config_settings), [라우팅/실제 제한](https://docs.litellm.ai/docs/proxy/load_balancing), [fallback](https://docs.litellm.ai/docs/proxy/reliability), [응답 ID/안전한 로깅](https://docs.litellm.ai/docs/proxy/logging).
- 위 문서는 최신 버전으로 변경될 수 있습니다. 여기서 주장하는 동작은 이 digest의 mock 통합 테스트 범위입니다. 고정은 최신 보안 패치를 자동 적용한다는 뜻이 아닙니다. 업데이트 시 같은 테스트를 다시 실행하세요.

## 먼저: 키 없는 검증 (모델 응답·토큰 모두 mock)

저장소 루트에서 실행하세요. Python 3.12 / uv 및 실행 중인 Docker Desktop + Compose v2가 필요합니다. Windows에서는 Docker Desktop의 Linux containers / WSL2 backend 요구사항을 운영자가 확인하세요. 이 프로젝트는 Docker/WSL2/가상화/시스템 정책을 설치하거나 변경하지 않습니다.

### Windows PowerShell

```powershell
docker version
docker compose version
uv sync --locked --extra dev
docker pull ghcr.io/berriai/litellm:v1.103.2@sha256:f63fb81b831b170ec16851e23c36ac5bf52ef106b271406429524a2ed730bbfd
docker image inspect ghcr.io/berriai/litellm:v1.103.2@sha256:f63fb81b831b170ec16851e23c36ac5bf52ef106b271406429524a2ed730bbfd --format "{{.Id}}"
$previousGatewayTest = $env:RAS_GATEWAY_TEST
$previousDotenv = $env:PYTHON_DOTENV_DISABLED
try {
    $env:RAS_GATEWAY_TEST = '1'
    $env:PYTHON_DOTENV_DISABLED = '1'
    uv run --locked --extra dev python -m pytest tests/gateway -q
} finally {
    $env:RAS_GATEWAY_TEST = $previousGatewayTest
    $env:PYTHON_DOTENV_DISABLED = $previousDotenv
}
```

### macOS Bash

```bash
docker version
docker compose version
uv sync --locked --extra dev
docker pull ghcr.io/berriai/litellm:v1.103.2@sha256:f63fb81b831b170ec16851e23c36ac5bf52ef106b271406429524a2ed730bbfd
docker image inspect ghcr.io/berriai/litellm:v1.103.2@sha256:f63fb81b831b170ec16851e23c36ac5bf52ef106b271406429524a2ed730bbfd --format "{{.Id}}"
RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway -q
```

테스트는 실제 Proxy와 로컬 HTTP mock upstream을 **고유 Compose project와 임시 loopback 포트**로 시작하고 health를 기다립니다. `.env`를 읽지 않으며 테스트용 키와 mock endpoint를 명시합니다. 모델 API/Exa/Apple 자료 호출은 하지 않습니다. 최초 패키지/이미지 설치는 네트워크가 필요합니다. Docker network가 완전한 egress 방화벽이라고 주장하지 않습니다. image 내부 모델 가격표를 사용하고 telemetry는 비활성화합니다.

`--pull never`로 실행하므로 **위의 정확한 digest pull/inspect 성공이 필수**입니다. 이미지가 없거나 daemon에 연결하지 못하면 preflight가 pull 명령과 함께 실패합니다. 이 실패나 opt-in 미설정에 따른 skip은 실제 Proxy 검증 성공이 아닙니다.

예상 결과 형태: `... passed`. 이것은 live 품질 검증이 아닙니다. 실패해도 `finally`에서 테스트 project만 `down` 합니다. 강제 프로세스 종료로 남았다면 `docker compose ls`에서 `ras-gateway-test-...` 이름을 확인하고 **그 project만** `docker compose -p <확인한-project> -f gateway/compose.mock.yaml down --volumes --remove-orphans`로 정리하세요. 다른 서비스는 종료하지 마세요.

### 단계별 학습 체크리스트

위 pytest 명령에 `-k <이름>`을 추가하면 해당 단계만 독립 stack에서 실행합니다. PowerShell에서는 `try` 블록 안 명령을 바꾸세요. 예상값과 관측 기록을 구분하세요.

| 단계 / 목적 | `-k` 이름 또는 명령 | 예상 결과 / 실패 시 확인 |
|---|---|---|
| 설치·기동·health | `docker version`, 전체 테스트 | daemon 연결, `/health/liveliness` 200. 실패: Desktop/이미지/포트/Compose 상태 |
| 정상 별칭·다른 별칭 | `auth_and_aliases` | 두 별칭 200, 실제 upstream 모델 구분, mock usage 11/7/18 |
| 누락·잘못된 인증 | `auth_and_aliases` | 누락 401, 잘못된 키 400, upstream 시도 0. 이 버전의 no-DB 동작 |
| fallback | `fallback_actual_upstream_count` | mock 401/429/503 뒤 secondary 성공, upstream 정확히 2회 |
| usage 누락 | `missing_usage` | app 관측 토큰/가격 `null`, `usage_source=unknown` |
| 실제 제한 | `real_rpm_limiter` | secondary 한도 초과 429, 거절 요청은 upstream에 도달하지 않음 |
| 전체 리서치 | `real_graph_mcp` | 실제 graph/MCP/tool calls/JSON/Reporter/Evaluator 통과; 모델만 mock |
| timeout·취소 | `timeout or deadline` | primary timeout 후 fallback, 양쪽 timeout 408; run 제한/취소는 실패/취소로 종료 |
| 로그 안전 | `proxy_logs` | 독립 실행도 primary 오류/fallback을 직접 발생시킨 후 stdout/stderr에 원본 mock 오류/키 미노출 검사 |
| 종료 | 테스트 종료 / `docker compose ls` | 해당 임시 project 제거. image는 재사용하도록 남김 |

테스트 진입점은 `tests/gateway/test_proxy.py`, mock은 `tests/gateway/upstream.py`입니다. mock의 `/control`은 **테스트 전용**이며 실제 gateway에 장애 주입 API를 추가하지 않습니다. 실패/한도 검증을 위해 실제 제공자의 장애를 유발하지 마세요.

## 운영자 설정 후 선택적 실제 연결

**아래 경로는 외부 유료 호출을 발생시킬 수 있습니다. 운영자가 두 endpoint/key와 비용 범위를 확인하고 명시적으로 승인한 뒤에만 호출하세요.** 이 변경의 검증에서는 실행하지 않았습니다. gateway 키와 upstream 키를 혼용하지 마세요.

1. 없는 경우에만 `gateway/.env.example`을 `gateway/.env`로 복사합니다. 기존 파일은 덮어쓰지 않습니다. 로컬 편집기로 값을 채웁니다. UTF-8로 저장하세요. PowerShell 5.1의 기본 `Out-File` UTF-16은 피하세요. 멀티라인 shell 명령을 복사하기보다 아래 한 줄 명령을 사용하세요.
2. `LITELLM_MASTER_KEY`는 gateway 전용 긴 난수 `sk-...` 키입니다. upstream 두 키는 `PRIMARY_API_KEY`, `SECONDARY_API_KEY`입니다. 이 최소 구성은 master key만 사용하므로 **관리자 권한 키**입니다. localhost 단일 운영자 용도에만 사용합니다. 브라우저에 넣지 마세요.
3. 두 모델은 `PRIMARY_MODEL`, `SECONDARY_MODEL`에 `openai/<실제 모델 식별자>` 형식으로 지정합니다. 두 upstream base URL은 해당 chat-completions API의 `/v1` 등을 포함합니다. OpenAI-compatible vLLM도 이 방식으로 연결할 수 있지만 실제 vLLM은 검증하지 않았습니다. 두 모델 모두 tool calling과 역할별 JSON 출력 계약을 지원해야 합니다. **secondary는 primary와 동등하거나 더 나은 역할 수행 품질을 권장**합니다. 저렴한 연결 가능한 모델이라는 이유만으로 고르지 마세요. Planner의 계획/스키마, Researcher의 도구 사용·근거 수집을 포함한 전체 역할과 반복 질문으로 평가하세요.
4. 외부 upstream은 HTTPS를 사용하세요. Docker 안의 `localhost`는 호스트가 아니라 컨테이너 자신입니다. Docker Desktop에서 별도로 실행 중인 호스트 모델 서버는 `host.docker.internal`을 검토하고 그 서버의 접근·바인딩 정책을 확인하세요. Linux Docker Engine은 별도 호스트 연결 설정이 필요할 수 있으며 여기서 검증하지 않았습니다. 앱의 loopback HTTP/원격 HTTPS URL 검증은 완화하지 않았습니다.

복사 명령 (각 OS에서 파일 존재 여부를 먼저 확인):

```powershell
if (-not (Test-Path gateway/.env)) { Copy-Item gateway/.env.example gateway/.env }
```

```bash
[ -e gateway/.env ] || cp gateway/.env.example gateway/.env
```

Windows/macOS 공통 명령 (저장소 루트):

```text
docker compose --env-file gateway/.env -f gateway/compose.yaml config --quiet
docker compose --env-file gateway/.env -f gateway/compose.yaml up -d --wait
docker compose --env-file gateway/.env -f gateway/compose.yaml ps
```

`config --quiet`는 비밀값을 출력하지 않고 구조만 검증합니다. 일반 `config`, `docker inspect`와 debug 로그는 키를 노출할 수 있으므로 공유하지 마세요. health는 프로세스 생존을 확인할 뿐 upstream 인증 성공을 뜻하지 않습니다. 포트 4000이 이미 쓰이면 기존 서비스를 중단하지 말고 이 Compose의 host port와 앱 base URL을 함께 변경하세요.

호스트 앱의 기존 로컬 `.env`에 **`gateway/app.env.example`의 설정을 병합**하세요. 기존 키/검색 설정을 덮어쓰지 마세요. gateway 전용 timeout profile과 관측 opt-in이 필요합니다. 다음 **이름과 값**을 설정합니다. 실제 키는 문서/채팅이 아닌 로컬 편집기에서만 입력하세요:

```dotenv
LLM_PROVIDER=openai-compatible
LLM_MODEL=research-primary
LLM_BASE_URL=http://127.0.0.1:4000/v1
LLM_GATEWAY_OBSERVATION=1
LLM_REQUEST_TIMEOUT=130
LISTENER_TIMEOUT=270
PLANNER_TIMEOUT=270
RESEARCHER_TIMEOUT=600
REPORTER_TIMEOUT=270
EVALUATOR_TIMEOUT=270
RUN_TIMEOUT=1800
# LLM_API_KEY에는 gateway/.env의 LITELLM_MASTER_KEY와 같은 값을 로컬에서 입력
```

앱 시작: Windows `.\scripts\start.ps1`, macOS `bash scripts/start.sh`. 기존 README의 live smoke 흐름을 따릅니다. `LLM_MODEL=research-secondary`로 변경하고 앱을 재시작하면 명시적 다른 별칭을 사용합니다. **역할별 자동 분배는 없습니다**. 전 역할은 공통 별칭을 사용합니다. fixture 선택 시에는 gateway를 사용하지 않습니다. 직접 연결로 돌아가려면 기존 provider/model/base URL/key 설정으로 되돌리고 앱을 재시작합니다.

기존 질문의 MCP 도구 호출 → 인용 보고서 → 평가까지 확인하세요. 200 응답만으로 JSON/tool 계약 호환성이 검증되지는 않습니다. Gemini 3.x 등 기존 adapter 제한도 그대로입니다. 모델 품질·사실성·과금은 mock 테스트가 검증하지 않습니다.

종료 (앱 터미널 Ctrl+C 후):

```text
docker compose --env-file gateway/.env -f gateway/compose.yaml down
```

## 관측, 한도, 실패 의미

앱 stderr에 `research.model`의 안전한 JSON 기록이 남습니다. 같은 allowlist 기록은 `model_complete.data.observation`으로 전달되며, 작업 상세 타임라인과 최근 공개 활동에 `served_by` / `fallback`을 표시합니다. raw provider metadata/응답 body model/header 전체/endpoint/key는 공개하지 않습니다. underlying model 이름은 아래 별도 공개 allowlist에 등록하고 header와 정확히 일치할 때만 표시합니다. 필드:

- `run_id` → 기존 이벤트의 `model_call_id` → 공식 응답 header의 `gateway_call_id` (`x-litellm-call-id`). 응답이 없는 오류/취소에서는 gateway ID가 `null`일 수 있습니다. run/role을 upstream으로 전송하는 임의 metadata는 추가하지 않습니다.
- `model`: **요청한** 알려진 별칭입니다. 직접 연결의 임의 모델명은 `configured-model`입니다. 실제 응답 body의 `model`은 정상 경로에서 요청 별칭, fallback에서 upstream 이름이 될 수 있으므로 served 모델 판정에 쓰지 않습니다.
- `gateway_model_id`: 검증한 `x-litellm-model-id` 응답값입니다. 번들 config의 명시적 `model_info.id` (`01` × 32 → primary, `02` × 32 → secondary)만 안전한 별칭으로 해석합니다. 자동 생성 hash를 키/URL로 역산하거나 임의 header/model 이름을 그대로 공개하지 않습니다.
- `served_by`: 해당 응답을 완료한 실제 deployment의 **공개 별칭**, upstream의 사적인 모델 문자열이 아닙니다. `LLM_GATEWAY_OBSERVATION=1`과 번들 ID 매핑을 함께 쓸 때만 해석합니다. 구 config/임의 proxy/알 수 없는 ID/직접 연결은 `null` (`unknown`)입니다. custom deployments를 추가할 때 이 ID를 다른 별칭에 재사용하지 마세요.
- `gateway_model_name`: `x-litellm-model-name`은 고정 버전에서 Router metadata의 실제 deployment 문자열(`litellm_params.model`, 예: `openai/<model>`)입니다. **`LLM_GATEWAY_MODEL_NAMES_JSON`의 served 별칭에 등록한 공개 이름과 정확히 일치할 때만** 기록합니다. 미등록/누락/불일치면 `null`. 본문 model 값으로 대신 채우지 않습니다.
- `attempted_fallbacks`: `x-litellm-attempted-fallbacks`가 제공한 비음수 정수(최대 9자리)만 기록합니다. 실제 pinned mock 응답에서 primary 정상은0, primary 실패 후 secondary 성공은1을 확인했습니다. 전체 upstream 요청 수/재시도 수와 같지 않습니다.
- `rate_limit_remaining_requests`: 같은 이름의 `x-ratelimit-remaining-requests` header를 비음수 정수(최대 9자리)로 기록합니다. 현재 단일 process/각 deployment30 설정의 초기 응답에서29를 확인했습니다. 다른 제공자/구성에서는 범위가 달라질 수 있으며 사용자 계정 전체 잔액·전역 예산·남은 실행 수로 해석하지 않습니다. 모든 선택적 header는 누락/잘못된 형식이면 `null`; HTTP header 전체를 전달하지 않습니다.
- `fallback`: opt-in된 gateway의 유효한 attempted-fallbacks header가 있으면 그 값이0보다 클 때 `true`,0이면 `false`. header가 없으면 번들의 알려진 requested/served 별칭 비교로 보수적으로 판정하며, 판단할 자료가 없으면 `null`. 명시적 secondary 요청의 secondary 응답은 `false`입니다. 이 값은 upstream 연산 중단 증명이 아닙니다. header가 없는 실패/취소는 unknown이며 성공 이벤트를 만들지 않습니다. 오래된 이벤트/fixture에는 observation이 없어도 기존 UI가 유지됩니다.
- `status`: 모델 요청의 `success`/`error`/`cancelled`, `latency_ms`: 앱에서 관측한 모델 호출 전체 대기 시간. JSON/인용 검증 실패는 그 다음 단계이므로 요청 success가 리서치 success를 뜻하지 않습니다. 역할/run timeout의 task 취소도 모델 로그에는 cancelled로 보일 수 있습니다. 최종 구분은 run 상태/오류를 확인하세요.
- `input_tokens`, `output_tokens`, `total_tokens`: 응답이 보고한 사용량입니다. Proxy가 usage 누락을 0으로 합성하는 경우를 고려하여 **total이 없거나 0이면 모두 unknown (`null`)**으로 기록합니다. 따라서 실제 0-token 응답도 보수적으로 unknown입니다. provider가 추정한 양의 토큰까지 실제 측정인지 판별하지는 못합니다.
- `reasoning_tokens`: 응답 `usage.completion_tokens_details.reasoning_tokens`에 명시된 비음수 정수만 기록합니다. 숫자가 없으면 `null`, 차액에서 추측하지 않습니다. total이 누락돼도 이 명시적 detail은 독립적으로 보존합니다. 다른 제공자 전용 필드를 임의로 reasoning으로 해석하지 않습니다.
- `unexplained_token_residual`: 알려진 `total - input - output`입니다. 음수도 데이터 불일치로 보존합니다. 필요한 수치가 없으면 `null`. **reasoning과 별도**이며 reasoning 수치를 residual에서 빼거나 total에 더하지 않습니다.
- `estimated_cost_usd`: 명시적으로 등록한 단가 × 최종 응답 input/output의 단순 추정치. 아래 가격 설정이 없거나 served 별칭/필수 사용량이 불명확하거나 residual이 0이 아니면 `null`입니다. `billing_cost_usd`는 항상 `null`입니다. 실제 청구서를 조회하지 않으며 Proxy 비용 header를 청구액으로 쓰지 않습니다.

공개 underlying 이름 표시가 필요하면 호스트 `.env`에 별칭별 **실제로 설정한 공개 모델명**을 명시하세요. 아래는 mock 예시일 뿐 실제 모델명이 아닙니다. gateway의 `PRIMARY_MODEL`/`SECONDARY_MODEL` 문자열과 정확히 맞아야 합니다:

```dotenv
LLM_GATEWAY_MODEL_NAMES_JSON={"research-primary":"openai/mock-primary","research-secondary":"openai/mock-secondary"}
```

기본 `{}`이면 served 별칭/fallback은 여전히 표시하되 underlying model 이름만 unknown입니다. 사용자 전용 deployment 이름에 민감한 정보가 있으면 등록하지 마세요. 임의 proxy가 보낸 이름을 자동으로 신뢰·공개하지 않기 위한 별도 opt-in입니다.

### 토큰 차액과 선택적 가격

사용자 보고의 **31 요청, total 128307, input+output 120369** 차이는 **7938**입니다. 원본 요청별 usage details가 제공되지 않아 그 차이를 reasoning으로 확정할 수 없습니다. 캐시/도구/제공자 집계·변환 방식도 요청별 계약을 확인해야 합니다. 이 집계만으로 모델별 단가나 실제 비용을 복원하지 않습니다.

고정 LiteLLM 1.103.2의 native Gemini 변환 코드(`llms/vertex_ai/gemini/vertex_and_google_ai_studio_gemini.py:1884–1919`)는 `thoughtsTokenCount`를 reasoning details에 넣고, candidate count 포함 여부에 따라 reasoning을 completion count에 이미 포함합니다. 그러나 번들 설정은 `openai/<model>` 경로이므로 사용자의 Gemini OpenAI-compatible endpoint가 native 변환과 같은 usage를 보냈다고 가정하지 않습니다. 테스트는 명시적인 OpenAI-compatible reasoning details 전달과 미설명 residual 보존을 각각 검증합니다. **output + reasoning을 다시 합산하면 중복 계산할 수 있습니다.**

호스트 `.env`의 `LLM_TOKEN_PRICES_JSON={}`가 기본(unknown)입니다. 다음은 계산법을 보여 주는 **가상 단가**, 실제 모델 가격이 아닙니다:

```dotenv
LLM_TOKEN_PRICES_JSON={"research-primary":{"input":2,"output":4},"research-secondary":{"input":3,"output":6}}
```

단위는 USD / 백만 토큰입니다. 번들은 별칭마다 deployment가 하나이므로 각 항목이 해당 deployment의 단가입니다. 별칭 아래 여러 deployment/가격을 추가하는 확장은 현재 매핑의 범위 밖입니다. 각 별칭에 input/output 둘 다 필요하고 유한 비음수 숫자만 허용합니다. 0은 명시적인 무료 단가로만 인정하며 누락을 0으로 치환하지 않습니다. 직접 연결에는 별도로 `configured-model` 키를 사용합니다. 계산식은 `(input_tokens × input_rate + output_tokens × output_rate) / 1000000`. 예: input100/output50, 2/4 단가 → `$0.0004`; output50 안에 reasoning20이 보고되어도 추가하지 않습니다. fallback이면 **served secondary 단가**를 사용합니다. 캐시 할인/계층 요금/도구 비용/실패한 upstream 시도는 반영하지 않는 추정치이며, 제공자 청구액이나 모든 upstream 시도를 포함한 총 실제 실행 비용이 아닙니다. 단가 변경 시 앱을 재시작하세요. vLLM GPU 운영비를 API 토큰 단가처럼 꾸미지 마세요.

### 실행별 추정 비용 합계

Progress의 실행 추정 비용은 서버 snapshot의 `cost_summary`를 사용합니다. `model_call_id`별 최종 응답 추정을 한 번만 합산하며, 시작했지만 실패/취소/응답 미확인인 호출도 unknown 요청으로 셉니다. 전체 이벤트를 유지하거나 브라우저에서 재합산하지 않으므로 SSE 중복/재연결·이벤트150건 축약으로 중복 계산하거나 소계를 잃지 않습니다. 서버 재시작/기존 run 제거 후에는 유지되지 않습니다.

- `model_requests`, `priced_requests`, `unknown_requests`: 앱 모델 요청 단위의 전체/추정 가능/미확인 개수. upstream fallback 시도 수가 아닙니다.
- `known_estimated_cost_usd`: 알려진 요청의 소계, 알려진 값이 하나도 없으면 `null`입니다.
- `estimated_cost_usd`: 관측된 모든 앱 요청의 단가/사용량을 알 때만 소계와 같고, 하나라도 unknown이면 `null`입니다. 실행 중에는 **현재까지**의 요청 기준이며 미래 요청 비용을 예측하지 않습니다.
- `estimate_status`: `complete`/`partial`/`unknown`은 비용 정보의 완전성이지 실행 성공 여부가 아닙니다. 일부만 알면 UI는 total `unknown`과 알려진 소계를 함께 표시합니다. fixture 실행은 실제 비용을 만들지 않으며 summary는 `null`입니다.

예: 가상 단가로 계산한 두 응답이 `$0.00005`, `$0.000075`면 알려진 소계 `$0.000125`; 세 번째 요청의 가격/사용량이 unknown이면 전체 추정 합계는 **unknown**, 미확인1/3입니다. 명시적0단가만0으로 인정합니다. reasoning은 output에 중복 가산하지 않습니다. 이 합계 역시 실제 청구액이 아니며 숨겨진 실패 upstream 시도/캐시·도구요금을 제외합니다.

한 번의 사용자 실행 ≠ 역할 수 ≠ 모델 요청 수 ≠ upstream 시도 수입니다. Researcher 도구 왕복·JSON 보정은 모델 요청을 늘리고, fallback은 한 모델 요청 안에서 upstream 시도를 늘립니다. mock 통합은 정상 실행의 모델 요청 7회/upstream 7회, 전 요청 primary 실패 시 7회/14회를 검사합니다. 이 숫자는 live 실행의 고정 호출 수가 아닙니다. MCP 도구 실행 자체는 Proxy를 거치지 않습니다. 전체 upstream 시도·실패 대상의 토큰 비용을 앱의 최종 응답 usage만으로 계산할 수 없습니다.

| 설정 | 범위 / 책임 |
|---|---|
| `LLM_MAX_OUTPUT_TOKENS` | 한 번의 모델 출력 상한. 기본 8192. RPM/TPM/누적 예산이 아님 |
| `rpm: 30` + `enforce_model_rate_limits` | 각 deployment별 실제 요청률 검사. secondary도 별도 30. 하나의 공유 전역 30이 아님. primary 제한에서 secondary fallback이 발생할 수 있음 |
| TPM | 이 구성에는 설정하지 않음. 토큰이 완료 후 알려지므로 공식 제한도 best-effort일 수 있음 |
| 누적 토큰/금액 budget | 이 구성에는 없음. 영속 합산/계정 과금 차단을 보장하지 않음 |
| 앱 OpenAI SDK | `max_retries=0`, 자동 provider retry 없음. JSON/인용 보정은 별도의 최대 1회 요청 |
| Proxy Router / upstream SDK | `num_retries=0`, deployment `max_retries=0`, primary → secondary 최대 fallback 1회. secondary에는 fallback 없음. mock 401/429/503/timeout에서 확인 |
| timeout | operator config: 각 upstream60초 × 최대2시도 < Router125초 < gateway app profile 요청130초. Listener/Planner/Reporter/Evaluator270초, Researcher600초, 전체run1800초. 먼저 도달하는 상위 제한이 우선 |

직접 연결 기본값(request60초, 기존 역할/run 제한)은 변경하지 않았습니다. **관측 opt-in만 켜도 timeout이 자동 변경되지는 않습니다**. gateway profile을 병합하지 않고 앱 기본60초를 유지하면 primary가 오래 걸린 뒤 fallback할 시간이 부족합니다. timeout을 조정할 때 `gateway/config.yaml`의 deployment timeout 둘과 `litellm_settings.request_timeout`, Router 총 제한, 앱 request/role/run을 함께 변경하고 gateway 및 앱을 재시작하세요. 권장 관계는 `primary + secondary < router < client`, 역할은 필요한 요청 수(보정 포함) × client + 도구 여유, run은 전체 역할/회차 정책에 맞춘 총 상한입니다. Researcher의 모든 가능한 도구 왕복/2회차 전부가 최대시간을 쓸 수 있다고 보장하는 값은 아닙니다.

mock 실패 테스트만 임시 config의 attempt1초/Router3초로 단축합니다. operator config는 변경 없이 12초 mock primary가 secondary로 넘어가지 않고 성공하는 회귀 테스트를 별도로 실행합니다. 이것은 실제 모델 지연/품질 검증이 아닙니다.

정상적인 모델 요청 하나는 최대 두 upstream 시도입니다. transport/auth 실패를 앱이 자체 반복하지 않습니다. 모델 JSON 보정은 새 모델 요청이며 별칭의 fallback 규칙이 다시 적용됩니다. 도구 반복·보정은 기존 역할 제한/Researcher 도구12회/최대2회차/전체 run 제한 안에 있습니다. 대기시간 상한은 이벤트루프 정리·네트워크 오버헤드까지 실시간 보장하는 SLA가 아닙니다. 취소는 앱의 asyncio/HTTP/MCP 정리를 시도하지만 gateway/upstream 계산과 청구가 즉시 멈춘다고 보장하지 않습니다.

카운터는 **단일 Proxy process의 메모리**입니다. 재시작하면 사라지고 여러 process/replica 사이에 공유되지 않습니다. 이 설정에서 cooldown은 꺼져 있어 새 요청마다 primary부터 재시도할 수 있습니다. 영속 virtual keys/사용자별 예산/spend tracking에는 PostgreSQL이 필요하고 분산 카운터에는 Redis 등이 필요합니다. OSS Proxy의 master-key auth/aliases/fallback/model rate limit을 사용하며 DB·Redis·유료 라이선스를 요구하지 않습니다. per-request callback 선택적 비활성화나 일부 기업용 tracing/SSO/감사 기능은 Enterprise일 수 있습니다. 본 구성은 그 기능이나 별도의 tracing 환경을 구축했다고 주장하지 않습니다.

## 사용자 보고 — 직접 재검증과 구분

출처: 이번 gateway 런타임 피드백의 사용자 직접 실행 보고(아래는 작성자의 live/Windows 실실행 결과가 아님).

- Windows / Docker Desktop **4.93** / Engine **29.8.1** / WSL2: mock **14 passed**, live gateway **4/4 성공**으로 보고되었습니다. 버전 표기는 사용자 제공값 그대로이며, commit SHA·Windows build·Compose/Python 세부 버전은 이 보고에서 독립 확인하지 않았습니다. 현재 변경을 그 환경에서 검증했다는 의미가 아닙니다.
- `gemini2.5flash-lite` standalone web **0/3**, 이번 gateway trial에서 Planner/Researcher 실패, Reporter/Evaluator 성공을 보고했습니다. 질문·프롬프트·역할·설정에 종속된 사용자 관측이며 모델 일반 성능의 보편적 결론/벤치마크가 아닙니다. fallback 품질을 primary 동급 이상으로 고르고 전체 역할을 검증할 이유입니다.
- 잘못된 key의 **400 / `No connected db.`**는 고정 버전 master-key/no-DB 구성에서 재현되는 거절입니다. 관리형 virtual key 조회를 위한 DB가 없다는 뜻이지 이 경로를 쓰기 위해 DB를 설치하라는 요구가 아닙니다. 누락 키는401이며 두 경우 모두 upstream 호출이 없어야 합니다. gateway master key를 로컬에서 확인하고 upstream key와 혼용하지 마세요.

## Windows 실행 결과 기록 (사용자 직접 작성)

아래는 **빈 기록 양식**, 실행 증거가 아닙니다.

```text
OS / PowerShell / Python / Docker Desktop / Compose:
git rev-parse HEAD:
모드: mock / 별도 승인 live
실행 명령:
결과(통과/실패, 안전한 HTTP 상태/요청 ID):
정상 별칭 / 다른 별칭 / 잘못된 인증:
fallback / limiter / usage unknown:
전체 리서치 / JSON / MCP / 보고서 / 평가:
취소 / timeout / 정리:
미확인 항목:
```

확인 후 설명해 볼 질문: 왜 직접 연결 대신 gateway를 두는가? 역할 수와 모델/upstream 호출 수는 왜 다른가? fallback과 Evaluator 재조사는 무엇이 다른가? 누락 usage를 0원으로 볼 수 있는가? 취소와 로컬 RPM 한도가 provider 청구를 보장하지 못하는 이유는 무엇인가?
