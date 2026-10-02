async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/config', route => route.fulfill({json:{configured:false,test_mode_available:true,capabilities:{general_web:false,search_provider:null},dataset:{name:'Browser QA fixture',as_of:'2026-01-01'},limits:{max_iterations:2}}}));
  await page.addInitScript(() => {
    sessionStorage.clear();
    window.EventSource = class { constructor(){ window.qaStream=this; } close(){} };
  });
  const snapshot={run_id:'qa',question:'Mock gateway routing metadata',mode:'test',status:'running',stage:'Researcher',iteration:1,started_at:'2026-01-01T00:00:00Z',finished_at:null,last_seq:1,interpreted_request:'Browser-only fixture, no model calls',plan:[],evidence:[],report:null,revisions:[],evaluation:null,feedback:[],errors:[]};
  await page.route('**/api/runs',route=>route.fulfill({json:snapshot}));
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:5199');
  await page.getByRole('textbox',{name:'리서치 질문'}).fill(snapshot.question);
  await page.getByRole('button',{name:'조사 시작'}).click();
  await page.waitForFunction(()=>!!window.qaStream);
  await page.evaluate(s => {
    const observations=[{served_by:'research-primary',gateway_model_name:'openai/mock-primary',fallback:false,attempted_fallbacks:0,rate_limit_remaining_requests:29,latency_ms:120.5,input_tokens:11,output_tokens:7,total_tokens:18,reasoning_tokens:3,unexplained_token_residual:0,estimated_cost_usd:0.00005},{served_by:'research-secondary',gateway_model_name:'openai/mock-secondary',fallback:true,attempted_fallbacks:1,rate_limit_remaining_requests:29,latency_ms:140,input_tokens:11,output_tokens:7,total_tokens:18,estimated_cost_usd:0.000075},{served_by:null,fallback:null}];
    observations.forEach((observation,i)=>window.qaStream.onmessage({data:JSON.stringify({run_id:'qa',seq:i+2,type:'model_complete',timestamp:`2026-01-01T00:00:0${i+2}Z`,data:{snapshot:{...s,last_seq:i+2,cost_summary:{model_requests:i+1,priced_requests:Math.min(i+1,2),unknown_requests:i===2?1:0,known_estimated_cost_usd:i===0?0.00005:0.000125,estimated_cost_usd:i===2?null:i===0?0.00005:0.000125,estimate_status:i===2?"partial":"complete"}},role:'Researcher',model_call_id:`mock-call-${i}`,observation}})}));
  },snapshot);
  await page.locator('.activity-details > summary').click();
  const results=[];
  for (const width of [1440,768,390]) {
    await page.setViewportSize({width,height:1000});
    for (const text of ['served_by: research-primary · fallback: false','served_by: research-secondary · fallback: true','served_by: unknown · fallback: unknown']) {
      await page.locator('.timeline-panel').getByText(text,{exact:false}).waitFor({state:'visible'});
      results.push({width,text,visible:await page.locator('.timeline-panel').getByText(text,{exact:false}).isVisible()});
    }
    for(const text of ['fallback 발생','served model: openai/mock-secondary','지연 120.5 ms','입력 11 · 출력 7 · 전체 18','reasoning 3 · 미설명 차액 0','지연 unknown','남은 요청 29']) {
      if(!await page.locator('.timeline-panel').getByText(text,{exact:false}).first().isVisible()) throw new Error('Missing '+text);
    }
    await page.getByText('실행 추정 비용: unknown',{exact:true}).waitFor({state:'visible'});
    await page.getByText('알려진 소계 $0.000125 · 사용량/단가 미확인 1/3 요청',{exact:true}).waitFor({state:'visible'});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow) throw new Error('Horizontal page overflow at '+width);
    results.push({width,noHorizontalOverflow:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('.timeline-panel').getByText('served_by: research-secondary',{exact:false}).scrollIntoViewIfNeeded();
  const y=await page.evaluate(()=>scrollY);
  await page.evaluate(s=>window.qaStream.onmessage({data:JSON.stringify({run_id:'qa',seq:5,type:'model_complete',timestamp:'2026-01-01T00:00:05Z',data:{snapshot:{...s,last_seq:5,cost_summary:{model_requests:4,priced_requests:2,unknown_requests:2,known_estimated_cost_usd:0.000125,estimated_cost_usd:null,estimate_status:"partial"}},role:'Reporter',model_call_id:'mock-call-4',observation:{served_by:'research-secondary',fallback:true}}})}),snapshot);
  await page.waitForFunction(()=>document.querySelectorAll('.timeline-event').length===4);
  const after=await page.evaluate(()=>scrollY);
  if(after!==y) throw new Error(`Unexpected event scroll ${y}->${after}`);
  if(errors.length) throw new Error(JSON.stringify(errors));
  await page.getByText('알려진 소계 $0.000125 · 사용량/단가 미확인 2/4 요청',{exact:true}).waitFor({state:'visible'});
  results.push({eventScrollStable:true,modelMetricsVisible:true,partialCostUnknown:true,consoleErrors:errors});
  return results;
}
