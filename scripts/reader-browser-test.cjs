const {chromium}=require(process.env.HOME+'/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],remote=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:8765')&&!r.url().startsWith('data:'))remote.push(r.url());});
 const run=process.argv[2];if(!run||!/^[a-z0-9]+$/i.test(run))throw Error('Provide a completed run id');
 const data=await (await page.request.get('http://127.0.0.1:8765/report/'+run+'/json')).json(),cid=data.case_id;
 await page.goto('http://127.0.0.1:8765/?case='+cid);await page.locator('.reader-title').waitFor();
 if(await page.locator('#method').inputValue()!=='B1')throw Error('wrong default');
 await page.locator('.arc-step').first().locator('[data-ref]').first().click();await page.locator('.evidence-card pre').waitFor();
 fs.mkdirSync('tmp/reader-v2',{recursive:true});await page.screenshot({path:'tmp/reader-v2/workspace.png',fullPage:false});
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('workspace mobile overflow');
 await page.goto('http://127.0.0.1:8765/report/'+run+'/html');await page.locator('h1').waitFor();
 if(await page.evaluate(()=>[...document.querySelectorAll('a[href^="#"]')].some(a=>!document.getElementById(a.hash.slice(1)))))throw Error('missing internal target');
 if(!await page.locator('.turn:not([open]) .turn-brief').first().isVisible())throw Error('turn summary must be readable without opening');
 const initially=await page.locator('.chapter[open]').count();if(initially!==0)throw Error('chapters should start compact');
 await page.getByRole('button',{name:'展开详细经过',exact:true}).click();
 if(await page.locator('.chapter:not([open])').count())throw Error('expand not applied (CSP?)');
 await page.getByRole('button',{name:'收起详细经过',exact:true}).click();
 if(await page.locator('.chapter[open]').count())throw Error('collapse failed');
 await page.locator('.now .refs a').first().click();
 await page.locator('.original:target[open]').waitFor({timeout:5000});
 const imageSource=page.locator('.original').filter({has:page.locator('.zoom-image')}).first();
 const label=(await imageSource.locator('summary strong').innerText()).split(' · ')[0];
 await page.locator('#source-search').fill(label);
 if(await page.locator('.original:not([hidden])').count()!==1)throw Error('search mismatch');
 if(!await page.locator('.original:not([hidden])').evaluate(d=>d.open))await page.locator('.original:not([hidden]) summary').click();
 await page.locator('.original:not([hidden]) .zoom-image').click();
 if(await page.locator('dialog[open] img').evaluate(img=>!img.complete||!img.naturalWidth))throw Error('image not loaded');
 await page.getByRole('button',{name:'关闭图片',exact:true}).click();
 if(await page.locator('dialog[open]').count())throw Error('dialog not closed');
 await page.locator('#source-search').fill('');
 await page.goto('http://127.0.0.1:8765/report/'+run+'/html');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('report mobile overflow');
 await page.screenshot({path:'tmp/reader-v2/mobile.png',fullPage:false});
 await page.setViewportSize({width:1200,height:1000});await page.screenshot({path:'tmp/reader-v2/desktop.png',fullPage:false});
 // Standalone file must retain interactions without localhost or remote requests.
 const exported=await (await page.request.get('http://127.0.0.1:8765/report/'+run+'/html')).body();
 fs.writeFileSync('tmp/reader-v2/offline.html',exported,{mode:0o600});
 await page.goto('file://'+process.cwd()+'/tmp/reader-v2/offline.html');
 await page.getByRole('button',{name:'展开详细经过',exact:true}).click();
 if(await page.locator('.chapter[open]').count()===0)throw Error('offline interaction failed');
 await page.getByRole('button',{name:'收起详细经过',exact:true}).click();
 await page.locator('#source-search').fill('no-such-source-for-print-test');
 if(await page.locator('.original:not([hidden])').count())throw Error('test filter did not hide original sources');
 await page.evaluate(()=>{window.print=()=>window.dispatchEvent(new Event('test-print-triggered'));});
 await Promise.all([
  page.evaluate(()=>new Promise(resolve=>addEventListener('test-print-triggered',resolve,{once:true}))),
  page.getByRole('button',{name:'打印 / 存为 PDF'}).click(),
 ]);
 await page.pdf({path:'tmp/reader-v2/print.pdf',preferCSSPageSize:true,printBackground:true});
 if(await page.locator('.chapter[open],.original:not([hidden])').count())throw Error('print did not restore screen state');
 if(errors.length)throw Error(errors.join('\n'));if(remote.filter(x=>!x.startsWith('file:')).length)throw Error('unexpected network');
 console.log('PASS: desktop/mobile reading, expandable stages/chapters, citations, original search, image zoom, offline HTML, no external requests.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
