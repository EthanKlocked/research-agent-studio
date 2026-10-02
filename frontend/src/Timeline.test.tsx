import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Timeline } from './Timeline';
import { snapshot } from './test/fixtures';
import type { RunEvent } from './types';
const event = (seq: number, type: string, data: Record<string, unknown> = {}): RunEvent => ({seq, type, run_id: 'run-1', timestamp: `2026-01-01T00:00:0${seq}Z`, data: { snapshot: snapshot({ last_seq: seq, stage: 'Researcher' }), ...data }});
describe('observable timeline', () => {
  it('distinguishes recoverable local budget from fatal quota without arbitrary categories', () => {
    render(<Timeline events={[event(1,'tool_error',{tool:'web_search',web_category:'budget',recoverable:true}),event(2,'tool_error',{tool:'read_page',web_category:'quota',recoverable:false}),event(3,'tool_error',{web_category:'SECRET'})]} complete lastSeq={3}/>);
    expect(screen.getByText(/web_category=budget · 기존 근거로 계속/)).toBeVisible();
    expect(screen.getByText(/web_category=quota/)).toBeVisible();
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  });
  it('shows safe served model, fallback badge, latency and token metrics', () => {
    render(<Timeline events={[event(1,'model_complete',{observation:{served_by:'research-secondary',gateway_model_name:'openai/mock-secondary',fallback:true,latency_ms:120.5,input_tokens:11,output_tokens:7,total_tokens:18,reasoning_tokens:3,unexplained_token_residual:0,estimated_cost_usd:0.00005,attempted_fallbacks:1,rate_limit_remaining_requests:29}})]} complete lastSeq={1}/>);
    expect(screen.getByText('fallback 발생')).toBeVisible();
    expect(screen.getByText(/served model: openai\/mock-secondary/)).toBeVisible();
    expect(screen.getByText(/지연 120.5 ms/)).toBeVisible();
    expect(screen.getByText(/입력 11 · 출력 7 · 전체 18/)).toBeVisible();
    expect(screen.getByText(/reasoning 3 · 미설명 차액 0/)).toBeVisible();
    expect(screen.getByText(/추정 \$0.00005/)).toBeVisible();
  });
  it('never renders missing tokens or latency as zero', () => {
    render(<Timeline events={[event(1,'model_complete',{observation:{served_by:null,fallback:null}})]} complete lastSeq={1}/>);
    expect(screen.getByText(/지연 unknown/)).toBeVisible();
    expect(screen.getByText(/입력 unknown · 출력 unknown · 전체 unknown/)).toBeVisible();
    expect(screen.getByText(/served model: unknown/)).toBeVisible();
    expect(screen.queryByText(/추정 \$0/)).not.toBeInTheDocument();
  });
  it.each([
    [{served_by:'research-secondary',fallback:true}, 'served_by: research-secondary · fallback: true'],
    [{served_by:'research-primary',fallback:false}, 'served_by: research-primary · fallback: false'],
    [{served_by:null,fallback:null}, 'served_by: unknown · fallback: unknown'],
    [{served_by:'private/raw-model',fallback:'yes'}, 'served_by: unknown · fallback: unknown'],
  ])('shows observed routing without guessing from requested model', (observation, text) => {
    render(<Timeline events={[event(1,'model_complete',{model_call_id:'m1',observation:{...observation,model:'research-primary',headers:{secret:'SECRET'}}})]} complete lastSeq={1}/>);
    expect(screen.getByText(text,{exact:false})).toBeVisible();
    expect(screen.queryByText(/private\/raw-model|SECRET/)).not.toBeInTheDocument();
  });
  it('leaves old events without observation backward compatible', () => {
    render(<Timeline events={[event(1,'model_complete')]} complete lastSeq={1}/>);
    expect(screen.queryByText(/served_by|fallback/)).not.toBeInTheDocument();
  });
  it.each(['도구 입력을 확인하고 다시 조회해 주세요.', '자료 조회 중 오류가 발생했습니다.'])('does not infer an input error category from reason: %s', (reason) => {
    render(<Timeline events={[event(1, 'tool_error', {tool:'read_page', reason})]} complete={false} lastSeq={1}/>);
    expect(screen.getByText(`도구 오류 · read_page · ${reason}`)).toBeVisible();
    expect(screen.queryByText(/도구 입력 오류/)).not.toBeInTheDocument();
  });
  it('preserves chronology for overlapping calls and only correlates explicit IDs', () => {
    render(<Timeline events={[event(2,'tool_start',{tool:'search',tool_call_id:'a'}),event(3,'tool_start',{tool:'search',tool_call_id:'b'}),event(4,'tool_complete',{tool:'search',tool_call_id:'a',count:2}),event(5,'tool_complete',{tool:'search',count:1})]} complete={false} lastSeq={5} />);
    const rows = screen.getAllByTestId('timeline-event');
    expect(rows.map(row=>row.getAttribute('data-seq'))).toEqual(['2','3','4','5']);
    expect(within(rows[2]).getByText('호출 #2 · 2초')).toBeVisible();
    expect(rows[3]).not.toHaveTextContent('호출 #');
    expect(screen.getAllByRole('group', {name:'1차 · Researcher'})).toHaveLength(1);
    expect(screen.getByText('검색 일치는 메타데이터입니다. 인용 근거는 수집 완료 후 반영됩니다.')).toBeVisible();
  });
  it('marks outstanding calls interrupted rather than successful on terminal failure', () => {
    const {rerender}=render(<Timeline events={[event(2,'tool_start',{tool:'get_document',tool_call_id:'a'})]} complete={false} lastSeq={2}/>);
    expect(screen.getByText('응답 대기')).toBeVisible();
    rerender(<Timeline events={[event(2,'tool_start',{tool:'get_document',tool_call_id:'a'})]} complete lastSeq={3}/>);
    expect(screen.getByText('응답 미확인 · 실행 종료')).toBeVisible();
    expect(screen.queryByText('완료')).not.toBeInTheDocument();
  });
  it('displays allowlisted model boundaries, unknown events and replay gaps without private data', () => {
    render(<Timeline events={[event(4,'model_start',{role:'Researcher',model_call_id:'m1',attempt:1,prompt:'SECRET'}),event(5,'model_complete',{role:'Researcher',model_call_id:'m1',attempt:1}),event(6,'validation_start',{role:'Researcher',scope:'output_schema',attempt:1}),event(7,'repair_start',{role:'Researcher',attempt:2}),event(8,'discovery_start',{purpose:'planner_context'}),event(9,'discovery_complete',{purpose:'planner_context',tool_count:4}),event(10,'unknown',{thought:'SECRET'})]} complete={false} lastSeq={10}/>);
    for(const text of ['모델 요청 시작','모델 응답 수신','출력 검증','출력 보정','도구 확인 시작','도구 확인 완료','상태 갱신']) expect(screen.getByText(text,{exact:false})).toBeVisible();
    expect(screen.getByText(/일부 이벤트 기록이 없습니다/)).toBeVisible();
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  });
  it('renders exact granular contract metadata without inferring completion or availability', () => {
    const id = '964621e7d54c4ce0b18cb679316a9631';
    render(<Timeline events={[
      event(1,'discovery_start',{purpose:'planner_context'}),
      event(2,'discovery_complete',{purpose:'research_execution',tool_count:6}),
      event(3,'model_start',{role:'Reporter',attempt:1,model_call_id:id}),
      event(4,'model_error',{role:'Reporter',attempt:1,model_call_id:id}),
      event(5,'validation_start',{role:'Reporter',scope:'output_schema',attempt:1}),
      event(6,'validation_error',{role:'Reporter',scope:'output_schema',attempt:1}),
      event(7,'repair_start',{role:'Reporter',attempt:2}),
      event(8,'validation_complete',{role:'Reporter',scope:'output_schema',attempt:2}),
      event(9,'validation_start',{role:'Reporter',scope:'citations'}),
      event(10,'validation_complete',{role:'Reporter',scope:'citations'}),
      event(11,'validation_error',{role:'Reporter',scope:'citations'}),
      event(12,'tool_start',{tool:'web_search',tool_call_id:'search-id',input_summary:'검색어 4자 · limit 5'}),
      event(13,'tool_complete',{tool:'web_search',tool_call_id:'search-id',count:2}),
      event(14,'tool_start',{tool:'read_page',tool_call_id:'page-id'}),
      event(15,'tool_complete',{tool:'read_page',tool_call_id:'page-id',count:0,retrieval_status:'unavailable',reason:'general_web_unavailable'}),
    ]} complete={false} lastSeq={15}/>);
    const rows = screen.getAllByTestId('timeline-event');
    expect(rows[0]).toHaveTextContent('도구 확인 시작 · 계획 참고');
    expect(rows[0]).not.toHaveTextContent('개');
    expect(rows[1]).toHaveTextContent('도구 확인 완료 · 조사 실행 · 도구 6개');
    expect(rows[3]).toHaveTextContent('모델 요청 오류 · Reporter · 시도 1');
    expect(rows[3]).toHaveClass('event-error');
    expect(rows[5]).toHaveTextContent('출력 검증 오류 · 출력 스키마 · Reporter · 시도 1');
    expect(rows[5]).toHaveClass('event-error');
    expect(rows[7]).toHaveTextContent('출력 검증 완료 · 출력 스키마 · Reporter · 시도 2');
    expect(rows[9]).toHaveTextContent('출력 검증 완료 · 인용 · Reporter');
    expect(rows[9]).not.toHaveTextContent('시도');
    expect(rows[10]).toHaveClass('event-error');
    fireEvent.click(within(rows[2]).getByText('공개 메타데이터'));
    expect(within(rows[2]).getByText(`${id} · model_start`)).toBeVisible();
    expect(rows[11]).toHaveTextContent('도구 호출 · web_search');
    expect(rows[14]).toHaveTextContent('read_page');
    expect(rows[14]).toHaveTextContent('자료 이용 불가 · 인용 제외');
    expect(screen.queryByText(/웹 검색 사용 가능|웹 검색 연결됨/)).not.toBeInTheDocument();
  });
  it('keeps disclosures open when a new event arrives', () => {
    const initial=[event(2,'tool_start',{tool:'get_document',input_summary:'문서 d1',tool_call_id:'a'})];
    const {rerender}=render(<Timeline events={initial} complete={false} lastSeq={2}/>);
    fireEvent.click(screen.getByText('공개 메타데이터'));
    const disclosure=screen.getByText('공개 메타데이터').closest('details');
    expect(disclosure).toHaveAttribute('open');
    rerender(<Timeline events={[...initial,event(3,'tool_complete',{tool:'get_document',tool_call_id:'a'})]} complete={false} lastSeq={3}/>);
    expect(disclosure).toHaveAttribute('open');
  });
});
