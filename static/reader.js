'use strict';
// Self-contained, offline interactions. No requests, analytics or model calls.
const sources=[...document.querySelectorAll('.original')];
function revealSource(){
  let id;
  try { id=decodeURIComponent(location.hash.slice(1)); } catch { return; }
  if(!id.startsWith('source-'))return;
  const el=document.getElementById(id);if(!el)return;
  el.hidden=false;el.open=true;el.scrollIntoView({block:'start'});
}
window.addEventListener('hashchange',revealSource);revealSource();
document.addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#source-"]');
  if(link?.hash===location.hash)revealSource();
});
document.querySelector('#source-search')?.addEventListener('input',e=>{
  const q=e.target.value.trim().toLocaleLowerCase();
  for(const item of sources)item.hidden=!item.textContent.toLocaleLowerCase().includes(q);
  document.querySelector('#source-count').textContent=`找到 ${sources.filter(s=>!s.hidden).length} 条材料`;
});
document.querySelector('#expand-story')?.addEventListener('click',e=>{
  const open=e.target.getAttribute('aria-expanded')!=='true';
  for(const d of document.querySelectorAll('.chapter'))d.open=open;
  e.target.setAttribute('aria-expanded',String(open));e.target.textContent=open?'收起详细经过':'展开详细经过';
});
const dialog=document.querySelector('#image-viewer');let lastImage;
for(const button of document.querySelectorAll('.zoom-image'))button.addEventListener('click',()=>{
  const img=button.querySelector('img');lastImage=button;
  dialog.querySelector('img').src=img.src;dialog.querySelector('img').alt=img.alt;
  dialog.querySelector('p').textContent=img.alt;dialog.showModal();
});
dialog?.querySelector('button').addEventListener('click',()=>dialog.close());
dialog?.addEventListener('close',()=>lastImage?.focus());

let printState;
window.addEventListener('beforeprint',()=>{
  if(printState)return;
  printState=[...document.querySelectorAll('main details')].map(item=>{
    const state={item,open:item.open,hidden:item.hidden};
    item.hidden=false;
    item.open=true;
    return state;
  });
});
window.addEventListener('afterprint',()=>{
  for(const {item,open,hidden} of printState||[]){
    item.open=open;
    item.hidden=hidden;
  }
  printState=undefined;
});
const printButton=document.querySelector('#print-report');
if(printButton){
  printButton.hidden=false;
  printButton.addEventListener('click',()=>window.print());
}
