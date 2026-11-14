// Read a completed synthetic run; exercise editorial progress without another model call.
const home=require('node:os').homedir();
const {chromium}=require(home+'/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
(async()=>{
  const rid=process.argv[2];if(!rid||!/^[a-z0-9]+$/i.test(rid))throw Error('Provide a completed synthetic run id');
  const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try{
    const page=await browser.newPage({baseURL:'http://127.0.0.1:8765',viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const response=await page.request.get('/report/'+rid+'/json');if(!response.ok())throw Error('Run not available');
    const run=await response.json();if(!run.editorial_quality||run.editorial_quality.status!=='passed')throw Error('Missing editorial review');
    await page.goto('/?case='+run.case_id);await page.locator('.reader-title').waitFor();
    if(await page.locator('.arc-step').count()!==run.report.reader.story.arc.length)throw Error('Story arc mismatch');
    await page.locator('.arc-step [data-ref]').first().click();await page.locator('.evidence-card pre').waitFor();
    await page.getByRole('button',{name:'运行记录',exact:true}).click();
    if(!(await page.locator('.run-item').first().innerText()).includes('自动编辑 '+run.editorial_trace.length+' 次'))throw Error('Editorial call accounting missing');
    const pdf=await page.request.get('/report/'+rid+'/pdf');if(!pdf.ok()||(await pdf.body()).subarray(0,4).toString()!=='%PDF')throw Error('PDF export failed');
    const html=await page.request.get('/report/'+rid+'/html');if(!html.ok()||!(await html.text()).includes(run.report.reader.title))throw Error('HTML export failed');
    await page.getByRole('button',{name:'事件报告',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
    fs.mkdirSync('output',{recursive:true});await page.screenshot({path:'output/editorial-mobile.png',fullPage:true});
    // Intercept progress only; no /api/analyze request and no new inference.
    const states=['editor_plan','editor_draft','editor_review_0','editor_rewrite_1','editor_review_1'];
    let ix=0;await page.route('**/api/jobs/editorialuitest',route=>route.fulfill({json:ix<states.length?
      {status:'running',phase:'editing',stage:states[ix++],step:0,total:0}:{status:'failed',error:'合成测试：自动编辑未通过，原始分析已保留。'}}));
    await page.evaluate(()=>pollJob('editorialuitest'));
    await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('提炼事件主线'));
    if((await page.locator('#feedback').innerText()).includes('0/0'))throw Error('Invalid progress denominator');
    await page.waitForFunction(()=>document.querySelector('#feedback').classList.contains('error'),null,{timeout:30000});
    if(await page.locator('#analyze').isDisabled())throw Error('Failed edit left button disabled');
    if(errors.length)throw Error(errors.join('\n'));
    console.log('PASS: actual edited report, references, call accounting, PDF/HTML, mobile layout, editorial progress and failure state');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
