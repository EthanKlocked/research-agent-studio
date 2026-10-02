import type { RunEvent } from './types';
import { estimatedUsd } from './RunCost';
const labels: Record<string, string> = {
  node_start: '단계 시작', node_complete: '단계 완료', tool_start: '도구 호출',
  tool_complete: '도구 완료', tool_error: '도구 오류', evaluation: '결과 평가',
  branch: '분기 결정', terminal: '실행 종료', model_start: '모델 요청 시작',
  model_complete: '모델 응답 수신', model_error: '모델 요청 오류',
  validation_start: '출력 검증 시작', validation_complete: '출력 검증 완료', validation_error: '출력 검증 오류',
  repair_start: '출력 보정', discovery_start: '도구 확인 시작', discovery_complete: '도구 확인 완료',
};
export function safeEvent(event: RunEvent) {
  if (!labels[event.type]) return '상태 갱신';
  const d = event.data;
  const observation = event.type === 'model_complete' ? d.observation : undefined;
  const served = observation?.served_by === 'research-primary' || observation?.served_by === 'research-secondary' ? observation.served_by : 'unknown';
  return [labels[event.type],
    d.purpose === 'planner_context' ? '계획 참고' : d.purpose === 'research_execution' ? '조사 실행' : null,
    typeof d.tool_count === 'number' ? `도구 ${d.tool_count}개` : null,
    d.scope === 'output_schema' ? '출력 스키마' : d.scope === 'citations' ? '인용' : null,
    d.tool_name || d.tool, d.input_summary,
    typeof d.count === 'number' ? `결과 ${d.count}건` : null,
    (d.state_fields || d.changed_fields)?.join(', '), d.reason,
    d.web_category && ['budget','quota','auth','timeout','security','oversize','invalid_input','unavailable'].includes(d.web_category) ? `web_category=${d.web_category}` : null,
    d.web_category === 'budget' && d.recoverable === true ? '기존 근거로 계속' : null,
    observation ? `served_by: ${served} · fallback: ${typeof observation.fallback === 'boolean' ? String(observation.fallback) : 'unknown'}` : null,
    d.role, typeof d.attempt === 'number' ? `시도 ${d.attempt}` : null,
    typeof d.duration_ms === 'number' ? `${d.duration_ms}ms` : null,
    d.decision, d.retrieval_status === 'unavailable' ? '자료 이용 불가 · 인용 제외' : null,
  ].filter(Boolean).join(' · ');
}
function ModelMetrics({observation: o}: {observation: NonNullable<RunEvent['data']['observation']>}) {
  const count = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? String(v) : 'unknown';
  const latency = typeof o.latency_ms === 'number' && Number.isFinite(o.latency_ms) && o.latency_ms >= 0 ? `${o.latency_ms} ms` : 'unknown';
  const name = typeof o.gateway_model_name === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(o.gateway_model_name) && !o.gateway_model_name.includes('://') ? o.gateway_model_name : 'unknown';
  return <div className="model-metrics">
    <span className={`fallback-badge ${o.fallback === true ? 'used' : ''}`}>{o.fallback === true ? 'fallback 발생' : o.fallback === false ? 'fallback 없음' : 'fallback 미확인'}</span>
    <p>served model: {name} · 지연 {latency}</p>
    <p>입력 {count(o.input_tokens)} · 출력 {count(o.output_tokens)} · 전체 {count(o.total_tokens)}</p>
    <p>reasoning {count(o.reasoning_tokens)} · 미설명 차액 {typeof o.unexplained_token_residual === 'number' && Number.isSafeInteger(o.unexplained_token_residual) ? String(o.unexplained_token_residual) : 'unknown'} · 추정 {estimatedUsd(o.estimated_cost_usd)}</p>
    <p>fallback 시도 {count(o.attempted_fallbacks)} · 남은 요청 {count(o.rate_limit_remaining_requests)} (응답 헤더 · 계정 잔액 아님)</p>
  </div>;
}
const groupLabel = (e: RunEvent) => `${e.data.snapshot.iteration}차 · ${e.data.snapshot.stage ?? '실행'}`;
const sameCall = (a: RunEvent, b: RunEvent) => !!a.data.tool_call_id &&
  a.data.tool_call_id === b.data.tool_call_id && a.run_id === b.run_id &&
  groupLabel(a) === groupLabel(b) && (a.data.tool_name || a.data.tool) === (b.data.tool_name || b.data.tool);
export function Timeline({ events, complete, lastSeq }: { events: RunEvent[]; complete: boolean; lastSeq: number }) {
  const groups: { key: number; label: string; events: RunEvent[] }[] = [];
  for (const e of events) {
    const last = groups.at(-1), label = groupLabel(e);
    if (last?.label === label) last.events.push(e);
    else groups.push({ key: e.seq, label, events: [e] });
  }
  const gap = lastSeq > events.length || events.some((e, i) => i > 0 && e.seq !== events[i-1].seq + 1);
  return <section className="timeline-panel" aria-label="작업 타임라인">
    <div className="panel-top"><h2>작업 타임라인</h2><span className="draft-label">수신 {events.length}건</span></div>
    <p className="timeline-boundary">발생 순서 · 공개 작업 정보 · 최대 150건</p>
    {gap && <p className="history-gap">일부 이벤트 기록이 없습니다. 복구된 상태는 최신 snapshot 기준입니다.</p>}
    <div className="timeline-feed" tabIndex={0} aria-label="시간순 작업 이벤트">
      {!events.length && <p className="muted small">아직 수신한 이벤트가 없습니다.</p>}
      {groups.map(group => <section className="event-group" role="group" aria-label={group.label} key={group.key}>
        <h3>{group.label}</h3><ol>
          {group.events.map(e => {
            const starts = events.filter(start => start.seq < e.seq && start.type === 'tool_start' && sameCall(start,e));
            const start = starts.length === 1 && ['tool_complete','tool_error'].includes(e.type) ? starts[0] : undefined;
            const seconds = start ? (Date.parse(e.timestamp) - Date.parse(start.timestamp)) / 1000 : NaN;
            const resolved = e.type === 'tool_start' && events.some(end => end.seq > e.seq && ['tool_complete','tool_error'].includes(end.type) && sameCall(e,end));
            return <li key={e.seq} data-testid="timeline-event" data-seq={e.seq} className={`timeline-event ${['tool_error','model_error','validation_error'].includes(e.type) ? 'event-error' : ''}`}>
              <div className="event-stamp"><span>#{e.seq}</span><time dateTime={e.timestamp}>{Number.isFinite(Date.parse(e.timestamp)) ? new Date(e.timestamp).toLocaleTimeString('ko-KR', {hour12:false}) : '시간 미확인'}</time></div>
              <p>{safeEvent(e)}</p>
              {e.type === 'model_complete' && e.data.observation && <ModelMetrics observation={e.data.observation}/>}
              {start && Number.isFinite(seconds) && seconds >= 0 && <small>호출 #{start.seq} · {seconds}초</small>}
              {e.type === 'tool_start' && !resolved && <small>{complete ? '응답 미확인 · 실행 종료' : '응답 대기'}</small>}
              {(e.data.tool_call_id || e.data.model_call_id || e.data.input_summary) && <details><summary>공개 메타데이터</summary>
                <p className="small">{e.data.tool_call_id || e.data.model_call_id || '호출 ID 없음'} · {e.type}</p>
              </details>}
            </li>;
          })}
        </ol>
      </section>)}
    </div>
    <p className="timeline-boundary">검색 일치는 메타데이터입니다. 인용 근거는 수집 완료 후 반영됩니다.</p>
  </section>;
}
