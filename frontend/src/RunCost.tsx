import type { CostSummary } from './types';
export function estimatedUsd(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? '$' + Number(value.toPrecision(6)).toString() : 'unknown';
}
export function RunCost({summary}: {summary?: CostSummary | null}) {
  if (!summary) return null;
  return <section className="run-cost small" aria-label="실행 추정 비용">
    <strong>실행 추정 비용: {estimatedUsd(summary.estimated_cost_usd)}</strong>
    <span>{summary.estimate_status === 'complete'
      ? `사용량·단가 확인 ${summary.priced_requests}/${summary.model_requests} 요청`
      : `알려진 소계 ${estimatedUsd(summary.known_estimated_cost_usd)} · 사용량/단가 미확인 ${summary.unknown_requests}/${summary.model_requests} 요청`}</span>
    {!!summary.residual_priced_requests && <span>차액을 출력 단가로 가정한 요청 {summary.residual_priced_requests}건 · reasoning으로 단정하지 않음</span>}
    <span className="muted">관측 응답 기준 · 실제 청구액 아님 · 실패한 upstream 시도 비용 제외</span>
  </section>;
}
