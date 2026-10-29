/* Layout-only enhancement of the copied reader. Existing nodes keep handlers. */
(() => {
  const details = label => {const block=document.createElement('details');block.className='reader-tools';const heading=document.createElement('summary');heading.textContent=label;block.appendChild(heading);return block;};
  function update(){
    const view=document.getElementById('readView');
    if(view&&!view.querySelector(':scope > .reader-tools')){
      const first=document.getElementById('readFirst')?.parentElement;
      const jump=document.getElementById('readJump')?.parentElement;
      if(first&&jump){const tools=details('Перейти к хадису');first.before(tools);tools.append(first,jump);}
      const nav=document.getElementById('readPrev')?.parentElement;if(nav)nav.classList.add('reader-page-nav');
    }
    const bar=document.getElementById('bookBotBar');
    if(bar&&bar.children.length&&!bar.querySelector(':scope > .reader-tools')){
      const children=Array.from(bar.children);
      const nav=children.find(row=>row.querySelector('button[title="Назад по книге"]'));
      if(nav){const tools=details('Страница, том и номер');bar.insertBefore(tools,bar.firstChild);for(const child of children)if(child!==nav)tools.appendChild(child);nav.classList.add('reader-page-nav');}
    }
    for(const id of ['readTitle','bookTitle']){const title=document.getElementById(id);if(title&&/^📖|^📚/.test(title.textContent))title.textContent=title.textContent.replace(/^[📖📚]\s*/u,'');}
    for(const id of ['readClose','bookClose']){const close=document.getElementById(id);if(close&&close.textContent!=='×'){close.textContent='×';close.setAttribute('aria-label','Закрыть книгу');}}
    for(const card of document.querySelectorAll('#res > .card,#readBody .card')){
      const arabic=card.querySelector(':scope > .ar'),translation=card.querySelector(':scope > .ru-out');
      if(arabic&&translation&&(translation.compareDocumentPosition(arabic)&Node.DOCUMENT_POSITION_FOLLOWING))arabic.after(translation);
    }
  }
  let scheduled=false;
  const observer=new MutationObserver(()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;update();});});
  observer.observe(document.body,{childList:true,subtree:true});update();
})();
