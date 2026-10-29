(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const STORAGE = 'muslimoon.design-lab.20261027.bookmarks';
  const FONT_STORAGE = 'muslimoon.design-lab.20261027.font';
  const FAVORITE_BOOK_STORAGE = 'muslimoon.design-lab.20261027.favorite-books';
  const state = {api:null,collections:[],categories:[],section:'hadith',category:'all',collection:'all',mode:'normal',view:'search',results:[],resultQuery:'',shown:8,numberMode:false,numberHasMore:false,browse:[],browseShown:12,bookmarks:[],favoriteBooks:[],libraryShown:24,libraryQuery:'',reader:null,searchToken:0,browseToken:0,readerToken:0,font:0};
  let toastTimeout;
  const expandedRecords=new Set();
  state.librarySearchMode = 'both';
  let activeBook = null, bookInfoToken = 0;
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE) || '[]');
    state.bookmarks = Array.isArray(saved) ? saved.filter(x => x && typeof x === 'object' && x.id != null) : [];
    state.font = Math.max(0,Math.min(2,Number(localStorage.getItem(FONT_STORAGE)) || 0));
  } catch (_) {}
  try {const favoriteBooks = JSON.parse(localStorage.getItem(FAVORITE_BOOK_STORAGE) || '[]'); state.favoriteBooks = Array.isArray(favoriteBooks) ? [...new Set(favoriteBooks.map(String))] : [];} catch (_) {}
  const sameRecord = (a,b) => `${a.kind || ''}:${a.collection || ''}:${a.id}` === `${b.kind || ''}:${b.collection || ''}:${b.id}`;
  const isSaved = record => state.bookmarks.some(x => sameRecord(x,record));
  const source = record => record.kind === 'quran' ? 'Коран' : record.bookTitle || state.collections.find(c => String(c.id) === String(record.collection))?.title || record.collection || 'Хадис';
  // Russian translation and Arabic original of one hadith (owner 29.10: «как это арабский недоступен?»). As in the old
  // app, our Russian numbering matches the Arabic for al-Bukhari and Abu Dawud (checked 9 of 9 pairs by meaning, 29.10);
  // Muslim's Russian numbering differs — there the two are not put side by side.
  const PAIRED_COLLECTIONS = new Set(['bukhari','abudawud']);
  const SUNNAH_COM = {bukhari:'bukhari',muslim:'muslim',abudawud:'abudawud',tirmidhi:'tirmidhi',nasai:'nasai',ibnmajah:'ibnmajah',malik:'malik',ahmad:'ahmad',darimi:'darimi'};
  const NATIVE_TOOLS = new Set(['narrators','audio','notes','source','explain','assistant','bookPage','copy','share','tashkeel']);
  const pairedTexts = record => PAIRED_COLLECTIONS.has(String(record.collection)) || (record.collection==='bukhari'&&['1','321'].includes(String(record.number)));
  const recordNumber = record => record.kind === 'quran' && record.sura && record.ayah ? `Сура ${record.sura}, аят ${record.ayah}` : record.number != null && String(record.number) !== '' ? (/^(т\.|стр\.)/.test(String(record.number)) ? String(record.number) : `№ ${record.number}`) : '';
  const fold = text => String(text).toLocaleLowerCase('ru').replace(/ё/g,'е');
  const noNoteMarkers = text => String(text || '').replace(/\[\s*[0-9٠-٩۰-۹]+\s*\]/g,'').replace(/\s+/g,' ').trim();
  function excerpt(text) {
    const clean = noNoteMarkers(text), folded = fold(clean), query = fold(state.resultQuery).trim();
    let match = query ? folded.indexOf(query) : -1;
    if (match < 0 && query) {
      const hits = query.split(/\s+/).filter(word => word.length > 2).map(word => folded.indexOf(word)).filter(index => index >= 0);
      if (hits.length) match = Math.min(...hits);
    }
    let start = 0;
    if (match >= 0) {
      const quote = Math.max(clean.lastIndexOf('«',match),clean.lastIndexOf('“',match));
      if (quote >= 0 && match - quote <= 150) start = quote;
      else if (match > 105) {
        start = Math.max(0,match - 75);
        const nextSpace = clean.indexOf(' ',start);
        if (nextSpace >= 0 && nextSpace < match) start = nextSpace + 1;
      }
    }
    let end = Math.min(clean.length,start + 220);
    if (end < clean.length) {
      const lastSpace = clean.lastIndexOf(' ',end);
      if (lastSpace > start + 170 && (match < 0 || lastSpace > match + Math.min(query.length,30))) end = lastSpace;
    }
    return (start > 0 ? '…' : '') + clean.slice(start,end).trim() + (end < clean.length ? '…' : '');
  }
  // Before any way out of the app — a question (owner's law since v1095, repeated 29.10). Sites open in the
  // external browser through Telegram; the person stays in the app until they say «Перейти».
  const leaveDialog = document.createElement('dialog'); leaveDialog.className = 'leave-dialog';
  leaveDialog.innerHTML = '<form method="dialog" class="leave-shell"><h2>Выйти из приложения?</h2><p class="leave-text"></p><p class="leave-url" dir="ltr"></p><div class="leave-actions"><button value="stay" class="leave-stay">Остаться</button><button value="go" class="leave-go">Перейти</button></div></form>';
  document.body.appendChild(leaveDialog);
  const SITE_NAMES = [[/wikipedia\.org$/,'Википедия'],[/shamela\.ws$/,'Шамиля'],[/sunnah\.com$/,'sunnah.com'],[/dorar\.net$/,'dorar.net'],[/sunnah\.one$/,'sunnah.one'],[/islamweb\.net$/,'islamweb.net'],[/quran\.com$/,'quran.com'],[/turath\.io$/,'turath.io'],[/(^|\.)t\.me$/,'Telegram'],[/github\.(io|com)$/,'GitHub']];
  function isExternal(url) {try {const x = new URL(String(url),location.href); return /^https?:$/.test(x.protocol) && x.host !== location.host;} catch (_) {return false;}}
  function askLeave(url) {
    let host = ''; try {host = new URL(String(url)).hostname.replace(/^www\./,'');} catch (_) {return;}
    const name = (SITE_NAMES.find(([re]) => re.test(host)) || [null,host])[1];
    leaveDialog.querySelector('.leave-text').textContent = `Откроется сайт «${name}» во внешнем браузере. Это не наш ресурс — за его содержимое мы не отвечаем.`;
    leaveDialog.querySelector('.leave-url').textContent = String(url).length > 110 ? String(url).slice(0,110) + '…' : String(url);
    leaveDialog.returnValue = ''; leaveDialog.showModal();
    // Opened right in the tap on «Перейти»: Telegram opens links only from a user's tap, not from a later close event.
    leaveDialog.querySelector('.leave-go').onclick = event => {event.preventDefault(); leaveDialog.close('go'); const tg = window.Telegram && window.Telegram.WebApp;
      try {if (tg && tg.initData && tg.openLink) tg.openLink(url); else window.open(url,'_blank','noopener');} catch (_) {window.open(url,'_blank','noopener');}};
    leaveDialog.querySelector('.leave-stay').onclick = event => {event.preventDefault(); leaveDialog.close('stay');};
  }
  document.addEventListener('click',event => {const a = event.target.closest && event.target.closest('a[href]'); if (!a || !isExternal(a.href)) return; event.preventDefault(); askLeave(a.href);},true);
  window.addEventListener('message',event => {if (event.data && typeof event.data.muslimoonLeave === 'string' && isExternal(event.data.muslimoonLeave)) askLeave(event.data.muslimoonLeave);});
  document.addEventListener('pointerdown',event=>{const b=event.target.closest('button,[role="button"],a.setting-card,summary,select');if(!b||b.disabled)return;
    b.classList.remove('tap-flash');void b.offsetWidth;b.classList.add('tap-flash');setTimeout(()=>b.classList.remove('tap-flash'),460);
    try{const h=window.Telegram&&window.Telegram.WebApp&&window.Telegram.WebApp.HapticFeedback;if(h&&window.Telegram.WebApp.initData)h.selectionChanged();}catch(_){}},{passive:true,capture:true});
  function toast(message) {
    $('#toast').textContent = message; $('#toast').hidden = false;
    clearTimeout(toastTimeout); toastTimeout = setTimeout(() => $('#toast').hidden = true,2900);
  }
  function loading(target,title='Ищем в источниках',subtitle='Ещё немного — и можно читать') {
    target.innerHTML = `<div class="loading-state"><span class="loading-orbit"></span><p>${escape(title)}<span>${escape(subtitle)}</span></p></div><div class="skeleton-card"><span></span><i></i><i></i><i></i></div>`;
    target.setAttribute('aria-busy','true');
  }
  function empty(target,title,description,action,handler) {
    target.setAttribute('aria-busy','false');
    target.innerHTML = `<div class="empty-state">${icon('book')}<h3>${escape(title)}</h3><p>${escape(description)}</p>${action ? `<button type="button">${escape(action)}</button>` : ''}</div>`;
    if (action) $('button',target).onclick = handler;
  }
  function showWelcome() {
    state.results = []; $('#search-results-heading').hidden = true; $('#more-results').hidden = true; $('#search-notice').hidden = true;
    $('#search-results').setAttribute('aria-busy','false');
    $('#search-results').innerHTML = '';
  }
  const NAMES_AR={bukhari:'صحيح البخاري',muslim:'صحيح مسلم',abudawud:'سنن أبي داود',tirmidhi:'سنن الترمذي',ibnmajah:'سنن ابن ماجه',ibnmaja:'سنن ابن ماجه',nasai:'سنن النسائي',malik:'موطأ مالك',ahmad:'مسند أحمد'};
  function arabicTitleOf(record) {return String(record.arabicTitle||NAMES_AR[record.collection]||'').trim();}
  // One source line everywhere (owner 29.10): «Русское | العربي · № N» — two names of one book on one level.
  function sourceLine(russianTitle,arabicTitle,number,className) {
    const ru=String(russianTitle||'').trim(),ar=String(arabicTitle||'').trim(),both=ar&&ar!==ru;
    return `<span class="${className} source-line"><span class="source-ru">${escape(ru)}</span>${both?`<span class="source-sep" aria-hidden="true">|</span><span class="source-ar" lang="ar" dir="rtl">${escape(ar)}</span>`:''}${number?(/^\d+$/.test(String(number).replace(/^№\s*/,''))?`<span class="num-badge" title="${escape(number)}">${escape(String(number).replace(/^№\s*/,''))}</span>`:`<span class="card-number">· ${escape(number)}</span>`):''}</span>`;
  }
  function openBookOfRecord(record) {
    if (!record) return; const code = record.collection === 'ibnmaja' ? 'ibnmajah' : record.collection;
    const row = state.collections.find(c => c.id === code || c.id === record.collection || (record.bid && String(c.bid) === String(record.bid)));
    openBookInfo(row || {id: code, bid: record.bid, title: source(record), arabicTitle: arabicTitleOf(record)});
  }
  function card(record,index) {
    if(record.kind==='hadith'&&record.arabic&&record.russian&&!pairedTexts(record))record={...record,russian:'',pairingUnverified:true};
    const saved = isSaved(record), russian = String(record.russian || '').trim(), text = russian || String(record.arabic || '').trim();
    const bookSource = source(record), number = recordNumber(record), title = noNoteMarkers(record.title || '');
    if(record.kind==='quran')return `<article class="hadith-card quran-card" data-card="${index}" data-record-id="${escape(record.id)}"><div class="card-header"><span class="book-seal">${icon('quran')}</span><span class="card-source">Коран${number?`<span class="card-number"> · ${escape(number)}</span>`:''}</span></div><div class="card-text arabic-preview" lang="ar" dir="rtl">${escape(excerpt(record.arabic||''))}</div>${russian?`<p class="quran-card-translation">${escape(excerpt(russian))}</p>`:''}<div class="card-footer"><div class="card-actions"><button type="button" class="card-save${saved?' saved':''}" data-save="${index}" aria-label="${saved?'Убрать из закладок':'Сохранить в закладки'}" aria-pressed="${saved}">${icon('bookmark')}</button><button type="button" class="open-card" data-open="${index}">Подробнее${icon('arrow')}</button></div></div></article>`;
    const metadata = record.isExcerpt ? '<span class="card-title">Отрывок из издания</span>' : record.kind==='book' ? '<span class="card-title">Текст из издания</span>' : title && fold(title).trim() !== fold(bookSource).trim() ? `<span class="card-title">${escape(title)}</span>` : '';
    const arabicTitle=arabicTitleOf(record);
    const arabic=String(record.arabic||'').trim();
    const expanded=expandedRecords.has(String(record.id));
    const secondary=russian&&arabic?`<div class="card-arabic-extra"><span>Оригинал</span><p lang="ar" dir="rtl">${escape(expanded?arabic:excerpt(arabic))}</p></div>`:'';
    const canExpand=!record.isExcerpt&&Math.max(text.length,arabic.length)>220;
    return `<article class="hadith-card" data-card="${index}" data-record-id="${escape(record.id)}"><div class="card-header"><button type="button" class="book-seal seal-button" data-book-about="${index}" aria-label="О книге: ${escape(bookSource)}">${icon('book')}</button>${sourceLine(bookSource,arabicTitle,number,'card-source')}</div><div class="card-text${!russian && text ? ' arabic-preview' : ''}"${!russian && text ? ' lang="ar" dir="rtl"' : ''}>${escape(text ? (expanded?text:excerpt(text)) : record.title || 'Открыть текст')}</div>${secondary}${canExpand?`<button type="button" class="card-expand" data-expand="${index}" aria-expanded="${expanded}">${expanded?'Свернуть':'Развернуть'}</button>`:''}<div class="card-footer">${metadata}<div class="card-actions"><button type="button" class="card-save${saved ? ' saved' : ''}" data-save="${index}" aria-label="${saved ? 'Убрать из закладок' : 'Сохранить в закладках'}" aria-pressed="${saved}">${icon('bookmark')}</button><button type="button" class="open-card" data-open="${index}">Подробнее${icon('arrow')}</button></div></div></article>`;
  }
  const cardPartsCache=new Map(),cardPartsPending=new Map(),cardPartsObservers=new WeakMap();
  const deferredCardRenders=new Map(),deferredCardPaints=new Map();let selectionGestureTarget=null,selectionFlushTimer;
  function selectingWithin(target){
    const selection=window.getSelection();
    return !!(selectionGestureTarget&&target.contains(selectionGestureTarget))||!!(selection&&!selection.isCollapsed&&selection.anchorNode&&target.contains(selection.anchorNode));
  }
  function flushCardSelection(){
    clearTimeout(selectionFlushTimer);selectionFlushTimer=setTimeout(()=>{
      for(const [target,args] of deferredCardRenders){if(!target.isConnected){deferredCardRenders.delete(target);continue;}if(!selectingWithin(target)){deferredCardRenders.delete(target);renderCards(target,args.items,args.count);}}
      for(const [element,args] of deferredCardPaints){if(!element.isConnected){deferredCardPaints.delete(element);continue;}if(!selectingWithin(element)){deferredCardPaints.delete(element);paintCardParts(element,args.record,args.parts);}}
    },180);
  }
  document.addEventListener('pointerdown',event=>{const block=event.target.closest?.('.card-text,.card-arabic-extra,.quran-card-translation');if(block)selectionGestureTarget=block;});
  document.addEventListener('pointerup',()=>{selectionGestureTarget=null;flushCardSelection();});
  document.addEventListener('pointercancel',()=>{selectionGestureTarget=null;flushCardSelection();});
  document.addEventListener('selectionchange',flushCardSelection);
  let cardPartsActive=0;const cardPartsQueue=[];
  function runCardPartsQueue(){
    while(cardPartsActive<2&&cardPartsQueue.length){
      const job=cardPartsQueue.shift();cardPartsActive++;
      state.api.read(job.record).then(full=>{const parts=Array.isArray(full?.parts)?full.parts:[];cardPartsCache.set(job.key,parts);job.resolve(parts);}).catch(()=>job.resolve([])).finally(()=>{cardPartsPending.delete(job.key);cardPartsActive--;runCardPartsQueue();});
    }
  }
  function cardParts(record){
    const key=[record.collection,record.number,record.arabic].join('|');
    if(cardPartsCache.has(key))return Promise.resolve(cardPartsCache.get(key));
    if(cardPartsPending.has(key))return cardPartsPending.get(key);
    const promise=new Promise(resolve=>cardPartsQueue.push({key,record,resolve}));cardPartsPending.set(key,promise);runCardPartsQueue();return promise;
  }
  function paintCardParts(element,record,parts){
    if(!element.isConnected||!parts.some(p=>p.role==='isnad')||!parts.some(p=>p.role==='matn'))return;
    if(selectingWithin(element)){deferredCardPaints.set(element,{record,parts});return;}
    const block=element.querySelector('.card-arabic-extra p')||element.querySelector('.card-text.arabic-preview');if(!block)return;
    const labels={isnad:'Иснад',matn:'Матн',comment:'Комментарий'};
    const expanded=element.querySelector('[data-expand]')?.getAttribute('aria-expanded')==='true';
    block.innerHTML=parts.filter(p=>p.text&&labels[p.role]).map(p=>`<span class="card-part card-part-${escape(p.role)}"><span class="card-part-label" dir="ltr">${labels[p.role]}</span><span lang="ar" dir="rtl">${escape(expanded?String(p.text):excerpt(p.text))}</span></span>`).join('');
  }
  function renderCards(target,items,count) {
    if(selectingWithin(target)){deferredCardRenders.set(target,{items,count});return;}
    deferredCardRenders.delete(target);
    cardPartsObservers.get(target)?.disconnect();
    target.setAttribute('aria-busy','false');
    // Stable list (owner 29.10: «дёргается, исчезает, появляется»): number search arrives in parts every ~250 ms.
    // Cards already on screen stay mounted; only new ones are appended below. Full redraw only when the list changed.
    // Cards on screen stay mounted (keyed by record id); new ones are slotted in between them; nothing replays.
    const ids=items.slice(0,count).map(record=>String(record?.id)),nodes=[...target.querySelectorAll(':scope>.hadith-card')];
    const byId=new Map(nodes.map(node=>[node.dataset.recordId,node])),kept=ids.filter(id=>byId.has(id));
    if(nodes.length&&kept.length===nodes.length&&kept.every((id,i)=>nodes[i].dataset.recordId===id)){
      let next=0;
      ids.forEach((id,i)=>{const node=byId.get(id);
        if(node){node.dataset.card=i;for(const key of ['open','save','expand','bookAbout'])node.querySelectorAll(`[data-${key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())}]`).forEach(b=>b.dataset[key]=i);next++;}
        else{const html=card(items[i],i);if(nodes[next])nodes[next].insertAdjacentHTML('beforebegin',html);else target.insertAdjacentHTML('beforeend',html);}});
    }else target.innerHTML = items.slice(0,count).map(card).join('');
    target.__cardIds=ids;
    $$('[data-open]',target).forEach(button => button.onclick = () => openReader(items[Number(button.dataset.open)]));
    $$('[data-book-about]',target).forEach(button => button.onclick = () => openBookOfRecord(items[Number(button.dataset.bookAbout)]));
    $$('[data-save]',target).forEach(button => button.onclick = () => {toggleSave(items[Number(button.dataset.save)]); renderAllBookmarkStates();});
    $$('[data-expand]',target).forEach(button=>button.onclick=()=>{
      const record=items[Number(button.dataset.expand)],element=button.closest('.hadith-card');
      const expanded=button.getAttribute('aria-expanded')!=='true';if(expanded)expandedRecords.add(String(record.id));else expandedRecords.delete(String(record.id));button.setAttribute('aria-expanded',String(expanded));button.textContent=expanded?'Свернуть':'Развернуть';
      const safeRussian=record.kind==='hadith'&&record.arabic&&record.russian&&!pairedTexts(record)?'':String(record.russian||'');
      const text=safeRussian||String(record.arabic||'');const main=element.querySelector('.card-text');if(main)main.textContent=expanded?text:excerpt(text);
      const ar=element.querySelector('.card-arabic-extra p');if(ar)ar.textContent=expanded?String(record.arabic||''):excerpt(record.arabic||'');
      if(record.kind==='hadith'&&record.arabic)cardParts(record).then(parts=>paintCardParts(element,record,parts));
    });
    const cards=$$('.hadith-card',target);
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
      if(!entry.isIntersecting)return;observer.unobserve(entry.target);
      const record=items[Number(entry.target.dataset.card)];
      if(record?.kind!=='hadith'||!record.arabic||!state.api)return;
      cardParts(record).then(parts=>paintCardParts(entry.target,record,parts));
    }),{rootMargin:'150px'});
    cardPartsObservers.set(target,observer);
    cards.forEach(element=>observer.observe(element));
  }
  function renderAllBookmarkStates() {
    if (state.view === 'bookmarks') renderBookmarks();
    else if (state.view === 'search' && state.results.length) renderCards($('#search-results'),state.results,state.shown);
    else if (state.view === 'library' && !$('#browse-area').hidden) renderCards($('#browse-results'),state.browse,state.browseShown);
    if (state.reader) updateReaderSave();
  }
  function toggleSave(record) {
    const saved = isSaved(record);
    if (saved) state.bookmarks = state.bookmarks.filter(x => !sameRecord(x,record)); else state.bookmarks.unshift({...record});
    try {localStorage.setItem(STORAGE,JSON.stringify(state.bookmarks)); toast(saved ? 'Закладка удалена' : 'Сохранено в закладках');}
    catch (_) {toast('Закладка сохранена до закрытия страницы');}
  }
  function showView(view) {
    state.view = view;
    $$('.page-view').forEach(el => el.hidden = el.id !== `view-${view}`);
    // MUSLIMOON stands only over search; other sections open with their own heading (owner 29.10).
    $('.masthead').hidden = view !== 'search';
    $$('[data-view]').forEach(el => {el.classList.toggle('active',el.dataset.view === view); if (el.classList.contains('nav-item')) {if (el.dataset.view === view) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current');}});
    if (view === 'bookmarks') renderBookmarks();
    window.scrollTo({top:0,behavior:'smooth'});
    try {syncBack(); saveSpot();} catch (_) {}
  }
  $$('[data-view]').forEach(button => button.onclick = () => showView(button.dataset.view));
  // The AI button sits in the middle of the bottom bar (owner 29.10).
  $$('[data-ai-open]').forEach(button => button.onclick = () => openNativeAssistant());
  // MUSLIMOON at the top is «домой» (owner #4320: «главная кнопка сверху не работает» — on the search screen it changed
  // nothing): close what is open, clear the search, leave AI mode, back to hadiths at the top of the page.
  $('#brand-home').onclick = event => {
    event.preventDefault(); $$('dialog[open]').forEach(d => {try {d.close();} catch (_) {}});
    if (state.aiMode) setAiMode(false);
    if (state.section === 'quran') $('[data-section="hadith"]')?.click();
    $('#reset-filters')?.click(); $('#refine-panel').hidden = true; $('#refine-toggle').setAttribute('aria-expanded','false'); modeChips.hidden = true; syncRefineLink();
    $('#query').value = ''; state.searchToken++; showWelcome(); syncPlaceholder();
    showView('search'); window.scrollTo({top:0,behavior:'smooth'});
  };
  $('.rail-mark').onclick = event => {event.preventDefault(); showView('search');};
  // ── Закладки = всё избранное в одном месте (owner 29.10). Each kind keeps its own store (nothing moves, nothing is
  // lost); this view gathers them, groups by kind, filters and searches.
  const readLS=(k,d)=>{try{const v=JSON.parse(localStorage.getItem(k)||'null');return v==null?d:v;}catch(_){return d;}};
  const FAV_NARR='muslimoon.favNarrators';
  const favNarrators=()=>{const a=readLS(FAV_NARR,[]);return Array.isArray(a)?a:[];};
  function toggleFavNarrator(n){const a=favNarrators(),i=a.findIndex(x=>String(x.id)===String(n.id));if(i>=0)a.splice(i,1);else a.push({id:String(n.id),name:n.full||n.name,kunya:n.kunya||'',death:n.death||'',hajar:n.hajar||''});try{localStorage.setItem(FAV_NARR,JSON.stringify(a.slice(-500)));}catch(_){}return i<0;}
  let bmFilter='all';
  function bookmarkItems(){
    const items=[],seen=new Set(),add=(kind,key,obj)=>{if(seen.has(kind+'|'+key))return;seen.add(kind+'|'+key);items.push({kind,key,...obj});};
    for(const r of state.bookmarks){if(r.kind==='quran')add('ayah',r.sura+':'+r.ayah,{title:'Коран '+r.sura+':'+r.ayah,text:r.russian||r.arabic||'',record:r});
      else if(r.kind==='book')add('book','b'+r.bid+':'+r.page,{title:source(r)+(r.number?' · '+r.number:''),text:r.arabic||'',record:r});
      else add('hadith',r.collection+'|'+String(r.number).replace(/\D.*$/,''),{title:source(r)+(r.number?' № '+r.number:''),text:r.russian||r.arabic||'',record:r});}
    for(const f of readLS('muslimoon_fav',[])||[]){if(!f||!f.k)continue;const p=String(f.k).split('|');
      if(p[0]==='q')add('ayah',p[1],{title:f.label||'Коран '+p[1],text:f.text||'',open:{type:'q',v:p[1]}});
      else if(p[0]==='h'){const c=state.collections.find(x=>x.id===p[1]);add('hadith',p[1]+'|'+p[2],{title:(c?c.title:(f.coll||p[1]))+' № '+p[2],text:f.text||'',open:{type:'h',v:p[1]+' '+p[2]}});}}
    for(const id of state.favoriteBooks){const c=state.collections.find(x=>String(x.id)===String(id));if(c)add('book',String(c.id),{title:c.title,text:String(c.author||'').split('|').pop().trim(),book:c});}
    for(const bid of readLS('cat_favs',[])||[]){const c=state.collections.find(x=>String(x.bid)===String(bid));if(c)add('book',String(c.id),{title:c.title,text:String(c.author||'').split('|').pop().trim(),book:c});}
    for(const n of favNarrators())add('narrator',n.id,{title:n.name,text:[n.kunya,n.death?'ум. '+n.death:'',n.hajar].filter(Boolean).join(' · '),narrator:n});
    for(const n of notesLoad().slice().reverse())add('note',n.rk,{title:n.label||'Свободная заметка',text:n.text||'',note:n});
    return items;
  }
  const BM_KINDS=[['all','Все'],['hadith','Хадисы'],['ayah','Аяты'],['book','Книги'],['narrator','Передатчики'],['note','Заметки']];
  const BM_HEAD={hadith:'Хадисы',ayah:'Аяты',book:'Книги',narrator:'Передатчики',note:'Заметки'};
  function renderBookmarks() {
    let bar=$('#bm-bar');
    if(!bar){bar=document.createElement('div');bar.id='bm-bar';bar.className='bm-bar';bar.innerHTML='<input type="search" class="bm-search" placeholder="Поиск по закладкам" aria-label="Поиск по закладкам"><div class="bm-kinds"></div>';
      $('#bookmark-results').before(bar);bar.querySelector('.bm-search').addEventListener('input',renderBookmarks);
      bar.querySelector('.bm-kinds').addEventListener('click',e=>{const b=e.target.closest('[data-bm-kind]');if(!b)return;bmFilter=b.dataset.bmKind;renderBookmarks();});}
    const all=bookmarkItems(),q=catalogFold(bar.querySelector('.bm-search').value).trim();
    const count=k=>k==='all'?all.length:all.filter(x=>x.kind===k).length;
    bar.querySelector('.bm-kinds').innerHTML=BM_KINDS.map(([k,t])=>`<button type="button" class="collection-chip${bmFilter===k?' selected':''}" data-bm-kind="${k}">${t}<b>${count(k)}</b></button>`).join('');
    $('#bookmark-count').textContent=String(all.length);
    const list=all.filter(x=>(bmFilter==='all'||x.kind===bmFilter)&&(!q||catalogFold(x.title+' '+x.text).includes(q)));
    if(!all.length){empty($('#bookmark-results'),'Пока ничего не сохранено','Звёздочка или закладка у хадиса, аята, книги или передатчика — и он появится здесь. Заметки тоже здесь.','К поиску',()=>showView('search'));return;}
    if(!list.length){$('#bookmark-results').innerHTML='<p class="notes-hint">Ничего не найдено.</p>';return;}
    let html='',last='';
    for(const [i,x] of list.entries()){if(bmFilter==='all'&&x.kind!==last){html+=`<h3 class="bm-head">${BM_HEAD[x.kind]}</h3>`;last=x.kind;}
      html+=`<button type="button" class="bm-row" data-bm-i="${i}"><span class="bm-kind">${icon({hadith:'book',ayah:'quran',book:'book',narrator:'helper',note:'pen'}[x.kind]||'book')}</span><span class="bm-main"><strong dir="auto">${escape(x.title)}</strong>${x.text?`<small dir="auto">${escape(cutText(x.text,140))}</small>`:''}</span>${icon('arrow')}</button>`;}
    $('#bookmark-results').setAttribute('aria-busy','false');$('#bookmark-results').innerHTML=html;
    $('#bookmark-results').onclick=e=>{const b=e.target.closest('[data-bm-i]');if(!b)return;const x=list[+b.dataset.bmI];if(!x)return;
      if(x.record)openReader(x.record);
      else if(x.open&&x.open.type==='q')ASSIST_ACTIONS.quran.run(x.open.v);
      else if(x.open&&x.open.type==='h')ASSIST_ACTIONS.search.run(x.open.v);
      else if(x.book)openBookInfo(x.book);
      else if(x.note)openNoteEditor(x.note.rk,x.note.label,x.note.ref);
      else if(x.narrator)toast(x.title+(x.text?' — '+x.text:''));};
  }
  (function isnadMarkSetting(){
    const font=document.getElementById('font-label')?.closest('.setting-card');if(!font)return;
    const card=document.createElement('div');card.className='setting-card mark-setting';
    card.innerHTML='<div class="setting-heading"><span class="type-icon">ع</span><h2>Выделять иснад и матн</h2></div><p>Цепочка передатчиков — приглушённо, слова хадиса — ярко. Выключите, чтобы текст был ровным.</p><button type="button" class="mark-switch" role="switch"></button>';
    font.after(card);const sw=card.querySelector('.mark-switch');
    const sync=()=>{let on=true;try{on=localStorage.getItem('muslimoon.isnadMark')!=='0';}catch(_){}sw.setAttribute('aria-checked',String(on));sw.textContent=on?'Включено':'Выключено';};
    sw.onclick=()=>{let on=true;try{on=localStorage.getItem('muslimoon.isnadMark')!=='0';localStorage.setItem('muslimoon.isnadMark',on?'0':'1');}catch(_){}sync();};sync();
  })();
  function applyFont() {
    document.documentElement.style.setProperty('--body-scale',String([1,1.12,1.24][state.font])); $('#font-label').textContent = ['Обычный','Крупный','Очень крупный'][state.font];
    $('#font-down').disabled = state.font === 0; $('#font-up').disabled = state.font === 2;
    try {localStorage.setItem(FONT_STORAGE,String(state.font));} catch (_) {}
  }
  $('#font-down').onclick = () => {state.font = Math.max(0,state.font - 1); applyFont();};
  $('#font-up').onclick = () => {state.font = Math.min(2,state.font + 1); applyFont();}; applyFont();
  $$('[data-theme-option]').forEach(a => a.classList.toggle('active',a.dataset.themeOption === document.documentElement.dataset.theme));
  // «Настроить поиск» → under the field a row of modes, one tap each (owner 29.10); the detailed panel stays below.
  const MODE_CHIPS = [['normal','По словам'],['diac','С огласовками'],['root','По корню'],['matnonly','Только матн'],['narr','Передатчик'],['ctor','Цепь'],['rag','RAG']];
  const modeChips = document.createElement('div'); modeChips.className = 'mode-chips'; modeChips.setAttribute('role','group'); modeChips.setAttribute('aria-label','Как искать'); modeChips.hidden = true;
  modeChips.innerHTML = MODE_CHIPS.map(([id,label]) => `<button type="button" class="mode-chip" data-mode-chip="${id}" aria-pressed="false">${label}</button>`).join('');
  $('.search-options').after(modeChips);
  function syncModeChips() {modeChips.querySelectorAll('[data-mode-chip]').forEach(b => {const on = state.aiMode ? b.dataset.modeChip === 'ai' : b.dataset.modeChip === (state.mode || 'normal'); b.classList.toggle('selected',on); b.setAttribute('aria-pressed',String(on));});}
  modeChips.addEventListener('click',event => {
    const chip = event.target.closest('[data-mode-chip]'); if (!chip) return; const id = chip.dataset.modeChip;
    if (id === 'ai') {setAiMode(true); $('#query').focus(); return;}
    if (id === 'ctor') {invokeTool('chain',null); return;}
    if (state.aiMode) setAiMode(false);
    $('#mode-select').value = id; filtersChanged(); syncModeChips(); if ($('#query').value.trim()) performSearch();
  });
  // The search line turns into a question to the helper (owner 29.10): no second boxed button — the magnifier itself is a
  // quiet switch «Поиск ⇄ ИИ»; in AI mode the field glows gold, the hint changes and the arrow sends to the helper's chat.
  const spark = document.createElementNS('http://www.w3.org/2000/svg','symbol'); spark.id = 'i-spark'; spark.setAttribute('viewBox','0 0 24 24');
  spark.innerHTML = '<path d="M12 3.5l1.7 5.1 5.1 1.7-5.1 1.7L12 17.1l-1.7-5.1-5.1-1.7 5.1-1.7Z"/><path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7Z"/>';
  $('.icon-definitions').appendChild(spark);
  const aiSwitch = document.createElement('button'); aiSwitch.type = 'button'; aiSwitch.className = 'ai-switch'; aiSwitch.setAttribute('aria-pressed','false');
  aiSwitch.setAttribute('aria-label','Переключить: поиск или вопрос ИИ-помощнику'); aiSwitch.innerHTML = icon('search') + icon('spark');
  $('.search-icon').replaceWith(aiSwitch); state.aiMode = false;
  function setAiMode(on) {
    state.aiMode = !!on; $('.search-field').classList.toggle('ai-mode',state.aiMode); aiSwitch.setAttribute('aria-pressed',String(state.aiMode)); $('.ai-quick')?.setAttribute('aria-pressed',String(state.aiMode));
    $('#query').placeholder = state.aiMode ? 'Спросите ИИ-помощника…' : ''; $('#query-example').hidden = state.aiMode;
    $('#search-summary').textContent = state.aiMode ? '✦ Вопрос ИИ-помощнику · ответ откроется в чате' : $('#search-summary').dataset.normal || $('#search-summary').textContent;
    syncModeChips();
  }
  aiSwitch.onclick = () => {setAiMode(!state.aiMode); $('#query').focus();};
  // «✦ Спросить ИИ» beside «Настроить поиск» on the start screen (owner #4325): the same switch, easier to find.
  const aiQuick = document.createElement('button'); aiQuick.type = 'button'; aiQuick.className = 'ai-quick'; aiQuick.setAttribute('aria-pressed','false');
  aiQuick.innerHTML = icon('spark') + '<span>Спросить ИИ</span>';
  const optionRow = document.createElement('div'); optionRow.className = 'search-option-row'; $('#refine-toggle').before(optionRow); optionRow.append($('#refine-toggle'),aiQuick);
  aiQuick.onclick = () => {setAiMode(!state.aiMode); $('#query').focus();};
  // The chain constructor is the «Цепь» mode chip (owner П-46): no separate card in the settings.
  // Коран: выбор суры и аята «крутилками» под строкой поиска (owner 29.10: «как в старой — сура и аят»). На телефоне
  // <select> открывается колесом выбора. Сура меняет список аятов; «Открыть» показывает аят.
  const quranPick=document.createElement('div');quranPick.className='quran-pick';quranPick.hidden=true;
  quranPick.innerHTML='<label><span>Сура</span><select class="qp-sura" aria-label="Сура"></select></label><label><span>Аят</span><select class="qp-ayah" aria-label="Аят"></select></label><button type="button" class="qp-open">Открыть</button>';
  $('.search-options').after(quranPick);
  let suraInfo=null;
  async function fillQuranPick(){
    if(!suraInfo){try{suraInfo=await state.api.suraInfo();}catch(_){return;}}
    const s=quranPick.querySelector('.qp-sura');if(!s.options.length)s.innerHTML=suraInfo.names.map((n,i)=>`<option value="${i+1}">${i+1}. ${escape(n)}</option>`).join('');
    fillAyahs();
  }
  function fillAyahs(){const s=+quranPick.querySelector('.qp-sura').value||1,n=suraInfo&&suraInfo.ayahs[s-1]||7,a=quranPick.querySelector('.qp-ayah'),keep=+a.value||1;
    a.innerHTML=Array.from({length:n},(_,i)=>`<option value="${i+1}">${i+1}</option>`).join('');a.value=String(Math.min(keep,n));}
  quranPick.querySelector('.qp-sura').onchange=()=>{quranPick.querySelector('.qp-ayah').value='1';fillAyahs();};
  quranPick.querySelector('.qp-open').onclick=()=>{const s=quranPick.querySelector('.qp-sura').value,a=quranPick.querySelector('.qp-ayah').value;$('#query').value=s+':'+a;syncPlaceholder();performSearch();};
  function syncQuranPick(){const q=state.section==='quran';quranPick.hidden=!q;$('#refine-toggle').hidden=q;if(q){$('#refine-panel').hidden=true;$('#refine-toggle').setAttribute('aria-expanded','false');if(state.api)fillQuranPick();}}
  function askAssistant(text) {openNativeAssistant(); const question = String(text || '').trim(); if (question) {assistantInput.value = question; $('#native-assistant-form').requestSubmit();}}
  // The open panel is visibly tied to its button (owner 29.10): the button lights up and the panel hangs from it.
  function syncRefineLink() {const open = !$('#refine-panel').hidden; $('#refine-toggle').classList.toggle('is-open',open); $('#refine-panel').classList.toggle('is-attached',open); modeChips.classList.toggle('is-attached',open);}
  $('#refine-toggle').onclick = () => {const opened = $('#refine-panel').hidden; $('#refine-panel').hidden = !opened; modeChips.hidden = !opened || state.section === 'quran'; syncModeChips(); $('#refine-toggle').setAttribute('aria-expanded',String(opened)); syncRefineLink();};
  const modeHelp = {normal:'Введите слово или фразу на русском или арабском.',diac:'Совпадение строго с огласовками — так, как вы набрали.',rag:'Ищем по смыслу в подготовленных книгах нашей базы.',root:'Введите арабское слово: найдём также слова с тем же корнем.',matnonly:'Ищем в самом высказывании, без цепочки передатчиков.',narr:'Введите имя человека, который передал хадис.',chain:'Введите арабские имена из цепочки передатчиков — иснада.'};
  const modeNames = {normal:'По словам',diac:'С огласовками',rag:'RAG · по смыслу',root:'По корню слова',matnonly:'Текст хадиса',narr:'По передатчику',chain:'В цепочке передатчиков'};
  const multiScope=[];
  const scopeBox=document.createElement('details');scopeBox.className='multi-scope';
  scopeBox.innerHTML='<summary>Несколько книг и разделов</summary><p>Выберите книгу или раздел выше, затем добавьте или исключите его. Исключения имеют приоритет.</p><div><button type="button" data-scope-action="include">Добавить в поиск</button><button type="button" data-scope-action="exclude">Исключить</button></div><ul class="scope-list"></ul>';
  document.querySelector('label[for="mode-select"]').before(scopeBox);
  // ── «Где искать» (owner П-46: «облегчить выбор книги конкретной, либо книг, либо групп книг»). Одно касание —
  // группа или книга; любая другая книга или раздел из 8 589 — набором названия. Под капотом тот же список условий
  // multiScope, что и раньше, — поиск по нему уже умеет и включать, и исключать.
  const MAIN_BOOKS=['bukhari','muslim','abudawud','tirmidhi','nasai','ibnmajah','malik','ahmad','darimi'];
  const BOOK_SHORT={bukhari:'Бухари',muslim:'Муслим',abudawud:'Абу Дауд',tirmidhi:'Тирмизи',nasai:'Насаи',ibnmajah:'Ибн Маджа',malik:'Малик',ahmad:'Ахмад',darimi:'Дарими'};
  const GROUPS=[{id:'six',title:'Шесть сборников',ids:['bukhari','muslim','abudawud','tirmidhi','nasai','ibnmajah']},{id:'two',title:'Два Сахиха',ids:['bukhari','muslim']},
    {id:'sunan',title:'Сунаны',ids:['abudawud','tirmidhi','nasai','ibnmajah','darimi']},{id:'musnad',title:'Муснад и Муватта',ids:['ahmad','malik']}];
  const SECTION_PICKS=['كتب السنة','شروح الحديث','علوم الحديث','التفسير','العقيدة','الفقه العام','التراجم والطبقات','السيرة النبوية'];
  const authorPicks=[];
  const where=document.createElement('div');where.className='where-block';
  where.innerHTML='<p class="where-title">Где искать</p><div class="where-row where-groups" hidden></div><div class="where-row where-books"></div>'
    +'<details class="where-more"><summary>Ещё условия: раздел, автор, другая книга</summary><p class="where-sub">Раздел библиотеки</p><div class="where-row where-sections"></div>'
    +'<p class="where-sub">Книга, автор или другой раздел</p><div class="where-find"><input type="search" class="where-input" placeholder="Название, автор или раздел — начните вводить" aria-label="Найти книгу, автора или раздел"><div class="where-suggest" hidden></div></div>'
    +'<p class="where-sub where-later">По времени (век автора) — появится, когда соберём годы жизни авторов: в каталоге их пока нет.</p></details><div class="where-chosen"></div>';
  $('#refine-panel .refine-head').after(where);
  // the old pickers stay working underneath, but out of sight: one way to choose, not three
  ['label[for="category-select"]','#category-select','label[for="collection-select"]','#collection-select','#collection-chips','label[for="mode-select"]','#mode-select'].forEach(sel=>document.querySelector(sel)?.classList.add('legacy-scope'));
  scopeBox.classList.add('legacy-scope');
  const includedIds=()=>multiScope.filter(x=>!x.exclude&&x.kind==='book').map(x=>x.id);
  const sameSet=(a,b)=>a.length===b.length&&a.every(x=>b.includes(x));
  function bookTitleOf(id){return state.collections.find(c=>String(c.id)===String(id))?.title||BOOK_SHORT[id]||id;}
  function setScope(list){multiScope.length=0;list.forEach(x=>multiScope.push(x));$('#category-select').value='all';$('#collection-select').value='all';renderMultiScope();filtersChanged();}
  function scopeLabel(){
    if(!multiScope.length)return 'Все книги';
    if(authorPicks.length&&multiScope.every(x=>x.kind==='book'&&authorPicks.some(a=>a.ids.includes(x.id))))return 'автор: '+authorPicks.map(a=>a.name).join(', ');
    const inc=includedIds(),onlyBooks=multiScope.every(x=>x.kind==='book'&&!x.exclude),g=onlyBooks&&GROUPS.find(g=>sameSet(g.ids,inc));if(g)return g.title;
    const name=x=>x.kind==='book'?(BOOK_SHORT[x.id]||shortCollection(x.title)):x.title.split('|')[0].trim();
    const yes=multiScope.filter(x=>!x.exclude).map(name),no=multiScope.filter(x=>x.exclude).map(name);
    return (yes.length?(yes.length>2?yes.slice(0,2).join(', ')+' и ещё '+(yes.length-2):yes.join(', ')):'Все книги')+(no.length?' · без: '+no.join(', '):'');
  }
  function renderWhere(){
    const inc=includedIds(),onlyBooks=multiScope.every(x=>x.kind==='book'&&!x.exclude);
    // books one by one (owner 29.10: «убери кнопки комбо, оставь по одному»)
    where.querySelector('.where-groups').innerHTML=`<button type="button" class="collection-chip${multiScope.length?'':' selected'}" data-where-all>Все книги</button>`;
    where.querySelector('.where-books').innerHTML=`<button type="button" class="collection-chip${multiScope.length?'':' selected'}" data-where-all>Все книги</button>`+MAIN_BOOKS.filter(id=>state.collections.some(c=>c.id===id)).map(id=>`<button type="button" class="collection-chip${inc.includes(id)?' selected':''}" data-where-book="${id}" aria-pressed="${inc.includes(id)}">${BOOK_SHORT[id]}</button>`).join('');
    const authorIds=new Set(authorPicks.flatMap(a=>a.ids));
    const extra=multiScope.filter(x=>(x.exclude||!MAIN_BOOKS.includes(x.id)||x.kind!=='book')&&!(x.kind==='book'&&authorIds.has(x.id)&&!x.exclude));
    const cats=state.categories.filter(c=>SECTION_PICKS.includes(String(c.id)));
    where.querySelector('.where-sections').innerHTML=cats.map(c=>{const on=multiScope.some(x=>x.kind==='category'&&x.id===String(c.id)&&!x.exclude);return `<button type="button" class="collection-chip${on?' selected':''}" data-where-section="${escape(c.id)}">${escape(c.title.split('|')[0].replace(/\s*\(.*?\)\s*/g,' ').trim())}</button>`;}).join('');
    where.querySelector('.where-chosen').innerHTML=authorPicks.map((a,i)=>`<span class="where-pick">автор: ${escape(a.name)} · ${a.ids.length}<button type="button" data-where-author-remove="${i}" aria-label="Убрать">×</button></span>`).join('')+extra.map(x=>`<span class="where-pick${x.exclude?' excluded':''}">${x.exclude?'без: ':''}${escape(x.kind==='book'?shortCollection(x.title):x.title.split('|')[0].trim())}<button type="button" data-where-remove="${escape(x.kind+'|'+x.id)}" aria-label="Убрать">×</button></span>`).join('');
  }
  where.addEventListener('click',event=>{
    const t=event.target.closest('button');if(!t)return;
    if(t.hasAttribute('data-where-all')){authorPicks.length=0;setScope([]);return;}
    if(t.dataset.whereSection){const id=t.dataset.whereSection,item=state.categories.find(c=>String(c.id)===id),on=multiScope.some(x=>x.kind==='category'&&x.id===id);
      setScope(on?multiScope.filter(x=>!(x.kind==='category'&&x.id===id)):[...multiScope,{kind:'category',id,title:item?item.title:id,exclude:false}]);return;}
    if(t.dataset.whereAuthorRemove){const a=authorPicks.splice(+t.dataset.whereAuthorRemove,1)[0];if(a)setScope(multiScope.filter(x=>!(x.kind==='book'&&a.ids.includes(x.id))));return;}
    if(t.dataset.whereAuthor){const name=t.dataset.whereAuthor,ids=state.collections.filter(c=>String(c.author||'').trim()===name).map(c=>String(c.id)).slice(0,90);if(!ids.length)return;
      authorPicks.push({name:name.split('|').pop().trim(),ids});setScope([...multiScope.filter(x=>!ids.includes(x.id)),...ids.map(id=>({kind:'book',id,title:bookTitleOf(id),exclude:false}))]);
      where.querySelector('.where-input').value='';where.querySelector('.where-suggest').hidden=true;return;}
    if(false){}
    else if(t.dataset.whereGroup){const g=GROUPS.find(x=>x.id===t.dataset.whereGroup);setScope(g.ids.filter(id=>state.collections.some(c=>c.id===id)).map(id=>({kind:'book',id,title:bookTitleOf(id),exclude:false})));}
    else if(t.dataset.whereBook){const id=t.dataset.whereBook,list=multiScope.filter(x=>!(x.kind==='book'&&x.id===id));if(list.length===multiScope.length)list.push({kind:'book',id,title:bookTitleOf(id),exclude:false});setScope(list);}
    else if(t.dataset.whereRemove){const [kind,...rest]=t.dataset.whereRemove.split('|'),id=rest.join('|');setScope(multiScope.filter(x=>!(x.kind===kind&&x.id===id)));}
    else if(t.dataset.whereAdd){const [kind,...rest]=t.dataset.whereAdd.split('|'),id=rest.join('|'),exclude=t.dataset.whereExclude==='1';
      const item=kind==='book'?state.collections.find(c=>String(c.id)===id):state.categories.find(c=>String(c.id)===id);if(!item)return;
      setScope([...multiScope.filter(x=>!(x.kind===kind&&x.id===id)),{kind,id,title:item.title,exclude}]);where.querySelector('.where-input').value='';where.querySelector('.where-suggest').hidden=true;}
  });
  where.querySelector('.where-input').addEventListener('input',event=>{
    const q=catalogFold(event.target.value).trim(),box=where.querySelector('.where-suggest');if(q.length<2){box.hidden=true;box.innerHTML='';return;}
    const cats=state.categories.filter(c=>catalogFold(c.title).includes(q)).slice(0,3).map(c=>({kind:'category',id:String(c.id),title:c.title.split('|')[0].trim(),sub:`раздел · ${c.count||''} книг`}));
    const books=state.collections.filter(c=>catalogFold(`${c.title} ${c.arabicTitle||''} ${c.author||''}`).includes(q)).slice(0,6).map(c=>({kind:'book',id:String(c.id),title:c.title,sub:String(c.author||'').split('|').pop().trim()}));
    const authorsSeen=new Map();for(const c of state.collections){const a=String(c.author||'').trim();if(a&&catalogFold(a).includes(q))authorsSeen.set(a,(authorsSeen.get(a)||0)+1);}
    const authors=[...authorsSeen.entries()].sort((x,y)=>y[1]-x[1]).slice(0,3).map(([a,n])=>({kind:'author',id:a,title:a.split('|').pop().trim(),sub:`автор · ${n} книг`}));
    const rows=[...authors,...cats,...books];
    box.innerHTML=rows.length?rows.map(r=>r.kind==='author'?`<div class="where-option"><span dir="auto"><strong>${escape(r.title)}</strong><small>${escape(r.sub)}</small></span><button type="button" data-where-author="${escape(r.id)}">Все его книги</button></div>`:`<div class="where-option"><span dir="auto"><strong>${escape(r.title)}</strong><small>${escape(r.sub)}</small></span><button type="button" data-where-add="${escape(r.kind+'|'+r.id)}">Искать</button><button type="button" class="where-exclude" data-where-add="${escape(r.kind+'|'+r.id)}" data-where-exclude="1">Без</button></div>`).join(''):'<p class="where-none">Не нашлось — попробуйте по-арабски или по автору</p>';
    box.hidden=false;
  });
  function renderMultiScope(){
    $('.scope-list',scopeBox).innerHTML=multiScope.map((item,i)=>`<li>${item.exclude?'Исключить':'Искать'}: ${escape(item.title)} <button type="button" data-remove-scope="${i}" aria-label="Убрать из выбора: ${escape(item.title)}">×</button></li>`).join('');
    scopeBox.querySelectorAll('[data-remove-scope]').forEach(b=>b.onclick=()=>{multiScope.splice(Number(b.dataset.removeScope),1);renderMultiScope();filtersChanged();});
  }
  scopeBox.querySelectorAll('[data-scope-action]').forEach(button=>button.onclick=()=>{
    const book=state.collections.find(c=>String(c.id)===$('#collection-select').value),category=state.categories.find(c=>String(c.id)===$('#category-select').value),chosen=book||category;
    if(!chosen){toast('Сначала выберите книгу или раздел выше');return;}
    const kind=book?'book':'category',id=String(chosen.id),exclude=button.dataset.scopeAction==='exclude';
    const previous=multiScope.findIndex(x=>x.kind===kind&&x.id===id);if(previous>=0)multiScope.splice(previous,1);
    multiScope.push({kind,id,title:chosen.title,exclude});$('#category-select').value='all';$('#collection-select').value='all';renderMultiScope();filtersChanged();
  });
  function filtersChanged() {
    state.category = $('#category-select').value; state.collection = $('#collection-select').value; state.mode = $('#mode-select').value;
    $('#mode-help').textContent = state.section === 'quran' ? 'Введите текст аята или его номер, например 2:255.' : modeHelp[state.mode];
    $('.filter-dot').hidden = state.section==='quran' || (state.category === 'all' && state.collection === 'all' && state.mode === 'normal' && !multiScope.length);
    scopeBox.hidden=state.section==='quran';
    for(const id of ['category-select','collection-select','mode-select']){const el=$('#'+id);el.hidden=state.section==='quran';const label=document.querySelector(`label[for="${id}"]`);if(label)label.hidden=state.section==='quran';}
    const chosen = state.collections.find(c => String(c.id) === state.collection);
    const category = state.categories.find(c => String(c.id) === state.category);
    $('#search-summary').dataset.normal = state.section === 'quran' ? 'Коран · Текст или номер аята' : `${multiScope.length?scopeLabel():(state.collections.find(c => String(c.id) === state.collection)?.title || state.categories.find(c => String(c.id) === state.category)?.title || 'Все книги')} · ${modeNames[state.mode]||'По словам'}`;
    if (!state.aiMode) $('#search-summary').textContent = state.section === 'quran' ? 'Коран · Текст или номер аята' : `${multiScope.length?scopeLabel():(chosen?.title || category?.title || 'Все книги')} · ${modeNames[state.mode]}`;
    renderChips(); syncModeChips(); if (state.section === 'quran') modeChips.hidden = true;
    try {where.hidden = state.section === 'quran'; renderWhere();} catch (_) {}
  }
  $('#category-select').onchange = () => {$('#collection-select').value = 'all'; filtersChanged();};
  $('#collection-select').onchange = () => {$('#category-select').value = 'all'; filtersChanged();};
  $('#mode-select').onchange = filtersChanged;
  $('#reset-filters').onclick = () => {$('#category-select').value = 'all'; $('#collection-select').value = 'all'; $('#mode-select').value = 'normal';multiScope.length=0;renderMultiScope(); filtersChanged(); const wi = $('.where-input'); if (wi) {wi.value = ''; $('.where-suggest').hidden = true;}};
  $$('[data-section]').forEach(button => button.onclick = () => {
    state.section = button.dataset.section; state.searchToken++;
    $$('[data-section]').forEach(b => {b.classList.toggle('selected',b === button); b.setAttribute('aria-pressed',String(b === button));});
    $('#collection-chips').hidden = state.section === 'quran'; $('#category-select').disabled = state.section === 'quran'; $('#collection-select').disabled = state.section === 'quran'; $('#mode-select').disabled = state.section === 'quran';
    filtersChanged(); showWelcome(); resetPlaceholder(); try {syncQuranPick();} catch (_) {}
  });
  function shortCollection(title) {return String(title || '').replace(/^Сахих\s+/i,'').replace(/^Сунан\s+/i,'').replace(/\s*\([^)]*\)\s*/g,' ').trim();}
  function renderChips() {
    const shortcuts = [{id:'all',title:'Все книги'},...state.collections.filter(c => c.readable !== false).slice(0,3)];
    if (state.collection !== 'all' && !shortcuts.some(c => String(c.id) === state.collection)) {const current = state.collections.find(c => String(c.id) === state.collection); if (current) shortcuts.push(current);}
    $('#collection-chips').innerHTML = shortcuts.map(c => `<button type="button" class="collection-chip${String(c.id) === state.collection ? ' selected' : ''}" data-collection="${escape(c.id)}" aria-pressed="${String(c.id) === state.collection}">${escape(c.id === 'all' ? c.title : shortCollection(c.title))}</button>`).join('');
    $$('[data-collection]').forEach(button => button.onclick = () => {$('#category-select').value = 'all'; $('#collection-select').value = button.dataset.collection; filtersChanged();});
  }
  const catalogFold = text => fold(text).replace(/[\u064b-\u065f\u0670\u0640]/g,'');
  const favoriteBook = collection => state.favoriteBooks.includes(String(collection.id));
  // One look for every book (owner 29.10: «разброс — где-то русский, где-то арабский»): the original Arabic title
  // always on top (every book has one), the Russian translation under it when we have one, then the author.
  const hasArabic = t => /[؀-ۿ]/.test(t), hasCyrillic = t => /[Ѐ-ӿ]/.test(t);
  function bookTile(collection) {
    const favorite = favoriteBook(collection), id = escape(collection.id);
    const title = String(collection.title || '').trim(), ar = String(collection.arabicTitle || (hasArabic(title) && !hasCyrillic(title) ? title : '')).trim(), ru = hasCyrillic(title) ? title : '';
    return `<article class="collection-tile"><button type="button" class="collection-open" data-book-id="${id}" aria-label="Открыть ${escape(ru || ar)}"><span class="book-seal">${icon('book')}</span>${ar ? `<h2 class="tile-ar" lang="ar" dir="rtl">${escape(ar)}</h2>` : ''}${ru ? `<p class="tile-ru">${escape(ru)}</p>` : ''}<p class="tile-author">${escape(collection.author || collection.subtitle || '')}</p>${icon('arrow')}</button><button type="button" class="favorite-book${favorite ? ' selected' : ''}" data-favorite-book="${id}" aria-pressed="${favorite}" aria-label="${favorite ? 'Убрать из избранных книг' : 'Добавить в избранные книги'}: ${escape(collection.title)}">${icon('star')}</button><button type="button" class="book-about" data-book-info="${id}" aria-label="О книге ${escape(collection.title)}">${icon('info')}<span>О книге</span></button></article>`;
  }
  function toggleFavoriteBook(id) {
    const exists = state.favoriteBooks.includes(id);
    state.favoriteBooks = exists ? state.favoriteBooks.filter(bookId => bookId !== id) : [...state.favoriteBooks,id];
    try {localStorage.setItem(FAVORITE_BOOK_STORAGE,JSON.stringify(state.favoriteBooks)); toast(exists ? 'Книга убрана из избранного' : 'Книга в избранном');} catch (_) {toast('Избранное сохранено до закрытия страницы');}
    renderLibrary(); updateBookFavorite();
  }
  function bindBookButtons(target) {
    $$('[data-book-id]',target).forEach(button => button.onclick = () => {const collection = state.collections.find(book => String(book.id) === button.dataset.bookId); if (collection) browseCollection(collection);});
    $$('[data-favorite-book]',target).forEach(button => button.onclick = () => toggleFavoriteBook(button.dataset.favoriteBook));
    $$('[data-book-info]',target).forEach(button => button.onclick = () => {const collection = state.collections.find(book => String(book.id) === button.dataset.bookInfo); if (collection) openBookInfo(collection);});
  }
  function renderLibrary() {
    const query = catalogFold(state.libraryQuery).trim();
    const books = state.collections.filter(collection => {if (!query) return true; const title = `${collection.title || ''} ${collection.arabicTitle || ''}`, author = String(collection.author || ''); return catalogFold(state.librarySearchMode === 'author' ? author : state.librarySearchMode === 'title' ? title : `${title} ${author}`).includes(query);});
    const favorites = books.filter(favoriteBook);
    // Favourites are a section you open (owner 29.10), not a list that always hangs above the catalog.
    $('.favorite-books-section').hidden = true;
    let favButton = $('#favorites-open'); if (!favButton) {favButton = document.createElement('button'); favButton.type = 'button'; favButton.id = 'favorites-open'; favButton.className = 'favorites-open'; $('.favorite-books-section').after(favButton); favButton.onclick = () => {state.libraryFavOnly = !state.libraryFavOnly; state.libraryShown = 24; renderLibrary(); window.scrollTo({top: 0, behavior: 'smooth'});};}
    favButton.innerHTML = state.libraryFavOnly ? `${icon('back')}<span>Все книги</span>` : `${icon('star')}<span>Избранные книги</span><b>${state.favoriteBooks.length || ''}</b>${icon('arrow')}`;
    const shown = state.libraryFavOnly ? favorites : books;
    $('#favorite-books').innerHTML = '';
    $('#favorite-book-count').textContent = favorites.length ? String(favorites.length) : '';
    $('#favorite-books-empty').hidden = favorites.length > 0;
    $('#favorite-books-empty').textContent = query && state.favoriteBooks.length ? 'Среди избранных нет книг с таким названием.' : 'Отметьте книгу звёздочкой — она будет здесь.';
    $('#catalog-count').textContent = query ? `${shown.length} найдено` : String(shown.length);
    const allHeading = $('#catalog-count').previousElementSibling; if (allHeading) allHeading.textContent = state.libraryFavOnly ? 'Избранные книги' : 'Все книги';
    $('#library-collections').setAttribute('aria-busy','false');
    if (shown.length) $('#library-collections').innerHTML = shown.slice(0,state.libraryShown).map(bookTile).join('');
    else $('#library-collections').innerHTML = `<p class="catalog-empty">${state.libraryFavOnly ? 'Отметьте книгу звёздочкой — она появится здесь.' : 'Книги с таким названием не найдены.'}</p>`;
    const remaining = Math.max(0,shown.length - state.libraryShown);
    $('#more-books').hidden = remaining === 0;
    $('#more-books').innerHTML = `Показать ещё ${Math.min(24,remaining)}${icon('down')}`;
    bindBookButtons($('#favorite-books')); bindBookButtons($('#library-collections'));
  }
  $('#catalog-query').addEventListener('input',() => {state.libraryQuery = $('#catalog-query').value; state.libraryShown = 24; renderLibrary();});
  $('#catalog-search-mode').onchange = () => {state.librarySearchMode = $('#catalog-search-mode').value; state.libraryShown = 24; $('#catalog-query').placeholder = state.librarySearchMode === 'author' ? 'Имя автора' : state.librarySearchMode === 'title' ? 'Название книги' : 'Название книги или имя автора'; renderLibrary();};
  $('#more-books').onclick = () => {state.libraryShown += 24; renderLibrary();};
  function showLibraryOverview() {$('#browse-area').hidden = true; $('#library-overview').hidden = false; $('#library-collections').hidden = false; $('#full-library').hidden = false;}
  function updateBookFavorite() {
    const button = $('#book-dialog-favorite'); if (!button || !activeBook) return;
    const saved = favoriteBook(activeBook); button.classList.toggle('selected',saved); button.setAttribute('aria-pressed',String(saved)); button.innerHTML = `${icon('star')}${saved ? 'В избранных книгах' : 'Добавить в избранные'}`;
  }
  function authorBooks(author) {
    $('#book-dialog').close(); showView('library'); showLibraryOverview(); state.librarySearchMode = 'author'; state.libraryQuery = String(author); state.libraryShown = 24;
    $('#catalog-search-mode').value = 'author'; $('#catalog-query').value = String(author); $('#catalog-query').placeholder = 'Имя автора'; renderLibrary();
  }
  function safeWebUrl(value) {try {const url = new URL(String(value)); return ['https:','http:'].includes(url.protocol) ? url.href : '';} catch (_) {return '';}}
  async function openBookInfo(collection) {
    activeBook = collection; const token = ++bookInfoToken, author = String(collection.author || '');
    const dialog = $('#book-dialog'); if (!dialog.open) dialog.showModal(); document.body.style.overflow = 'hidden';
    $('#book-dialog-body').innerHTML = `<span class="book-seal book-detail-seal">${icon('book')}</span><h1 id="book-dialog-title">${escape(collection.title)}</h1>${collection.arabicTitle && collection.arabicTitle !== collection.title ? `<p class="book-arabic-title" lang="ar" dir="rtl">${escape(collection.arabicTitle)}</p>` : ''}<div class="book-detail-meta"><span>Автор</span>${author ? `<button type="button" id="book-author">${escape(author)}${icon('arrow')}</button>` : '<p>В каталоге не указан</p>'}${collection.categoryLabel || collection.category ? `<span>Раздел</span><p>${escape(collection.categoryLabel || collection.category)}</p>` : ''}</div><div id="book-description"><div class="loading-state"><span class="loading-orbit"></span><p>Ищем сведения о книге<span>Загружаем описание из источника</span></p></div></div><div class="book-dialog-actions"><button type="button" class="book-read-button" id="book-dialog-read">Читать книгу${icon('arrow')}</button><button type="button" class="book-favorite-button" id="book-dialog-favorite"></button></div>`;
    if ($('#book-author')) $('#book-author').onclick = () => authorBooks(author);
    // «Читать книгу» — сама книга с первой страницы издания: предисловие, все главы (owner 29.10); хадисы по номерам — второй путь.
    $('#book-dialog-read').onclick = () => {dialog.close(); if (collection.bid) openNativeBook(collection.bid,1,collection.title,{arabicTitle:collection.arabicTitle}); else {showView('library'); browseCollection(collection);}};
    if (collection.bid && !String(collection.id||'').startsWith('book:')) $('#book-dialog-read').insertAdjacentHTML('afterend','<button type="button" class="book-list-button" id="book-dialog-list">Хадисы по номерам</button>');
    if ($('#book-dialog-list')) $('#book-dialog-list').onclick = () => {dialog.close(); showView('library'); browseCollection(collection);};
    $('#book-dialog-favorite').onclick = () => toggleFavoriteBook(String(collection.id)); updateBookFavorite();
    $('#book-dialog-body').scrollTop = 0;
    // Owner 29.10: Wikipedia first, then links to Maktaba ash-Shamila and sunnah.com (all through «Выйти?»).
    const titleEnd = $('#book-dialog-body .book-arabic-title') || $('#book-dialog-title');
    const links = document.createElement('div'); links.className = 'book-links'; titleEnd.after(links); links.after($('#book-description'));
    // Each source with its own recognizable mark (owner 29.10: «фирменную, узнаваемую и заметнее»), drawn in CSS — no
    // third-party images are loaded.
    const linkRow = wiki => {links.innerHTML = [wiki ? `<a class="book-link brand-wiki" href="${escape(wiki)}"><span class="brand-mark">W</span><span class="brand-name">Википедия</span></a>` : '', collection.bid ? `<a class="book-link brand-shamela" href="https://shamela.ws/book/${encodeURIComponent(collection.bid)}"><span class="brand-mark" lang="ar">الشاملة</span><span class="brand-name">Мактаба аш-Шамила</span></a>` : '', SUNNAH_COM[collection.id] ? `<a class="book-link brand-sunnah" href="https://sunnah.com/${SUNNAH_COM[collection.id]}"><span class="brand-mark">sunnah<b>.com</b></span><span class="brand-name">этот сборник</span></a>` : ''].filter(Boolean).join('');};
    linkRow('');
    // «Что за издание» (owner 29.10): the edition card from the library itself — tahqiq, publisher, printing, volumes.
    if (collection.bid && state.api && typeof state.api.bookMeta === 'function') state.api.bookMeta(collection.bid).then(meta => {
      if (token !== bookInfoToken || !dialog.open || !meta?.info || $('#book-edition')) return;
      $('#book-dialog-body').insertAdjacentHTML('beforeend', `<section class="book-edition" id="book-edition"><h2>Издание</h2><p lang="ar" dir="rtl">${escape(meta.info)}</p></section>`);
    }).catch(() => {});
    try {
      if (!state.api || typeof state.api.bookInfo !== 'function') throw new Error('Book information unavailable');
      const info = await state.api.bookInfo(collection.id); if (token !== bookInfoToken || !dialog.open) return;
      const url = safeWebUrl(info?.sourceUrl), description = String(info?.description || '').trim();
      if (/wikipedia\.org/.test(url)) linkRow(url);
      $('#book-description').innerHTML = `<h2>О книге${/wikipedia\.org/.test(url) ? '<small class="book-desc-from">из Википедии</small>' : ''}</h2><p class="book-description-text" dir="auto">${escape(description || 'Описание этой книги из источников пока не получено.')}</p>${info?.notice ? `<p class="book-info-notice">${escape(info.notice)}</p>` : ''}${url && !/wikipedia\.org/.test(url) ? `<a class="book-description-source" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(info.sourceTitle || 'Источник описания')}${info.language ? ` · ${escape(info.language)}` : ''}${icon('source')}</a>` : ''}`;
    } catch (_) {if (token === bookInfoToken && dialog.open) $('#book-description').innerHTML = '<h2>О книге</h2><p class="book-info-notice">Сейчас не удалось получить описание из источника. Доступные сведения из каталога показаны выше.</p>';}
  }
  $('#book-dialog-close').onclick = () => $('#book-dialog').close();
  $('#book-dialog').addEventListener('close',() => {bookInfoToken++; document.body.style.overflow = '';});
  $('#book-dialog').addEventListener('click',event => {if (event.target === $('#book-dialog')) $('#book-dialog').close();});
  async function performSearch() {
    const query = $('#query').value.trim();
    if (!query) {$('#query').focus(); return;}
    if (!state.api) {toast('Библиотека ещё открывается'); return;}
    const token = ++state.searchToken; state.results = []; state.resultQuery = query;state.shown=8;state.numberMode=false;state.numberHasMore=false;
    $('#result-count').textContent = ''; $('#search-notice').hidden = true; $('#more-results').hidden = true; $('#search-results-heading').hidden = false;
    $('#results-title').textContent = 'Результаты поиска'; $('#refine-panel').hidden = true; $('#refine-toggle').setAttribute('aria-expanded','false'); loading($('#search-results'));
    const request = {query,category:state.section === 'quran' ? 'all' : state.category,collection:state.section === 'quran' ? 'all' : state.collection,section:state.section,mode:state.section === 'quran' ? 'normal' : state.mode,scope:state.section==='hadith'?multiScope.map(({kind,id,exclude})=>({kind,id,exclude})):[]};
    try {
      const result = await state.api.search(request); if (token !== state.searchToken) return;
      if (result.opened) {showWelcome(); return;}
      if(result.numeric){applyNumberResults(result);return;}
      state.results = Array.isArray(result.items) ? result.items : []; state.shown = 8;
      $('#result-count').textContent = `${Number.isFinite(Number(result.total)) ? Number(result.total).toLocaleString('ru-RU') : state.results.length} найдено`;
      if (result.notice) {$('#search-notice').textContent = String(result.notice); $('#search-notice').hidden = false;}
      if (result.heading) $('#results-title').textContent = String(result.heading);
      if (state.results.length) {renderCards($('#search-results'),state.results,state.shown); $('#more-results').hidden = state.shown >= state.results.length;}
      else empty($('#search-results'),'Попробуйте другие слова','Сократите фразу или выберите все сборники в настройках поиска.');
    } catch (error) {
      if (token !== state.searchToken) return;
      empty($('#search-results'),'Поиск пока недоступен','Не удалось получить тексты. Можно попробовать ещё раз.','Повторить поиск',performSearch); $('#result-count').textContent = ''; console.warn('Muslimoon search unavailable',error);
    }
  }
  function applyNumberResults(result){
    if(!result||result.query!==state.resultQuery||state.section!=='hadith')return;
    state.numberMode=true;state.numberHasMore=!!result.hasMore;state.results=Array.isArray(result.items)?result.items:[];
    $('#result-count').textContent=state.results.length?`${state.results.length.toLocaleString('ru-RU')} найдено`:result.empty?'0 найдено':'Ищем по книгам…';
    $('#search-notice').hidden=true;
    if(state.results.length)renderCards($('#search-results'),state.results,state.shown);
    else if(result.empty)empty($('#search-results'),'Не найдено','Книгу с таким номером не удалось найти.');
    else loading($('#search-results'),'Ищем по номеру','Сверяем книги и издания');
    $('#more-results').hidden=state.shown>=state.results.length&&!state.numberHasMore;
    $('#more-results').firstChild.textContent=state.numberHasMore&&state.shown>=state.results.length?'Ещё книги':'Показать ещё';
  }
  $('#search-form').onsubmit = event => {event.preventDefault(); if (state.aiMode) {askAssistant($('#query').value); return;} performSearch();};
  $('#more-results').onclick = async () => {
    state.shown+=8;
    if(state.numberMode&&state.shown>state.results.length&&state.numberHasMore){
      const button=$('#more-results');button.disabled=true;
      try{applyNumberResults(await state.api.numberMore(state.resultQuery));}
      catch(e){toast('Не удалось загрузить следующие книги');console.warn(e);}
      finally{button.disabled=false;}
    }else if(state.numberMode)applyNumberResults({query:state.resultQuery,items:state.results,hasMore:state.numberHasMore});
    else{renderCards($('#search-results'),state.results,state.shown);$('#more-results').hidden=state.shown>=state.results.length;}
  };
  let nativeBook=null,nativeBookToken=0;
  function ensureNativeBook(){
    let dialog=$('#native-book-reader');if(dialog)return dialog;
    dialog=document.createElement('dialog');dialog.id='native-book-reader';dialog.className='reader-dialog native-book-dialog';dialog.setAttribute('aria-labelledby','native-book-title');
    dialog.innerHTML=`<div class="reader-shell"><header class="reader-toolbar"><button type="button" class="icon-button native-book-close" aria-label="Закрыть книгу">${icon('back')}</button><span>ЧТЕНИЕ КНИГИ</span><button type="button" class="text-button native-book-about">О книге</button></header><div class="reader-body native-book-body"><h1 id="native-book-title"></h1><div class="native-book-location" aria-live="polite"></div><div class="native-book-actions"><button type="button" class="nb-action native-book-toc">${icon('book')}Оглавление</button><button type="button" class="nb-action native-book-translate">${icon('helper')}Перевод ИИ</button></div><div class="native-book-headings" lang="ar" dir="rtl"></div><div class="native-book-text" lang="ar" dir="rtl"></div><div class="native-book-tr" hidden></div><div class="native-book-notes"></div><p class="native-book-status" role="status" aria-live="polite"></p><button type="button" class="native-book-tools">Инструменты книги</button></div><nav class="native-book-bar" aria-label="Листание книги" dir="ltr"><button type="button" class="nb-turn native-book-next" aria-label="Следующая страница">${icon('back')}</button><div class="nb-jump"><button type="button" class="nb-edge nb-end">Конец</button><label class="nb-field"><span>Страница</span><input class="nb-page" inputmode="numeric" enterkeyhint="go" aria-label="Перейти на страницу издания"></label><label class="nb-field nb-field-num"><span>№ хадиса</span><input class="nb-hadith" inputmode="numeric" enterkeyhint="go" placeholder="—" aria-label="Перейти к хадису, асару или документу по его номеру в книге"></label><button type="button" class="nb-edge nb-start">Начало</button></div><button type="button" class="nb-turn native-book-prev" aria-label="Предыдущая страница">${icon('arrow')}</button></nav></div>`;
    document.body.appendChild(dialog);
    $('.native-book-close',dialog).onclick=()=>dialog.close();
    $('.native-book-about',dialog).onclick=()=>{const book=nativeBook;if(book)openBookInfo(collectionForBid(book.bid,book.title));};
    dialog.addEventListener('close',()=>{nativeBookToken++;});
    dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
    $('.native-book-prev',dialog).onclick=()=>loadNativeBookLeaf(nativeBook.leaf-1);
    $('.native-book-next',dialog).onclick=()=>loadNativeBookLeaf(nativeBook.leaf+1);
    // Jumps as in Maktaba, only by Enter: printed page, hadith number, the book's start and end.
    const onEnter=(input,go)=>input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();input.blur();go(Number(String(input.value).replace(/[^0-9]/g,'')));}});
    onEnter($('.nb-page',dialog),page=>{if(page>0)jumpPrinted(page);});
    onEnter($('.nb-hadith',dialog),async number=>{if(!(number>0)||!nativeBook)return;const status=$('.native-book-status',dialog);status.textContent='Ищем хадис №'+number+'…';
      try{const place=await state.api.leafByHadith(nativeBook.bid,number);nativeBook.mark=String(number);loadNativeBookLeaf(place.leaf);}catch(error){status.textContent=String(error?.message||'Не найден');}});
    $('.nb-start',dialog).onclick=()=>loadNativeBookLeaf(1);
    $('.nb-end',dialog).onclick=async()=>{if(!nativeBook)return;const status=$('.native-book-status',dialog);status.textContent='Ищем конец книги…';
      try{const last=await state.api.lastLeaf(nativeBook.bid,nativeBook.leaf);nativeBook.last=last.leaf;loadNativeBookLeaf(last.leaf);}catch(_){status.textContent='Конец книги сейчас не определился';}};
    $('.native-book-toc',dialog).onclick=()=>openBookToc();
    $('.native-book-translate',dialog).onclick=()=>translateBookPage();
    $('.native-book-tools',dialog).onclick=async()=>{const book=nativeBook;dialog.close();try{await state.api.tool('bookPage',{kind:'book',bid:book.bid,page:String(book.leaf)});}catch(_){toast('Инструменты книги сейчас недоступны');}};
    return dialog;
  }
  // A book is known to the library by its Maktaba id; fall back to a bare card when the catalog has no row for it.
  function collectionForBid(bid,title){return state.collections.find(c=>String(c.bid)===String(bid))||{id:'book:'+bid,bid:String(bid),title:String(title||'Книга')};}
  // The page exactly as the edition prints it: the text above the rule, the edition's footnotes below it (folded).
  function pageParts(text){const raw=String(text||''),cut=raw.search(/\n\s*_{5,}\s*\n?/);return cut<0?{body:raw,notes:''}:{body:raw.slice(0,cut).trim(),notes:raw.slice(cut).replace(/^\s*_{5,}\s*/,'').trim()};}
  // Mark the hadith we came from by its number as printed («٣٢١ -»), nothing else is touched.
  function markHadith(escaped,number){
    const n=String(number||'').replace(/[^0-9]/g,'');if(!n)return escaped;
    const arabic=n.replace(/[0-9]/g,d=>'٠١٢٣٤٥٦٧٨٩'[+d]);
    return escaped.replace(new RegExp(`(^|[\\s(])(${arabic}|${n})(\\s*-)`,'m'),'$1<mark class="hadith-anchor">$2$3</mark>');
  }
  // Numbers of the hadiths/athar printed on this page («٣٢١ - حدثنا…» at the start of a line) — to name them plainly.
  function pageNumbers(body){const out=[];String(body||'').replace(/(^|\n)\s*[(\[]?([0-9\u0660-\u0669]{1,6})[)\]]?\s*[-–ـ]\s/g,(m,a,n)=>{const v=String(n).replace(/[\u0660-\u0669]/g,d=>String(d.charCodeAt(0)-0x660));if(!out.includes(v))out.push(v);return m;});return out;}
  // Оглавление книги: главы по уровням, текущая подсвечена, нажатие — на лист главы.
  async function openBookToc(){
    const book=nativeBook;if(!book)return;const dialog=ensureNativeBook();let box=$('.native-book-tocbox',dialog);
    if(box){box.remove();return;}
    box=document.createElement('div');box.className='native-book-tocbox';box.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Загружаю оглавление</span></div>';
    $('.native-book-actions',dialog).after(box);
    let hs=book.toc;if(!hs){try{hs=(await state.api.bookToc(book.bid)).headings||[];book.toc=hs;}catch(_){hs=[];}}
    if(nativeBook!==book||!box.isConnected)return;
    if(!hs.length){box.innerHTML='<p class="notes-hint">У этой книги нет оглавления в источнике. Листайте страницы или переходите по номеру.</p>';return;}
    let cur=-1;hs.forEach((h,i)=>{if(h.p<=book.leaf)cur=i;});
    box.innerHTML=`<input type="search" class="toc-find" placeholder="Найти главу" lang="ar" dir="rtl"><div class="toc-list" lang="ar" dir="rtl"></div>`;
    // Big books have thousands of chapters (Bukhari ~4000): top level first, a chapter opens its sections on tap;
    // the search looks through every level.
    const top=Math.min(...hs.map(h=>h.l)),kids=i=>{const out=[];for(let k=i+1;k<hs.length&&hs[k].l>hs[i].l;k++)out.push(k);return out;};
    let curTop=-1;hs.forEach((h,i)=>{if(h.l===top&&i<=cur)curTop=i;});
    const item=i=>`<button type="button" class="toc-item lvl-${Math.min(4,hs[i].l-top+1)}${i===cur?' current':''}" data-toc="${i}">${escape(hs[i].t)}</button>`;
    const draw=q=>{const f=catalogFold(q||''),list=box.querySelector('.toc-list');
      if(f){const hit=[];for(let i=0;i<hs.length&&hit.length<400;i++)if(catalogFold(hs[i].t).includes(f))hit.push(item(i));list.innerHTML=hit.join('')||'<p class="notes-hint">Глава не найдена</p>';return;}
      list.innerHTML=hs.map((h,i)=>{if(h.l!==top)return '';const k=kids(i);return `<div class="toc-group${i===curTop?' open':''}" data-group="${i}"><div class="toc-row">${item(i)}${k.length?`<button type="button" class="toc-more" data-more="${i}" aria-label="Разделы главы">${k.length}${icon('down')}</button>`:''}</div>${i===curTop?`<div class="toc-kids">${k.map(item).join('')}</div>`:''}</div>`;}).join('');};
    draw('');box.querySelector('.toc-find').addEventListener('input',e=>draw(e.target.value));
    box.querySelector('.toc-list').onclick=e=>{const m=e.target.closest('[data-more]');if(m){const g=m.closest('.toc-group'),i=+m.dataset.more;let kb=g.querySelector('.toc-kids');if(kb){kb.remove();g.classList.remove('open');}else{g.insertAdjacentHTML('beforeend',`<div class="toc-kids">${kids(i).map(item).join('')}</div>`);g.classList.add('open');}return;}
      const b=e.target.closest('[data-toc]');if(!b)return;const h=hs[+b.dataset.toc];box.remove();book.mark='';loadNativeBookLeaf(h.p);};
    const c=box.querySelector('.toc-item.current');if(c)c.scrollIntoView({block:'center'});
  }
  // Machine translation says «Бог» for الله; in Muslimoon the Name stays «Аллах» (Богу → Аллаху, Богом → Аллахом).
  const allahName=t=>String(t||'').replace(/(^|[^А-Яа-яЁё])Бог(а|у|ом|е)?(?![А-Яа-яЁё])/g,(m,a,e)=>a+'Аллах'+(e||''));
  // Перевод ИИ этой страницы — кусками до 1500 знаков (предел сервера), с честной пометкой.
  async function translateBookPage(){
    const book=nativeBook;if(!book)return;const dialog=ensureNativeBook(),box=$('.native-book-tr',dialog),text=pageParts($('.native-book-text',dialog).textContent).body.trim();
    if(!box.hidden&&box.dataset.leaf===String(book.leaf)){box.hidden=true;return;}
    if(!text){toast('На этой странице нет текста');return;}
    box.hidden=false;box.dataset.leaf=String(book.leaf);box.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Перевожу страницу</span></div>';
    const chunks=[];let rest=text;while(rest&&chunks.length<4){if(rest.length<=1500){chunks.push(rest);break;}let cut=Math.max(rest.lastIndexOf('.',1500),rest.lastIndexOf('،',1500),rest.lastIndexOf('\n',1500));if(cut<600)cut=1500;chunks.push(rest.slice(0,cut+1));rest=rest.slice(cut+1).trim();}
    const out=[];
    for(const part of chunks){try{out.push((await state.api.translate(part,'maktaba',book.bid)).translation);}catch(error){out.push('');if(!out.some(Boolean)){if(nativeBook===book&&box.dataset.leaf===String(book.leaf))box.innerHTML=`<p class="notes-hint">${escape(String(error?.message||'Перевод сейчас недоступен'))}</p>`;return;}}
      if(nativeBook!==book||box.dataset.leaf!==String(book.leaf))return;}
    box.innerHTML=`<p class="nb-tr-label">Перевод ИИ — черновой, сверяйте с оригиналом${rest&&chunks.length>=4?' · переведено начало страницы':''}</p>${out.filter(Boolean).map(t=>`<p>${escape(allahName(t))}</p>`).join('')}`;
  }
  function openNativeBook(bid,leaf,title,options={}){
    const dialog=ensureNativeBook(),safeLeaf=Number(leaf);
    nativeBook={bid:String(bid),leaf:Number.isSafeInteger(safeLeaf)&&safeLeaf>0?safeLeaf:1,title:String(title||'Книга'),mark:options.mark?String(options.mark):''};
    $('#native-book-title',dialog).innerHTML=sourceLine(nativeBook.title,options.arabicTitle||'','','native-book-source');
    $('.native-book-text',dialog).textContent='';$('.native-book-notes',dialog).textContent='';$('.native-book-headings',dialog).textContent='';$('.native-book-location',dialog).textContent='';
    $('.native-book-tocbox',dialog)?.remove();if(!dialog.open)dialog.showModal();loadNativeBookLeaf(nativeBook.leaf);
  }
  // Printed page → leaf: start from the current leaf−page offset, correct by what the server says (≤4 probes).
  // Pages restart in every volume and one printed page can span several leaves (Bukhari, Sultaniya: ~5), so stay in
  // the current volume, step by the observed slope, and once the target is bracketed halve down to the FIRST leaf of it.
  async function jumpPrinted(target){
    if(!nativeBook)return;const book=nativeBook,volume=book.volume||null,status=$('.native-book-status',ensureNativeBook());
    status.textContent='Ищем страницу '+target+'…';
    const probe=async l=>{const p=await state.api.bookPageData(book.bid,l);if(p.printedPage==null)return null;
      return volume&&p.volume&&p.volume!==volume?(Number(p.volume)>Number(volume)?Infinity:-Infinity):p.printedPage;};
    let lo=null,hi=null,a={leaf:book.leaf,page:book.page},leaf=Math.max(1,target+(book.offset||0));
    try{
      for(let i=0;i<16;i++){
        const page=await probe(leaf);if(page==null)break;
        if(page<target)lo=leaf;else hi=hi==null?leaf:Math.min(hi,leaf);
        if(lo!=null&&hi!=null){if(hi-lo<=1)break;leaf=Math.floor((lo+hi)/2);continue;}
        const slope=Number.isFinite(page)&&a.page!=null&&page!==a.page?Math.abs((leaf-a.leaf)/(page-a.page)):1;
        const delta=Number.isFinite(page)?Math.round((target-page)*Math.max(1,Math.min(30,slope))):(page>0?-60:60);
        if(Number.isFinite(page))a={leaf,page};
        leaf=Math.max(1,leaf+(delta||(page<target?1:-1)));
        if(hi==null&&lo!=null&&leaf<=lo)leaf=lo+1;
      }
    }catch(_){}
    loadNativeBookLeaf(hi!=null?hi:leaf);
  }
  async function loadNativeBookLeaf(leaf){
    if(!nativeBook||!Number.isSafeInteger(leaf)||leaf<1)return;
    const dialog=ensureNativeBook(),token=++nativeBookToken,bid=nativeBook.bid,status=$('.native-book-status',dialog),prev=$('.native-book-prev',dialog),next=$('.native-book-next',dialog);
    status.textContent='Загружаем лист…';prev.disabled=true;next.disabled=true;
    try{
      const page=await state.api.bookPageData(bid,leaf);
      if(token!==nativeBookToken||!dialog.open)return;
      nativeBook.leaf=page.leaf;
      // «Том 1 · стр. 3» as the printed book says; the leaf number only when the edition has no page numbers.
      const parts0=pageParts(page.text),nums=pageNumbers(parts0.body);
      $('.native-book-location',dialog).innerHTML=`<span class="nb-loc-page">${escape(page.printedPage!=null?`${page.volume?(/^\d+$/.test(String(page.volume))?'Том '+page.volume:page.volume)+' · ':''}Страница ${page.printedPage}`:`Лист ${page.leaf}`)}</span>`+(nums.length?`<span class="nb-loc-num">${nums.length===1?'№ хадиса':'№ хадисов'} ${escape(nums.length>3?nums[0]+'–'+nums[nums.length-1]:nums.join(', '))}</span>`:'');
      $('.nb-hadith',dialog).value=nativeBook.mark&&nums.includes(String(nativeBook.mark))?String(nativeBook.mark):(nums[0]||'');
      const tr=$('.native-book-tr',dialog);tr.hidden=true;tr.innerHTML='';
      nativeBook.offset=page.printedPage!=null?page.leaf-page.printedPage:0;nativeBook.page=page.printedPage;nativeBook.volume=page.volume||null;$('.nb-page',dialog).value=page.printedPage!=null?String(page.printedPage):String(page.leaf);
      $('.native-book-headings',dialog).textContent=page.headings.join(' ‹ ');
      const parts=pageParts(page.text);
      $('.native-book-text',dialog).innerHTML=markHadith(escape(parts.body),nativeBook.mark);
      $('.native-book-notes',dialog).innerHTML=parts.notes?`<details class="edition-notes"><summary><span>Сноски страницы</span>${icon('down')}</summary><p lang="ar" dir="rtl">${escape(parts.notes)}</p></details>`:'';
      status.textContent='';$('.native-book-body',dialog).scrollTop=0;
      const anchor=$('.hadith-anchor',dialog);if(anchor)anchor.scrollIntoView({block:'center'});
    }catch(error){if(token===nativeBookToken&&dialog.open)status.textContent='Не удалось открыть этот лист. '+String(error?.message||'Попробуйте ещё раз.');}
    finally{if(token===nativeBookToken&&dialog.open){prev.disabled=nativeBook.leaf<=1;next.disabled=!!nativeBook.last&&nativeBook.leaf>=nativeBook.last;}}
  }
  async function browseCollection(collection) {
    if (!state.api) return;
    if(collection.id?.startsWith('book:')&&collection.bid){openNativeBook(collection.bid,1,collection.title);return;}
    const token = ++state.browseToken;
    $('#library-overview').hidden = true; $('#browse-area').hidden = false; $('#browse-title').textContent = collection.title; $('#browse-count').textContent = ''; $('#more-browse').hidden = true; state.browse = [];
    loading($('#browse-results'),'Открываем сборник','Готовим тексты для чтения');
    try {
      const response = await state.api.browse(collection.id); if (token !== state.browseToken) return;
      if (response.opened) {showLibraryOverview(); return;}
      state.browse = Array.isArray(response.items) ? response.items : []; state.browseShown = 12;
      $('#browse-count').textContent = `${Number.isFinite(Number(response.total)) ? Number(response.total).toLocaleString('ru-RU') : state.browse.length} текстов`;
      if (state.browse.length) {renderCards($('#browse-results'),state.browse,state.browseShown); $('#more-browse').hidden = state.browseShown >= state.browse.length;}
      else empty($('#browse-results'),'Сборник пока не открыт','Тексты этого сборника ещё не доступны для чтения.');
    } catch (error) {if (token !== state.browseToken) return; empty($('#browse-results'),'Не удалось открыть сборник','Попробуем получить тексты ещё раз.','Повторить',() => browseCollection(collection)); console.warn('Muslimoon collection unavailable',error);}
  }
  $('#browse-back').onclick = () => {state.browseToken++; showLibraryOverview();};
  $('#more-browse').onclick = () => {state.browseShown += 12; renderCards($('#browse-results'),state.browse,state.browseShown); $('#more-browse').hidden = state.browseShown >= state.browse.length;};
  async function invokePanel(method,record) {
    if (!state.api) {toast('Библиотека ещё открывается'); return;}
    try {if (typeof state.api[method] !== 'function') throw new Error('Panel is unavailable'); await state.api[method](record);}
    catch (error) {toast('Раздел пока недоступен. Попробуйте позже.'); console.warn('Muslimoon panel unavailable',error);}
  }
  $('#full-library').onclick = () => invokePanel('library');
  async function invokeTool(name,record) {
    $('#assistant-notice').hidden = true;
    if(name==='bookPage'&&record?.bid&&record?.page){openNativeBook(record.bid,record.page,source(record));return;}
    if(name==='assistant'||name==='explain'){openNativeAssistant(record);return;}
    if(name==='notes'){const k=noteKeyOf(record);if(k)openNoteEditor(k.rk,k.label,k.ref);else openNotes();return;}
    if(name==='narrators'){openNarrators(record);return;}
    if(name==='audio'){speakRecord(record);return;}
    if(name==='copy'){const text=[record.arabic,record.russian,source(record)+(record.number?' № '+record.number:'')].filter(Boolean).join('\n\n');
      try{await navigator.clipboard.writeText(text);toast('Скопировано: оригинал, перевод и источник');}catch(_){toast('Не удалось скопировать — разрешите доступ к буферу');}return;}
    if(name==='share'){const n=String(record.number||'').replace(/\D.*$/,''),link=record.kind==='hadith'&&record.collection&&n?'https://t.me/muslimoontt_bot/app?startapp='+(record.collection==='muhaymin'?'m_'+n:'r_'+record.collection+'_'+n):'https://t.me/muslimoontt_bot/app';
      const text=source(record)+(record.number?' № '+record.number:'')+(record.russian?'\n'+cutText(record.russian,300):'');const tg=window.Telegram&&window.Telegram.WebApp;
      try{if(tg&&tg.initData&&tg.openTelegramLink)tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+encodeURIComponent(text));else if(navigator.share)await navigator.share({text,url:link});else{await navigator.clipboard.writeText(text+'\n'+link);toast('Ссылка скопирована');}}catch(_){}return;}
    if(name==='tashkeel'){const on=$('#reader').classList.toggle('no-tashkeel');$$('#reader .reader-arabic').forEach(el=>{if(on){el.dataset.full=el.innerHTML;el.innerHTML=el.innerHTML.replace(/[\u064B-\u065F\u0670\u06D6-\u06ED]/g,'');}else if(el.dataset.full){el.innerHTML=el.dataset.full;delete el.dataset.full;}});
      const b=[...$$('#reader [data-reader-tool="tashkeel"]')].find(x=>x.offsetParent);if(b)b.querySelector('span').textContent=on?'С огласовками':'Без огласовок';return;}
    if(name==='source'){const base=SUNNAH_COM[record.collection];if(base)askLeave(`https://sunnah.com/${base}:${String(record.number).replace(/\D.*$/,'')}`);return;}
    try {
      if (!state.api || typeof state.api.tool !== 'function') throw new Error('Tool unavailable');
      const response = await state.api.tool(name,record);
      if (response === false || response?.ok === false || response?.opened === false || response?.error) throw new Error('Tool did not open');
      if (response?.notice && !response?.opened) {$('#assistant-notice').textContent = String(response.notice); $('#assistant-notice').hidden = false;}
    } catch (_) {
      const message = name === 'chain' ? 'В этом макете конструктор передач сейчас недоступен.' : ['assistant','rag'].includes(name) ? 'В этом макете помощник не ответил. Поиск и чтение источников доступны.' : 'В этом макете инструмент сейчас недоступен. Поиск и чтение источников доступны.';
      // a short message where the person is — not a jump to an empty «Инструменты» page (owner 29.10: «голая страница»)
      toast(message);
    }
  }
  $$('[data-tool]').forEach(button => button.onclick = () => invokeTool(button.dataset.tool));
  const assistantDialog=$('#native-assistant'),assistantInput=$('#native-assistant-input'),assistantMessages=$('#native-assistant-messages');
  // The conversation stays on this device (owner 29.10: «переписка всегда сохраняется»); the phone shows the last 20
  // and brings older ones back by 20 when the person scrolls up, so a long chat does not slow it down.
  const assistantKey='muslimoon_assist',ASSIST_PAGE=20;let assistantBusy=false,assistantShown=ASSIST_PAGE;
  function assistantHistory(){
    try{let raw=localStorage.getItem(assistantKey);if(raw==null){raw=sessionStorage.getItem(assistantKey);if(raw!=null)localStorage.setItem(assistantKey,raw);}
      const rows=JSON.parse(raw||'[]');return Array.isArray(rows)?rows:[];}catch(_){return [];}
  }
  function saveAssistantHistory(rows){try{localStorage.setItem(assistantKey,JSON.stringify(rows.slice(-400)));}catch(_){}}
  // A clean answer: the helper's markdown becomes plain emphasis, quotes and lists; code and web addresses are dropped.
  function chatHtml(raw){
    // «да будет НЕдоволен им Аллах» о сподвижнике — ошибка модели, а не благопожелание (29.10.2026)
    const clean=String(raw||'').replace(/(да\s+будет\s+)недовол/gi,'$1довол').replace(/```[\s\S]*?```/g,'').replace(/^[^\n]*:[ \t]*\n?[ \t]*<?https?:\/\/\S+>?[ \t]*$/gm,'').replace(/\[([^\]\n]+)\]\((?:https?:)?\/\/[^)\s]+\)/g,'$1')
      .replace(/<?https?:\/\/[^\s>)»]+>?/g,'').replace(/[ \t]+$/gm,'').replace(/\n{3,}/g,'\n\n').trim();
    const inline=x=>escape(x).replace(/`([^`]+)`/g,'$1').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/__([^_]+)__/g,'<b>$1</b>')
      .replace(/(^|[\s(«])\*([^*\s][^*]*?)\*(?=[\s.,;:!?»)]|$)/g,'$1<i>$2</i>').replace(/\*\*/g,'');
    const out=[];let kind='',buf=[];
    const flush=()=>{if(buf.length)out.push(kind==='ul'?'<ul>'+buf.map(x=>'<li dir="auto">'+x+'</li>').join('')+'</ul>':kind==='ol'?'<ol>'+buf.map(x=>'<li dir="auto">'+x+'</li>').join('')+'</ol>':kind==='q'?'<blockquote dir="auto">'+buf.join('<br>')+'</blockquote>':'<p dir="auto">'+buf.join('<br>')+'</p>');buf=[];kind='';};
    const add=(k,h)=>{if(k!==kind)flush();kind=k;buf.push(h);};
    for(const line of clean.split('\n')){
      const l=line.trim();let m;
      if(!l||/^([-*_])\1{2,}$/.test(l)){flush();continue;}
      if((m=l.match(/^#{1,6}\s+(.*)$/))){flush();out.push('<p class="chat-h" dir="auto">'+inline(m[1].replace(/\*\*/g,''))+'</p>');continue;}
      if((m=l.match(/^>\s?(.*)$/))){add('q',inline(m[1]));continue;}
      if((m=l.match(/^[-*•]\s+(.*)$/))){add('ul',inline(m[1]));continue;}
      if((m=l.match(/^\d{1,2}[.)]\s+(.*)$/))){add('ol',inline(m[1]));continue;}
      add('p',inline(l));
    }
    flush();return out.join('');
  }
  function chatRow(row){
    if(row.role==='place')return `<div class="native-chat-place" dir="auto">${escape(row.text||'')}</div>`;
    const hits=Array.isArray(row.hits)&&row.hits.length?`<div class="chat-hits"><p class="chat-hits-title">Найдено в книгах приложения</p>${row.hits.map((h,i)=>`<article class="chat-hit"><p class="chat-hit-src">${escape(source(h))}${h.number?' · № '+escape(h.number):''}</p>${h.arabic?`<p class="chat-hit-ar" lang="ar" dir="rtl">${escape(cutText(h.arabic,240))}</p>`:''}${h.russian?`<p class="chat-hit-ru">${escape(cutText(h.russian,340))}</p>`:''}<button type="button" data-chat-hit="${i}">Открыть карточку</button></article>`).join('')}${row.text?'<p class="chat-hits-title chat-hits-note">Пояснение помощника</p>':''}</div>`:'';
    const body=row.role==='user'?escape(row.text||''):hits+chatHtml(row.text||'');
    return `<div class="native-chat-bubble ${row.role==='user'?'native-chat-user':'native-chat-bot native-chat-rich'}">${body}${row.cached?' <small>из памяти</small>':''}${Array.isArray(row.actions)&&row.actions.length?`<div class="native-chat-actions">${row.actions.map(a=>`<button type="button" data-assist-action="${escape(a.id)}" data-assist-arg="${escape(a.arg||'')}">${escape(a.title)}</button>`).join('')}</div>`:''}</div>`;
  }
  function renderAssistant(keepPlace){
    const rows=assistantHistory(),from=Math.max(0,rows.length-assistantShown),before=assistantMessages.scrollHeight-assistantMessages.scrollTop;
    const head=from>0?`<div class="native-chat-older">Выше ещё ${from} — прокрутите, чтобы подгрузить</div>`:rows.length>=40?'<div class="native-chat-older">Беседа сохранена на этом устройстве. В длинной беседе помощник помнит ранние сообщения в сжатом виде.</div>':'';
    assistantMessages.innerHTML=rows.length?head+rows.slice(from).map(chatRow).join(''):'<div class="native-chat-empty">Спросите о хадисе, аяте, слове или теме. Проверяйте ответ по источникам.</div>';
    assistantMessages.style.scrollBehavior='auto';assistantMessages.scrollTop=keepPlace?assistantMessages.scrollHeight-before:assistantMessages.scrollHeight;assistantMessages.style.scrollBehavior='';
  }
  assistantMessages.addEventListener('scroll',()=>{
    if(assistantMessages.scrollTop>40||assistantBusy)return;const total=assistantHistory().length;if(assistantShown>=total)return;
    assistantShown+=ASSIST_PAGE;renderAssistant(true);
  },{passive:true});
  // ── Помощник-агент, экранная часть (owner 29.10, #4296–#4298). Actions come ONLY from this white list; the helper
  // proposes them as buttons and the person taps — nothing runs by itself, nothing reaches the server.
  const BOOKS_RU={bukhari:/бухари/i,muslim:/муслим/i,abudawud:/абу\s*дауд/i,tirmidhi:/тирмизи/i,ibnmajah:/ибн\s*мадж/i,nasai:/насаи/i,malik:/малик|муватт/i,ahmad:/ахмад|муснад/i};
  const ASSIST_ACTIONS={
    fontUp:{title:'Сделать текст крупнее',run:()=>{state.font=Math.min(2,state.font+1);applyFont();toast('Текст: '+$('#font-label').textContent);}},
    fontDown:{title:'Сделать текст мельче',run:()=>{state.font=Math.max(0,state.font-1);applyFont();toast('Текст: '+$('#font-label').textContent);}},
    settings:{title:'Открыть настройки',run:()=>{showView('settings');setTimeout(()=>{const g=$$('.more-group');(g[g.length-1]||g[0])?.scrollIntoView({behavior:'smooth'});},250);}},
    library:{title:'Открыть библиотеку',run:()=>showView('library')},
    favorites:{title:'Избранные книги',run:()=>{showView('library');if(!state.libraryFavOnly){state.libraryFavOnly=true;renderLibrary();}}},
    bookmarks:{title:'Мои закладки',run:()=>showView('bookmarks')},
    openBook:{title:'Открыть книгу',run:arg=>{const c=state.collections.find(x=>x.id===arg);if(c){showView('library');browseCollection(c);}}},
    findBooks:{title:'Найти книги',run:arg=>{showView('library');state.libraryFavOnly=false;$('#catalog-search-mode').value='both';state.librarySearchMode='both';$('#catalog-query').value=arg;state.libraryQuery=arg;state.libraryShown=24;renderLibrary();}},
    search:{title:'Искать',run:arg=>{showView('search');$('#query').value=arg;$('#query').dispatchEvent(new Event('input',{bubbles:true}));performSearch();}},
    quran:{title:'Открыть аят',run:arg=>{showView('search');$('[data-section="quran"]').click();$('#query').value=arg;$('#query').dispatchEvent(new Event('input',{bubbles:true}));performSearch();}},
    theme:{title:'Сменить оттенок',run:()=>{location.href=document.documentElement.dataset.theme==='ice'?'./':'ice.html';}},
    chain:{title:'Конструктор цепей',run:()=>invokeTool('chain',null)},
    openHadith:{title:'Открыть хадис',run:arg=>ASSIST_ACTIONS.search.run(arg)}
  };
  const act=(id,arg,title)=>({id,arg:arg||'',title:title||ASSIST_ACTIONS[id].title});
  // What the person may want, read from their words: only proposals, shown as buttons.
  function intentActions(text){
    const t=String(text||'').toLowerCase(),out=[];
    if(/крупн|больше.*(шрифт|текст)|(шрифт|текст).*больш|увелич|плохо вижу|мелко/.test(t))out.push(act('fontUp'));
    if(/мельч|меньше.*(шрифт|текст)|(шрифт|текст).*меньш|уменьш/.test(t))out.push(act('fontDown'));
    if(/настро/.test(t))out.push(act('settings'));
    if(/избранн/.test(t))out.push(act('favorites'));
    if(/заклад/.test(t))out.push(act('bookmarks'));
    if(/оттен|серебр|золот|лунн/.test(t))out.push(act('theme'));
    if(/конструктор|цепоч|иснад/.test(t))out.push(act('chain'));
    const verse=t.match(/(\d{1,3})\s*[:.]\s*(\d{1,3})/);
    if(verse&&!/хадис/.test(t))out.push(act('quran',verse[1]+':'+verse[2],'Открыть аят '+verse[1]+':'+verse[2]));
    for(const [code,re] of Object.entries(BOOKS_RU)){
      if(!re.test(t))continue;const c=state.collections.find(x=>x.id===code);const num=verse?null:t.match(/(\d{1,5})/);
      if(num)out.push(act('search',`${code} ${num[1]}`,`Найти ${c?shortCollection(c.title):code} №${num[1]}`));
      if(c)out.push(act('openBook',code,'Открыть «'+c.title+'»'));
      const author=String(c?.author||'').split('|')[0].trim();if(author)out.push(act('findBooks',author,'Все книги: '+author));
    }
    if(/книг|библиотек/.test(t)&&!out.some(a=>a.id==='openBook'||a.id==='findBooks'))out.push(act('library'));
    return out.filter((a,i)=>out.findIndex(b=>b.id===a.id&&b.arg===a.arg)===i).slice(0,5);
  }
  // Where the person is now, and what the helper can do right here (first message on each screen).
  // «[[действие:ИМЯ|ПАРАМЕТР]]» из ответа Гермеса → кнопки. Только из белого списка и только если цель существует
  // (книга есть в библиотеке, аят в пределах Корана) — иначе кнопку не показываем (совет Gemini #4301).
  function hermesActions(answer){
    const actions=[];
    const text=String(answer||'').replace(/\[\[\s*действие\s*:\s*([A-Za-z]{2,20})\s*(?:\|\s*([^\]]{0,80}))?\]\]/g,(m,id,arg)=>{
      arg=String(arg||'').trim();const a=ASSIST_ACTIONS[id];if(!a)return '';
      if(id==='openBook'&&!state.collections.some(c=>c.id===arg))return '';
      if(id==='quran'){const v=arg.match(/^(\d{1,3}):(\d{1,3})$/);if(!v||+v[1]<1||+v[1]>114||+v[2]<1||+v[2]>286)return '';}
      if((id==='search'||id==='findBooks'||id==='openHadith')&&!arg)return '';
      if(id==='openHadith'){const m=arg.match(/^([a-z]+)\s+(\d{1,5})$/);const c=m&&state.collections.find(x=>x.id===m[1]);if(!m)return '';
        if(!actions.some(x=>x.id===id&&x.arg===arg))actions.push(act(id,arg,'Открыть: '+(c?shortCollection(c.title):m[1])+' № '+m[2]));return '';}
      const book=id==='openBook'?state.collections.find(c=>c.id===arg):null;
      if(id==='findBooks'){authorChoices(arg).forEach(a=>{if(!actions.some(x=>x.id===a.id&&x.arg===a.arg))actions.push(a);});return '';}
      if(!actions.some(x=>x.id===id&&x.arg===arg))actions.push(act(id,arg,book?'Открыть «'+book.title+'»':id==='search'?'Найти: '+arg:id==='quran'?'Открыть аят '+arg:undefined));
      return '';
    }).replace(/\n{3,}/g,'\n\n').trim();
    return {text,actions};
  }
  // «Книги такого-то»: the name is checked against the catalog's authors. One author — one button with the count;
  // several (ابن حجر → العسقلاني and الهيتمي) — a button for each, at most five, so the person picks (owner 29.10).
  function authorChoices(name){
    const key=catalogFold(name).trim();if(!key)return [];const counts=new Map();
    for(const c of state.collections){const a=String(c.author||'').trim();if(a&&catalogFold(a).includes(key))counts.set(a,(counts.get(a)||0)+1);}
    const exact=[...counts.keys()].find(a=>catalogFold(a).trim()===key);
    const list=exact?[[exact,counts.get(exact)]]:[...counts.entries()].sort((x,y)=>y[1]-x[1]).slice(0,5);
    if(!list.length)return [act('findBooks',name,'Книги: '+name)];
    return list.map(([a,n])=>act('findBooks',a,`Книги: ${a.split('|').pop().trim()} · ${n}`));
  }
  // First words of the helper (owner П-45: «проще — скажи, что ты помощник ИИ, чем помочь; конструктор цепей —
  // для профессионалов, зачем его предлагать»). The greeting is short; `screen` tells the helper where the person is.
  function screenContext(){
    const where=$('#native-book-reader')?.open?`читает книгу «${nativeBook?.title||''}», ${$('.native-book-location')?.textContent||''}`:$('#reader')?.open&&state.reader?`читает ${state.reader.kind==='quran'?'аят '+state.reader.sura+':'+state.reader.ayah:'хадис '+source(state.reader)+' № '+state.reader.number}`:
      ({search:state.section==='quran'?'поиск по Корану':'поиск хадисов',library:'библиотека',bookmarks:'закладки',settings:'раздел «Ещё»'}[state.view]||'приложение');
    const tips=[act('search','дела по намерениям','Хадис о намерениях'),act('quran','2:255','Аят аль-Курси'),act('findBooks','النووي','Книги ан-Навави')];
    return {key:'hello',screen:where,text:'Ас-саляму алейкум! Я ИИ-помощник Muslimoon. Отвечаю по первоисточникам — Корану, хадисам и книгам библиотеки. Чем помочь?\nНе знаете, с чего начать, — нажмите подсказку.',actions:tips};
  }
  function oldScreenContext(){
    if($('#native-book-reader')?.open)return {key:'book:'+(nativeBook?.bid||''),text:`Вы читаете «${nativeBook?.title||'книгу'}», ${$('.native-book-location')?.textContent||''}. Могу: найти страницу или хадис по номеру, рассказать о книге и издании, сделать текст крупнее.`,actions:[act('fontUp')]};
    if($('#reader')?.open)return {key:'reader:'+(state.reader?.id||''),text:'Вы читаете хадис. Могу: объяснить его, найти, где он ещё передаётся, открыть страницу в книге, сделать текст крупнее.',actions:[act('fontUp')]};
    const v=state.view||'search';
    if(v==='library')return {key:'library',text:'Вы в библиотеке (8 589 книг). Могу: найти книгу по названию или автору, открыть избранные, открыть любой из сборников.',actions:[act('favorites'),act('openBook','bukhari','Открыть «Сахих аль-Бухари»')]};
    if(v==='bookmarks')return {key:'bookmarks',text:'Здесь ваши закладки. Могу: найти сохранённое, открыть библиотеку или поиск.',actions:[act('library')]};
    if(v==='settings')return {key:'settings',text:'Здесь инструменты и настройки. Скажите, что поменять — например «сделай текст крупнее» или «смени оттенок».',actions:[act('fontUp'),act('theme')]};
    return {key:'search:'+(state.section||'hadith'),text:state.section==='quran'?'Вы в поиске по Корану. Напишите слово, тему или номер вроде 2:255 — открою аят, объясню слово, найду по корню.':'Вы в поиске хадисов. Напишите тему, слова или «бухари 1» — найду; могу объяснить хадис, термин или помочь настроить поиск.',actions:[act('settings','','Настроить приложение'),act('chain')]};
  }
  const cutText=(t,n)=>{t=String(t||'').replace(/\s+/g,' ').trim();return t.length>n?t.slice(0,n).replace(/\s+\S*$/,'')+'…':t;};
  assistantMessages.addEventListener('click',event=>{
    const hitButton=event.target.closest('[data-chat-hit]');
    if(hitButton){const bubble=hitButton.closest('.native-chat-bubble'),rows=assistantHistory(),shown=rows.slice(Math.max(0,rows.length-assistantShown));
      const index=[...assistantMessages.querySelectorAll('.native-chat-bubble,.native-chat-place')].indexOf(bubble),row=shown[index],hit=row&&row.hits&&row.hits[+hitButton.dataset.chatHit];
      if(hit){assistantDialog.close();openReader(hit);}return;}
    const button=event.target.closest('[data-assist-action]');if(!button)return;const action=ASSIST_ACTIONS[button.dataset.assistAction];if(!action)return;
    assistantDialog.close();action.run(button.dataset.assistArg||'');
  });
  // «Откуда пришёл» — коротко, одной строкой: книга и номер (или аят) и начало текста (owner 29.10).
  function placeOf(record){
    if(!record)return '';const where=record.kind==='quran'?`Коран ${record.sura}:${record.ayah}`:[source(record),record.number?'№ '+record.number:''].filter(Boolean).join(' · ');
    const quote=String(record.russian||record.arabic||'').replace(/\s+/g,' ').trim(),cut=quote.length>70?quote.slice(0,70).replace(/\s+\S*$/,'')+'…':quote;
    return 'Из: '+where+(cut?` · «${cut}»`:'');
  }
  let assistantPlace=null;
  function openNativeAssistant(record){
    const ctx=screenContext(),rows=assistantHistory();assistantShown=ASSIST_PAGE;
    const place=placeOf(record),last=rows[rows.length-1];assistantPlace=record||null;
    if(place){if(!(last&&last.role==='place'&&last.text===place))rows.push({role:'place',text:place,ctx:ctx.key});saveAssistantHistory(rows);}
    else if(!rows.length||[...rows].reverse().find(r=>r.ctx)?.ctx!==ctx.key){rows.push({role:'bot',text:ctx.text,actions:ctx.actions,ctx:ctx.key});saveAssistantHistory(rows);}
    renderAssistant();
    if(!assistantDialog.open)assistantDialog.showModal();assistantMessages.style.scrollBehavior='auto';assistantMessages.scrollTop=assistantMessages.scrollHeight;assistantMessages.style.scrollBehavior='';setTimeout(()=>assistantInput.focus(),30);
  }
  $('#native-assistant-close').onclick=()=>assistantDialog.close();
  // Header that says what this is (owner П-45: «не просто „Помощник“ — серьёзный помощник»), with the session
  // number in small letters; outside Telegram — a plain note that the full helper lives inside Telegram.
  const assistTitle=$('#native-assistant-title');assistTitle.textContent='AI MUSLIMOON';
  const assistSub=document.createElement('p');assistSub.className='native-assistant-sub';assistTitle.after(assistSub);
  const inTelegram=!!(window.Telegram&&window.Telegram.WebApp&&window.Telegram.WebApp.initData);
  function syncAssistHead(){let sid='';try{sid=localStorage.getItem('muslimoon_assist_sid')||'';}catch(_){}
    assistSub.textContent=(inTelegram?'по Корану, хадисам и книгам библиотеки':'вне Телеграма — короткие ответы')+(sid?' · сессия '+sid:'');}
  syncAssistHead();
  if(!inTelegram){const note=document.createElement('p');note.className='native-assistant-outside';note.textContent='Полный помощник работает внутри Телеграма: откройте Muslimoon через бота @muslimoontt_bot.';$('.native-assistant-foot').prepend(note);}

  // ── Мои заметки в новом виде (owner П-45: «заметки точно удобно? красиво?»). Те же заметки, что у прежнего вида:
  // хранятся на устройстве под «muslimoon_notes», ключи те же (h|книга|№, q|сура|аят, free_…).
  const NOTES_KEY='muslimoon_notes';
  const notesLoad=()=>{try{const a=JSON.parse(localStorage.getItem(NOTES_KEY));return Array.isArray(a)?a:[];}catch(_){return [];}};
  const notesSave=a=>{try{localStorage.setItem(NOTES_KEY,JSON.stringify(a.slice(-1000)));return true;}catch(_){toast('Не удалось сохранить заметку');return false;}};
  const noteId=()=>'n'+Date.now().toString(36)+(Date.now()%9973).toString(36);
  const nowStr=()=>{const d=new Date(),p=x=>String(x).padStart(2,'0');return `${p(d.getDate())}.${p(d.getMonth()+1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;};
  function noteKeyOf(record){
    if(!record)return null;
    if(record.kind==='quran'&&record.sura)return {rk:`q|${record.sura}|${record.ayah}`,label:`Коран ${record.sura}:${record.ayah}`,ref:{type:'q',s:record.sura,a:record.ayah}};
    if(record.kind==='hadith'&&record.collection&&record.number){const n=String(record.number).replace(/#.*/,'');
      return record.collection==='muhaymin'?{rk:'m|'+n,label:'аль-Мухаймин № '+n,ref:{type:'m',n}}:{rk:`h|${record.collection}|${n}`,label:`${source(record)} № ${n}`,ref:{type:'h',source:record.collection,num:n}};}
    return null;
  }
  const notesDialog=document.createElement('dialog');notesDialog.className='native-assistant-dialog notes-dialog';notesDialog.setAttribute('aria-labelledby','notes-title');
  notesDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('pen')}</span><h2 id="notes-title">Мои заметки</h2><button type="button" class="native-assistant-close notes-close" aria-label="Закрыть">×</button></header><div class="notes-body"><div class="notes-tools"><input type="search" class="notes-search" placeholder="Поиск по заметкам" aria-label="Поиск по заметкам"><button type="button" class="notes-new">${icon('pen')}<span>Новая</span></button></div><p class="notes-hint">Заметки хранятся только на этом устройстве. К хадису или аяту — «Мои заметки» в его карточке.</p><div class="notes-list"></div></div></div>`;
  document.body.appendChild(notesDialog);
  const noteEditor=document.createElement('dialog');noteEditor.className='leave-dialog note-editor';
  noteEditor.innerHTML='<form method="dialog" class="leave-shell"><h2>Заметка</h2><p class="note-editor-label"></p><textarea class="note-editor-text" rows="6" placeholder="Ваша мысль, пометка, вопрос…"></textarea><div class="leave-actions"><button type="button" class="note-delete">Удалить</button><span class="note-spacer"></span><button type="button" class="leave-stay note-cancel">Отмена</button><button type="button" class="leave-go note-save">Сохранить</button></div></form>';
  document.body.appendChild(noteEditor);
  function renderNotes(){
    const q=notesDialog.querySelector('.notes-search').value.trim().toLowerCase(),all=notesLoad().slice().reverse();
    const list=q?all.filter(n=>`${n.text||''} ${n.label||''}`.toLowerCase().includes(q)):all;
    notesDialog.querySelector('.notes-list').innerHTML=list.length?list.map(n=>`<article class="note-card" data-rk="${escape(n.rk)}">${n.label?`<p class="note-label" dir="auto">${escape(n.label)}</p>`:''}<p class="note-text" dir="auto">${escape(n.text||'')}</p><footer><time>${escape(n.date||'')}</time><span>${n.ref?'<button type="button" data-note-open>Открыть</button>':''}<button type="button" data-note-edit>Изменить</button></span></footer></article>`).join(''):`<div class="native-chat-empty">${all.length?'Ничего не найдено.':'Пока нет заметок. Нажмите «Новая» или откройте хадис и выберите «Мои заметки».'}</div>`;
  }
  function openNotes(){notesDialog.querySelector('.notes-search').value='';renderNotes();if(!notesDialog.open)notesDialog.showModal();}
  function openNoteEditor(rk,label,ref){
    const existing=notesLoad().find(n=>n.rk===rk),text=noteEditor.querySelector('.note-editor-text'),del=noteEditor.querySelector('.note-delete');
    noteEditor.querySelector('.note-editor-label').textContent=label||'Свободная заметка';text.value=existing?existing.text:'';
    del.hidden=!existing;del.textContent='Удалить';delete del.dataset.armed;noteEditor.returnValue='';noteEditor.showModal();setTimeout(()=>text.focus(),40);
    del.onclick=()=>{if(!del.dataset.armed){del.dataset.armed='1';del.textContent='Точно удалить?';return;}
      const a=notesLoad(),i=a.findIndex(n=>n.rk===rk);if(i>=0){a.splice(i,1);notesSave(a);toast('Заметка удалена');}noteEditor.close('deleted');if(notesDialog.open)renderNotes();};
    // Saved right in the tap (the dialog's close event is not something to lean on — it may come late or not at all).
    noteEditor.querySelector('.note-save').onclick=()=>{const a=notesLoad(),i=a.findIndex(n=>n.rk===rk),v=text.value.trim();
      if(!v){if(i>=0){a.splice(i,1);notesSave(a);}}else{const rec={id:existing?existing.id:noteId(),rk,text:v,label:label||'',ref:ref||null,date:nowStr()};if(i>=0)a[i]=rec;else a.push(rec);if(notesSave(a))toast('Заметка сохранена');}
      noteEditor.close('save');if(notesDialog.open)renderNotes();};
    noteEditor.querySelector('.note-cancel').onclick=()=>noteEditor.close('cancel');
  }
  function openNoteRef(ref){if(!ref)return;if(ref.type==='q')ASSIST_ACTIONS.quran.run(ref.s+':'+(ref.a||1));else if(ref.type==='h')ASSIST_ACTIONS.search.run(`${ref.source} ${ref.num}`);else if(ref.type==='m')ASSIST_ACTIONS.search.run('мухаймин '+ref.n);}
  notesDialog.querySelector('.notes-close').onclick=()=>notesDialog.close();
  notesDialog.querySelector('.notes-search').addEventListener('input',renderNotes);
  notesDialog.querySelector('.notes-new').onclick=()=>openNoteEditor('free_'+noteId(),'',null);
  notesDialog.querySelector('.notes-list').addEventListener('click',event=>{const card=event.target.closest('.note-card');if(!card)return;const n=notesLoad().find(x=>x.rk===card.dataset.rk);if(!n)return;
    if(event.target.closest('[data-note-edit]'))openNoteEditor(n.rk,n.label,n.ref);else if(event.target.closest('[data-note-open]')){notesDialog.close();openNoteRef(n.ref);}});
  window.addEventListener('muslimoon-notes',openNotes);

  // ── Передатчики — в новом виде. Итог о каждом — по свидетельствам 48 муʿтабаров (владелец 29.10: «48 мутабаров дают
  // два свидетельства, чтобы передатчик был достоверным, а не Ибн Хаджар»); Ибн Хаджар и аз-Захаби — справочно, не в
  // счёт. Цепь нарисована от собирателя к Пророку ﷺ, между звеньями — как передано (حدثنا, أخبرنا, عن…).
  const narrDialog=document.createElement('dialog');narrDialog.className='native-assistant-dialog narr-dialog';
  narrDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('book')}</span><h2>Передатчики</h2><button type="button" class="native-assistant-close narr-close" aria-label="Закрыть">×</button></header><div class="notes-body narr-body"></div></div>`;
  document.body.appendChild(narrDialog);narrDialog.querySelector('.narr-close').onclick=()=>narrDialog.close();
  const VERDICT_RU={sahabi:'сподвижник',sound:'надёжный',mixed:'спорный',weak:'слабый',rejected:'отвергается',unknown:'надёжность не установлена',none:'свидетельств в базе нет'};
  const FORM_RU={TH:'рассказал нам — слышал',THi:'рассказал мне — слышал лично',AKH:'сообщил нам — чтение шейху',AKHi:'сообщил мне — чтение шейху',ANB:'известил — иджаза',SAM:'я слышал — явное слышание',AN:'от — без уточнения, как получил',ANN:'что — без уточнения',QAL:'сказал',NA:'нам — сокращённо'};
  const COLLECTOR={bukhari:'البخاري',muslim:'مسلم',abudawud:'أبو داود',tirmidhi:'الترمذي',nasai:'النسائي',ibnmajah:'ابن ماجه',malik:'مالك',ahmad:'أحمد',darimi:'الدارمي'};
  const narrLink=(via,mud)=>via&&via.ar?`<div class="chain-link chain-${via.cls==='S'||via.cls==='Q'?'heard':via.cls==='A'?'an':'other'}" title="${escape(via.tip||'')}"><span class="chain-line"></span><span class="chain-form"><b lang="ar" dir="rtl">${escape(via.ar)}</b><small>${escape(FORM_RU[via.form]||via.tip||'')}</small></span>${mud&&via.cls==='A'?'<span class="chain-flag">мудаллис передаёт через «عن»</span>':''}</div>`:'<div class="chain-link chain-other"><span class="chain-line"></span></div>';
  // «مالك بن أنس بن مالك بن أبي عامر …» → three links of the lineage, the rest in the tooltip
  const shortNasab=t=>{const parts=String(t||'').split(/\s+بن\s+/);return parts.length>3?parts.slice(0,3).join(' بن ')+' …':String(t||'');};
  async function openNarrators(record){
    const body=narrDialog.querySelector('.narr-body');body.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Разбираю цепочку</span></div>';
    if(!narrDialog.open)narrDialog.showModal();
    let full=record;if(!full.arabic&&state.api){try{full={...record,...(await state.api.read(record))};}catch(_){}}
    if(!full.arabic){body.innerHTML='<p class="notes-hint">У этой записи нет арабского текста с цепочкой — разобрать передатчиков не из чего.</p>';return;}
    let items=[],how='',toProphet=null;try{const r=await state.api.narrators(full.arabic,full.collection,full.number);items=r.items||[];how=r.how||'';toProphet=r.toProphet||null;}catch(_){}
    if(!items.length){body.innerHTML='<p class="notes-hint">Цепочку передатчиков из этого текста выделить не удалось.</p>';return;}
    const byName=how!=='chain';
    const cnt=k=>items.filter(n=>n.verdict&&n.verdict.kind===k).length,good=cnt('sound')+cnt('sahabi'),bad=cnt('weak')+cnt('rejected');
    const anMud=items.filter((n,i)=>n.mudallis&&items[i+1]&&items[i+1].via&&items[i+1].via.cls==='A').length;
    const collector=COLLECTOR[full.collection]||'';
    const summary=`<div class="chain-summary"><b>${items.length} ${items.length===1?'звено':items.length<5?'звена':'звеньев'}</b><span class="vs-sound">надёжных ${good}</span>${cnt('mixed')?`<span class="vs-mixed">спорных ${cnt('mixed')}</span>`:''}${bad?`<span class="vs-weak">слабых ${bad}</span>`:''}${cnt('unknown')+cnt('none')?`<span class="vs-unknown">не установлено ${cnt('unknown')+cnt('none')}</span>`:''}${anMud?`<span class="vs-mixed">мудаллис с «عن»: ${anMud}</span>`:''}</div>`
      +'<p class="chain-rule">Надёжность — по свидетельствам 48 муʿтабаров: нужно два подтверждения (توثيق), «в Сахихайн» без тяжкого джарха — тоже два. Ибн Хаджар и аз-Захаби — поздние своды, в счёт не идут. Это оценка звеньев, а не приговор хадису.</p>';
    const node=(n,i)=>{const v=n.verdict||{kind:'none'},kind=byName&&v.kind!=='sahabi'?'muted':v.kind;
      // «ثقة — надёжный (توثيق ≥2 муʿтабаров)» → the Arabic term into the badge, the reason on its own line
      const term=v.kind==='sahabi'?'صحابي':String(v.v||'').split(' — ')[0].trim(),reason=v.kind==='sahabi'?'الصحابة عدول — сподвижники надёжны по единогласию учёных (иджма)':((String(v.v||'').match(/\(([^()]*)\)\s*$/)||[])[1]||'');
      const why=v.muts&&v.muts.length?`<details class="narr-why"><summary>Кто из 48 сказал</summary>${v.muts.map(m=>`<p lang="ar" dir="rtl"><b>${escape(m[0])}:</b> ${escape(m[1])}</p>`).join('')}</details>`:'';
      const late=(n.hajar||n.dhahabi)?`<p class="narr-late">Справочно, не в счёт: ${n.hajar?`Ибн Хаджар — <b lang="ar" dir="rtl">${escape(n.hajar)}</b>`:''}${n.hajar&&n.dhahabi?' · ':''}${n.dhahabi?`аз-Захаби — <b lang="ar" dir="rtl">${escape(n.dhahabi)}</b>`:''}</p>`:'';
      const counts=v.kind==='sahabi'?'':v.kind==='none'?'':`<span class="narr-count">توثيق <b>${v.nT}</b> из 48${v.sahihayn?' · в Сахихайн':''}${v.nJ?` · джарх <b>${v.nJ}</b>`:''}</span>`;
      return `<article class="narr-row narr-${kind}"><span class="narr-step">${i+1}</span><div class="narr-main"><p class="narr-name" lang="ar" dir="rtl" title="${escape(n.full||n.name)}">${escape(shortNasab(n.full||n.name))}</p>`
        +`${(n.kunya||n.nisba)?`<p class="narr-sub" lang="ar" dir="rtl">${escape([n.kunya,n.nisba].filter(Boolean).join(' · '))}</p>`:''}`
        +`${n.death?`<p class="narr-meta">ум. ${escape(n.death)}${n.tabaqa?' · табака '+escape(n.tabaqa):''}</p>`:''}`
        +(n.id?`<p class="narr-verdict"><span class="narr-badge">${escape(VERDICT_RU[v.kind]||'')}${term?` <bdi lang="ar">${escape(term)}</bdi>`:''}</span>${counts}</p>${reason?`<p class="narr-v">Основание: <bdi>${escape(reason)}</bdi></p>`:''}${v.note?`<p class="narr-note">${escape(v.note)}</p>`:''}${why}${late}`:'<p class="narr-meta">в нашей базе не найден</p>')
        +`${n.mudallis?`<p class="narr-note">Отмечен как мудаллис${n.mudallis?' ('+escape(n.mudallis)+')':''}: его «عن» без явного слышания требует проверки.</p>`:''}`
        +`</div>${n.id?`<button type="button" class="narr-fav${favNarrators().some(f=>String(f.id)===String(n.id))?' on':''}" data-narr-fav="${i}" aria-label="В избранные передатчики">${icon('star')}</button>`:''}</article>`;};
    body.innerHTML=`<p class="notes-hint">${escape(source(full))}${full.number?' · № '+escape(full.number):''} · от собирателя к Пророку ﷺ</p>`
      +(byName?'<p class="narr-warn">Готовой цепочки для этого хадиса в базе нет: передатчики определены по написанию имён — у тёзок возможна путаница, итог сверяйте.</p>':'')
      +summary
      +`<div class="chain-flow">`
      +(collector?`<div class="chain-end"><span lang="ar" dir="rtl">${escape(collector)}</span><small>собиратель</small></div>`:'')
      +items.map((n,i)=>(collector||i?narrLink(n.via,i?items[i-1].mudallis:false):'')+node(n,i)).join('')
      +narrLink(toProphet,false)+`<div class="chain-end chain-prophet"><span lang="ar" dir="rtl">رسول الله ﷺ</span><small>Пророк</small></div></div>`;
    body.onclick=e=>{const b=e.target.closest('[data-narr-fav]');if(!b)return;const on=toggleFavNarrator(items[+b.dataset.narrFav]);b.classList.toggle('on',on);toast(on?'Передатчик в избранном — он в «Закладках»':'Убрано из избранного');};
  }
  // ── Озвучить — голосом самого телефона (как в прежнем виде): арабский, если в телефоне есть арабский голос, иначе перевод.
  function speakRecord(record){
    const synth=window.speechSynthesis;if(!synth||typeof SpeechSynthesisUtterance==='undefined'){toast('Озвучка на этом телефоне недоступна');return;}
    if(synth.speaking||synth.pending){synth.cancel();toast('Озвучка остановлена');return;}
    const voices=synth.getVoices()||[],arVoice=voices.find(v=>/^ar/i.test(v.lang)),useAr=!!(arVoice&&record.arabic),text=String(useAr?record.arabic:(record.russian||record.arabic||'')).replace(/\s+/g,' ').slice(0,4000);
    if(!text){toast('Нечего озвучить');return;}
    const u=new SpeechSynthesisUtterance(text);u.lang=useAr?'ar-SA':(record.russian?'ru-RU':'ar-SA');if(useAr)u.voice=arVoice;u.rate=.95;synth.speak(u);
    toast(useAr?'Озвучиваю арабский текст — нажмите ещё раз, чтобы остановить':record.russian?'Арабского голоса в телефоне нет — озвучиваю перевод':'Озвучиваю — нажмите ещё раз, чтобы остановить');
  }

  // ── «Назад» всегда под рукой (owner П-45): кнопка «назад» Телеграма закрывает верхнее окно, иначе возвращает к поиску.
  const tgBack=window.Telegram&&window.Telegram.WebApp&&window.Telegram.WebApp.BackButton;
  function syncBack(){if(!tgBack||!inTelegram)return;const need=!!document.querySelector('dialog[open]')||state.view!=='search';try{need?tgBack.show():tgBack.hide();}catch(_){}}
  if(tgBack&&inTelegram){try{tgBack.onClick(()=>{const open=[...document.querySelectorAll('dialog[open]')];if(open.length)open[open.length-1].close();else showView('search');syncBack();saveSpot();});}catch(_){}}
  new MutationObserver(()=>{syncBack();saveSpot();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});

  // ── Вернуться туда, где был (owner П-45: «при повторном включении — в последнее открытое, даже в чат с помощником»).
  const SPOT_KEY='muslimoon.spot';let spotRestored=false;
  function saveSpot(){if(!spotRestored)return;try{localStorage.setItem(SPOT_KEY,JSON.stringify({t:Date.now(),view:state.view,section:state.section,q:$('#query').value,mode:state.mode,ai:!!state.aiMode,
    chat:assistantDialog.open,notes:notesDialog.open,reader:$('#reader')?.open&&state.reader?state.reader:null}));}catch(_){}}
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')saveSpot();});
  window.addEventListener('pagehide',saveSpot);
  async function restoreSpot(){
    let s=null;try{s=JSON.parse(localStorage.getItem(SPOT_KEY)||'null');}catch(_){}
    try{
      if(!s||Date.now()-s.t>7*864e5)return;
      if(s.section==='quran')$('[data-section="quran"]')?.click();
      if(s.mode&&Array.from($('#mode-select').options).some(o=>o.value===s.mode)){$('#mode-select').value=s.mode;filtersChanged();}
      if(s.view&&s.view!=='search')showView(s.view);
      if(s.ai)setAiMode(true);
      if(s.q&&!s.ai){$('#query').value=s.q;syncPlaceholder();if(s.view==='search'||!s.view)performSearch();}else if(s.q){$('#query').value=s.q;syncPlaceholder();}
      if(s.reader&&s.reader.id)openReader(s.reader);
      if(s.notes)openNotes();
      if(s.chat)openNativeAssistant();
    }finally{spotRestored=true;syncBack();}
  }
  window.addEventListener('muslimoon-native-assistant',()=>openNativeAssistant());
  $('#native-assistant-form').onsubmit=async event=>{
    event.preventDefault();const question=assistantInput.value.trim();if(!question||assistantBusy)return;
    if(!state.api){toast('Помощник ещё подключается');return;}
    assistantBusy=true;$('#native-assistant-send').disabled=true;assistantInput.value='';
    const history=assistantHistory();history.push({role:'user',text:question});const proposals=intentActions(question);saveAssistantHistory(history);assistantShown=Math.max(assistantShown,ASSIST_PAGE);renderAssistant();
    const pending=document.createElement('div');pending.className='native-chat-bubble native-chat-bot native-chat-pending';
    pending.innerHTML='<span class="think-dots" aria-hidden="true"><i></i><i></i><i></i></span><span class="think-text">Думаю</span>';assistantMessages.appendChild(pending);assistantMessages.scrollTop=assistantMessages.scrollHeight;
    const phases=[[7000,'Собираю ответ'],[18000,'Ещё немного']].map(([ms,t])=>setTimeout(()=>{const x=pending.querySelector('.think-text');if(x)x.textContent=t;},ms));
    try{const ctx=screenContext();if(assistantPlace)ctx.text=placeOf(assistantPlace).replace(/^Из: /,'Человек пришёл из: ')+'. '+ctx.text;
      // Hermes is open only to the owner while on trial (#4303); everyone else quietly gets the previous helper.
      // The first question after coming from a hadith or ayah carries its text (the server takes 800 characters).
      let asked=question;if(assistantPlace&&!assistantPlace._sent){const room=780-question.length-60,body=String(assistantPlace.russian||assistantPlace.arabic||'').replace(/\s+/g,' ').trim();
        if(room>120&&body)asked=`[${placeOf(assistantPlace).replace(/^Из: /,'').replace(/ · «.*$/,'')}. Текст: ${body.slice(0,room)}] Вопрос: ${question}`;assistantPlace._sent=true;}
      let hits=[];
      if(!assistantPlace&&/хадис|сунн|бухари|муслим|абу\s*дауд|тирмизи|насаи|ибн\s*мадж|пророк|посланник|ﷺ|حديث|رسول/i.test(question)){
        try{const found=await Promise.race([state.api.search({query:question,category:'all',collection:'all',section:'hadith',mode:'rag',scope:[]}),new Promise(r=>setTimeout(()=>r(null),15000))]);
          hits=(found&&Array.isArray(found.items)?found.items:[]).slice(0,3).map(h=>({id:h.id,kind:h.kind,collection:h.collection,title:h.title,number:h.number,arabic:h.arabic,russian:h.russian}));}catch(_){}
      }
      const opora=hits.map((h,i)=>`${i+1}) ${source(h)} № ${h.number} [openHadith|${h.collection} ${String(h.number).replace(/\D.*$/,'')}]: ${cutText(h.arabic,300)} — ${cutText(h.russian,380)}`).join('\n');
      const response=await state.api.hermesAsk(asked,'человек: '+(ctx.screen||ctx.text),Object.keys(ASSIST_ACTIONS),opora).catch(async error=>{
        if(!/в проверке/.test(String(error?.message||'')))throw error;
        const old=await state.api.assistantAsk(asked);return {answer:old.answer,model:''};});
      if(response.session){try{localStorage.setItem('muslimoon_assist_sid',String(response.session));}catch(_){}syncAssistHead();}
      const parsed=hermesActions(response.answer);const next=assistantHistory();
      // The helper's own buttons first, then the quick ones read from the question — one row, without repeats.
      const buttons=parsed.actions.concat(proposals.filter(a=>!parsed.actions.some(b=>b.id===a.id&&b.arg===a.arg))).slice(0,6);
      next.push({role:'bot',text:parsed.text.replace(/модель ИИ \(Muslimoon\)/,'модель ИИ: '+(response.model||'Muslimoon')),actions:buttons,hits});saveAssistantHistory(next);}
    catch(error){const next=assistantHistory();next.push({role:'bot',text:error?.name==='AbortError'?'Помощник долго не отвечает. Попробуйте позже.':String(error?.message||'Связь с помощником недоступна.'),actions:proposals});saveAssistantHistory(next);}
    finally{phases.forEach(clearTimeout);assistantBusy=false;$('#native-assistant-send').disabled=false;renderAssistant();}
  };
  function updateReaderSave() {
    const saved = state.reader && isSaved(state.reader); $('#reader-save').classList.toggle('saved',!!saved); $('#reader-save').setAttribute('aria-pressed',String(!!saved)); $('#reader-save').setAttribute('aria-label',saved ? 'Убрать из закладок' : 'Сохранить в закладки');
  }
  $('#reader-save').onclick = () => {if (!state.reader) return; toggleSave(state.reader); updateReaderSave(); renderAllBookmarkStates();};
  const noteNumber = number => String(number).replace(/[٠-٩]/g,c => String(c.charCodeAt(0)-1632)).replace(/[۰-۹]/g,c => String(c.charCodeAt(0)-1776));
  function textWithNotes(text,record) {
    let output = '', last = 0;
    const raw = String(text || ''), pattern = /\[\s*([0-9٠-٩۰-۹]+)\s*\]/g;
    for (const match of raw.matchAll(pattern)) {output += escape(raw.slice(last,match.index)); if (noteText(record,noteNumber(match[1]))) output += `<sup class="footnote-marker"><button type="button" data-note="${escape(noteNumber(match[1]))}" aria-label="Примечание ${escape(match[1])}" aria-controls="reader-note">${escape(match[1])}</button></sup>`; last = match.index + match[0].length;}
    return output + escape(raw.slice(last));
  }
  function noteText(record,number) {
    const notes = record.footnotes;
    let value;
    if (Array.isArray(notes)) {
      value = notes.find(entry => entry && typeof entry === 'object' && noteNumber(entry.number ?? entry.id ?? entry.marker ?? '') === String(number));
      if (value === undefined && !notes.some(entry => entry && typeof entry === 'object' && (entry.number != null || entry.id != null || entry.marker != null))) value = notes[Number(number)-1];
    } else if (notes && typeof notes === 'object') value = notes[number] ?? notes[`[${number}]`];
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    if (value && typeof value === 'object') {const text = value.text ?? value.content ?? value.body ?? value.note; if (typeof text === 'string') return text;}
    return '';
  }
  // Edition notes split off the matn by the bridge: a trailing grade becomes its own line, the rest folds away.
  const GRADE_WORDS = 'حسن صحيح|صحيح لغيره|حسن لغيره|ضعيف جدا|صحيح|حسن|ضعيف|موضوع|منكر|شاذ|باطل';
  const EDITION_GRADE = new RegExp(`(?:^|[\\s.\\]»])\\s*((?:(?:سنده|إسناده)\\s+)?(?:${GRADE_WORDS})(?:\\s+[^\\s.\\[\\]]+){0,4})\\s*\\.?\\s*$`);
  // The next chapter's heading glued after the grade («…صحيح بَابُ مَتَى…», «…صحيح فَضْلُ عَلِيٍّ…»): headings are
  // vocalised, editor's notes are not — that is the line between them (Ibn Majah: 1 298 such headings).
  const EDITION_CHAPTER = /(?:^|\s)((?:بَابُ|بَابٌ|بَابِ|كِتَابُ|كِتَابٌ)\s[\s\S]*)$/;
  const EDITION_HEADING_AFTER_GRADE = new RegExp(`((?:${GRADE_WORDS})(?:\\s+[^\\s\\u064B-\\u0652]+){0,3})\\s+(\\S*[\\u064B-\\u0652][\\s\\S]*)$`);
  function editionNotes(record) {
    const notes = Array.isArray(record.editionNotes) ? record.editionNotes.filter(note => typeof note === 'string' && note.trim()) : [];
    if (!notes.length) return '';
    const grades = [], others = [], chapters = [];
    for (let note of notes) {
      const chapter = EDITION_CHAPTER.exec(note) || EDITION_HEADING_AFTER_GRADE.exec(note);
      if (chapter) {const heading = chapter[chapter.length-1].trim(); chapters.push(heading); note = note.slice(0, note.length - heading.length).trim(); if (!note) continue;}
      const match = EDITION_GRADE.exec(note), sep = match && /^[\s.\]»]/.test(match[0]) ? 1 : 0;
      const head = match ? note.slice(0,match.index+sep).trim() : '', before = head.replace(/[\s.]+$/,'').trim();
      // Only a grade that stands alone or after a closed note («…] . صحيح», «…الذهبي. ضعيف»): never cut the tail off a sentence.
      if (match && (!before || /[\].]$/.test(head))) {grades.push(match[1].trim()); if (before) others.push(before);}
      else others.push(note.trim());
    }
    // No caption (owner 29.10: «и так понятно»); the colour carries the degree, weak ones lean red.
    const degree = g => /^(?:(?:سنده|إسناده)\s+)?(?:ضعيف|موضوع|منكر|شاذ|باطل)/.test(g) ? 'weak' : /^(?:(?:سنده|إسناده)\s+)?حسن(?! صحيح)/.test(g) ? 'good' : 'sound';
    const grade = grades.length ? `<p class="edition-grade">${grades.map(g => `<b class="grade-${degree(g)}" lang="ar" dir="rtl">${escape(g)}</b>`).join('')}</p>` : '';
    const more = others.length ? `<details class="edition-notes"><summary><span>Примечания издания · ${others.length}</span>${icon('down')}</summary>${others.map(note => `<p lang="ar" dir="rtl">${escape(note.replace(/^\[ش\s*/,'').replace(/\]\s*$/,''))}</p>`).join('')}</details>` : '';
    const next = chapters.map(heading => `<p class="edition-chapter"><span>Следующая глава в книге</span><b lang="ar" dir="rtl">${escape(heading)}</b></p>`).join('');
    return grade + more + next;
  }
  function readerArabic(record) {
    return readerArabicText(record) + editionNotes(record);
  }
  function isnadMarkOn() {try {return localStorage.getItem('muslimoon.isnadMark') !== '0';} catch (_) {return true;}}
  function readerArabicText(record) {
    const parts = Array.isArray(record.parts) ? record.parts.filter(part => part && typeof part.text === 'string' && part.text.trim()) : [];
    if (!parts.length) return record.arabic ? `<div class="reader-arabic" lang="ar" dir="rtl">${textWithNotes(record.arabic,record)}</div>` : '<p class="reader-missing">Арабский текст для этой записи пока недоступен.</p>';
    // The original as one text (owner 29.10: «зачем скрыл иснад? пусть оригинал будет, просто выделяй»): the chain
    // quieter, the words of the hadith brighter; «Выделять иснад и матн» in «Ещё» turns the difference off.
    const roles = new Set(parts.map(part => part.role)), mark = isnadMarkOn() && roles.has('isnad') && roles.has('matn');
    const legend = mark ? '<div class="parts-legend" aria-label="Разделы текста"><span class="legend-isnad">иснад — приглушённо</span><span>матн — ярко</span></div>' : '';
    const flow = parts.filter(part => part.role !== 'comment').map(part => `<span class="flow-${escape(part.role || 'text')}">${textWithNotes(part.text,record)}</span>`).join(' ');
    const comments = parts.filter(part => part.role === 'comment').map(part => `<section class="comment-block"><p class="part-label">${escape(part.label || 'Комментарий составителя')}</p><div class="reader-arabic" lang="ar" dir="rtl">${textWithNotes(part.text,record)}</div></section>`).join('');
    return legend + `<div class="reader-arabic reader-flow${mark ? ' mark-parts' : ''}" lang="ar" dir="rtl">${flow}</div>` + comments;
  }
  function mountQuranWords(record){
    const part=$('.arabic-part',$('#reader-body')),text=$('.reader-arabic',part);if(!part||!text||!record.arabic)return;
    const toolbar=document.createElement('div');toolbar.className='quran-word-toolbar';
    toolbar.innerHTML='<button type="button" class="quran-word-toggle" aria-pressed="false">Разобрать слова</button><span class="quran-word-hint">Нажмите кнопку, затем слово</span>';
    const panel=document.createElement('aside');panel.className='quran-word-info';panel.hidden=true;panel.setAttribute('aria-live','polite');
    part.insertBefore(toolbar,text);part.appendChild(panel);
    const button=$('.quran-word-toggle',toolbar),hint=$('.quran-word-hint',toolbar);let data=null,busy=false,enabled=false;
    let onDisable=()=>{};
    button.onclick=async()=>{
      if(busy)return;
      if(enabled){onDisable();enabled=false;button.setAttribute('aria-pressed','false');button.textContent='Разобрать слова';text.textContent=record.arabic;panel.hidden=true;hint.textContent='Нажмите кнопку, затем слово';return;}
      if(!data){
        const token=state.readerToken;busy=true;button.disabled=true;hint.textContent='Загружаем сведения о словах…';
        try{data=await state.api.quranWordData(Number(record.sura),Number(record.ayah),record.arabic);}
        catch(e){if(token===state.readerToken)hint.textContent='Данные слов недоступны. Попробуйте ещё раз.';return;}
        finally{busy=false;button.disabled=false;}
        if(token!==state.readerToken||!$('#reader').open)return;
      }
      enabled=true;button.setAttribute('aria-pressed','true');button.textContent='Завершить разбор';hint.textContent=data.aligned?'Нажмите на слово':'Нажмите на слово; пословный перевод не сопоставлен';
      text.replaceChildren();
      for(const item of data.tokens){
        if(!item.word){text.appendChild(document.createTextNode(item.text));continue;}
        const word=document.createElement('button');word.type='button';word.className='quran-word';word.lang='ar';word.textContent=item.text;
        word.onclick=()=>{
          text.querySelectorAll('.quran-word').forEach(w=>w.classList.remove('selected'));word.classList.add('selected');
          const refs=Array.isArray(item.references)?item.references:[];
          panel.hidden=false;panel.innerHTML=`<div class="quran-word-name" lang="ar" dir="rtl">${escape(item.text)}</div><dl><dt>Пословный перевод</dt><dd>${escape(item.translation||'Не сопоставлен в доступных данных')}</dd><dt>Корень</dt><dd lang="ar" dir="rtl">${escape(item.root||'Не найден')}</dd><dt>Грамматика</dt><dd>${escape(item.grammar||'Не определена')}</dd></dl><p class="quran-word-source">Перевод сопоставлен по порядку слов; корень и грамматика — по индексу словоформ. Возможные неоднозначности требуют проверки в контексте.</p>${refs.length?`<details><summary>Места этого корня в Коране · ${refs.length}</summary><div class="quran-root-refs">${refs.filter(ref=>/^\d{1,3}:\d{1,3}$/.test(ref)).map(ref=>`<button type="button" data-quran-ref="${escape(ref)}">${escape(ref)}</button>`).join('')}</div></details>`:''}`;
          panel.querySelectorAll('[data-quran-ref]').forEach(ref=>ref.onclick=async()=>{const [s,a]=ref.dataset.quranRef.split(':').map(Number),token=state.readerToken;ref.disabled=true;try{const verse=await state.api.quranVerse(s,a);if(token===state.readerToken&&$('#reader').open)openReader(verse);}catch(_){toast('Не удалось открыть аят');}finally{ref.disabled=false;}});
        };
        text.appendChild(word);
      }
    };
    return {enable:async()=>{if(!enabled)await button.onclick();return enabled;},words:()=>Array.from(text.querySelectorAll('.quran-word')),onDisable:fn=>{onDisable=fn;}};
  }
  let stopReaderAudio=()=>{},quranContinuous=false;
  function mountQuranAudio(record,words,autoAudio){
    if(!words||!record.sura||!record.ayah)return;
    const part=$('.arabic-part',$('#reader-body')),bar=document.createElement('div');
    bar.className='quran-audio-controls';
    bar.innerHTML='<button type="button" class="quran-audio-play">▶ Слушать аят</button><button type="button" class="quran-audio-sync">♫ Подсветка слов · аль-Хусари</button><label class="quran-continuous"><input type="checkbox"> Читать дальше по аятам</label><p class="quran-audio-status" aria-live="polite">Выберите воспроизведение или чтение с подсветкой.</p>';
    part.insertBefore(bar,$('.quran-word-toolbar',part));
    const play=$('.quran-audio-play',bar),sync=$('.quran-audio-sync',bar),status=$('.quran-audio-status',bar);
    const continuous=$('.quran-continuous input',bar);continuous.checked=quranContinuous;continuous.onchange=()=>{quranContinuous=continuous.checked;};
    let audio=null,generation=0,mode='',finishing=false;
    function clearHighlight(){words.words().forEach(w=>w.classList.remove('audio-current'));}
    function stop(message){generation++;finishing=false;if(audio){audio.pause();audio.removeAttribute('src');audio.load();audio=null;}mode='';clearHighlight();play.textContent='▶ Слушать аят';sync.textContent='♫ Подсветка слов · аль-Хусари';if(message)status.textContent=message;}
    stopReaderAudio=stop;words.onDisable(()=>{if(mode==='sync')stop('Подсветка остановлена.');});
    async function finish(id,reader,which){
      if(id!==generation||finishing)return;finishing=true;
      if(!quranContinuous){stop('Аят завершён.');return;}
      if(audio){audio.pause();audio.removeAttribute('src');audio.load();audio=null;}
      clearHighlight();status.textContent='Переходим к следующему аяту…';
      try{
        const next=await state.api.quranNeighbor(Number(record.sura),Number(record.ayah),1);
        if(id!==generation||reader!==state.readerToken||!$('#reader').open)return;
        if(!quranContinuous){stop('Аят завершён.');return;}
        if(!next){stop('Достигнут последний аят Корана.');return;}
        openReader(next,{autoAudio:which});
      }catch(_){if(id===generation)stop('Не удалось загрузить следующий аят.');}
    }
    async function start(which){
      if(mode===which){stop('Воспроизведение остановлено.');return;}
      stop();const id=++generation,reader=state.readerToken;mode=which;(which==='sync'?sync:play).textContent='■ Остановить';status.textContent='Подготавливаем аудио…';
      try{
        let info;
        if(which==='sync'){
          if(!await words.enable())throw Error('Не удалось загрузить слова аята');
          if(id!==generation||reader!==state.readerToken)return;
          info=await state.api.quranTimedAudio(Number(record.sura),Number(record.ayah),words.words().length);
        }else info=await state.api.quranAudioInfo(Number(record.sura),Number(record.ayah));
        if(id!==generation||reader!==state.readerToken)return;
        const player=new Audio();audio=player;player.preload='metadata';player.src=info.url;
        player.addEventListener('error',()=>{if(id===generation)stop('Аудио недоступно. Проверьте соединение и попробуйте снова.');});
        player.addEventListener('ended',()=>finish(id,reader,which));
        if(which==='sync'){
          await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Аудио не отвечает')),20000);player.addEventListener('loadedmetadata',()=>{clearTimeout(timer);resolve();},{once:true});player.addEventListener('error',()=>{clearTimeout(timer);reject(Error('Аудио недоступно'));},{once:true});});
          if(id!==generation||reader!==state.readerToken)return;
          player.currentTime=info.start/1000;
          player.addEventListener('timeupdate',()=>{
            if(id!==generation)return;
            const now=player.currentTime*1000;if(now>=info.end){finish(id,reader,which);return;}
            const segment=info.segments.find(([,from,to])=>now>=from&&now<to),index=segment?segment[0]-1:-1;
            words.words().forEach((word,i)=>word.classList.toggle('audio-current',i===index));
          });
        }
        await player.play();if(id!==generation)return;
        (which==='sync'?sync:play).textContent='■ Остановить';
        status.textContent='Чтец: '+info.reciter+(info.fallback?' · запасной чтец для этой суры':'')+(which==='sync'?' · подсветка по временным меткам':'');
      }catch(error){if(id===generation)stop((error&&error.message?error.message:'Не удалось воспроизвести аудио')+'. Попробуйте ещё раз.');}
    }
    play.onclick=()=>start('play');sync.onclick=()=>start('sync');
    if(autoAudio==='play'||autoAudio==='sync')start(autoAudio);
  }
  function renderReader(record,options={}) {
    const russian = String(record.russian || '').trim(), title = String(record.title || '').trim(), bookSource = record.kind==='quran'&&title?title:source(record), number = record.kind==='quran'&&record.ayah?'аят '+record.ayah:recordNumber(record);
    const distinctTitle = title && fold(title) !== fold(bookSource).trim();
    $('#reader-body').setAttribute('aria-busy','false');
    $('#reader-body').innerHTML = `<div class="reader-source"><span class="book-seal">${icon(record.kind === 'quran' ? 'quran' : 'book')}</span>${sourceLine(bookSource,record.kind==='quran'?'':arabicTitleOf(record),number,'reader-source-text')}</div>${record.kind==='hadith'&&!record.isExcerpt&&record.collection?`<div class="reader-modes" role="group" aria-label="Как читать"><button type="button" class="reader-mode active" aria-pressed="true">Хадис</button><button type="button" class="reader-mode" id="reader-open-page" aria-pressed="false">Страница в книге</button><button type="button" class="text-button reader-about" id="reader-about">О книге</button></div>`:''}<h1 id="reader-title"${distinctTitle ? '' : ' class="visually-hidden"'}>${escape(distinctTitle ? title : `${bookSource}${number ? ' · '+number : ''}`)}</h1><div class="reader-translation-control"><button type="button" id="translation-toggle" class="translation-toggle active" aria-pressed="true" aria-controls="reader-translation">Перевод${icon('check')}</button></div><div class="arabic-part"><p class="reader-language">АРАБСКИЙ ОРИГИНАЛ</p>${readerArabic(record)}</div><div class="translation-part" id="reader-translation"><div class="reader-divider"></div><p class="reader-language">РУССКИЙ ПЕРЕВОД</p>${russian ? `<div class="reader-russian">${textWithNotes(russian,record)}</div>` : '<p class="reader-missing">Русский перевод для этой записи пока недоступен.</p>'}</div><aside id="reader-note" class="reader-footnote-preview" hidden aria-live="polite"></aside><div class="reader-tool-actions"><button type="button" class="reader-chain">${icon('grid')}<span>Конструктор передач<small>Исследовать цепочку передатчиков</small></span>${icon('arrow')}</button><button type="button" class="reader-scientific">${icon('source')}<span>Сравнить версии<small>Открыть инструменты исследования источника</small></span>${icon('arrow')}</button></div>`;
    // «Страница в книге»: the same hadith inside its printed page — chapters, neighbours, the author's words, untouched.
    if ($('#reader-open-page')) $('#reader-open-page').onclick = async () => {
      const button = $('#reader-open-page'), label = button.textContent; button.disabled = true; button.textContent = 'Ищем страницу…';
      try {
        // never silent (owner 29.10: «ничего не открывается, ошибки не пришло»): 15 s, then a plain message
        const place = await Promise.race([state.api.locateLeaf(record.collection, record.number, record.arabic || ''), new Promise((_,reject) => setTimeout(() => reject(new Error('Лист издания не нашёлся за 15 секунд — попробуйте ещё раз или откройте книгу через «О книге»')),15000))]);
        $('#reader').close(); openNativeBook(place.bid, place.leaf, bookSource, {mark: record.number, arabicTitle: arabicTitleOf(record)});
      } catch (error) {toast(String(error?.message || 'Страница издания не найдена'));}
      finally {button.disabled = false; button.textContent = label;}
    };
    if ($('#reader-about')) $('#reader-about').onclick = () => openBookOfRecord(record);
    $('#translation-toggle').onclick = () => {const button = $('#translation-toggle'), shown = button.getAttribute('aria-pressed') !== 'true'; button.setAttribute('aria-pressed',String(shown)); button.classList.toggle('active',shown); $('#reader-translation').hidden = !shown;};
    if(record.kind==='quran'){
      mountQuranAudio(record,mountQuranWords(record),options.autoAudio);
      const nav=document.createElement('nav');nav.className='quran-verse-nav';nav.setAttribute('aria-label','Навигация по аятам');
      nav.innerHTML='<button type="button" data-verse-step="1">← Следующий аят</button><button type="button" data-verse-step="-1">Предыдущий аят →</button>';   // Arabic reads right→left: next is on the left
      $('.translation-part',$('#reader-body')).after(nav);
      nav.querySelectorAll('button').forEach(button=>{
        const direction=Number(button.dataset.verseStep);
        if((Number(record.sura)===1&&Number(record.ayah)===1&&direction===-1)||(Number(record.sura)===114&&Number(record.ayah)===6&&direction===1))button.disabled=true;
        button.onclick=async()=>{
          const token=state.readerToken,buttons=Array.from(nav.querySelectorAll('button')),disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);
          try{const next=await state.api.quranNeighbor(Number(record.sura),Number(record.ayah),direction);if(token!==state.readerToken||!$('#reader').open)return;if(next)openReader(next);else toast(direction>0?'Это последний аят Корана':'Это первый аят Корана');}
          catch(_){if(token===state.readerToken)toast('Не удалось загрузить соседний аят');}
          finally{if(token===state.readerToken)buttons.forEach((b,i)=>b.disabled=disabled[i]);}
        };
      });
    }
    $$('[data-note]',$('#reader-body')).forEach(button => button.onclick = () => {
      const number = button.dataset.note, text = noteText(record,number), panel = $('#reader-note');
      panel.hidden = false; panel.innerHTML = `<header><span>Примечание ${escape(number)}</span><button type="button" aria-label="Закрыть примечание">${icon('close')}</button></header><p>${escape(text || 'В источнике есть ссылка на примечание, но его текст не передан.')}</p>`;
      $('button',panel).onclick = () => panel.hidden = true;
      const scroller = $('#reader-body'), position = panel.offsetTop - scroller.offsetTop - 24;
      scroller.scrollTo({top:position,behavior:reducedMotion.matches ? 'instant' : 'smooth'});
    });
    if(record.isExcerpt){
      const available=record.page&&record.bid;
      $('#reader-body').insertAdjacentHTML('afterbegin',`<aside class="excerpt-guide"><strong>Показан только найденный отрывок</strong><p>Он может содержать начало цепочки передатчиков без самого текста хадиса. Граница иснада и матна здесь не установлена.</p>${available?'<button type="button" id="excerpt-source">Открыть страницу источника →</button>':'<p>Страница источника для этого отрывка пока недоступна.</p>'}</aside>`);
      if(available)$('#excerpt-source').onclick=()=>{$('#reader').close();invokeTool('bookPage',record);};
    }else if(record.kind==='hadith'&&record.arabic&&!(Array.isArray(record.parts)&&record.parts.length)){
      $('#reader-body').insertAdjacentHTML('afterbegin','<p class="reader-missing">Разделение цепочки передатчиков и текста хадиса для этой записи пока не подтверждено.</p>');
    }
    const readerTools = record.kind==='quran'?[{id:'quranReader',title:'Открыть читалку Корана',icon:'book'},{id:'explain',title:'Пояснение',icon:'helper'}]:record.kind==='book'?[...(record.page?[{id:'bookPage',title:'Открыть страницу книги',icon:'book'}]:[]),{id:'explain',title:'Пояснение',icon:'helper'},{id:'notes',title:'Мои заметки',icon:'pen'}]:[{id:'narrators',title:'Передатчики',icon:'book'},{id:'explain',title:'Пояснение',icon:'helper'},{id:'audio',title:'Озвучить',icon:'audio'},{id:'notes',title:'Мои заметки',icon:'pen'},{id:'copy',title:'Копировать',icon:'source'},{id:'share',title:'Поделиться',icon:'arrow'},{id:'tashkeel',title:'Без огласовок',icon:'info'},...(SUNNAH_COM[record.collection]?[{id:'source',title:'На sunnah.com',icon:'source'}]:[])];
    $('.reader-tool-actions').innerHTML = `<details class="reader-tools-disclosure" open><summary>Инструменты <span>${readerTools.length}</span></summary><div class="reader-tools-grid">${readerTools.map(tool => `<button type="button" data-reader-tool="${tool.id}">${icon(tool.icon)}<span>${tool.title}</span>${icon('arrow')}</button>`).join('')}</div>${record.kind==='book'?'<p>Для этого отрывка доступны перечисленные инструменты. Остальные функции требуют полного текста и проверки источника.</p>':''}</details>`;
    $$('[data-reader-tool]').forEach(button => button.onclick = () => {if (!NATIVE_TOOLS.has(button.dataset.readerTool)) $('#reader').close(); invokeTool(button.dataset.readerTool,record);});
  }
  async function openReader(record,options={}) {
    stopReaderAudio();
    const token = ++state.readerToken; state.reader = record; updateReaderSave();
    const dialog = $('#reader'); if (!dialog.open) dialog.showModal(); document.body.style.overflow = 'hidden';
    loading($('#reader-body'),'Открываем текст','Оригинал и перевод — в одном месте');
    try {const full = state.api ? await state.api.read(record) : record; if (token !== state.readerToken || !dialog.open) return; state.reader = full ? {...record,...full} : record; renderReader(state.reader,options); updateReaderSave(); $('#reader-body').scrollTop = 0;}
    catch (error) {if (token !== state.readerToken) return; empty($('#reader-body'),'Не удалось загрузить текст','Попробуем открыть его ещё раз.','Повторить',() => openReader(record)); console.warn('Muslimoon reader unavailable',error);}
  }
  $('.reader-close').onclick = () => $('#reader').close();
  $('#reader').addEventListener('close',() => {stopReaderAudio();state.readerToken++; document.body.style.overflow = '';});
  $('#reader').addEventListener('click',event => {if (event.target === $('#reader')) $('#reader').close();});
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const EXAMPLES = {hadith:['бухари 1','дела по намерениям','إنما الأعمال بالنيات','муслим 8'],quran:['2:255','милость','1:1','الرحمن الرحيم']};
  const exs = () => EXAMPLES[state.section === 'quran' ? 'quran' : 'hadith'];
  // The example types itself in, letter by letter, as a pale hint with a caret (owner #4334): it is a hint, not text in
  // the field. When it is typed, the search button lights up for a moment and dims again — the button wakes only for
  // the person's own words.
  let exampleIndex = 0, exampleTimer, exampleFadeTimer;
  const exampleIdle = () => $('#query').value || document.activeElement === $('#query') || reducedMotion.matches || document.hidden || state.aiMode;
  function stopExample() {clearTimeout(exampleTimer); clearTimeout(exampleFadeTimer); $('#search-submit').classList.remove('demo-ready'); $('#query-example').classList.remove('typing');}
  function syncPlaceholder() {
    // in AI mode the hint «Спросите ИИ-помощника…» stands alone — no running example on top of it (owner 29.10)
    const hidden = Boolean($('#query').value) || document.activeElement === $('#query') || !!state.aiMode;
    $('#clear-query').hidden = !$('#query').value;
    $('#search-submit').disabled = !$('#query').value.trim();
    $('#query-example').hidden = hidden;
    stopExample();
    if (hidden) return;
    if (reducedMotion.matches || document.hidden) {$('#query-example').textContent = exs()[exampleIndex % exs().length]; return;}
    exampleTimer = setTimeout(typeExample, 900);
  }
  function typeExample() {
    if (exampleIdle()) return;
    const el = $('#query-example'), text = exs()[exampleIndex % exs().length]; el.lang = /[؀-ۿ]/.test(text) ? 'ar' : 'ru'; el.classList.add('typing');
    let n = 0;
    const step = () => {if (exampleIdle()) return; el.textContent = text.slice(0, ++n);
      if (n < text.length) {exampleTimer = setTimeout(step, 75 + Math.random() * 55); return;}
      exampleTimer = setTimeout(() => {if (exampleIdle()) return; $('#search-submit').classList.add('demo-ready');
        exampleFadeTimer = setTimeout(() => $('#search-submit').classList.remove('demo-ready'), 1100);
        exampleTimer = setTimeout(erase, 2300);}, 250);};
    const erase = () => {if (exampleIdle()) return; el.textContent = el.textContent.slice(0, -1);
      if (el.textContent) {exampleTimer = setTimeout(erase, 32); return;}
      exampleIndex = (exampleIndex + 1) % exs().length; exampleTimer = setTimeout(typeExample, 650);};
    el.textContent = ''; step();
  }
  function resetPlaceholder() {exampleIndex = 0; $('#query-example').textContent = ''; $('#query-example').lang = 'ru'; syncPlaceholder();}
  $('#query').addEventListener('input',() => {syncPlaceholder(); if (!$('#query').value.trim() && state.api) {state.searchToken++; showWelcome();}});
  $('#clear-query').onclick = () => {$('#query').value = ''; state.searchToken++; showWelcome(); syncPlaceholder(); $('#query').focus();};
  $('#query').addEventListener('focus',syncPlaceholder); $('#query').addEventListener('blur',syncPlaceholder);
  document.addEventListener('visibilitychange',syncPlaceholder); reducedMotion.addEventListener('change',syncPlaceholder); syncPlaceholder();
  async function initialize() {
    try {
      for (let attempt=0; attempt<100 && !window.MuslimoonData; attempt++) await new Promise(resolve => setTimeout(resolve,100));
      if (!window.MuslimoonData) throw new Error('MuslimoonData was not loaded');
      state.api = window.MuslimoonData;state.api.onNumberUpdate(applyNumberResults); const info = await state.api.ready();
      state.collections = Array.isArray(info.collections) ? info.collections : []; state.categories = Array.isArray(info.categories) ? info.categories : []; $('#data-version').textContent = info.version ? `Библиотека · ${info.version}` : '';
      $('#category-select').innerHTML = '<option value="all">Все разделы</option>' + state.categories.map(c => `<option value="${escape(c.id)}">${escape(c.title)}${Number.isFinite(c.count) ? ` · ${c.count}` : ''}</option>`).join('');
      $('#collection-select').innerHTML = '<option value="all">Все книги</option>' + state.collections.map(c => `<option value="${escape(c.id)}">${escape(c.title)}${c.arabicTitle&&c.arabicTitle!==c.title?' | '+escape(c.arabicTitle):''}</option>`).join('');
      filtersChanged(); renderLibrary(); showWelcome(); $('.search-field').classList.remove('warming');
      if (!sessionStorage.getItem('muslimoon.design.preview-state')) restoreSpot(); else spotRestored = true;
      let restoredQuery = '';
      try {restoredQuery = String(sessionStorage.getItem('muslimoon.design.preview-query') || '').trim(); sessionStorage.removeItem('muslimoon.design.preview-query');} catch (_) {}
      let previewState=null;
      try {previewState=JSON.parse(sessionStorage.getItem('muslimoon.design.preview-state')||'null');sessionStorage.removeItem('muslimoon.design.preview-state');}catch(_){}
      if(previewState){
        const section=$('[data-section="'+(previewState.section==='quran'?'quran':'hadith')+'"]');if(section)section.click();
        for(const [id,value] of [['category-select',previewState.category],['collection-select',previewState.collection],['mode-select',previewState.mode]])if(value&&Array.from($('#'+id).options).some(o=>o.value===value))$('#'+id).value=value;
        filtersChanged();
        state.libraryQuery=String(previewState.libraryQuery||'');$('#catalog-query').value=state.libraryQuery;
        if(['all','title','author'].includes(previewState.libraryMode)){state.librarySearchMode=previewState.libraryMode;$('#catalog-search-mode').value=state.librarySearchMode;}
        renderLibrary();
        if(['search','library','bookmarks','assistant','settings'].includes(previewState.view))showView(previewState.view);
      }
      if (restoredQuery) {$('#query').value = restoredQuery; syncPlaceholder(); if(state.view==='search')await performSearch();}
    } catch (error) {
      state.api = null; $('.search-field').classList.remove('warming');
      empty($('#search-results'),'Библиотека ещё не ответила','Тексты не загрузились. Попробуем подключиться ещё раз.','Попробовать снова',initialize);
      empty($('#library-collections'),'Нужно подключение','Сборники появятся, когда библиотека будет доступна.','Повторить',initialize);
      console.warn('Muslimoon initialization unavailable',error);
    }
  }
  $('#tasks-toggle').onclick = () => {const opened = $('#tasks-list').hidden; $('#tasks-list').hidden = !opened; $('#tasks-toggle').setAttribute('aria-expanded',String(opened));};
  let tasksFetching = false, lastTaskData = '', tasksErrored = false;
  async function updateTasks() {
    if (tasksFetching || document.hidden) return; tasksFetching = true;
    try {
      const response = await fetch('tasks.json',{cache:'no-store'}); if (!response.ok) throw new Error('Task list unavailable');
      const payload = await response.json(), tasks = Array.isArray(payload) ? payload : Array.isArray(payload?.tasks) ? payload.tasks : [];
      const signature = JSON.stringify(tasks); if (signature === lastTaskData && !tasksErrored) return; lastTaskData = signature; tasksErrored = false;
      const verified = tasks.filter(task => task.status === 'verified').length, percentage = tasks.length ? Math.round(verified/tasks.length*100) : 0;
      $('#tasks-total').textContent = String(tasks.length); $('#tasks-progress').textContent = `${verified}/${tasks.length} · ${percentage}%`; $('#tasks-progress-bar').style.width = `${percentage}%`;
      const active = tasks.find(task => task.status === 'working') || tasks.find(task => task.status === 'queued');
      $('#tasks-active').textContent = active ? String(active.title || 'Задача без названия') : tasks.length && verified === tasks.length ? 'Все задачи проверены' : 'Нет активных задач';
      const labels = {queued:'В очереди',working:'В работе',verified:'Проверено'};
      $('#tasks-list').innerHTML = tasks.map(task => `<div class="task-row task-${labels[task.status] ? task.status : 'unknown'}"><span class="task-status-dot"></span><div><div class="task-row-heading"><strong>${escape(task.title || 'Задача без названия')}</strong><span>${escape(labels[task.status] || 'Статус не указан')}</span></div>${task.detail ? `<p>${escape(task.detail)}</p>` : ''}</div></div>`).join('') || '<p class="tasks-empty">В списке пока нет задач.</p>';
    } catch (_) {tasksErrored = true; $('#tasks-active').textContent = lastTaskData ? 'Не удалось обновить список задач' : 'Список задач пока недоступен';}
    finally {tasksFetching = false;}
  }
  updateTasks(); setInterval(updateTasks,2000); document.addEventListener('visibilitychange',() => {if (!document.hidden) updateTasks();});
  initialize();
})();
