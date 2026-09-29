import { useEffect, useRef, useState } from "react";
import { request } from "./api";
import { isComplete, safeUrl } from "./state";
import { useRun } from "./useRun";
import type { Config, Report, RunEvent, Stage } from "./types";
const stages: { id: Stage; label: string; active: string }[] = [
  { id: "Listener", label: "요청 해석", active: "요청 해석 중" },
  { id: "Planner", label: "조사 계획", active: "조사 계획 중" },
  { id: "Researcher", label: "근거 수집", active: "근거 수집 중" },
  { id: "Reporter", label: "보고서 작성", active: "보고서 작성 중" },
  { id: "Evaluator", label: "결과 평가", active: "결과 평가 중" },
];
const statusText = {
  queued: "실행 대기 중",
  running: "조사 중",
  success: "조사가 완료되었습니다",
  limit_reached: "반복 한도에 도달했습니다",
  empty: "관련 근거를 찾지 못했습니다",
  error: "조사 중 오류가 발생했습니다",
  cancelled: "실행이 중단되었습니다",
};
const eventLabels: Record<string, string> = {
  node_start: "단계 시작",
  node_complete: "단계 완료",
  tool_start: "도구 호출",
  tool_complete: "도구 완료",
  tool_error: "도구 입력 오류",
  evaluation: "결과 평가",
  branch: "분기 결정",
  terminal: "실행 종료",
};
function List({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? (
    <ul className="text-list">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  ) : (
    <p className="muted small">{empty}</p>
  );
}
function elapsed(start?: string, end?: string | null) {
  if (!start) return "—";
  const ms = (end ? Date.parse(end) : Date.now()) - Date.parse(start);
  if (!Number.isFinite(ms)) return "—";
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}
function ReportBody({
  report,
  onCitation,
}: {
  report: Report;
  onCitation: (id: string) => void;
}) {
  return (
    <>
      <h2 className="report-title">{report.title}</h2>
      <p className="report-summary">{report.summary}</p>
      <div className="section-heading">
        <span>핵심 발견</span>
        <span className="muted">근거와 함께 읽기</span>
      </div>
      <ol className="claims">
        {report.claims.map((claim, i) => (
          <li key={i}>
            <span className="claim-index">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div>
              <p>{claim.text}</p>
              <div className="citations">
                {claim.citation_ids.map((id) => (
                  <button
                    key={id}
                    className="citation"
                    aria-label={`출처 ${id} 보기`}
                    onClick={() => onCitation(id)}
                  >
                    ↗ {id}
                  </button>
                ))}
              </div>
            </div>
          </li>
        ))}
      </ol>
      {report.limitations.length > 0 && (
        <section className="limitations">
          <h3>해석의 한계</h3>
          <List items={report.limitations} empty="" />
        </section>
      )}
    </>
  );
}
function safeEvent(event: RunEvent) {
  const d = event.data;
  return [
    eventLabels[event.type] ?? "상태 갱신",
    d.tool_name || d.tool,
    d.input_summary,
    typeof d.count === "number" ? `결과 ${d.count}건` : null,
    (d.state_fields || d.changed_fields)?.join(", "),
    d.reason,
  ]
    .filter(Boolean)
    .join(" · ");
}
export default function App() {
  const [config, setConfig] = useState<Config | null>(null),
    [configError, setConfigError] = useState(""),
    [question, setQuestion] = useState(""),
    [mode, setMode] = useState<"test" | "live">("test"),
    [scenario, setScenario] = useState("revise"),
    [revision, setRevision] = useState<number | null>(null),
    [source, setSource] = useState<string | null>(null),
    [, tick] = useState(0);
  const sourcePanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (source) sourcePanel.current?.focus();
  }, [source]);
  const run = useRun(),
    s = run.snapshot;
  const active = !!s && !isComplete(s),
    busy = active || run.pending;
  useEffect(() => {
    let mounted = true;
    request<Config>("/api/config")
      .then((c) => {
        if (mounted) {
          setConfig(c);
          if (!c.test_mode_available && c.configured) setMode("live");
        }
      })
      .catch((e) => {
        if (mounted) setConfigError(e.message);
      });
    return () => {
      mounted = false;
    };
  }, []);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [active]);
  useEffect(() => {
    setRevision(null);
    setSource(null);
    if (s?.question) setQuestion(s.question);
  }, [s?.run_id]);
  const revisions = s?.revisions ?? [],
    selected =
      revision === null
        ? revisions.at(-1)
        : revisions.find((r) => r.iteration === revision),
    report = selected?.report ?? s?.report;
  const previous = selected
    ? revisions.filter((r) => r.iteration < selected.iteration).at(-1)
    : undefined;
  const evidence = s?.evidence.find((e) => e.id === source);
  const evidenceUrl = evidence ? safeUrl(evidence.url) : null;
  const actualMode = s?.mode ?? mode;
  const tools = run.events.filter(
    (e) => e.type === "tool_start" || e.type === "tool_complete" || e.type === "tool_error",
  );
  const currentLabel = active
    ? (stages.find((stage) => stage.id === s?.stage)?.active ?? "실행 대기 중")
    : s
      ? statusText[s.status]
      : "질문을 기다리고 있습니다";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#report">
        보고서로 건너뛰기
      </a>
      <header className="topbar">
        <a href="#" className="brand">
          <span className="brand-mark" aria-hidden="true">
            r<span>•</span>
          </span>
          <span>
            Research Agent <strong>Studio</strong>
          </span>
        </a>
        <div className="topbar-note">
          <span className="tiny-dot" /> 공개 데이터 기반 독립 구현{" "}
          <span className="local-label">LOCAL WORKBENCH</span>
        </div>
      </header>
      <main>
        <section className="intro">
          <div>
            <p className="eyebrow">EVIDENCE-LED RESEARCH</p>
            <h1>
              질문에서 근거까지, <span>하나의 흐름으로.</span>
            </h1>
            <p className="intro-copy">
              계획하고, 조사하고, 검토합니다. 결과는 출처와 함께 확인하세요.
            </p>
          </div>
          <div className="dataset">
            <span className="eyebrow">DATASET</span>
            <strong>{config?.dataset.name ?? "데이터 정보 확인 중"}</strong>
            <span>
              자료 기준일 <b>{config?.dataset.as_of ?? "—"}</b>
            </span>
          </div>
        </section>
        <section className="query-panel" aria-label="리서치 실행 설정">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim() && !busy)
                void run.start(question.trim(), mode, scenario);
            }}
          >
            <div className="query-label">
              <label htmlFor="question">어떤 내용을 조사할까요?</label>
              <span>공개 자료 범위에서 근거를 찾습니다</span>
            </div>
            <div className="query-row">
              <textarea
                id="question"
                aria-label="리서치 질문"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="예: 공개 자료를 바탕으로 기업의 실적과 주요 위험요인을 분석해 주세요."
                maxLength={2000}
                rows={2}
                disabled={busy}
              />
              {active ? (
                <button
                  className="stop-button"
                  type="button"
                  disabled={run.pending}
                  onClick={() => void run.cancel()}
                >
                  실행 중단 <span aria-hidden="true">■</span>
                </button>
              ) : (
                <button
                  className="primary"
                  disabled={
                    !config ||
                    !question.trim() ||
                    busy ||
                    (mode === "live" && !config.configured) ||
                    (mode === "test" && !config.test_mode_available)
                  }
                >
                  {run.pending ? "실행 준비 중" : "리서치 시작"}{" "}
                  <span aria-hidden="true">↗</span>
                </button>
              )}
            </div>
            <div className="query-options">
              <div className="controls">
                <label className="sr-only" htmlFor="mode">
                  실행 모드
                </label>
                <select
                  id="mode"
                  value={mode}
                  disabled={busy}
                  onChange={(e) => setMode(e.target.value as "test" | "live")}
                >
                  <option value="test" disabled={!config?.test_mode_available}>
                    테스트 모드
                  </option>
                  <option value="live" disabled={!config?.configured}>
                    {config?.configured
                      ? "실제 모델"
                      : "실제 모델 · 연결 미설정"}
                  </option>
                </select>
                {mode === "test" && (
                  <>
                    <label className="sr-only" htmlFor="scenario">
                      테스트 시나리오
                    </label>
                    <select
                      id="scenario"
                      value={scenario}
                      disabled={busy}
                      onChange={(e) => setScenario(e.target.value)}
                    >
                      <option value="revise">재조사 후 개선</option>
                      <option value="pass">정상 완료</option>
                      <option value="limit">반복 한도 도달</option>
                      <option value="empty">근거 없음</option>
                      <option value="tool_error">도구 오류</option>
                      <option value="timeout">시간 초과</option>
                    </select>
                  </>
                )}
              </div>
              <span className="mode-notice">
                {actualMode === "test"
                  ? "테스트 모드 / 실제 모델 호출 없음"
                  : "실제 모델 모드 · 로컬 운영자 설정 사용"}
              </span>
            </div>
          </form>
        </section>
        {(configError || run.error) && (
          <div role="alert" className="error-banner">
            {configError || run.error}
          </div>
        )}
        <section className="flow-panel" aria-label="실행 흐름">
          <div className="run-meta">
            <span className={`run-status ${s?.status ?? "idle"}`} role="status">
              <span className={active ? "status-dot active" : "status-dot"} />
              {currentLabel}
            </span>
            <div>
              <span>
                경과 <b>{elapsed(s?.started_at, s?.finished_at)}</b>
              </span>
              <span>
                회차{" "}
                <b>
                  {s?.iteration ?? "—"} / {config?.limits.max_iterations ?? "—"}
                </b>
              </span>
            </div>
          </div>
          {run.disconnected && (
            <p role="status" className="connection-warning">
              연결 복구 중 · 서버의 최신 상태를 다시 확인합니다.
            </p>
          )}
          <ol className="stages">
            {stages.map((stage, i) => {
              const current = s?.stage === stage.id;
              return (
                <li
                  key={stage.id}
                  className={current ? "current" : ""}
                  aria-current={current ? "step" : undefined}
                >
                  <span className="stage-number">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span>
                    <strong>{stage.label}</strong>
                    <small>{stage.id}</small>
                  </span>
                  {i < 4 && (
                    <span className="stage-arrow" aria-hidden="true">
                      →
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
          <div
            className={`return-path ${s?.evaluation?.decision === "revise" || s?.feedback.length ? "revising" : ""}`}
          >
            <span aria-hidden="true">↶</span> 평가 후 추가 조사가 필요하면, 기존
            근거를 유지하고 계획으로 돌아갑니다.
            {s && s.iteration > 1 && (
              <strong> {s.iteration}회차 재계획 실행</strong>
            )}
          </div>
        </section>
        <div className="workspace">
          <section
            id="report"
            className="report-panel"
            aria-label="리서치 보고서"
            tabIndex={-1}
          >
            <div className="panel-top">
              <div>
                <span className="eyebrow">RESEARCH REPORT</span>
                <h2>리서치 보고서</h2>
              </div>
              {revisions.length > 0 ? (
                <label className="revision-select">
                  버전{" "}
                  <select
                    aria-label="보고서 버전"
                    value={selected?.iteration ?? ""}
                    onChange={(e) => {
                      setRevision(Number(e.target.value));
                      setSource(null);
                    }}
                  >
                    {revisions.map((r) => (
                      <option value={r.iteration} key={r.iteration}>
                        {r.iteration}차 보고서
                        {r === revisions.at(-1) ? " · 최신" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="draft-label">근거 기반 작성</span>
              )}
            </div>
            {report ? (
              <div className="report-content">
                <div className="report-kicker">
                  {selected
                    ? `${selected.iteration}차 검토본`
                    : "작성 중인 보고서"}{" "}
                  <span>
                    {actualMode === "test"
                      ? "테스트 실행 결과"
                      : "모델 생성 결과"}
                  </span>
                </div>
                <ReportBody
                  report={report}
                  onCitation={(id) => setSource(id)}
                />
                {selected && (
                  <div className="revision-evidence">
                    <strong>
                      추가 근거 {selected.added_evidence_ids.length}건
                    </strong>
                    <div className="citations">
                      {selected.added_evidence_ids.map((id) => (
                        <button
                          key={id}
                          className="citation"
                          onClick={() => setSource(id)}
                        >
                          ↗ {id}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {previous && (
                  <details className="comparison">
                    <summary>이전 보고서와 비교</summary>
                    <p className="eyebrow">{previous.iteration}차 보고서</p>
                    <h3>{previous.report.title}</h3>
                    <p>{previous.report.summary}</p>
                    <List
                      items={previous.report.claims.map((c) => c.text)}
                      empty="이전 주장 없음"
                    />
                    <h4>이전 평가의 보완 요청</h4>
                    <List
                      items={previous.evaluation.issues}
                      empty="보완 요청 없음"
                    />
                  </details>
                )}
                <p className="report-footnote">
                  인용 연결은 사실성 보장이 아닙니다. 원문과 자료 기준일을 함께
                  확인하세요.
                </p>
              </div>
            ) : (
              <div className="report-empty">
                <div className="paper-symbol" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <p className="eyebrow">FROM QUESTION TO EVIDENCE</p>
                <h3>
                  {s?.status === "empty"
                    ? "자료 범위를 바꿔 다시 질문해 보세요"
                    : s?.status === "error"
                      ? "조사를 완료하지 못했습니다"
                      : s?.status === "cancelled"
                        ? "새 질문으로 다시 시작할 수 있습니다"
                        : active
                          ? "근거를 모아 보고서를 만들고 있습니다"
                          : "좋은 조사는, 좋은 질문에서 시작됩니다."}
                </h3>
                <p>
                  {active
                    ? "실행 단계와 작업 노트에서 실제 진행 상황을 확인할 수 있습니다."
                    : "질문을 입력하면 조사 계획부터 출처를 담은 보고서까지 이곳에 정리됩니다."}
                </p>
                <div className="empty-principles">
                  <span>01 질문 구조화</span>
                  <span>02 출처 확인</span>
                  <span>03 결과 검토</span>
                </div>
              </div>
            )}
            {s?.status === "limit_reached" && (
              <div className="limit-banner">
                최대 반복 횟수에 도달했습니다. 남아 있는 평가 이슈와 보고서의
                한계를 확인하세요.
              </div>
            )}
            {s?.errors.length ? (
              <div className="error-banner" role="alert">
                <List items={s.errors} empty="" />
              </div>
            ) : null}
            <section className="sources">
              <div className="section-heading">
                <h3>근거 자료</h3>
                <span>{s?.evidence.length ?? 0}건</span>
              </div>
              {s?.evidence.length ? (
                <div className="source-chips">
                  {s.evidence.map((e) => (
                    <button
                      key={e.id}
                      onClick={() => setSource(e.id)}
                      aria-pressed={source === e.id}
                    >
                      <span>{e.id}</span>
                      {e.title}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="muted small">
                  조회된 출처와 인용 구간이 여기에 표시됩니다.
                </p>
              )}
              {source && !evidence && (
                <p role="alert">이 인용에 연결된 근거를 찾을 수 없습니다.</p>
              )}
              {evidence && (
                <article
                  ref={sourcePanel}
                  tabIndex={-1}
                  className="source-detail"
                  aria-label="선택한 출처"
                >
                  <div className="source-title">
                    <h4>{evidence.title}</h4>
                    <button
                      aria-label="출처 닫기"
                      onClick={() => setSource(null)}
                    >
                      ×
                    </button>
                  </div>
                  <p className="source-dates">
                    게시일 {evidence.published_at}{" "}
                    <span>자료 기준일 {evidence.as_of}</span>
                  </p>
                  <blockquote>{evidence.excerpt}</blockquote>
                  <div className="source-bottom">
                    <small>
                      {evidence.document_id} / {evidence.section_id}
                    </small>
                    {evidenceUrl ? (
                      <a
                        href={evidenceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        원문 보기 ↗
                      </a>
                    ) : (
                      <span className="muted small">안전한 원문 링크 없음</span>
                    )}
                  </div>
                  {evidenceUrl && <p className="source-url">{evidenceUrl}</p>}
                </article>
              )}
            </section>
          </section>
          <aside className="work-panel" aria-label="작업 노트">
            <div className="panel-top">
              <div>
                <span className="eyebrow">WORK NOTES</span>
                <h2>작업 노트</h2>
              </div>
              <span className="note-icon" aria-hidden="true">
                ≡
              </span>
            </div>
            <section>
              <h3>
                <span>01</span> 요청 해석
              </h3>
              <p className={s?.interpreted_request ? "small" : "muted small"}>
                {s?.interpreted_request ||
                  "대상과 기간, 질문의 요구사항을 정리합니다."}
              </p>
            </section>
            <section>
              <h3>
                <span>02</span> 조사 계획
              </h3>
              <List
                items={s?.plan ?? []}
                empty="실행 후 구체적인 조사 항목을 확인할 수 있습니다."
              />
            </section>
            <section>
              <h3>
                <span>03</span> 자료 조회 <small>MCP</small>
              </h3>
              {tools.length ? (
                <ul className="tool-list">
                  {tools.slice(-8).map((e) => (
                    <li key={e.seq}>
                      <span aria-hidden="true">
                        {e.type === "tool_error" ? "⚠" : e.type === "tool_complete" ? "✓" : "↗"}
                      </span>
                      <div>
                        {e.data.tool_name || e.data.tool || "자료 조회"}
                        {e.data.input_summary && <small>{e.data.input_summary}</small>}
                        <small>
                          {e.type === "tool_error"
                            ? "도구 입력 오류"
                            : e.type === "tool_complete"
                              ? "조회 완료"
                              : "호출 시작"}
                          {typeof e.data.count === "number"
                            ? ` · ${e.data.count}건`
                            : ""}
                        </small>
                        {e.type === "tool_error" && e.data.reason && (
                          <small>{e.data.reason}</small>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">
                  실제 도구 호출 내역이 표시됩니다.
                  {s && isComplete(s)
                    ? " 재접속 이전 이벤트는 재생하지 않습니다."
                    : ""}
                </p>
              )}
            </section>
            <section>
              <h3>
                <span>04</span> 평가와 다음 조사
              </h3>
              {s?.evaluation ? (
                <>
                  <span className={`decision ${s.evaluation.decision}`}>
                    {s.evaluation.decision === "pass"
                      ? "✓ 검토 통과"
                      : "↶ 추가 조사 필요"}
                  </span>
                  <List
                    items={s.evaluation.issues}
                    empty="추가 보완 요청이 없습니다."
                  />
                  {s.evaluation.follow_up.length > 0 && (
                    <>
                      <h4>다음 조사 항목</h4>
                      <List items={s.evaluation.follow_up} empty="" />
                    </>
                  )}
                </>
              ) : (
                <p className="muted small">
                  질문 충족 여부, 근거 충분성, 불확실성 표현을 검토합니다.
                </p>
              )}
              {!!s?.feedback.length && (
                <details className="feedback">
                  <summary>누적 평가 피드백</summary>
                  <List items={s.feedback} empty="" />
                </details>
              )}
            </section>
            <p className="work-boundary">
              명시적인 계획과 결과만 표시합니다.
              <br />
              모델 내부 추론은 노출하지 않습니다.
            </p>
          </aside>
        </div>
        <details className="developer">
          <summary>
            <span>개발 상세</span>
            <span>
              실행 이벤트 · State 변경 <b>{run.events.length}</b>
            </span>
          </summary>
          <p className="muted small">
            현재 연결에서 수신한 안전한 이벤트 요약입니다. 최대 150건만
            표시합니다.
          </p>
          {run.events.length ? (
            <ol className="event-log">
              {run.events.map((event) => (
                <li key={event.seq}>
                  <code>#{event.seq}</code>
                  <span>{safeEvent(event)}</span>
                  <time>
                    {new Date(event.timestamp).toLocaleTimeString("ko-KR")}
                  </time>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted small">아직 수신한 이벤트가 없습니다.</p>
          )}
          <div className="state-fields">
            <span>공통 State</span>
            <code>
              question · interpreted_request · plan · evidence · report ·
              revisions · evaluation · feedback · iteration · status
            </code>
          </div>
        </details>
        <footer>
          <span>
            Research Agent Studio <span className="footer-divider">/</span> 공개
            데이터 기반 독립 리서치 프로토타입
          </span>
          <span>실행 기록은 서버 메모리에만 유지됩니다.</span>
        </footer>
      </main>
    </div>
  );
}
