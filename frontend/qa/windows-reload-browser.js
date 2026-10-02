async (page) => {
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/config',r=>r.fulfill({json:{configured:false,test_mode_available:true,capabilities:{general_web:false,search_provider:null},dataset:{name:'Offline browser fixture',as_of:'2026-01-01'},limits:{max_iterations:2}}}));
  await page.addInitScript(()=>{window.EventSource=class {constructor(url){window.qaStream=this;window.qaStreamUrl=url;} close(){}};});
  const initial={run_id:'reload-qa',question:'Offline reload verification',mode:'test',status:'running',stage:'Researcher',iteration:1,started_at:'2026-10-02T00:01:00+09:00',run_context:{started_at:'2026-10-02T00:01:00+09:00',current_date:'2026-10-02',timezone:'Asia/Seoul'},finished_at:null,last_seq:1,interpreted_request:'Browser fixture, no live model or search calls',plan:[],evidence:[],report:null,revisions:[],evaluation:null,feedback:[],errors:[]};
  const cost={model_requests:2,priced_requests:1,unknown_requests:1,known_estimated_cost_usd:0.00048,estimated_cost_usd:null,estimate_status:'partial',residual_priced_requests:1};
  const events=[{run_id:initial.run_id,seq:2,type:'model_complete',timestamp:initial.started_at,data:{snapshot:{...initial,last_seq:2,cost_summary:cost},role:'Researcher',model_call_id:'a'.repeat(32),observation:{served_by:'research-secondary',gateway_model_name:'openai/mock-secondary',fallback:true,attempted_fallbacks:1,input_tokens:100,output_tokens:50,total_tokens:170,reasoning_tokens:30,unexplained_token_residual:20,latency_ms:123,estimated_cost_usd:0.00048,input_output_estimated_cost_usd:0.0004,cost_assumption:'residual_at_output_rate'}}}];
  let restored={...initial,last_seq:2,cost_summary:cost,retained_events:events};
  await page.route('**/api/runs',r=>r.fulfill({json:initial}));
  await page.route('**/api/runs/reload-qa?include_events=true',r=>r.fulfill({json:restored}));
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:5201');
  await page.evaluate(()=>sessionStorage.clear());
  await page.reload();
  await page.getByRole('textbox',{name:'리서치 질문'}).fill(initial.question);
  await page.getByRole('button',{name:'조사 시작'}).click();
  await page.waitForFunction(()=>!!window.qaStream);
  await page.evaluate(e=>window.qaStream.onmessage({data:JSON.stringify(e)}),events[0]);
  await page.locator('.activity-details > summary').click();
  await page.locator('.timeline-panel').getByText('served model: openai/mock-secondary',{exact:false}).waitFor();
  await page.reload();
  await page.waitForFunction(()=>window.qaStreamUrl?.endsWith('after=2'));
  await page.locator('.activity-details > summary').click();
  await page.evaluate(e=>window.qaStream.onmessage({data:JSON.stringify(e)}),events[0]);
  if(await page.locator('.timeline-event').count()!==1)throw new Error('Restored/SSE duplicate');
  const terminal={run_id:initial.run_id,seq:3,type:'terminal',timestamp:'2026-10-02T00:01:08+09:00',data:{snapshot:{...initial,last_seq:3,status:'success',finished_at:'2026-10-02T00:01:08+09:00',cost_summary:cost}}};
  await page.evaluate(e=>window.qaStream.onmessage({data:JSON.stringify(e)}),terminal);
  restored={...terminal.data.snapshot,retained_events:[...events,terminal]};
  await page.reload();
  await page.getByText('조사가 완료되었습니다',{exact:true}).waitFor();
  await page.locator('.activity-details > summary').click();
  const results=[];
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:1000});
    for(const text of ['served model: openai/mock-secondary','지연 123 ms','입력 100 · 출력 50 · 전체 170','입력·출력 소계 $0.0004 · 차액 제외','추정 가정: 미설명 차액을 출력 단가로 계산','fallback 발생']){
      if(!await page.locator('.timeline-panel').getByText(text,{exact:false}).first().isVisible())throw new Error('Missing '+text);
    }
    await page.getByText('실행 기준일 2026-10-02 · Asia/Seoul',{exact:true}).waitFor();
    await page.getByText('차액을 출력 단가로 가정한 요청 1건 · reasoning으로 단정하지 않음',{exact:true}).waitFor();
    await page.getByText('알려진 소계 $0.00048 · 사용량/단가 미확인 1/2 요청',{exact:true}).waitFor();
    if(await page.locator('.timeline-event').count()!==2)throw new Error('Terminal restore lost history');
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Overflow '+width);
    await page.locator('.timeline-panel').scrollIntoViewIfNeeded();
    await page.screenshot({path:`/tmp/ras-windows-reload-${width}.png`,fullPage:true});
    results.push({width,activeReload:true,terminalReload:true,sseDedup:true,events:2,metrics:true,partialCostUnchanged:true,noHorizontalOverflow:true});
  }
  if(errors.length)throw new Error(JSON.stringify(errors));
  return {results,pageErrors:errors};
}
