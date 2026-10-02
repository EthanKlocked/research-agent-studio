import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { RunCost } from './RunCost';

describe('run cost summary', () => {
  it('shows a complete observed-response estimate, never actual billing', () => {
    render(<RunCost summary={{model_requests:2,priced_requests:2,unknown_requests:0,known_estimated_cost_usd:0.125,estimated_cost_usd:0.125,estimate_status:'complete'}}/>);
    expect(screen.getByText('실행 추정 비용: $0.125')).toBeVisible();
    expect(screen.getByText(/2\/2 요청/)).toBeVisible();
    expect(screen.getByText(/실제 청구액 아님/)).toBeVisible();
  });
  it('marks partial unknown totals with an explicit known subtotal', () => {
    render(<RunCost summary={{model_requests:3,priced_requests:2,unknown_requests:1,known_estimated_cost_usd:0.125,estimated_cost_usd:null,estimate_status:'partial'}}/>);
    expect(screen.getByText('실행 추정 비용: unknown')).toBeVisible();
    expect(screen.getByText(/알려진 소계 \$0.125/)).toBeVisible();
    expect(screen.getByText(/미확인 1\/3 요청/)).toBeVisible();
  });
  it('does not call unpriced requests free', () => {
    render(<RunCost summary={{model_requests:3,priced_requests:0,unknown_requests:3,known_estimated_cost_usd:null,estimated_cost_usd:null,estimate_status:'unknown'}}/>);
    expect(screen.getByText('실행 추정 비용: unknown')).toBeVisible();
    expect(screen.queryByText(/\$0/)).not.toBeInTheDocument();
  });
  it('keeps explicit zero and missing summaries distinct', () => {
    const {rerender}=render(<RunCost summary={{model_requests:1,priced_requests:1,unknown_requests:0,known_estimated_cost_usd:0,estimated_cost_usd:0,estimate_status:'complete'}}/>);
    expect(screen.getByText('실행 추정 비용: $0')).toBeVisible();
    rerender(<RunCost summary={null}/>);
    expect(screen.queryByText(/실행 추정 비용/)).not.toBeInTheDocument();
  });
});
