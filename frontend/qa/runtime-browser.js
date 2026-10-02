async (page) => {
  // Browser-only deterministic events against the production build; no providers.
  const errors=[], results=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/config',r=>r.fulfill({json:{configured:false,test_mode_available:true,capabilities:{general_web:false,search_provider:null},dataset:{name:'Offline browser QA fixture',as_of:null},limits:{max_iterations:2}}}));
  await page.addInitScript(()=>{sessionStorage.clear();window.EventSource=class{constructor(){window.qaStream=this;}close(){this.closed=true;}};});
  const base={run_id:'runtime-qa',question:'Offline runtime contract demonstration',mode:'test',status:'running',stage:'Listener',iteration:0,started_at:'2026-10-02T00:01:00Z',run_context:{started_at:'2026-10-02T00:01:00Z',current_date:'2026-10-02',timezone:'UTC'},finished_at:null,last_seq:1,interpreted_request:'Browser fixture only; no model or web calls',plan:[],evidence:[],report:null,revisions:[],evaluation:null,feedback:[],errors:[]};
  const evidence={id:'fixture:page',document_id:'fixture',section_id:'page',title:'Deterministic browser fixture',url:'https://example.com/fixture',published_at:'2026-10-02',as_of:null,provenance:'browser_fixture',excerpt:'This is fixture evidence, not a live research result.'};
  const outcomes=[
    {status:'unsupported',unsupported_reason:'개인 맞춤 종목 추천은 지원하지 않습니다. 기업 공시의 사실 비교를 요청해 주세요.',label:'지원하지 않는 요청입니다'},
    {status:'budget_exhausted',stage:'Researcher',iteration:1,web_budget_exhausted:['read'],label:'웹 조회 예산을 소진했습니다'},
    {status:'budget_exhausted',stage:'Evaluator',iteration:1,web_budget_exhausted:['search'],evidence:[evidence],report:{title:'오프라인 부분 보고서',summary:'브라우저 검증용 고정 자료입니다.',claims:[{text:evidence.excerpt,citation_ids:[evidence.id]}],limitations:['실행별 웹 조회 예산 소진 · 전체 조사가 아닙니다.']},evaluation:{decision:'revise',issues:['추가 근거 부족'],follow_up:[]},label:'웹 조회 예산을 소진했습니다'},
    {status:'error',stage:'Researcher',iteration:1,errors:['[Researcher/tool] [web_category=quota] 검색 제공자의 할당량 또는 요청 제한에 도달했습니다.'],label:'조사 중 오류가 발생했습니다'}
  ];
  await page.route('**/api/runs',r=>r.fulfill({json:base}));
  for (const width of [1440,768,390]) for (const [index,outcome] of outcomes.entries()) {
    await page.setViewportSize({width,height:1000});
    await page.goto('http://127.0.0.1:5200');
    await page.getByRole('textbox',{name:'리서치 질문'}).fill(base.question);
    await page.getByRole('button',{name:'조사 시작'}).click();
    await page.waitForFunction(()=>!!window.qaStream);
    const final={...base,...outcome,last_seq:3,finished_at:'2026-10-02T00:01:12Z'};
    await page.evaluate(s=>window.qaStream.onmessage({data:JSON.stringify({seq:2,run_id:s.run_id,type:'node_complete',timestamp:s.finished_at,data:{snapshot:{...s,last_seq:2,finished_at:null}}})}),final);
    if(await page.evaluate(()=>!!window.qaStream.closed)) throw new Error('Closed before terminal');
    await page.evaluate(s=>window.qaStream.onmessage({data:JSON.stringify({seq:3,run_id:s.run_id,type:'terminal',timestamp:s.finished_at,data:{snapshot:s}})}),final);
    await page.getByText(outcome.label,{exact:true}).waitFor({state:'visible'});
    await page.getByText('실행 기준일 2026-10-02 · UTC',{exact:true}).waitFor({state:'visible'});
    if(!await page.evaluate(()=>!!window.qaStream.closed)) throw new Error('Stream not closed');
    if(await page.getByText('조사가 완료되었습니다',{exact:true}).count()) throw new Error('False success');
    if(index===0) await page.getByText(outcome.unsupported_reason,{exact:true}).waitFor({state:'visible'});
    if(index===1) await page.getByText('보고서를 작성할 근거가 부족합니다',{exact:true}).waitFor({state:'visible'});
    if(index===2) {
      await page.getByText('오프라인 부분 보고서',{exact:true}).waitFor({state:'visible'});
      await page.getByRole('button',{name:'수집 자료 보기'}).click();
      await page.getByRole('button',{name:/Deterministic browser fixture/}).click();
      await page.locator('blockquote').getByText(evidence.excerpt,{exact:true}).waitFor({state:'visible'});
      await page.getByRole('button',{name:'보고서 보기'}).click();
    }
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error('Horizontal overflow');
    results.push({width,outcome:index,visible:true,noFalseSuccess:true,streamFinalized:true});
  }
  if(errors.length) throw new Error(JSON.stringify(errors));
  return {results,consoleErrors:errors,provenance:'browser-only fixtures; no live provider calls'};
}
