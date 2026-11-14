const {chromium}=require(process.env.HOME+'/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}),page=await browser.newPage({viewport:{width:1200,height:900}});
 const cid=process.argv[2];if(!cid||!/^[a-z0-9]+$/i.test(cid))throw Error('Provide a case id with a completed run');
 const base='http://127.0.0.1:8765';
 const data=await (await page.request.get(base+'/api/cases/'+cid)).json();let continued=false,payload;
 const job={id:'uiresumetest',case_id:cid,status:'interrupted',stage:'editor_draft',max_requests:20,cached_steps:2,uncertain:true,error:'连接中断，当前阶段计费未知。',usage:{requests:3,input_tokens:1200,output_tokens:300,cached_input_tokens:500,unknown_usage_requests:1}};
 await page.route('**/api/cases/'+cid,r=>r.fulfill({json:{...data,jobs:continued?[{...job,status:'completed'}]:[job]}}));
 await page.route('**/api/resume',r=>{payload=r.request().postDataJSON();continued=true;r.fulfill({json:{id:job.id,status:'running'}})});
 await page.route('**/api/jobs/uiresumetest',r=>r.fulfill({json:{...job,status:'completed',result:data.runs[0]}}));
 await page.goto(base+'/?case='+cid);await page.locator('[data-resume]').waitFor();
 await page.screenshot({path:'tmp/reader-v2/progress.png'});
 if(!(await page.locator('#task-progress').innerText()).includes('用量未知'))throw Error('uncertain usage hidden');
 await page.reload();await page.locator('[data-resume]').waitFor();await page.locator('[data-resume]').click();
 await page.waitForFunction(()=>document.querySelector('#task-progress').classList.contains('hidden'));
 if(!payload.allow_uncertain||payload.max_requests!==20||payload.max_total_tokens!==60000||payload.job_id!==job.id)throw Error('retry acknowledgement mismatch');
 // Deterministic editorial failures expose reasons instead of a paid retry.
 continued=false;job.status='failed';job.uncertain=false;job.can_resume=false;
 job.error='有定位的内容审稿仍未通过';job.diagnostics=[{path:'/reader/verdict',problem:'结局与原文冲突',requested_change:'保留未完成状态'}];
 await page.reload();await page.locator('#task-progress details summary').waitFor();
 if(await page.locator('[data-resume]').count())throw Error('semantic failure offers blind retry');
 await page.locator('#task-progress details summary').click();
 if(!(await page.locator('#task-progress').innerText()).includes('结局与原文冲突'))throw Error('missing concrete diagnostics');
 console.log('PASS: disk-style interrupted progress survives refresh, unknown billing visible, explicit resume preserves limit, completed panel clears; resume mocked, no model calls.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
