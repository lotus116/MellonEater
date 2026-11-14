'use strict';
const $=s=>document.querySelector(s);
let config, current, runs=[], activeRun=null, tab='report', filter='全部', attachments=[], fileName='', activeJob=null, caseJobs=[];
const methods={B0:'普通提示',B1:'标准阅读',B2:'证据工作流',A1:'自由笔记对照',imported:'导入结果'};
const stages={bind_sources:'核对发言、场景与原文',bind_sources_repair:'补正原文定位',compose:'撰写新报告',compose_repair:'补正成稿格式',audit_0:'对照原文审稿',audit_1:'核对局部返修',audit_2:'最终核对',patch_1:'修正具体问题',patch_2:'修正剩余问题',queued:'准备材料',discover:'发现事件',evidence:'整理证据与来源',assess:'核对主张与评价',review:'复核分析与反证',editor_plan:'提炼事件主线',editor_plan_repair:'修正主线提纲',editor_draft:'撰写阅读稿',editor_review_0:'核对主线、时间和证据',editor_review_1:'复核返修稿',editor_review_2:'最终复核',editor_rewrite_1:'自动优化阅读稿',editor_rewrite_2:'再次优化阅读稿',B0:'直接分析',B1:'按详细规则分析',notes:'整理自由笔记',notes_assess:'推敲判断与反证'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,data){const options=data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Chigua-Token':config.token},body:JSON.stringify(data)};const res=await fetch(path,options);const out=await res.json();if(!res.ok)throw Error(out.error||'请求失败');return out;}
function feedback(text,error=false){const box=$('#feedback');box.textContent=text;box.classList.toggle('error',error);box.classList.toggle('hidden',!text);}
function refLabel(id){const i=current?.messages.findIndex(m=>m.id===id)??-1;return i<0?'未知材料':'M'+String(i+1).padStart(3,'0');}
function readableNote(note){return String(note||'').replaceAll('missingImage','导出包中没有对应图片').replaceAll('ambiguousImage','同名图片无法确定对应关系').replaceAll('imageTooLarge','图片超过处理上限').replaceAll('imageFormatUnavailable','图片格式暂时无法读取').replaceAll('未自动发送给模型。','导入步骤本身未启动模型分析。');}
function refButtons(ids){return(ids||[]).map(id=>`<button class="ref" data-ref="${esc(id)}" title="查看 ${esc(refLabel(id))} 原文">${esc(refLabel(id))}</button>`).join('');}
function badge(status){return `<span class="badge ${status==='无法判断'||status==='有条件'?'unknown':status==='存在反证'?'conflict':''}">${esc(status)}</span>`;}
function reportNotice(){return '<p class="notice">编号校验通过仅表示引用可回查；证据是否支持判断仍需人工核对。</p>';}
function renderClaim(c,full=false){return `<article class="claim"><div class="claim-head">${badge(c.status)}<h3>${esc(c.statement)}</h3></div><p>${esc(c.reason)}</p><div class="detail">支持 ${refButtons(c.support_ids)||'尚缺'} ${c.conflict_ids.length?'　冲突 '+refButtons(c.conflict_ids):''}</div><details ${full?'open':''}><summary>查看标准、来源与未知项</summary><p><strong>适用标准：</strong>${esc(c.standard)}</p><p><strong>来源说明：</strong>${esc(c.source_note)}</p><p><strong>尚待确认：</strong>${esc(c.unknowns.join('；')||'无额外列项')}</p><p><strong>改变条件：</strong>${esc(c.would_change_if)}</p></details></article>`;}
function storyThreads(story){if(!story?.threads?.length)return '';return `<section class="story-threads"><h2>把支线放回主线</h2>${story.threads.map(t=>`<article><h3>${esc(t.name)}</h3><p>${esc(t.role_in_story)}</p>${refButtons(t.source_ids)}</article>`).join('')}</section>`;}
function usageText(u){if(!u)return '旧版运行未记录完整用量';return `实际请求 ${u.requests} 次 · 已记录输入 ${u.input_tokens.toLocaleString()} / 输出 ${u.output_tokens.toLocaleString()} token${u.reasoning_tokens?`（其中思考 ${u.reasoning_tokens.toLocaleString()}）`:""} · 服务端缓存命中 ${u.cached_input_tokens.toLocaleString()}${u.unknown_usage_requests?' · '+u.unknown_usage_requests+' 次用量未知':''}`;}
function taskPanel(){
  const box=$('#task-progress'),j=caseJobs[0]?.status!=='completed'?caseJobs[0]:null;
  box.classList.toggle('hidden',!j);if(!j)return;
  const running=j.status==='running', resumable=j.can_resume!==false;
  const details=j.diagnostics?.length?`<details><summary>查看 ${j.diagnostics.length} 个具体问题</summary><ul>${j.diagnostics.map(d=>`<li><strong>${esc(d.path||d.location||'校验')}</strong>：${esc(d.problem)}${d.requested_change||d.fix?`<p>修正方向：${esc(d.requested_change||d.fix)}</p>`:''}</li>`).join('')}</ul></details>`:'';
  box.innerHTML=`<strong>${running?'正在处理，已完成的步骤会保留':resumable?'进度已保存，可从这里继续':'需要处理具体问题，已停止追加调用'}</strong><p>${esc(stages[j.stage]||(j.stage?.startsWith('vision_')?'读取图片':j.stage?.startsWith('numbered_review_')?'对照证据审稿':j.stage?.startsWith('audit_contract_fix_')?'校正审稿定位':j.stage))} · 已缓存 ${j.cached_steps||0} 步</p><p class="muted">${esc(usageText(j.usage))} / 上限 ${j.max_requests||20} 次${j.max_total_tokens?` · 已记录 token 阈值 ${j.max_total_tokens}`:''}</p>${j.error?`<p>${esc(j.error)}</p>`:''}${details}${j.draft_available?`<p><a href="/report/${encodeURIComponent(j.id)}/draft" target="_blank" rel="noopener">查看已保存的底稿</a></p>`:''}${!running&&(j.cached_steps||j.uncertain)?`<button class="secondary" data-recheck="${esc(j.id)}">仅使用缓存恢复</button>`:''}${!running&&resumable?`<p class="muted">继续会复用已完成结果。${j.uncertain?'当前阶段的计费情况未知；点击继续表示同意仅重试这一阶段。':''}</p><label>请求上限（提高后才允许追加）<input id="resume-limit" type="number" min="${j.max_requests||20}" max="100" value="${j.max_requests||20}"></label><label>已记录 token 阈值（到达后停止下一请求）<input id="resume-token-limit" type="number" min="${j.max_total_tokens||1000}" max="1000000" value="${j.max_total_tokens||60000}"></label><button class="secondary" data-resume="${esc(j.id)}">${j.uncertain?'确认并继续未完成步骤':'从已保存的步骤继续'}</button>`:!running?'<p class="muted">不会原样重跑已经失败的返修。修正流程后可明确新建；旧候选稿与用量保留。</p>':''}`;
}
function storyMap(story){if(!story)return '';return `<section class="story-map" id="reader-turns"><h2>事情怎么发展</h2><p>${esc(story.central_question)}</p><p class="muted">点开一个阶段，查看变化和依据；编号是阅读顺序。</p><div class="turn-rail">${story.arc.map((step,i)=>`<details class="arc-step turn-step" ${i===0?'open':''}><summary><span class="turn-number">${i+1}</span><span><strong>${esc(step.stage)}</strong><small>${esc([step.event_time,step.order_basis,step.source_attribution].filter(Boolean).join(' · '))}</small></span></summary><div class="turn-content"><p>${esc(step.happened)}</p><p><strong>变化在这里：</strong>${esc(step.changed)}</p>${refButtons(step.source_ids)}</div></details>`).join('')}</div><details class="scope-details"><summary>时间范围与不确定之处</summary><p>${esc(story.timeline_note)}</p></details></section>`;}
function comparisonSection(items){if(!items?.length)return '';return `<section id="reader-comparisons"><h2>各方怎么说</h2>${items.map(d=>`<article class="reader-chapter"><h3>${esc(d.topic)}</h3>${d.accounts.map(a=>`<p><strong>${esc(a.speaker)}</strong> ${esc(a.statement)}</p>${refButtons(a.source_ids)}`).join('')}${d.limit?`<p>${esc(d.limit)}</p>`:''}</article>`).join('')}</section>`;}
function behaviorSection(items){
  if(!items.length)return '';
  return `<section id="reader-assessment"><h2>怎么看双方的做法</h2>${items.map(item=>`
    <article class="reader-chapter"><h3>${esc(item.title)}</h3>
    <p><strong>行为判断</strong> ${esc(item.judgment)}</p>
    <details class="dispute"><summary>看依据${item.inference?'和推测':''}</summary>
    <p><strong>记录里看到的</strong> ${esc(item.observation)}</p>${refButtons(item.source_ids)}
    ${item.inference?`<p><strong>一种解释</strong> ${esc(item.inference)}</p>`:''}
    ${item.counterpoint?`<p><strong>还要考虑</strong> ${esc(item.counterpoint)}</p>${refButtons(item.conflict_ids)}`:''}
    </details></article>`).join('')}</section>`;
}
function unresolvedSection(questions){
  if(!questions.length)return '';
  return `<section class="reader-unknown" id="reader-unresolved"><h2>还有哪些事没说清</h2><ul>${questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></section>`;
}
function renderReading(r){
  const story=r.reader, ids=new Set([...story.chapters.flatMap(c=>c.paragraphs.flatMap(p=>p.source_ids)),...story.verdict_source_ids]);
  const assessments=story.assessment||[];
  const questions=unresolvedSection(story.open_questions);
  const claims=assessments.length?[]:(r.claims||[]).filter(c=>[...c.support_ids,...c.conflict_ids].some(id=>ids.has(id))).slice(0,4);
  const minutes=Math.max(1,Math.ceil((story.lead+story.verdict+story.chapters.flatMap(c=>c.paragraphs.map(p=>p.text)).join('')).length/450));
  return `<article class="human-reader"><div class="reading-meta">约 ${minutes} 分钟读完 · 点击编号可核对原话</div><h2 class="reader-title">${esc(story.title)}</h2><p class="reader-deck">${esc(story.deck)}</p><nav class="reader-nav" aria-label="报告阅读导航"><a href="#reader-now">先看结果</a>${story.story?'<a href="#reader-turns">关键转折</a>':''}${assessments.length?'<a href="#reader-assessment">怎么看双方的做法</a>':''}${story.open_questions.length?'<a href="#reader-unresolved">待确认</a>':''}<a href="#reader-detail">详细经过</a>${claims.length?'<a href="#reader-disputes">争议焦点</a>':''}</nav><p class="report-summary">${esc(story.lead)}</p><section class="current-state" id="reader-now"><span class="state-label">目前进展</span><h3>${esc(story.verdict_title)}</h3><p>${esc(story.verdict)}</p><div>${refButtons(story.verdict_source_ids)}</div></section>${story.people.length?`<section class="cast"><h2>这件事里都有谁</h2><div class="people">${story.people.map(p=>`<div><strong>${esc(p.name)}</strong><span>${esc(p.role)}</span>${refButtons(p.source_ids)}</div>`).join('')}</div></section>`:''}${storyMap(story.story)}${comparisonSection(story.dispute_comparisons)}${behaviorSection(assessments)}${assessments.length?questions:''}<section id="reader-detail"><h2 class="section-title">把经过展开讲</h2>${story.chapters.map(ch=>`<section class="reader-chapter"><h3>${esc(ch.title)}</h3>${ch.paragraphs.map(p=>`<p>${esc(p.text)}</p><div class="reader-refs">${refButtons(p.source_ids)}</div>`).join('')}${ch.quote_text?`<blockquote>${esc(ch.quote_text)}<cite>${esc(ch.quote_speaker)} ${refButtons([ch.quote_source_id])}</cite></blockquote>`:''}${ch.image_id&&current.messages.find(m=>m.id===ch.image_id)?.image?`<figure><a href="/media/${encodeURIComponent(current.messages.find(m=>m.id===ch.image_id).image)}" target="_blank" rel="noopener"><img src="/media/${encodeURIComponent(current.messages.find(m=>m.id===ch.image_id).image)}" alt="${esc(ch.image_caption)}" loading="lazy"></a><figcaption>${esc(ch.image_caption)} ${refButtons([ch.image_id])}</figcaption></figure>`:''}</section>`).join('')}</section>${claims.length?`<section id="reader-disputes"><h2>大家争的是什么</h2><p class="muted">下面是材料中的主张与核对结果，不把一方的说法直接当成事实。</p>${claims.map(c=>`<details class="dispute"><summary>${esc(c.statement)} ${badge(c.status)}</summary>${renderClaim(c)}</details>`).join('')}</section>`:''}${storyThreads(story.story)}${assessments.length?'':questions}<details class="scope-details"><summary>这份整理用了哪些材料</summary><p>${esc(readableNote(current.source_note))}</p><p>${esc(methods[activeRun.method]||activeRun.method)} · ${esc(activeRun.trace?.[0]?.model||activeRun.editorial_trace?.[0]?.model||'模型未记录')}</p><p>正文使用角色称呼；原文和图片可能包含个人信息，分享前请另行核对。</p></details></article>`;
}
function render(){
  const target=$('#content');$('#open-reader').classList.toggle('hidden',!activeRun);if(activeRun)$('#open-reader').href='/report/'+activeRun.id+'/html';
  document.querySelectorAll('.tab').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);b.setAttribute('aria-selected',String(b.dataset.tab===tab));});
  if(!current){target.innerHTML='<div class="empty"><h2>先把材料放在一起</h2><p>导入聊天文字或截图，从一个真实案例开始。</p></div>';return;}
  if(tab==='materials'){
    target.innerHTML=`<label>搜索原文<input class="search" id="material-search" placeholder="输入人物或关键词"></label><p class="muted">共 ${current.messages.length} 个材料单元。编号表示本包顺序，不能代替原始时间。</p><div id="material-list"></div><p><a href="/api/export/${current.id}" download>导出材料包 JSON</a></p>`;
    const fill=q=>{$('#material-list').innerHTML=current.messages.filter(m=>(m.text+m.speaker).includes(q)).map(m=>`<article class="material"><div class="material-meta">${refButtons([m.id])}<strong>${esc(m.speaker)}</strong><span>${esc(m.timestamp||'时间未知')}</span></div><p>${esc(m.text)}</p>${m.image?`<button class="secondary" data-ref="${esc(m.id)}">查看图片</button>`:''}${m.parent_id?`<p class="muted">父容器：${esc(refLabel(m.parent_id))}</p>`:''}</article>`).join('')||'<p class="muted">没有匹配的材料。</p>';};fill('');$('#material-search').oninput=e=>fill(e.target.value);return;
  }
  if(tab==='runs'){
    target.innerHTML=`<h2>每次判断，都留下记录</h2><p class="muted">原始输入、模型、方法与结果分别保存。不同方法的结果不能直接当作质量排名。</p>${runs.map(r=>`<article class="run-item"><strong>${esc(methods[r.method]||r.method)}</strong><p>${esc(new Date(r.created_at).toLocaleString('zh-CN'))} · ${esc(r.origin==='live_model'?'模型实时生成':r.origin)}</p><p>分析 ${r.trace?.length||0} 步${r.editorial_trace?.length?' + 自动编辑 '+r.editorial_trace.length+' 步':''} · ${Math.round([...(r.trace||[]),...(r.editorial_trace||[])].reduce((s,t)=>s+(t.seconds||0),0))} 秒 · ${esc(r.trace?.[0]?.model||'未记录模型')}</p><p class="muted">${esc(usageText(r.usage))}</p><div class="run-actions"><button class="secondary" data-run="${r.id}">查看这份报告</button><a href="/report/${r.id}/json" download>结果 JSON</a><a href="/report/${r.id}/html" target="_blank" rel="noopener">独立报告</a></div></article>`).join('')||'<div class="empty"><p>还没有分析记录。点击上方“生成分析报告”开始。</p></div>'}<details><summary>在其他聊天中完成分析</summary><p><a href="/api/prompts/${current.id}" download>下载带原文的分析请求</a></p><label>导入分析结果 JSON<input id="result-file" type="file" accept=".json"></label><p class="muted">导入结果会标明来源；不会计为本程序自动分析。</p></details>`;
    const input=$('#result-file');if(input)input.onchange=async()=>{try{let data=JSON.parse(await input.files[0].text());await api('/api/import-result',{case_id:current.id,report:data.report||data});await loadCase(current.id);feedback('分析结果已导入并通过编号检查。');}catch(e){feedback(e.message,true);}};return;
  }
  if(!activeRun){target.innerHTML=`<div class="empty"><h2>材料已就绪</h2><p>已保存 ${current.messages.length} 个材料单元。现在可以生成报告，或先检查全部材料。</p><button class="secondary" id="view-materials">先看材料</button></div><div class="source-note">${esc(readableNote(current.source_note))}</div>`;$('#view-materials').onclick=()=>{tab='materials';render();};return;}
  const r=activeRun.report;
  if(tab==='claims'){
    const options=['全部','有依据','部分支持','有条件','存在反证','无法判断'];
    target.innerHTML=`<h2>逐条核对，不把说法当事实</h2><div class="filters">${options.map(s=>`<button class="filter ${s===filter?'active':''}" data-filter="${s}">${s}</button>`).join('')}</div>${r.claims.filter(c=>filter==='全部'||c.status===filter).map(c=>renderClaim(c,true)).join('')||'<p class="muted">没有这一类判断。</p>'}${reportNotice()}`;return;
  }
  if(r.reader){
    const quality=activeRun.editorial_quality;
    const limitations=quality?.status==='limited' ? quality.limitations||[] : [];
    const notice=limitations.length ? `<aside class="notice"><strong>已生成 · 复核有局限</strong><ul>${limitations.map(note=>`<li>${esc(note)}</li>`).join('')}</ul></aside>` : '';
    target.innerHTML=notice+renderReading(r);
    return;
  }
  target.innerHTML=`<div class="status-line">${esc(methods[activeRun.method]||activeRun.method)} · ${activeRun.origin==='live_model'?'模型实时生成':esc(activeRun.origin)} · ${esc(activeRun.trace?.[0]?.model||activeRun.editorial_trace?.[0]?.model||'模型未记录')}</div><p class="report-summary">${esc(r.summary)}</p><div class="source-note">${esc(readableNote(current.source_note))}</div><h2 class="section-title">发生了什么</h2>${r.events.map(e=>`<article class="event-item"><h3>${esc(e.title)}</h3><p>${esc(e.summary)}</p>${refButtons(e.message_ids)}</article>`).join('')}<h2 class="section-title">哪些判断站得住脚</h2>${r.claims.map(c=>renderClaim(c)).join('')}<h2 class="section-title">事件线索</h2><div class="timeline">${r.timeline.map(t=>`<div class="timeline-item"><strong>${esc(t.time_label)}</strong><p>${esc(t.description)}</p>${refButtons(t.message_ids)}</div>`).join('')}</div><h2 class="section-title">仍然不知道的部分</h2><ul class="limits">${r.limitations.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>${reportNotice()}`;
}
function showEvidence(id){const m=current?.messages.find(m=>m.id===id);if(!m)return;$('#evidence').innerHTML=`<article class="evidence-card"><span class="badge">${esc(refLabel(m.id))}</span><h3>${esc(m.speaker)}</h3><p class="muted">${esc(m.timestamp||'原始时间未知')}<br>${esc(m.source_kind)} / ${esc(m.unit)}</p>${m.parent_id?`<p class="muted">所属材料 ${refButtons([m.parent_id])}</p>`:''}<pre>${esc(m.text)}</pre>${m.image?`<a href="/media/${encodeURIComponent(m.image)}" target="_blank" rel="noopener"><img src="/media/${encodeURIComponent(m.image)}" alt="${esc(m.source_name)} 材料图片"></a>`:''}${m.uncertainty?`<p class="source-note">${esc(readableNote(m.uncertainty))}</p>`:''}<p class="muted">${esc(m.source_name)}<br>来源根：${esc(m.source_root||'未确认；不能据此假定为独立来源')}</p></article>`;if(innerWidth<=900)$('#evidence').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}
async function loadList(){const list=await api('/api/cases');$('#case-list').innerHTML=list.map(c=>`<button class="case-item ${current?.id===c.id?'selected':''}" data-case="${c.id}">${esc(c.title)}<small>${c.count} 个材料单元</small></button>`).join('');return list;}
async function loadCase(id){const obj=await api('/api/cases/'+id);current=obj.case;$('#clear-evidence').click();runs=obj.runs;caseJobs=obj.jobs||[];taskPanel();activeRun=runs[0]||null;history.replaceState(null,'','/?case='+encodeURIComponent(id));$('#case-title').textContent=current.title;$('#case-breadcrumb').textContent='我的案例 / '+current.title;$('#case-meta').textContent=`${current.messages.length} 个材料单元 · ${new Set(current.messages.map(m=>m.speaker)).size} 个发言标签 · ${current.messages.filter(m=>m.image).length} 张图片`;const gaps=current.messages.reduce((n,m)=>n+(m.parent_id?0:(m.source_reference?.media||[]).filter(x=>x.status==='unavailable').length),0);$('#media-warning').classList.toggle('hidden',!gaps);$('#supplement-images').classList.toggle('hidden',!gaps);$('#media-warning').textContent=gaps?`本包有 ${gaps} 张图片未取得，文件名不能代替图片内容。可在微信中单独保存图片，再点“补齐图片”逐条核对绑定。文字报告仍可生成，但会保留缺图说明。`:'';$('#identity').value=current.identity;$('#analyze').disabled=!!activeJob;await loadList();render();}
function showModel(){const m=config.model;$('#model-status').textContent=(m.provider==='manual'?'仅查看':m.provider==='deepseek'?'DeepSeek':m.provider==='api'?'API':'Codex')+' / '+m.model;}
async function refreshConfig(){config=await api('/api/config');showModel();}
document.addEventListener('click',async e=>{const ref=e.target.closest('[data-ref]');if(ref)showEvidence(ref.dataset.ref);const c=e.target.closest('[data-case]');if(c){try{await loadCase(c.dataset.case);feedback('');}catch(err){feedback(err.message,true);}}const r=e.target.closest('[data-run]');if(r){activeRun=runs.find(x=>x.id===r.dataset.run);tab='report';render();}const f=e.target.closest('[data-filter]');if(f){filter=f.dataset.filter;render();}});
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;render();});
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#clear-evidence').onclick=()=>{$('#evidence').innerHTML='<div class="evidence-empty"><h3>选择一条材料</h3><p>点击报告里的材料编号，查看完整原文。</p></div>';};
$('#new-case').onclick=()=>{$('#import-form').reset();attachments=[];fileName='';$('#upload-list').textContent='';$('#import-error').textContent='';$('#import-dialog').showModal();};
$('#import-files').onchange=async e=>{const files=[...e.target.files];$('#save-case').disabled=true;$('#import-error').textContent='';try{for(const file of files){$('#upload-list').textContent='正在读取 '+file.name+'…';if(/\.(txt|json|jsonl)$/i.test(file.name)){if($('#import-text').value.trim())throw Error('每次导入请使用一个文字文件；可在保存后另建案例。');$('#import-text').value=await file.text();fileName=file.name;}else{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});attachments.push(await api('/api/upload',{name:file.name,data}));}if(!$('#import-title').value)$('#import-title').value=file.name.replace(/\.[^.]+$/,'');}$('#upload-list').textContent=[fileName,...attachments.map(a=>`${a.source_name}（识别 ${a.ocr_lines.length} 行）`)].filter(Boolean).join('；');}catch(err){$('#import-error').textContent=err.message;}finally{$('#save-case').disabled=false;}};
$('#import-form').onsubmit=async e=>{e.preventDefault();$('#save-case').disabled=true;$('#import-error').textContent='';try{const c=await api('/api/cases',{title:$('#import-title').value,text:$('#import-text').value,filename:fileName||'粘贴文字.txt',attachments,question:$('#import-question').value});$('#import-dialog').close();tab='materials';await loadCase(c.id);feedback('材料已保存。可以检查原文，再开始分析。');}catch(err){$('#import-error').textContent=err.message;}finally{$('#save-case').disabled=false;}};
$('#analyze').onclick=async()=>{if(!current)return;$('#analyze').disabled=true;try{const job=await api('/api/analyze',{case_id:current.id,method:$('#method').value,identity:$('#identity').value,force:$('#force-new').checked,max_requests:Number($('#max-requests').value),max_total_tokens:Number($('#max-total-tokens').value)});$('#force-new').checked=false;activeJob=job.id;pollJob(job.id);}catch(err){feedback(err.message,true);$('#analyze').disabled=false;}};
async function pollJob(id,readFailures=0){try{const j=await api('/api/jobs/'+id);if(current?.id===j.case_id){caseJobs=[j,...caseJobs.filter(x=>x.id!==id)];taskPanel();}if(j.status==='running'){activeJob=id;$('#analyze').disabled=true;feedback(`${stages[j.stage]||j.stage}${j.phase==='editing'?'':`（${j.step}/${j.total}）`}… 已完成步骤不会重复请求。`);setTimeout(()=>pollJob(id),2500);}else{activeJob=null;$('#analyze').disabled=false;if(j.status==='completed'){if(current?.id===j.result.case_id){tab='report';await loadCase(current.id);}feedback(j.result.editorial_quality?.status==='limited'?'报告已生成。请留意页面注明的复核局限。':'报告已就绪。展开阶段看经过，点击编号核对原文。');}else feedback(j.error||'任务已暂停，已保存步骤可继续。',true);}}catch(err){if(readFailures<3&&activeJob===id){setTimeout(()=>pollJob(id,readFailures+1),2500);return;}activeJob=null;$('#analyze').disabled=false;feedback('暂时无法读取进度。连接恢复后刷新即可。',true);}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-recheck]');if(!b)return;b.disabled=true;try{const next=await api('/api/resume',{job_id:b.dataset.recheck,local_only:true});activeJob=next.id;pollJob(next.id);}catch(err){feedback(err.message,true);b.disabled=false;}});
document.addEventListener('click',async e=>{const b=e.target.closest('[data-resume]');if(!b)return;b.disabled=true;try{const j=caseJobs.find(x=>x.id===b.dataset.resume);const next=await api('/api/resume',{job_id:b.dataset.resume,allow_uncertain:!!j?.uncertain,max_requests:Number($('#resume-limit').value),max_total_tokens:Number($('#resume-token-limit').value)});activeJob=next.id;pollJob(next.id);}catch(err){feedback(err.message,true);b.disabled=false;}});
function providerFields(reset=false){const p=$('#provider').value;$('#deepseek-thinking-field').classList.toggle('hidden',p!=='deepseek');$('#api-fields').classList.toggle('hidden',!['api','deepseek'].includes(p));if(reset){if(p==='deepseek'){$('#base-url').value='https://api.deepseek.com';$('#model').value='deepseek-flash';}else if(p==='codex'){$('#model').value='';}}}
$('#provider').onchange=()=>providerFields(true);
$('#open-settings').onclick=async()=>{await refreshConfig();$('#provider').value=config.model.provider;$('#model').value=config.model.model==='未配置'||config.model.model==='本机 Codex 默认模型'?'':config.model.model;$('#base-url').value=config.model.base_url;$('#deepseek-thinking').value=config.model.deepseek_thinking||'disabled';$('#api-key').value='';$('#api-key').placeholder=config.model.has_key?'已配置；留空保留现有密钥':'仅保存在当前服务进程中';$('#mac-status').textContent=`本机微信 ${config.mac.wechat_version||'未检测到'}；本地截图识别${config.mac.ocr_available?'已就绪':'未就绪'}。`;$('#settings-error').textContent='';providerFields();$('#settings-dialog').showModal();};
$('#settings-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/settings',{provider:$('#provider').value,model:$('#model').value,base_url:$('#base-url').value,api_key:$('#api-key').value,deepseek_thinking:$('#deepseek-thinking').value});await refreshConfig();$('#settings-dialog').close();feedback('模型设置已更新；后续分析将使用新的入口。');}catch(err){$('#settings-error').textContent=err.message;}};
(async()=>{try{await refreshConfig();const list=await loadList();const requested=new URLSearchParams(location.search).get('case');if(list.length)await loadCase(list.find(c=>c.id===requested)?.id||list[0].id);if(config.active_jobs?.length){activeJob=config.active_jobs[0].id;$('#analyze').disabled=true;pollJob(activeJob);}}catch(err){feedback('连接本地服务失败：'+err.message,true);}})();

let zipBusy=false;
async function openZipImport(){
  $('#zip-form').reset();$('#zip-error').textContent='';$('#zip-progress').textContent='';
  $('#zip-dialog').showModal();
  try{const scope=await api('/api/wechat-zip/defaults');
    for(const field of ['group','start','end'])if(!$('#zip-'+field).value)$('#zip-'+field).value=scope[field]||'';
  }catch(e){$('#zip-error').textContent='未能读取默认范围，请填写群名和日期；若导入失败，请重新启动 demo。';}
}
$('#new-zip').onclick=openZipImport;
$('#switch-zip').onclick=()=>{$('#import-dialog').close();openZipImport();};
$('#zip-dialog').addEventListener('cancel',e=>{if(zipBusy)e.preventDefault();});
$('#zip-files').onchange=()=>{const files=[...$('#zip-files').files];$('#zip-error').textContent='';$('#zip-progress').textContent=`已选择 ${files.length} 个 ZIP`;if(files.length&&!$('#zip-title').value)$('#zip-title').value=files[0].name.replace(/\.zip$/i,'').slice(0,100);};
$('#zip-form').onsubmit=async e=>{
  e.preventDefault();if(zipBusy)return;
  const files=[...$('#zip-files').files];$('#zip-error').textContent='';
  if(!files.length||files.length>100||files.some(f=>! /\.zip$/i.test(f.name))||files.reduce((n,f)=>n+f.size,0)>256*1024*1024){$('#zip-error').textContent='请选择 1 至 100 个 ZIP，总大小不超过 256 MB。';return;}
  const start=$('#zip-start').value,end=$('#zip-end').value;
  if(start>end){$('#zip-error').textContent='结束日期不能早于开始日期。';return;}
  const payload={title:$('#zip-title').value,group:$('#zip-group').value,start:start+'T00:00:00+08:00',end:end+'T23:59:59+08:00',uploads:[]};
  zipBusy=true;$('#zip-form').setAttribute('aria-busy','true');
  $('#zip-form').querySelectorAll('input,button').forEach(el=>el.disabled=true);
  try{
    for(let i=0;i<files.length;i++){
      $('#zip-progress').textContent=`正在保存第 ${i+1}/${files.length} 个 ZIP 到本机…`;
      const response=await fetch('/api/wechat-zip/upload',{method:'POST',headers:{'Content-Type':'application/zip','X-Chigua-Token':config.token},body:files[i]});
      const result=await response.json();if(!response.ok)throw Error(result.error||'ZIP 保存失败，请重试。');payload.uploads.push(result.id);
    }
    $('#zip-progress').textContent='正在整理文字、时间和对应图片…';
    const result=await api('/api/wechat-zip/import',payload);
    $('#zip-dialog').close();tab='materials';await loadCase(result.cases[0].id);
    feedback(`已导入 ${result.materials} 条材料、${result.images.available||0} 张图片，分为 ${result.cases.length} 包。缺图 ${result.images.unavailable||0} 张，范围外排除 ${result.excluded} 条，重复候选 ${result.duplicates} 条保留。请先检查原文，再生成报告。`);
  }catch(err){$('#zip-error').textContent=err.message;$('#zip-progress').textContent='导入未完成，所选文件仍保留，可修改范围后重试。';}
  finally{zipBusy=false;$('#zip-form').setAttribute('aria-busy','false');$('#zip-form').querySelectorAll('input,button').forEach(el=>el.disabled=false);}
};

let supplementRows=[], supplementBusy=false, supplementCase=null;
function updateSupplementCount(){const selected=supplementRows.filter(x=>x.asset);const checked=selected.filter(x=>x.confirmed);$('#save-supplements').disabled=supplementBusy||!checked.length;$('#save-supplements').textContent=`保存已核对的对应${checked.length?'（'+checked.length+' 张）':''}`;}
function supplementLock(busy){supplementBusy=busy;$('#supplement-form').setAttribute('aria-busy',String(busy));$('#supplement-form').querySelectorAll('input,select,button').forEach(el=>el.disabled=busy);for(const [i,row] of supplementRows.entries()){$(`[data-supplement-confirm="${i}"]`).disabled=busy||!row.asset;}updateSupplementCount();}
$('#supplement-images').onclick=()=>{
  supplementCase=current.id;supplementRows=[];$('#supplement-error').textContent='';$('#supplement-progress').textContent='';
  current.messages.forEach((m,index)=>{if(m.parent_id)return;(m.source_reference?.media||[]).forEach((media,mediaIndex)=>{if(media.status==='unavailable')supplementRows.push({message:m,label:refLabel(m.id),index,mediaIndex,media,asset:null,confirmed:false,kind:'saved_image'});});});
  $('#supplement-list').innerHTML=supplementRows.map((row,i)=>{const m=row.message;const context=[current.messages[row.index-1],current.messages[row.index+1]].filter(Boolean);return `<article class="supplement-row"><h3>${esc(refLabel(m.id))} · ${esc(m.speaker)}</h3><p class="muted">${esc(m.timestamp||'时间未知')}<br>待补图片：${esc(row.media.reference)}</p><details><summary>查看前后文字</summary>${context.map(x=>`<p><strong>${esc(x.speaker)}</strong>：${esc(x.text.slice(0,240))}${x.text.length>240?'…':''}</p>`).join('')}</details><label>为 ${esc(refLabel(m.id))} 选择图片<input data-supplement-file="${i}" type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg"></label><label>图片来源<select data-supplement-kind="${i}"><option value="saved_image">从微信单独保存的图片</option><option value="screenshot">截图（可能经过裁切）</option></select></label><div data-supplement-preview="${i}"></div><label class="supplement-confirm"><input data-supplement-confirm="${i}" type="checkbox" disabled>我已在微信中核对，这张图对应上面的这条记录</label><button class="plain" type="button" data-supplement-remove="${i}">移除所选图片</button></article>`;}).join('');
  updateSupplementCount();$('#supplement-dialog').showModal();
};
$('#supplement-dialog').addEventListener('cancel',e=>{if(supplementBusy)e.preventDefault();});
$('#supplement-list').addEventListener('change',async e=>{
  const index=e.target.dataset.supplementFile??e.target.dataset.supplementKind??e.target.dataset.supplementConfirm;if(index===undefined)return;const row=supplementRows[Number(index)];
  if(e.target.hasAttribute('data-supplement-confirm')){row.confirmed=e.target.checked;updateSupplementCount();return;}
  row.confirmed=false;$(`[data-supplement-confirm="${index}"]`).checked=false;
  if(e.target.hasAttribute('data-supplement-kind')){row.kind=e.target.value;updateSupplementCount();return;}
  row.asset=null;$(`[data-supplement-preview="${index}"]`).innerHTML='';const file=e.target.files[0];if(!file){updateSupplementCount();return;}
  supplementLock(true);$('#supplement-error').textContent='';$('#supplement-progress').textContent='正在保存图片到本机…';
  try{
    if(!/\.(png|jpe?g)$/i.test(file.name)||file.size>8*1024*1024)throw Error('请选择不超过 8 MB 的 PNG 或 JPG 图片。');
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
    row.asset=await api('/api/supplements/upload',{data});
    $(`[data-supplement-preview="${index}"]`).innerHTML=`<img src="/media/${encodeURIComponent(row.asset.image)}" alt="为 ${esc(row.label)} 选择的待核对图片"><p class="muted">${esc(file.name)} · 请对照微信原记录后勾选确认。</p>`;
    $('#supplement-progress').textContent='图片已在本机保存，尚未绑定或发送给模型。';
  }catch(err){$('#supplement-error').textContent=err.message;$('#supplement-progress').textContent='';}
  finally{supplementLock(false);}
});
$('#supplement-list').addEventListener('click',e=>{const button=e.target.closest('[data-supplement-remove]');if(!button||supplementBusy)return;const index=button.dataset.supplementRemove;const row=supplementRows[Number(index)];row.asset=null;row.confirmed=false;$(`[data-supplement-file="${index}"]`).value='';$(`[data-supplement-preview="${index}"]`).innerHTML='';$(`[data-supplement-confirm="${index}"]`).checked=false;$(`[data-supplement-confirm="${index}"]`).disabled=true;updateSupplementCount();});
$('#supplement-form').onsubmit=async e=>{
 e.preventDefault();if(supplementBusy)return;$('#supplement-error').textContent='';const selected=supplementRows.filter(x=>x.asset);
 if(!selected.length||selected.some(x=>!x.confirmed)){$('#supplement-error').textContent='请核对每张所选图片；不能确认的图片请先移除。';return;}
 supplementLock(true);$('#supplement-progress').textContent='正在保存补图版案例…';
 try{const result=await api('/api/supplements/apply',{case_id:supplementCase,bindings:selected.map(x=>({message_id:x.message.id,media_index:x.mediaIndex,asset_id:x.asset.id,kind:x.kind,confirmed:true}))});$('#supplement-dialog').close();tab='materials';await loadCase(result.id);feedback('补图版已保存。请检查图片对应，再点击“生成分析报告”；旧报告保留在原案例中。');}
 catch(err){$('#supplement-error').textContent=err.message;$('#supplement-progress').textContent='保存未完成，可核对后重试。';}
 finally{supplementLock(false);}
};
