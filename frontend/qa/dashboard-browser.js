async (page) => {
  await page.route('**/api/config', route => route.fulfill({json:{configured:false,test_mode_available:true,capabilities:{general_web:false,search_provider:null},dataset:{name:'Browser QA fixture',as_of:'2026-01-01'},limits:{max_iterations:2}}}));
  await page.addInitScript(() => {
    sessionStorage.clear();
    window.EventSource = class { constructor(){ window.qaStream=this; } close(){} };
  });
  const snapshot={run_id:'qa',question:'Browser-only QA question',mode:'test',status:'running',stage:'Researcher',iteration:1,started_at:'2026-01-01T00:00:00Z',finished_at:null,last_seq:1,interpreted_request:'QA request',plan:[],evidence:[],report:null,revisions:[],evaluation:null,feedback:[],errors:[]};
  await page.route('**/api/runs',route=>route.fulfill({json:snapshot}));
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:5177');
  await page.getByRole('textbox',{name:'리서치 질문'}).fill('Browser-only QA question');
  await page.getByRole('button',{name:'리서치 시작'}).click();
  await page.waitForFunction(()=>!!window.qaStream);
  await page.evaluate(s=>window.qaStream.onmessage({data:JSON.stringify({run_id:'qa',seq:2,type:'model_start',timestamp:'2026-01-01T00:00:02Z',data:{snapshot:{...s,last_seq:2},role:'Researcher',attempt:1}})}),snapshot);
  await page.getByText('모델 요청 시작',{exact:false}).waitFor();
  const results=[];
  const check=(name,pass,actual)=>{results.push({name,pass,actual});};
  const desktop=await page.evaluate(()=>({background:getComputedStyle(document.body).backgroundColor,columns:getComputedStyle(document.querySelector('.workspace')).gridTemplateColumns,sidebar:document.querySelector('.workspace-sidebar').getBoundingClientRect().width,overflow:document.documentElement.scrollWidth>innerWidth,animation:getComputedStyle(document.querySelector('.timeline-event')).animationName}));
  check('white surface',desktop.background==='rgb(255, 255, 255)',desktop);
  check('desktop sidebar bounded',desktop.sidebar>=150&&desktop.sidebar<=220,desktop.sidebar);
  check('event motion enabled',desktop.animation!=='none',desktop.animation);
  check('desktop no page overflow',!desktop.overflow,desktop.overflow);
  await page.emulateMedia({reducedMotion:'reduce'});
  check('reduced motion removes event animation',await page.locator('.timeline-event').evaluate(el=>getComputedStyle(el).animationName)==='none');
  await page.setViewportSize({width:390,height:844});
  const mobile=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,sidebar:getComputedStyle(document.querySelector('.workspace-sidebar')).display,grid:getComputedStyle(document.querySelector('.workspace')).gridTemplateColumns,laneOverflow:getComputedStyle(document.querySelector('.stages')).overflowX}));
  check('mobile no page overflow',!mobile.overflow,mobile);
  check('mobile sidebar hidden',mobile.sidebar==='none',mobile.sidebar);
  check('mobile lane scroll contained',mobile.laneOverflow==='auto',mobile.laneOverflow);
  await page.getByRole('button',{name:'수집 자료 보기'}).click();
  check('mobile source view accessible',await page.getByText('검색 결과는 인용 근거가 아닙니다.',{exact:false}).isVisible());
  if(results.some(r=>!r.pass)) throw new Error(JSON.stringify(results));
  return results;
}
