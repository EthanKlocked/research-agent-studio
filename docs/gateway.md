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
- registry manifest에서 `linux/amd64`, `linux/arm64`를 확인했습니다. macOS Apple Silicon Docker Desktop에서 arm64를 실제 실행했습니다. Windows 실행은 **미검증**입니다.
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
RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway -q
```

테스트는 실제 Proxy와 로컬 HTTP mock upstream을 **고유 Compose project와 임시 loopback 포트**로 시작하고 health를 기다립니다. `.env`를 읽지 않으며 테스트용 키와 mock endpoint를 명시합니다. 모델 API/Exa/Apple 자료 호출은 하지 않습니다. 최초 패키지/이미지 설치는 네트워크가 필요합니다. Docker network가 완전한 egress 방화벽이라고 주장하지 않습니다. image 내부 모델 가격표를 사용하고 telemetry는 비활성화합니다.

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
| 로그 안전 | `proxy_logs` 대신 **전체 테스트** | 전체 failure 시나리오 실행 후 원본 mock 오류/키 미노출 검사 |
| 종료 | 테스트 종료 / `docker compose ls` | 해당 임시 project 제거. image는 재사용하도록 남김 |

테스트 진입점은 `tests/gateway/test_proxy.py`, mock은 `tests/gateway/upstream.py`입니다. mock의 `/control`은 **테스트 전용**이며 실제 gateway에 장애 주입 API를 추가하지 않습니다. 실패/한도 검증을 위해 실제 제공자의 장애를 유발하지 마세요.

## 운영자 설정 후 선택적 실제 연결

**아래 경로는 외부 유료 호출을 발생시킬 수 있습니다. 운영자가 두 endpoint/key와 비용 범위를 확인하고 명시적으로 승인한 뒤에만 호출하세요.** 이 변경의 검증에서는 실행하지 않았습니다. gateway 키와 upstream 키를 혼용하지 마세요.

1. 없는 경우에만 `gateway/.env.example`을 `gateway/.env`로 복사합니다. 기존 파일은 덮어쓰지 않습니다. 로컬 편집기로 값을 채웁니다. UTF-8로 저장하세요. PowerShell 5.1의 기본 `Out-File` UTF-16은 피하세요. 멀티라인 shell 명령을 복사하기보다 아래 한 줄 명령을 사용하세요.
2. `LITELLM_MASTER_KEY`는 gateway 전용 긴 난수 `sk-...` 키입니다. upstream 두 키는 `PRIMARY_API_KEY`, `SECONDARY_API_KEY`입니다. 이 최소 구성은 master key만 사용하므로 **관리자 권한 키**입니다. localhost 단일 운영자 용도에만 사용합니다. 브라우저에 넣지 마세요.
3. 두 모델은 `PRIMARY_MODEL`, `SECONDARY_MODEL`에 `openai/<실제 모델 식별자>` 형식으로 지정합니다. 두 upstream base URL은 해당 chat-completions API의 `/v1` 등을 포함합니다. OpenAI-compatible vLLM도 이 방식으로 연결할 수 있지만 실제 vLLM은 검증하지 않았습니다. 두 모델 모두 tool calling과 역할별 JSON 출력 계약을 지원해야 합니다.
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

호스트 앱의 기존 로컬 `.env`에서 다음 **이름과 값**을 설정합니다. 실제 키는 문서/채팅이 아닌 로컬 편집기에서만 입력하세요:

```dotenv
LLM_PROVIDER=openai-compatible
LLM_MODEL=research-primary
LLM_BASE_URL=http://127.0.0.1:4000/v1
# LLM_API_KEY에는 gateway/.env의 LITELLM_MASTER_KEY와 같은 값을 로컬에서 입력
```

앱 시작: Windows `.\scripts\start.ps1`, macOS `bash scripts/start.sh`. 기존 README의 live smoke 흐름을 따릅니다. `LLM_MODEL=research-secondary`로 변경하고 앱을 재시작하면 명시적 다른 별칭을 사용합니다. **역할별 자동 분배는 없습니다**. 전 역할은 공통 별칭을 사용합니다. fixture 선택 시에는 gateway를 사용하지 않습니다. 직접 연결로 돌아가려면 기존 provider/model/base URL/key 설정으로 되돌리고 앱을 재시작합니다.

기존 질문의 MCP 도구 호출 → 인용 보고서 → 평가까지 확인하세요. 200 응답만으로 JSON/tool 계약 호환성이 검증되지는 않습니다. Gemini 3.x 등 기존 adapter 제한도 그대로입니다. 모델 품질·사실성·과금은 mock 테스트가 검증하지 않습니다.

종료 (앱 터미널 Ctrl+C 후):

```text
docker compose --env-file gateway/.env -f gateway/compose.yaml down
```

## 관측, 한도, 실패 의미

앱 stderr에 `research.model`의 안전한 JSON 기록이 남습니다. 프런트/API에 raw provider metadata를 추가하지 않습니다. 필드:

- `run_id` → 기존 이벤트의 `model_call_id` → 공식 응답 header의 `gateway_call_id` (`x-litellm-call-id`). 응답이 없는 오류/취소에서는 gateway ID가 `null`일 수 있습니다. run/role을 upstream으로 전송하는 임의 metadata는 추가하지 않습니다.
- `model`: 알려진 gateway 별칭. 직접 연결의 임의 모델명은 안전을 위해 `configured-model`로 기록합니다. `gateway_model_id`는 선택된 deployment의 hex hash이며 endpoint/key는 기록하지 않습니다.
- `status`: 모델 요청의 `success`/`error`/`cancelled`, `latency_ms`: 앱에서 관측한 모델 호출 전체 대기 시간. JSON/인용 검증 실패는 그 다음 단계이므로 요청 success가 리서치 success를 뜻하지 않습니다. 역할/run timeout의 task 취소도 모델 로그에는 cancelled로 보일 수 있습니다. 최종 구분은 run 상태/오류를 확인하세요.
- `input_tokens`, `output_tokens`, `total_tokens`: 응답이 보고한 사용량입니다. Proxy가 usage 누락을 0으로 합성하는 경우를 고려하여 **total이 없거나 0이면 모두 unknown (`null`)**으로 기록합니다. 따라서 실제 0-token 응답도 보수적으로 unknown입니다. provider가 추정한 양의 토큰까지 실제 측정인지 판별하지는 못합니다.
- `estimated_cost_usd`, `billing_cost_usd`: 현재 **항상 `null`**. 가격을 등록하지 않았고 실제 청구서를 조회하지 않습니다. Proxy의 가격 추정 header를 실제 비용으로 취급하지 않습니다. vLLM GPU 운영비를 외부 API 토큰 단가로 대체하지 않습니다.

한 번의 사용자 실행 ≠ 역할 수 ≠ 모델 요청 수 ≠ upstream 시도 수입니다. Researcher 도구 왕복·JSON 보정은 모델 요청을 늘리고, fallback은 한 모델 요청 안에서 upstream 시도를 늘립니다. mock 통합은 정상 실행의 모델 요청 7회/upstream 7회, 전 요청 primary 실패 시 7회/14회를 검사합니다. 이 숫자는 live 실행의 고정 호출 수가 아닙니다. MCP 도구 실행 자체는 Proxy를 거치지 않습니다. 전체 upstream 시도·실패 대상의 토큰 비용을 앱의 최종 응답 usage만으로 계산할 수 없습니다.

| 설정 | 범위 / 책임 |
|---|---|
| `LLM_MAX_OUTPUT_TOKENS` | 한 번의 모델 출력 상한. 기본 8192. RPM/TPM/누적 예산이 아님 |
| `rpm: 30` + `enforce_model_rate_limits` | 각 deployment별 실제 요청률 검사. secondary도 별도 30. 하나의 공유 전역 30이 아님. primary 제한에서 secondary fallback이 발생할 수 있음 |
| TPM | 이 구성에는 설정하지 않음. 토큰이 완료 후 알려지므로 공식 제한도 best-effort일 수 있음 |
| 누적 토큰/금액 budget | 이 구성에는 없음. 영속 합산/계정 과금 차단을 보장하지 않음 |
| 앱 OpenAI SDK | `max_retries=0`, 자동 provider retry 없음. JSON/인용 보정은 별도의 최대 1회 요청 |
| Proxy Router / upstream SDK | `num_retries=0`, deployment `max_retries=0`, primary → secondary 최대 fallback 1회. secondary에는 fallback 없음. mock 401/429/503/timeout에서 확인 |
| timeout | upstream attempt 10초, Router timeout 25초. 두 upstream timeout은 2시도 뒤 408을 확인. 앱 요청 기본60/각 역할/전체run600초 중 먼저 도달하는 제한이 우선 |

정상적인 모델 요청 하나는 최대 두 upstream 시도입니다. transport/auth 실패를 앱이 자체 반복하지 않습니다. 모델 JSON 보정은 새 모델 요청이며 별칭의 fallback 규칙이 다시 적용됩니다. 도구 반복·보정은 기존 역할 제한/Researcher 도구12회/최대2회차/전체 run 제한 안에 있습니다. 대기시간 상한은 이벤트루프 정리·네트워크 오버헤드까지 실시간 보장하는 SLA가 아닙니다. 취소는 앱의 asyncio/HTTP/MCP 정리를 시도하지만 gateway/upstream 계산과 청구가 즉시 멈춘다고 보장하지 않습니다.

카운터는 **단일 Proxy process의 메모리**입니다. 재시작하면 사라지고 여러 process/replica 사이에 공유되지 않습니다. 이 설정에서 cooldown은 꺼져 있어 새 요청마다 primary부터 재시도할 수 있습니다. 영속 virtual keys/사용자별 예산/spend tracking에는 PostgreSQL이 필요하고 분산 카운터에는 Redis 등이 필요합니다. OSS Proxy의 master-key auth/aliases/fallback/model rate limit을 사용하며 DB·Redis·유료 라이선스를 요구하지 않습니다. per-request callback 선택적 비활성화나 일부 기업용 tracing/SSO/감사 기능은 Enterprise일 수 있습니다. 본 구성은 그 기능이나 별도의 tracing 환경을 구축했다고 주장하지 않습니다.

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
