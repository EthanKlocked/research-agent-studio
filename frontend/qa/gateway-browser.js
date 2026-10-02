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
    const observations=[{served_by:'research-primary',fallback:false},{served_by:'research-secondary',fallback:true},{served_by:null,fallback:null}];
    observations.forEach((observation,i)=>window.qaStream.onmessage({data:JSON.stringify({run_id:'qa',seq:i+2,type:'model_complete',timestamp:`2026-01-01T00:00:0${i+2}Z`,data:{snapshot:{...s,last_seq:i+2},role:'Researcher',model_call_id:`mock-call-${i}`,observation}})}));
  },snapshot);
  await page.locator('.activity-details > summary').click();
  const results=[];
  for (const width of [1440,768,390]) {
    await page.setViewportSize({width,height:1000});
    for (const text of ['served_by: research-primary · fallback: false','served_by: research-secondary · fallback: true','served_by: unknown · fallback: unknown']) {
      await page.locator('.timeline-panel').getByText(text,{exact:false}).waitFor({state:'visible'});
      results.push({width,text,visible:await page.locator('.timeline-panel').getByText(text,{exact:false}).isVisible()});
    }
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow) throw new Error('Horizontal page overflow at '+width);
    results.push({width,noHorizontalOverflow:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('.timeline-panel').getByText('served_by: research-secondary',{exact:false}).scrollIntoViewIfNeeded();
  const y=await page.evaluate(()=>scrollY);
  await page.evaluate(s=>window.qaStream.onmessage({data:JSON.stringify({run_id:'qa',seq:5,type:'model_complete',timestamp:'2026-01-01T00:00:05Z',data:{snapshot:{...s,last_seq:5},role:'Reporter',model_call_id:'mock-call-4',observation:{served_by:'research-secondary',fallback:true}}})}),snapshot);
  await page.waitForFunction(()=>document.querySelectorAll('.timeline-event').length===4);
  const after=await page.evaluate(()=>scrollY);
  if(after!==y) throw new Error(`Unexpected event scroll ${y}->${after}`);
  if(errors.length) throw new Error(JSON.stringify(errors));
  results.push({eventScrollStable:true,consoleErrors:errors});
  return results;
}
