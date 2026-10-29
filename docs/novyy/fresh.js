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
  const NATIVE_TOOLS = new Set(['tafsir','askAi','takhrij','narrators','audio','notes','source','explain','assistant','bookPage','copy','share','tashkeel']);
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
  // владелец 29.10: «копировать нажал — лёгкое красивое уведомление появляется и исчезает». Уведомление лежало под
  // открытым окном читалки (окно — верхний слой), поэтому его не было видно: кладём его в самое верхнее открытое окно.
  function toast(message) {
    const el=$('#toast'),top=[...document.querySelectorAll('dialog[open]')].pop();(top||document.body).appendChild(el);
    el.textContent = message; el.classList.remove('toast-out'); el.hidden = false;
    clearTimeout(toastTimeout); toastTimeout = setTimeout(() => {el.classList.add('toast-out');toastTimeout=setTimeout(()=>{el.hidden=true;el.classList.remove('toast-out');},320);},2200);
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
    const mk = document.querySelector('.maktaba-section'); if (mk) {mk.hidden = true; mkState.token++;}
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
    if(!element.isConnected)return;
    if(!parts.some(p=>p.role==='isnad')||!parts.some(p=>p.role==='matn')){   // не разделился (Муслим №321) — имена всё равно выделяем
      const whole=element.querySelector('.card-arabic-extra p')||element.querySelector('.card-text.arabic-preview');
      if(whole&&!whole.dataset.namesLinked){whole.dataset.namesLinked='1';linkIsnadNames(whole,record,null);}return;}
    if(selectingWithin(element)){deferredCardPaints.set(element,{record,parts});return;}
    const block=element.querySelector('.card-arabic-extra p')||element.querySelector('.card-text.arabic-preview');if(!block)return;
    // owner 29.10: «не надо блоками делить иснад/матн — как в оригинале вместе, лёгкая разница в цвете»
    const expanded=element.querySelector('[data-expand]')?.getAttribute('aria-expanded')==='true';
    block.classList.add('card-flow');
    block.innerHTML=splitRemarks(parts).filter(p=>p.text&&['isnad','matn','remark','comment'].includes(p.role)).map(p=>`<span class="card-part card-part-${escape(p.role)}" lang="ar" dir="rtl">${escape(expanded?String(p.text):excerpt(p.text))}</span>`).join(' ');
    const isn=block.querySelector('.card-part-isnad');if(isn)linkIsnadNames(isn,record,null);
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
    if (id === 'ctor') {openChainCtor(); return;}
    if (state.aiMode) setAiMode(false);
    $('#mode-select').value = id; filtersChanged(); syncModeChips(); if ($('#query').value.trim()) performSearch();
  });
  // The search line turns into a question to the helper (owner 29.10): no second boxed button — the magnifier itself is a
  // quiet switch «Поиск ⇄ ИИ»; in AI mode the field glows gold, the hint changes and the arrow sends to the helper's chat.
  const spark = document.createElementNS('http://www.w3.org/2000/svg','symbol'); spark.id = 'i-spark'; spark.setAttribute('viewBox','0 0 24 24');
  spark.innerHTML = '<path d="M12 3.5l1.7 5.1 5.1 1.7-5.1 1.7L12 17.1l-1.7-5.1-5.1-1.7 5.1-1.7Z"/><path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7Z"/>';
  $('.icon-definitions').appendChild(spark);
  [['play','<path d="M8 5.5v13l11-6.5z"/>'],['copy','<rect x="8.5" y="8.5" width="11" height="11" rx="2.2"/><path d="M15.5 8.5V6.2A1.7 1.7 0 0 0 13.8 4.5H6.2A1.7 1.7 0 0 0 4.5 6.2v7.6a1.7 1.7 0 0 0 1.7 1.7h2.3"/>'],['share','<path d="M12 15V4.5"/><path d="M7.5 9 12 4.5 16.5 9"/><path d="M5 13.5v4.3A1.7 1.7 0 0 0 6.7 19.5h10.6a1.7 1.7 0 0 0 1.7-1.7v-4.3"/>'],['more','<circle cx="5.5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18.5" cy="12" r="1.6"/>']].forEach(([id,path])=>{const s=document.createElementNS('http://www.w3.org/2000/svg','symbol');s.id='i-'+id;s.setAttribute('viewBox','0 0 24 24');s.innerHTML=path;$('.icon-definitions').appendChild(s);});
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
  // владелец 29.10: поиск «2:5» — а под строкой «1. аль-Фатиха / 1», «будто открылась Фатиха 1». Выбор всегда показывает
  // найденный или открытый аят.
  async function setQuranPick(sura,ayah){const su=+sura,ay=+ayah;if(!(su>=1&&su<=114))return;await fillQuranPick();
    const sel=quranPick.querySelector('.qp-sura');if(!sel.options.length)return;sel.value=String(su);quranPick.querySelector('.qp-ayah').value=String(ay||1);fillAyahs();
    quranPick.querySelector('.qp-ayah').value=String(Math.min(ay||1,suraInfo&&suraInfo.ayahs[su-1]||ay||1));}
  quranPick.querySelector('.qp-open').onclick=()=>{const s=quranPick.querySelector('.qp-sura').value,a=quranPick.querySelector('.qp-ayah').value;$('#query').value=s+':'+a;syncPlaceholder();performSearch();};
  const quranSugg=document.createElement('div');quranSugg.className='quran-sugg';quranSugg.hidden=true;quranPick.before(quranSugg);
  function syncQuranPick(){const q=state.section==='quran';quranPick.hidden=!q;$('#refine-toggle').hidden=q;if(!q)quranSugg.hidden=true;if(q){$('#refine-panel').hidden=true;$('#refine-toggle').setAttribute('aria-expanded','false');if(state.api)fillQuranPick();}}
  // Live hints while typing in the Quran (owner 29.10: «как в старой версии было удобно, когда набираешь номера аятов»):
  // «45» → the whole sura 45 and «4:5»; «2255» → 2:255, 22:55, 225:5…; a name → the suras by name (Russian or Arabic).
  const openAyah=(s,a)=>{quranSugg.hidden=true;$('#query').value=s+':'+(a||1);syncPlaceholder();performSearch();};
  async function quranSuggest(){
    if(state.section!=='quran'){quranSugg.hidden=true;return;}
    if(!suraInfo){try{suraInfo=await state.api.suraInfo();}catch(_){return;}}
    const raw=$('#query').value.trim().replace(/[٠-٩]/g,d=>'٠١٢٣٤٥٦٧٨٩'.indexOf(d)),names=suraInfo.names||[],ayahs=suraInfo.ayahs||[],opts=[];
    if(/^\d{1,4}$/.test(raw)){const n=+raw;if(n>=1&&n<=114)opts.push({s:n,a:0});
      for(let cut=1;cut<raw.length;cut++){const su=+raw.slice(0,cut),ay=+raw.slice(cut);if(su>=1&&su<=114&&ay>=1&&ay<=(ayahs[su-1]||0)&&!opts.some(o=>o.s===su&&o.a===ay))opts.push({s:su,a:ay});}}
    else if(/^\d{1,3}\s*[:.,\s]\s*\d{0,3}$/.test(raw)){const [su,ay]=raw.split(/[:.,\s]+/).map(Number);if(su>=1&&su<=114){if(ay>=1&&ay<=(ayahs[su-1]||0))opts.push({s:su,a:ay});else opts.push({s:su,a:0});}}
    else if(raw.length>=2&&!/\d/.test(raw)){const f=catalogFold(raw),mean=suraInfo.meanings||[],arn=suraInfo.arabic||[];names.forEach((nm,i)=>{if(opts.length<5&&(catalogFold(nm).includes(f)||(f.length>=3&&catalogFold(mean[i]||'').includes(f))||catalogFold(arn[i]||'').includes(f)))opts.push({s:i+1,a:0});});}
    if(!opts.length){quranSugg.hidden=true;quranSugg.innerHTML='';return;}
    quranSugg.innerHTML=opts.slice(0,6).map(o=>`<button type="button" data-qs="${o.s}:${o.a}"><b>${o.a?o.s+':'+o.a:'Сура '+o.s}</b><span>${escape(names[o.s-1]||'')}${o.a?'':` · ${ayahs[o.s-1]||''} аятов`}</span></button>`).join('');quranSugg.hidden=false;
  }
  quranSugg.addEventListener('click',e=>{const b=e.target.closest('[data-qs]');if(!b)return;const [s,a]=b.dataset.qs.split(':').map(Number);openAyah(s,a);});
  $('#query').addEventListener('input',()=>{if(state.section==='quran')quranSuggest();});
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
      // the list stays open (owner 29.10: «выбрал "без Бухари" — исчезает, а я хочу дальше выбирать»); a second tap undoes
      const cur=multiScope.find(x=>x.kind===kind&&x.id===id),same=!!cur&&!!cur.exclude===exclude;
      setScope(same?multiScope.filter(x=>!(x.kind===kind&&x.id===id)):[...multiScope.filter(x=>!(x.kind===kind&&x.id===id)),{kind,id,title:item.title,exclude}]);renderWhereSuggest();}
  });
  where.querySelector('.where-input').addEventListener('input',renderWhereSuggest);
  function renderWhereSuggest(){
    const q=catalogFold(where.querySelector('.where-input').value).trim(),box=where.querySelector('.where-suggest');if(q.length<2){box.hidden=true;box.innerHTML='';return;}
    const stateOf=(kind,id)=>{const x=multiScope.find(m=>m.kind===kind&&m.id===id);return x?(x.exclude?'ex':'in'):'';};
    const cats=state.categories.filter(c=>catalogFold(c.title).includes(q)).slice(0,3).map(c=>({kind:'category',id:String(c.id),title:c.title.split('|')[0].trim(),sub:`раздел · ${c.count||''} книг`}));
    const books=state.collections.filter(c=>catalogFold(`${c.title} ${c.arabicTitle||''} ${c.author||''}`).includes(q)).slice(0,6).map(c=>({kind:'book',id:String(c.id),title:c.title,sub:String(c.author||'').split('|').pop().trim()}));
    const authorsSeen=new Map();for(const c of state.collections){const a=String(c.author||'').trim();if(a&&catalogFold(a).includes(q))authorsSeen.set(a,(authorsSeen.get(a)||0)+1);}
    const authors=[...authorsSeen.entries()].sort((x,y)=>y[1]-x[1]).slice(0,3).map(([a,n])=>({kind:'author',id:a,title:a.split('|').pop().trim(),sub:`автор · ${n} книг`}));
    const rows=[...authors,...cats,...books];
    box.innerHTML=rows.length?rows.map(r=>r.kind==='author'?`<div class="where-option"><span dir="auto"><strong>${escape(r.title)}</strong><small>${escape(r.sub)}</small></span><button type="button" data-where-author="${escape(r.id)}">Все его книги</button></div>`:`<div class="where-option"><span dir="auto"><strong>${escape(r.title)}</strong><small>${escape(r.sub)}</small></span><button type="button" class="${stateOf(r.kind,r.id)==='in'?'on':''}" data-where-add="${escape(r.kind+'|'+r.id)}">${stateOf(r.kind,r.id)==='in'?'Ищем ✓':'Искать'}</button><button type="button" class="where-exclude${stateOf(r.kind,r.id)==='ex'?' on':''}" data-where-add="${escape(r.kind+'|'+r.id)}" data-where-exclude="1">${stateOf(r.kind,r.id)==='ex'?'Без ✓':'Без'}</button></div>`).join(''):'<p class="where-none">Не нашлось — попробуйте по-арабски или по автору</p>';
    box.hidden=false;
  }
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
    // раздел — как «Все разделы» в старом окне Мактабы, только своим видом (владелец 29.10: «весь каталог — старое опять высветилось»)
    let catSel = $('#catalog-category'); if (!catSel) {catSel = document.createElement('select'); catSel.id = 'catalog-category'; catSel.className = 'catalog-search-mode catalog-category'; catSel.setAttribute('aria-label','Раздел библиотеки'); $('.catalog-search').after(catSel);
      catSel.onchange = () => {state.libraryCategory = catSel.value; state.libraryShown = 24; renderLibrary();};}
    if (catSel.options.length < 2 && state.categories.length) catSel.innerHTML = `<option value="">Все разделы · ${state.collections.length}</option>` + state.categories.map(c => `<option value="${escape(String(c.id))}">${escape(String(c.title).split('|')[0].trim())} · ${c.count || ''}</option>`).join('');
    const cat = state.libraryCategory || '';
    const books = state.collections.filter(collection => {if (cat && String(collection.category || '') !== cat) return false; if (!query) return true; const title = `${collection.title || ''} ${collection.arabicTitle || ''}`, author = String(collection.author || ''); return catalogFold(state.librarySearchMode === 'author' ? author : state.librarySearchMode === 'title' ? title : `${title} ${author}`).includes(query);});
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
  // ── «Во всей Мактабе» — second wave under the hadith results (owner 29.10: «по умолчанию — по всем 8000 книгам»)
  const mkSection=document.createElement('section');mkSection.className='maktaba-section';mkSection.hidden=true;
  mkSection.innerHTML='<p class="mk-head"><span>Во всей Мактабе</span><small></small></p><div id="maktaba-results" class="results-list"></div><button type="button" class="more-button mk-more" hidden>Ещё из Мактабы</button>';
  $('#more-results').after(mkSection);
  let mkState={q:'',page:1,items:[],token:0};
  async function maktabaWave(query,more){
    if(!state.api||typeof state.api.maktabaSearch!=='function')return;
    const token=more?mkState.token:++mkState.token;if(!more)mkState={q:query,page:1,items:[],token};
    const head=mkSection.querySelector('small'),btn=mkSection.querySelector('.mk-more');mkSection.hidden=false;
    if(!more){$('#maktaba-results').innerHTML='';head.textContent='ищу по всем книгам…';btn.hidden=true;}else{btn.disabled=true;btn.textContent='Загружаю…';}
    try{const r=await state.api.maktabaSearch(query,mkState.page);if(token!==mkState.token)return;
      mkState.items=mkState.items.concat(r.items||[]);
      if(!mkState.items.length){head.textContent='ничего не нашлось';btn.hidden=true;return;}
      head.textContent=`${mkState.items.length}${r.total>mkState.items.length?' из ~'+Number(r.total).toLocaleString('ru-RU'):''}`;
      renderCards($('#maktaba-results'),mkState.items,mkState.items.length);
      btn.hidden=!(r.items||[]).length||mkState.items.length>=r.total;btn.disabled=false;btn.textContent='Ещё из Мактабы';}
    catch(error){if(token!==mkState.token)return;head.textContent=String(error?.message||'сейчас не ответила');btn.hidden=true;}
  }
  mkSection.querySelector('.mk-more').onclick=()=>{mkState.page++;maktabaWave(mkState.q,true);};
  async function performSearch() {
    const query = $('#query').value.trim();
    if (!query) {$('#query').focus(); return;}
    if (state.section==='quran'){const m=query.match(/^(\d{1,3})\s*[:.\s]\s*(\d{1,3})$/)||query.match(/^(\d{1,3})$/);if(m)setQuranPick(m[1],m[2]||1);}
    if (!state.api) {toast('Библиотека ещё открывается'); return;}
    const token = ++state.searchToken; state.results = []; state.resultQuery = query;state.shown=8;state.numberMode=false;state.numberHasMore=false;
    $('#result-count').textContent = ''; $('#search-notice').hidden = true; $('#more-results').hidden = true; $('#search-results-heading').hidden = false;
    $('#results-title').textContent = 'Результаты поиска'; $('#refine-panel').hidden = true; $('#refine-toggle').setAttribute('aria-expanded','false'); loading($('#search-results'));
    // the whole library — at the same time, for an ordinary text query without chosen books
    const wholeLibrary=state.section==='hadith'&&!state.aiMode&&!multiScope.length&&state.category==='all'&&state.collection==='all'&&['normal','diac','root'].includes(state.mode||'normal')&&!/^[\d٠-٩\s:№#.]+$/.test(query);
    mkState.token++;mkSection.hidden=true;if(wholeLibrary)maktabaWave(query,false);
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
    dialog.innerHTML=`<div class="reader-shell"><header class="reader-toolbar"><button type="button" class="back-labeled native-book-close" aria-label="Назад">${icon('back')}<span>Назад</span></button><span>ЧТЕНИЕ КНИГИ</span><button type="button" class="help-q" data-help="book" aria-label="Справка по этой странице">?</button><button type="button" class="text-button native-book-about">О книге</button></header><div class="reader-body native-book-body"><h1 id="native-book-title"></h1><div class="native-book-location" aria-live="polite"></div><div class="native-book-actions"><button type="button" class="nb-action native-book-toc">${icon('book')}Оглавление</button><button type="button" class="nb-action native-book-translate">${icon('helper')}Перевод ИИ</button></div><div class="native-book-headings" lang="ar" dir="rtl"></div><div class="native-book-text" lang="ar" dir="rtl"></div><div class="native-book-tr" hidden></div><div class="native-book-notes"></div><p class="native-book-status" role="status" aria-live="polite"></p><button type="button" class="native-book-tools">Инструменты книги</button></div><nav class="native-book-bar" aria-label="Листание книги" dir="ltr"><button type="button" class="nb-turn native-book-next" aria-label="Следующая страница">${icon('back')}</button><div class="nb-jump"><button type="button" class="nb-edge nb-end">Конец</button><label class="nb-field"><span>Страница</span><input class="nb-page" inputmode="numeric" enterkeyhint="go" aria-label="Перейти на страницу издания"></label><label class="nb-field nb-field-num"><span>№ хадиса</span><input class="nb-hadith" inputmode="numeric" enterkeyhint="go" placeholder="—" aria-label="Перейти к хадису, асару или документу по его номеру в книге"></label><button type="button" class="nb-edge nb-start">Начало</button></div><button type="button" class="nb-turn native-book-prev" aria-label="Предыдущая страница">${icon('arrow')}</button></nav></div>`;
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
    for(const [k,part] of chunks.entries()){try{out.push((await state.api.translate(part,'maktaba',book.bid+'_'+book.leaf+'_'+k)).translation);}catch(error){out.push('');if(!out.some(Boolean)){if(nativeBook===book&&box.dataset.leaf===String(book.leaf))box.innerHTML=`<p class="notes-hint">${escape(String(error?.message||'Перевод сейчас недоступен'))}</p>`;return;}}
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
      $('.native-book-notes',dialog).innerHTML=parts.notes?`<details class="edition-notes"><summary><span>Сноски страницы</span><button type="button" class="src-q" data-help="grade" aria-label="Что это">?</button>${icon('down')}</summary><p lang="ar" dir="rtl">${escape(parts.notes)}</p></details>`:'';
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
  // «Весь каталог книг»: родной список всех книг (state.collections — все 8589), а не старое окно Мактабы
  $('#full-library').onclick = () => {state.libraryFavOnly = false; state.libraryQuery = ''; state.libraryCategory = ''; state.libraryShown = 24; $('#catalog-query').value = ''; renderLibrary();
    const box = $('.catalog-search'); if (box) box.scrollIntoView({block:'start', behavior: reducedMotion.matches ? 'instant' : 'smooth'}); setTimeout(() => $('#catalog-query').focus({preventScroll:true}), 350);};
  async function invokeTool(name,record) {
    $('#assistant-notice').hidden = true;
    if(name==='bookPage'&&record?.bid&&record?.page){openNativeBook(record.bid,record.page,source(record));return;}
    if(name==='assistant'||name==='explain'){openNativeAssistant(record);return;}
    if(name==='notes'){const k=noteKeyOf(record);if(k)openNoteEditor(k.rk,k.label,k.ref);else openNotes();return;}
    if(name==='narrators'){openNarrators(record);return;}
    if(name==='takhrij'){openTakhrij(record);return;}
    if(name==='tafsir'){openTafsir(record);return;}
    if(name==='askAi'){askAssistant(record.kind==='quran'?`Аят ${record.sura}:${record.ayah}${record.title?' ('+record.title+')':''}: о чём он, коротко, и что говорят толкователи?`:`${source(record)}${record.number?' № '+record.number:''}: о чём этот хадис и насколько он достоверен?`);return;}
    if(name==='audio'){speakRecord(record);return;}
    if(name==='copy'){const text=[record.arabic,record.russian,source(record)+(record.number?' № '+record.number:'')].filter(Boolean).join('\n\n');
      try{await navigator.clipboard.writeText(text);toast('✓ Скопировано — оригинал, перевод и источник');}catch(_){toast('Не удалось скопировать — разрешите доступ к буферу');}return;}
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
  let pageGuides=null;fetch('data/obyasneniya_stranic.json').then(r=>r.ok?r.json():{}).then(j=>{pageGuides=j||{};}).catch(()=>{pageGuides={};});
  function pageKey(){
    const open=[...document.querySelectorAll('dialog[open]')].map(d=>d.className+' '+d.id).join(' ');
    if(/ncard-dialog/.test(open))return 'ncard';if(/ctor-dialog/.test(open))return 'ctor';if(/takh-dialog/.test(open))return 'takhrij';
    if(/qs-dialog/.test(open))return 'quransettings';if(/sura-dialog/.test(open))return 'quran';if(/narr-dialog/.test(open))return 'narrators';
    if($('#native-book-reader')?.open)return 'book';if($('#book-dialog')?.open)return 'bookinfo';
    if($('#reader')?.open&&state.reader)return state.reader.kind==='quran'?($('.q-word-sheet:not([hidden])')?'quranword':'quran'):'reader';
    return {library:'library',bookmarks:'bookmarks',settings:'settings'}[state.view]||'main';
  }
  function screenContext(){
    const where=$('#native-book-reader')?.open?`читает книгу «${nativeBook?.title||''}», ${$('.native-book-location')?.textContent||''}`:$('#reader')?.open&&state.reader?`читает ${state.reader.kind==='quran'?'аят '+state.reader.sura+':'+state.reader.ayah:'хадис '+source(state.reader)+' № '+state.reader.number}`:
      ({search:state.section==='quran'?'поиск по Корану':'поиск хадисов',library:'библиотека',bookmarks:'закладки',settings:'раздел «Ещё»'}[state.view]||'приложение');
    const tips=[act('search','дела по намерениям','Хадис о намерениях'),act('quran','2:255','Аят аль-Курси'),act('findBooks','النووي','Книги ан-Навави')];
    // the prepared explanation of this page (local 27B, owner 29.10): the helper starts from where the person is
    const g=pageGuides&&pageGuides[pageKey()];
    if(g&&g.kratko){const can=(g.chto_mozhno||[]).slice(0,4).map(x=>'• '+x).join('\n');
      return {key:'page:'+pageKey()+':'+(state.reader?.id||''),screen:(where+' · '+g.kratko).slice(0,380),text:'Ас-саляму алейкум! '+g.kratko+(can?'\nЗдесь можно:\n'+can:'')+'\nСпросите о чём угодно — отвечу по первоисточникам.',actions:tips};}
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
    const eff=n=>n.doubt?'unsure':(n.verdict&&n.verdict.kind),cnt=k=>items.filter(n=>eff(n)===k).length,good=cnt('sound')+cnt('sahabi'),bad=cnt('weak')+cnt('rejected');
    const anMud=items.filter((n,i)=>n.mudallis&&items[i+1]&&items[i+1].via&&items[i+1].via.cls==='A').length;
    const collector=COLLECTOR[full.collection]||'';
    // each count is a button: it brings the screen to those links one after another (owner 29.10)
    const jump=(cls,set,label)=>`<button type="button" class="${cls}" data-jump="${set}">${label}</button>`;
    const summary=`<div class="chain-summary"><b>${items.length} ${items.length===1?'звено':items.length<5?'звена':'звеньев'}</b>${good?jump('vs-sound','sound sahabi','надёжных '+good):''}${cnt('mixed')?jump('vs-mixed','mixed','спорных '+cnt('mixed')):''}${bad?jump('vs-weak','weak rejected','слабых '+bad):''}${cnt('unknown')+cnt('none')?jump('vs-unknown','unknown none','не установлено '+(cnt('unknown')+cnt('none'))):''}${cnt('unsure')?jump('vs-mixed','unsure','сверить с текстом '+cnt('unsure')):''}${anMud?jump('vs-mixed','mud','мудаллис с «عن»: '+anMud):''}</div>`
      +'<p class="chain-rule">Свидетельства — с карточек передатчиков Мактабы и sunnah.com. Надёжность — по свидетельствам 48 муʿтабаров: нужно два подтверждения (توثيق), «в Сахихайн» без тяжкого джарха — тоже два. Ибн Хаджар и аз-Захаби — поздние своды, в счёт не идут. Это оценка звеньев, а не приговор хадису.</p>';
    const node=(n,i)=>{const v=n.verdict||{kind:'none'},kind=(byName&&v.kind!=='sahabi')||n.doubt?'muted':v.kind;
      // «ثقة — надёжный (توثيق ≥2 муʿтабаров)» → the Arabic term into the badge, the reason on its own line
      const term=v.kind==='sahabi'?'صحابي':String(v.v||'').split(' — ')[0].trim(),reason=v.kind==='sahabi'?'الصحابة عدول — сподвижники надёжны по единогласию учёных (иджма)':((String(v.v||'').match(/\(([^()]*)\)\s*$/)||[])[1]||'');
      const why=v.muts&&v.muts.length?`<details class="narr-why"><summary>Кто из 48 сказал</summary>${v.muts.map(m=>`<p lang="ar" dir="rtl"><b>${escape(m[0])}:</b> ${escape(m[1])} <span class="src-tag src-${m[2]==='sunnah'?'sunnah':'maktaba'}" dir="ltr">${m[2]==='sunnah'?'sunnah.com':'Мактаба'}</span></p>`).join('')}</details>`:'';
      // both narrator cards the testimonies come from (owner 29.10: «со ссылками к первоисточникам»)
      const cards=n.links?`<p class="narr-cards">Карточки: <a class="src-tag src-maktaba" href="${escape(n.links.maktaba)}">Мактаба</a>${n.links.sunnah?` <a class="src-tag src-sunnah" href="${escape(n.links.sunnah)}">sunnah.com</a>`:''}${v.fromSunnah?` · с sunnah.com добавлено ${v.fromSunnah}, чего не было в Мактабе`:''}</p>`:'';
      const late=(n.hajar||n.dhahabi)?`<p class="narr-late">Справочно, не в счёт: ${n.hajar?`Ибн Хаджар — <b lang="ar" dir="rtl">${escape(n.hajar)}</b>`:''}${n.hajar&&n.dhahabi?' · ':''}${n.dhahabi?`аз-Захаби — <b lang="ar" dir="rtl">${escape(n.dhahabi)}</b>`:''}</p>`:'';
      const counts=v.kind==='sahabi'?'':v.kind==='none'?'':`<span class="narr-count"><bdi lang="ar">توثيق</bdi> <b>${v.nT}</b> из 48${v.sahihayn?' · в Сахихайн':''}${v.nJ?` · джарх <b>${v.nJ}</b>`:''}</span>`;
      return `<article class="narr-row narr-${kind}" data-eff="${escape(eff(n)||'none')}"${n.mudallis?' data-mud="1"':''}><span class="narr-step">${i+1}</span><div class="narr-main">${n.id?`<button type="button" class="narr-name narr-name-btn" data-narr-card="${escape(n.id)}" lang="ar" dir="rtl" title="${escape(n.full||n.name)}">${escape(shortNasab(n.full||n.name))}</button>`:`<p class="narr-name" lang="ar" dir="rtl" title="${escape(n.full||n.name)}">${escape(shortNasab(n.full||n.name))}</p>`}`
        +`${n.ru?`<p class="narr-ru">${escape(n.ru)}</p>`:''}`
        +`${(n.kunya||n.nisba)?`<p class="narr-sub" lang="ar" dir="rtl">${escape([n.kunya,n.nisba].filter(Boolean).join(' · '))}</p>`:''}`
        +`${n.death?`<p class="narr-meta">ум. ${escape(n.death)}${n.tabaqa?' · табака '+escape(n.tabaqa):''}</p>`:''}`
        +(n.id?`<p class="narr-verdict"><span class="narr-badge">${escape(VERDICT_RU[v.kind]||'')}${term?` <bdi lang="ar">${escape(term)}</bdi>`:''}</span>${counts}</p>${reason?`<p class="narr-v">Основание: <bdi dir="ltr">${escape(reason)}</bdi></p>`:''}${v.note?`<p class="narr-note">${escape(v.note)}</p>`:''}${why}${late}${cards}`:'<p class="narr-meta">в нашей базе не найден</p>')
        +`${n.doubt?`<p class="narr-warn">${String(n.doubt).startsWith('late')?`Сомнительное звено: умер в ${escape(n.doubt.split(':')[1])} г., а собиратель — в ${escape(n.doubt.split(':')[2])} г. Готовая разметка цепи, похоже, взяла тёзку — итог по нему не учитывайте, сверьте с текстом.`:'Этого имени нет в тексте иснада: звено взято из готовой разметки цепи и может быть ошибочным — итог по нему не учитывайте, сверьте с текстом.'}</p>`:''}`
        +`${n.mudallis?`<p class="narr-note">Отмечен как мудаллис${n.mudallis?' ('+escape(n.mudallis)+')':''}: его «عن» без явного слышания требует проверки.</p>`:''}`
        +`</div>${n.id?`<button type="button" class="narr-fav${favNarrators().some(f=>String(f.id)===String(n.id))?' on':''}" data-narr-fav="${i}" aria-label="В избранные передатчики">${icon('star')}</button>`:''}</article>`;};
    // the original at hand: the isnad, the words of the hadith, or both folded (owner 29.10)
    const fparts=Array.isArray(full.parts)?full.parts.filter(p=>p&&p.text&&p.text.trim()):[];
    const isnadText=fparts.filter(p=>p.role==='isnad').map(p=>p.text).join(' ')||'',matnText=fparts.filter(p=>p.role==='matn').map(p=>p.text).join(' ')||'';
    const origin=`<div class="narr-origin"><div class="narr-origin-bar">${isnadText?'<button type="button" data-origin="isnad">Развернуть иснад</button>':''}<button type="button" data-origin="matn">${isnadText?'Развернуть хадис':'Развернуть текст'}</button><button type="button" data-origin="none" hidden>Свернуть всё</button></div>${isnadText?`<div class="narr-origin-text origin-isnad" lang="ar" dir="rtl" hidden>${escape(isnadText)}</div>`:''}<div class="narr-origin-text origin-matn" lang="ar" dir="rtl" hidden>${escape(isnadText?matnText:full.arabic)}</div></div>`;
    body.innerHTML=`<p class="notes-hint">${escape(source(full))}${full.number?' · № '+escape(full.number):''} · от собирателя к Пророку ﷺ</p>`+origin
      +(byName?'<p class="narr-warn">Готовой цепочки для этого хадиса в базе нет: передатчики определены по написанию имён — у тёзок возможна путаница, итог сверяйте.</p>':'')
      +(!byName&&cnt('unsure')>=2?`<p class="narr-warn">${cnt('unsure')} звена из ${items.length} не находятся в тексте иснада. Готовая разметка, похоже, описывает другую цепь под этим номером — другой риваят того же хадиса или сбой нумерации. Итог по цепи сверяйте с текстом.</p>`:'')
      +summary
      +`<div class="chain-flow">`
      +(collector?`<div class="chain-end"><span lang="ar" dir="rtl">${escape(collector)}</span><small>собиратель</small></div>`:'')
      +items.map((n,i)=>(collector||i?narrLink(n.via,i?items[i-1].mudallis:false):'')+node(n,i)).join('')
      +narrLink(toProphet,false)+`<div class="chain-end chain-prophet"><span lang="ar" dir="rtl">رسول الله ﷺ</span><small>Пророк</small></div></div>`
      +(items.filter(n=>n.id).length>=2?'<button type="button" class="apply-button narr-to-ctor">Искать хадисы с этой цепью</button><p class="notes-hint">Откроется конструктор цепи: верхние звенья (ближе к Пророку ﷺ) строго по порядку, с теми же формами передачи — их можно поменять.</p>':'');
    const toCtor=body.querySelector('.narr-to-ctor');if(toCtor)toCtor.onclick=()=>{const known=items.filter(n=>n.id),last=known.slice(-5);narrDialog.close();openChainCtor({mode:'seq',sel:last.map(n=>({id:String(n.id),name:n.full||n.name,death:n.death||''})),forms:last.slice(1).map(n=>n.via&&n.via.form||'')});};
    const isn=body.querySelector('.origin-isnad');if(isn)linkIsnadNames(isn,full,null);
    let jumpAt={};
    body.onclick=e=>{
      const o=e.target.closest('[data-origin]');if(o){const w=o.dataset.origin,box=body.querySelector('.narr-origin');
        if(w==='none'){box.querySelectorAll('.narr-origin-text').forEach(x=>x.hidden=true);}
        else{const t=box.querySelector('.origin-'+w);if(t)t.hidden=!t.hidden;}
        const any=[...box.querySelectorAll('.narr-origin-text')].some(x=>!x.hidden);box.querySelector('[data-origin="none"]').hidden=!any;
        box.querySelectorAll('[data-origin="isnad"],[data-origin="matn"]').forEach(b=>{const t=box.querySelector('.origin-'+b.dataset.origin);b.classList.toggle('on',!!t&&!t.hidden);b.textContent=(t&&!t.hidden?'Свернуть ':'Развернуть ')+(b.dataset.origin==='isnad'?'иснад':isnadText?'хадис':'текст');});return;}
      const j=e.target.closest('[data-jump]');if(j){const set=j.dataset.jump.split(' '),rows=[...body.querySelectorAll('.narr-row')].filter(r=>set.includes('mud')?r.dataset.mud==='1':set.includes(r.dataset.eff));
        if(!rows.length)return;const k=(jumpAt[j.dataset.jump]||0)%rows.length;jumpAt[j.dataset.jump]=k+1;const row=rows[k];
        row.scrollIntoView({block:'center',behavior:reducedMotion.matches?'instant':'smooth'});row.classList.remove('flash-row');void row.offsetWidth;row.classList.add('flash-row');
        if(rows.length>1)toast(`${k+1} из ${rows.length} — нажмите ещё раз, чтобы перейти к следующему`);return;}
      const b=e.target.closest('[data-narr-fav]');if(!b)return;const on=toggleFavNarrator(items[+b.dataset.narrFav]);b.classList.toggle('on',on);toast(on?'Передатчик в избранном — он в «Закладках»':'Убрано из избранного');};
  }
  // ── Где ещё передаётся — тахридж прежнего вида, только подтверждённый источником (указ владельца: совпадения «по
  // похожему тексту» не показываем — это были бы догадки). Номер — кнопка: наш сборник открывается в карточке, прочие
  // книги — в читалке издания на этом номере.
  const takhDialog=document.createElement('dialog');takhDialog.className='native-assistant-dialog narr-dialog takh-dialog';
  takhDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('source')}</span><h2>Где ещё передаётся</h2><button type="button" class="native-assistant-close takh-close" aria-label="Закрыть">×</button></header><div class="notes-body takh-body"></div></div>`;
  document.body.appendChild(takhDialog);takhDialog.querySelector('.takh-close').onclick=()=>takhDialog.close();
  // Two texts are the same hadith when most long words of the shorter one are in the other (isnad names alone are
  // not enough: unrelated hadiths share narrators, so short texts need a clear majority).
  function sameText(a,b){const f=t=>new Set(String(t||'').replace(/[ً-ٰٟـ]/g,'').replace(/[أإآ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه').split(/[^ء-ي]+/).filter(w=>w.length>=4));
    const x=f(a),y=f(b);if(!x.size||!y.size)return true;const [s,l]=x.size<y.size?[x,y]:[y,x];let hit=0;s.forEach(w=>{if(l.has(w))hit++;});return hit/s.size>=0.35;}
  async function openTakhrij(record){
    const body=takhDialog.querySelector('.takh-body');body.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Ищу в тахридже</span></div>';
    if(!takhDialog.open)takhDialog.showModal();
    let blocks=[];try{blocks=(await state.api.takhrij(record.collection,record.number)).blocks||[];}catch(_){}
    const places=[];
    const chip=(p,same)=>{places.push({...p,same:!!same});return `<button type="button" class="takh-num" data-place="${places.length-1}"${p.bid||p.code?'':' disabled'}>${escape(p.n)}</button>`;};
    const head=`<p class="notes-hint">${escape(source(record))}${record.number?' · № '+escape(record.number):''}</p>`;
    if(!blocks.length){body.innerHTML=head+'<p class="takh-empty">Проверенного тахриджа для этого хадиса у нас пока нет.</p><p class="notes-hint">Показываем только то, что подтверждено источником: тахкик шейха Шуайба аль-Арнаута (издания ар-Рисаля — Ахмад, Абу Давуд, Тирмизи, ан-Насаи, Ибн Маджа), أطراف Сахиха аль-Бухари, сноски мухаккиков изданий и свод sunnah.one. Совпадения, найденные только по похожему тексту, не показываем — это были бы догадки.</p>';return;}
    body.innerHTML=head+blocks.map(b=>{
      const src=b.source?`<p class="takh-src">Источник: ${escape(b.source)}</p>`:'';
      const hukm=b.hukm?`<p class="takh-hukm"><span>Оценка источника:</span> <b lang="ar" dir="rtl">${escape(b.hukm)}</b><button type="button" class="src-q" data-help="grade" aria-label="Что это за оценка">?</button></p>`:'';
      if(b.kind==='text')return `<section class="takh-block"><h3>${escape(b.title)}</h3>${hukm}<p class="takh-text" lang="ar" dir="rtl">${escape(b.text)}</p>${src}</section>`;
      if(b.kind==='muhaymin')return `<section class="takh-block"><h3>${escape(b.title)}</h3><div class="takh-nums">${b.nums.map(n=>`<button type="button" class="takh-num" data-muh="${escape(n)}">${escape(n)}</button>`).join('')}</div>${src}</section>`;
      return `<section class="takh-block"><h3>${escape(b.title)}</h3>${hukm}${(b.groups||[]).map(g=>`<p class="takh-group">${escape(g.label)}</p>${g.rows.map(r=>`<div class="takh-row"><p class="takh-book"><b lang="ar" dir="rtl">${escape(r.ar)}</b>${r.ru?`<small>${escape(r.ru)}</small>`:''}</p><div class="takh-nums">${r.places.map(p=>chip(p,g.same)).join('')}</div></div>`).join('')}`).join('')}${src}</section>`;
    }).join('')+'<p class="notes-hint">Нажмите на номер — хадис откроется. Совпадения «по похожему тексту» здесь не показываются.</p>';
    body.onclick=async e=>{const m=e.target.closest('[data-muh]');if(m){takhDialog.close();ASSIST_ACTIONS.search.run('мухаймин '+m.dataset.muh);return;}
      const b=e.target.closest('[data-place]');if(!b)return;const p=places[+b.dataset.place];if(!p)return;
      if(p.code&&state.collections.some(c=>c.id===p.code)){
        // «the same hadith» must be the same text in OUR edition: numbers from another printing (al-Nasai's «al-Kubra»
        // listed as al-Nasai) would open someone else's hadith. Shawahid are different hadiths by nature — not checked.
        if(p.same){b.disabled=true;let ok=true,target=null;try{const [src,dst]=await Promise.all([record.arabic?record:state.api.read(record),state.api.read({kind:'hadith',collection:p.code,number:p.n})]);target=dst;ok=sameText(src.arabic,dst.arabic);}catch(_){}finally{b.disabled=false;}
          if(!ok){if(p.code==='nasai'){try{const place=await state.api.leafByHadith('8361',Number(p.n));takhDialog.close();toast('Номер по «ас-Сунан аль-Кубра» ан-Насаи — открываю её');openNativeBook('8361',place.leaf,'Ас-Сунан аль-Кубра ан-Насаи',{mark:p.n});}catch(_){toast('Под этим номером в нашем ан-Насаи другой хадис, а в «аль-Кубре» номер не нашёлся');}return;}
            toast('Под этим номером в нашем издании другой хадис — номер дан по другой печати');return;}
          takhDialog.close();openReader(target&&target.arabic?{kind:'hadith',collection:p.code,number:p.n,...target}:{kind:'hadith',collection:p.code,number:p.n});return;}
        takhDialog.close();openReader({kind:'hadith',collection:p.code,number:p.n});return;}
      if(p.bid){b.disabled=true;try{const place=await state.api.leafByHadith(p.bid,Number(p.n));takhDialog.close();const c=collectionForBid(p.bid,b.closest('.takh-row')?.querySelector('.takh-book small')?.textContent||'');openNativeBook(p.bid,place.leaf,c.title,{mark:p.n,arabicTitle:c.arabicTitle});}catch(_){toast('Этот номер в издании сейчас не открылся');}finally{b.disabled=false;}}};
  }
  // ── Конструктор цепи — в новом виде (owner: «конструктор цепи с формами передачи»). Поиск — прежний, по реестру
  // размеченных цепей 64 печатей: «вместе в иснаде», «рядом», «строго по порядку» с формой на каждом ребре.
  const CTOR_FORMS=[['','любая форма'],['!AN','явное слышание (не «عن»)'],['TH','حدّثنا — рассказал нам'],['THi','حدّثني — рассказал мне'],['AKH','أخبرنا — сообщил нам'],['AKHi','أخبرني — сообщил мне'],['SAM','سمعت — я слышал'],['ANB','أنبأنا — известил'],['AN','عن — от'],['ANN','أنّ — что'],['QAL','قال — сказал']];
  const CTOR_HELP={any:'Все выбранные передатчики стоят в одном иснаде — в любом порядке.',adj:'Выбранные стоят в иснаде подряд, рядом друг с другом.',seq:'Порядок ввода = порядок цепи: 1-й передаёт ОТ 2-го, 2-й ОТ 3-го… Между ними можно задать форму передачи.'};
  const ORD=['1-го','2-го','3-го','4-го','5-го'];
  const ctor={sel:[],mode:'any',forms:[]};let ctorSuggToken=0,ctorSuggTimer=0;
  const ctorDialog=document.createElement('dialog');ctorDialog.className='native-assistant-dialog narr-dialog ctor-dialog';
  ctorDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('book')}</span><h2>Конструктор цепи</h2><button type="button" class="native-assistant-close ctor-close" aria-label="Закрыть">×</button></header><div class="notes-body ctor-body"><div class="ctor-modes" role="radiogroup" aria-label="Как искать"><button type="button" data-ctor-mode="any">Вместе в иснаде</button><button type="button" data-ctor-mode="adj">Рядом</button><button type="button" data-ctor-mode="seq">Строго по порядку</button></div><p class="ctor-help"></p><div class="ctor-slots"></div><div class="ctor-add"><input type="search" class="ctor-input" autocomplete="off" dir="auto" enterkeyhint="search"><div class="ctor-sugg"></div></div><button type="button" class="apply-button ctor-go" disabled>Найти хадисы</button><div class="ctor-out"></div></div></div>`;
  document.body.appendChild(ctorDialog);
  const cq=s=>ctorDialog.querySelector(s);
  cq('.ctor-close').onclick=()=>ctorDialog.close();
  function openChainCtor(preset){
    if(preset){ctor.sel=(preset.sel||[]).slice(0,5);ctor.mode=preset.mode||'any';ctor.forms=(preset.forms||[]).slice(0,4);}
    cq('.ctor-out').innerHTML='';cq('.ctor-sugg').innerHTML='';cq('.ctor-input').value='';renderCtor();if(!ctorDialog.open)ctorDialog.showModal();
    if(preset&&ctor.sel.length>=2)runCtor();
  }
  function renderCtor(){
    ctorDialog.querySelectorAll('[data-ctor-mode]').forEach(b=>{const on=b.dataset.ctorMode===ctor.mode;b.classList.toggle('selected',on);b.setAttribute('aria-checked',String(on));b.setAttribute('role','radio');});
    cq('.ctor-help').textContent=CTOR_HELP[ctor.mode];
    cq('.ctor-slots').innerHTML=ctor.sel.map((n,i)=>`<div class="ctor-slot"><span class="narr-step">${i+1}</span><div class="ctor-slot-main"><button type="button" class="narr-name-btn" data-narr-card="${escape(n.id)}" lang="ar" dir="rtl">${escape(shortNasab(n.name))}</button>${n.death?`<small>ум. ${escape(n.death)}</small>`:''}</div><button type="button" class="ctor-remove" data-ctor-remove="${i}" aria-label="Убрать">×</button></div>`
      +(i<ctor.sel.length-1?`<label class="ctor-edge"><span>${ctor.mode==='seq'?`${i+1}-й получил от ${i+2}-го:`:'Связь между ними — как передано:'}</span><select data-ctor-form="${i}">${CTOR_FORMS.map(([v,t])=>`<option value="${v}"${(ctor.forms[i]||'')===v?' selected':''}>${t}</option>`).join('')}</select></label>`:'')).join('');
    const input=cq('.ctor-input');input.hidden=ctor.sel.length>=5;input.placeholder=`Имя ${ORD[ctor.sel.length]||''} передатчика — по-арабски или по-русски`;
    cq('.ctor-go').disabled=ctor.sel.length<2;cq('.ctor-go').textContent=ctor.sel.length<2?`Выберите ещё ${2-ctor.sel.length} — и можно искать`:'Найти хадисы';
  }
  ctorDialog.addEventListener('click',e=>{
    const m=e.target.closest('[data-ctor-mode]');if(m){ctor.mode=m.dataset.ctorMode;cq('.ctor-out').innerHTML='';renderCtor();return;}
    const r=e.target.closest('[data-ctor-remove]');if(r){const i=+r.dataset.ctorRemove;ctor.sel.splice(i,1);ctor.forms.splice(Math.max(0,i-1),1);cq('.ctor-out').innerHTML='';renderCtor();return;}
    const s=e.target.closest('[data-ctor-pick]');if(s){const x=JSON.parse(s.dataset.ctorPick);if(ctor.sel.some(n=>n.id===x.id)){toast('Он уже в цепи');return;}ctor.sel.push(x);cq('.ctor-input').value='';cq('.ctor-sugg').innerHTML='';cq('.ctor-out').innerHTML='';renderCtor();cq('.ctor-input').focus();return;}
  });
  // a form is a condition between two neighbouring links (owner 29.10: «между передатчиками выбирать связь — ан или хаддасана»):
  // choosing one in «вместе / рядом» switches to «строго по порядку», where the condition applies
  ctorDialog.addEventListener('change',e=>{const f=e.target.closest('[data-ctor-form]');if(f){ctor.forms[+f.dataset.ctorForm]=f.value;cq('.ctor-out').innerHTML='';
    if(f.value&&ctor.mode!=='seq'){ctor.mode='seq';renderCtor();toast('Форма передачи — условие между соседними звеньями: включён режим «Строго по порядку» (1-й передаёт от 2-го)');}}});
  cq('.ctor-input').addEventListener('input',()=>{clearTimeout(ctorSuggTimer);ctorSuggTimer=setTimeout(ctorSuggest,300);});
  async function ctorSuggest(){
    const q=cq('.ctor-input').value.trim(),box=cq('.ctor-sugg'),token=++ctorSuggToken;if(q.length<2){box.innerHTML='';return;}
    box.innerHTML='<p class="notes-hint">Ищу передатчика…</p>';
    let items=[];try{items=(await state.api.narrCands(q,ctor.mode==='seq'&&ctor.sel.length?ctor.sel[ctor.sel.length-1].id:'')).items||[];}catch(_){}
    if(token!==ctorSuggToken)return;
    box.innerHTML=items.length?items.map(x=>`<button type="button" class="ctor-cand" data-ctor-pick='${escape(JSON.stringify({id:x.id,name:x.name,death:x.death}))}'><span lang="ar" dir="rtl">${escape(shortNasab(x.name))}</span><small>${escape([x.kunya,x.death?'ум. '+x.death:''].filter(Boolean).join(' · '))}${x.pairs?` · подряд с предыдущим: ${x.pairs} цеп.`:''}</small></button>`).join(''):'<p class="notes-hint">Такого передатчика не нашлось. Попробуйте полнее: «مالك بن أنس», «Малик ибн Анас».</p>';
  }
  cq('.ctor-go').onclick=runCtor;
  function ctorPlaceBtn(p,list){list.push(p);return `<button type="button" class="takh-num" data-ctor-place="${list.length-1}">${escape(p.n)}</button>`;}
  async function runCtor(){
    if(ctor.sel.length<2)return;const out=cq('.ctor-out'),go=cq('.ctor-go');go.disabled=true;
    out.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Ищу по размеченным иснадам 64 печатей</span></div>';
    let r=null;try{r=await state.api.chainFind(ctor.sel.map(n=>n.id),ctor.mode,ctor.mode==='seq'?ctor.forms.slice(0,ctor.sel.length-1):[]);}catch(error){out.innerHTML=`<p class="notes-hint">${escape(String(error?.message||'Поиск сейчас не удался'))}</p>`;go.disabled=false;return;}
    go.disabled=false;const places=[];
    if(r.missing&&r.missing.length){out.innerHTML=`<p class="notes-hint">У ${escape(ctor.sel.filter(n=>r.missing.includes(String(n.id))).map(n=>shortNasab(n.name)).join(', '))} нет размеченного участия в цепях. Возьмите более полную форму имени.</p>`;return;}
    if(r.mode!=='seq'){
      if(!r.found){out.innerHTML='<p class="takh-empty">Такого сочетания в размеченных иснадах нет.</p><p class="notes-hint">Попробуйте «Вместе в иснаде» вместо «Рядом» или другую форму имени.</p>';return;}
      out.innerHTML=`<p class="ctor-total">Хадисов: <b>${r.found}</b>${r.scanned<r.total?(r.found>=400?' · показаны первые 400 — добавьте звено, чтобы сузить':` · просмотрено ${r.scanned} из ${r.total} мест — добавьте звено, чтобы сузить`):''}</p>`
        +r.books.map(b=>`<section class="takh-block"><p class="takh-book"><b lang="ar" dir="rtl">${escape(b.name)}</b><small>${b.places.length}</small></p><div class="takh-nums">${b.places.map(p=>ctorPlaceBtn({...p,book:b.name},places)).join('')}</div></section>`).join('');
    } else {
      if(!r.total){out.innerHTML='<p class="takh-empty">Цепей с такой конструкцией подряд не нашлось.</p><p class="notes-hint">Проверьте порядок (1-й передаёт ОТ 2-го), снимите формы или переключитесь на «Вместе в иснаде».</p>';return;}
      const hints=(r.avail||[]).map((a,k)=>a.length?`<p class="ctor-hint">${k+1}-й ← ${k+2}-й, встречаются формы:</p><p class="ctor-fpills">${a.slice(0,6).map(f=>`<span class="ctor-fpill"><b lang="ar">${escape(f.ar)}</b><small>${f.count}</small></span>`).join('')}</p>`:'').join('');
      out.innerHTML=`<p class="ctor-total">Цепей: <b>${r.total}</b> · хадисов: <b>${r.hadiths}</b>${r.total>40?' · показаны 40 самых частых':''}</p>${hints}`
        +r.chains.map((c,ci)=>`<section class="takh-block ctor-chain"><div class="ctor-chain-head"><b>${c.n} ${c.n===1?'хадис':c.n<5?'хадиса':'хадисов'}</b>${c.unk?'<span class="ctor-unk">форма передачи в этом своде не размечена</span>':''}</div><div class="ctor-links" dir="rtl">${c.links.map((l,i)=>`${i&&l.ar?`<span class="ctor-form">${escape(l.ar)}</span>`:i?'<span class="ctor-form ctor-form-none">·</span>':''}<button type="button" class="ctor-link" data-narr-card="${escape(l.id)}" lang="ar">${escape(shortNasab(l.name)||'#'+l.id)}</button>`).join('')}</div><details class="ctor-places"><summary>Хадисы с этой цепью (${c.places.length})</summary>${c.places.map(p=>`<span class="ctor-place"><small>${escape(p.book)}</small>${ctorPlaceBtn(p,places)}</span>`).join('')}</details></section>`).join('');
    }
    out.onclick=async e=>{const b=e.target.closest('[data-ctor-place]');if(!b)return;const p=places[+b.dataset.ctorPlace];if(!p)return;
      if(p.code&&state.collections.some(c=>c.id===p.code)){ctorDialog.close();openReader({kind:'hadith',collection:p.code,number:p.n});return;}
      b.disabled=true;try{const leaf=p.leaf||(await state.api.leafByHadith(p.bid,Number(p.n))).leaf;ctorDialog.close();const c=collectionForBid(p.bid,p.book);openNativeBook(p.bid,leaf,c.title,{mark:p.n,arabicTitle:c.arabicTitle});}catch(_){toast('Это место в издании сейчас не открылось');}finally{b.disabled=false;}};
  }
  // ── Имена передатчиков в тексте иснада — кнопки (owner 29.10: «передатчики должны быть кликабельны, везде»).
  // The bridge gives the names as the text spells them, with the narrator's number; each is wrapped in place, in order.
  async function linkIsnadNames(box,record,token){
    if(!box||!state.api||typeof state.api.isnadLinks!=='function')return;
    let links=[];try{links=(await state.api.isnadLinks(record.arabic,record.collection,record.number)).links||[];}catch(_){return;}
    if(token!=null&&token!==state.readerToken)return;if(!box.isConnected)return;
    const walker=()=>{const nodes=[];const w=document.createTreeWalker(box,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement&&n.parentElement.closest('button,.isnad-name')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});let n;while((n=w.nextNode()))nodes.push(n);return nodes;};
    // the name is found whatever its vowels: «سماك بن حرب» meets «سِمَاكِ بْنِ حَرْبٍ», «أبو» meets «أَبِي»
    const DIA='[\\u064B-\\u065F\\u0670\\u0640]*';
    const nameRe=s=>{const f=String(s).replace(/[\u064B-\u065F\u0670\u0640]/g,'').replace(/\s+/g,' ').trim();if(!f)return null;
      const word=w=>/^[اأإآ]ب[ويا]$/.test(w)?'[اأإآ]'+DIA+'ب'+DIA+'[وياى]'+DIA:w.split('').map(ch=>(/[اأإآ]/.test(ch)?'[اأإآ]':/[يى]/.test(ch)?'[يى]':/[هة]/.test(ch)?'[هة]':ch.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'))+DIA).join('');
      return new RegExp(f.split(' ').map(word).join('\\s+'));};
    let from={node:null,offset:0};
    // владелец 29.10: «все должны быть передатчики выделены» — и без опознанного номера: такой зовёт выбор из тёзок
    // ищем вперёд от прошлого имени; не нашлось — с начала текста (запасной поиск имён дописывает пропущенных в конец
    // списка: у ат-Тирмизи №5 «قتيبة، وهناد، قالا» разбор отдал одним куском, а «قتيبة» и «هناد» пришли последними)
    const tryLink=(l,re,pos)=>{const nodes=walker();let started=!pos.node;
      for(const node of nodes){if(!started){if(node===pos.node)started=true;else continue;}
        const start=node===pos.node?pos.offset:0,m=re.exec(node.data.slice(start));if(!m)continue;const at=start+m.index;
        const range=document.createRange();range.setStart(node,at);range.setEnd(node,at+m[0].length);
        const b=document.createElement('button');b.type='button';b.className='isnad-name'+(l.id?'':' isnad-name-unknown');if(l.id)b.dataset.narrCard=l.id;else b.dataset.narrSaid=l.said;b.setAttribute('aria-label',l.id?'Передатчик — открыть карточку':'Передатчик не опознан однозначно — выбрать из тёзок');
        try{range.surroundContents(b);}catch(_){return null;}
        const next=b.nextSibling;return next&&next.nodeType===3?{node:next,offset:0}:{node:null,offset:0};}
      return null;};
    for(const l of links){if(!l.said)continue;const re=nameRe(l.said);if(!re)continue;
      const r=tryLink(l,re,from);if(r){from=r;continue;}if(from.node)tryLink(l,re,{node:null,offset:0});}
  }
  // ── Карточка передатчика — одна на весь новый вид: из текста иснада, «Передатчиков», конструктора, закладок.
  const nCardDialog=document.createElement('dialog');nCardDialog.className='native-assistant-dialog narr-dialog ncard-dialog';
  nCardDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('helper')}</span><h2>Передатчик</h2><button type="button" class="help-q" data-help="ncard" aria-label="Справка по этой странице">?</button><button type="button" class="native-assistant-close ncard-close" aria-label="Закрыть">×</button></header><div class="notes-body ncard-body"></div></div>`;
  document.body.appendChild(nCardDialog);nCardDialog.querySelector('.ncard-close').onclick=()=>nCardDialog.close();
  let nCardToken=0;
  async function openNarratorCard(id){
    const body=nCardDialog.querySelector('.ncard-body'),token=++nCardToken;
    body.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Открываю карточку</span></div>';
    if(!nCardDialog.open)nCardDialog.showModal();
    let c=null;try{c=await state.api.narrCard(id);}catch(error){if(token===nCardToken)body.innerHTML=`<p class="notes-hint">${escape(String(error?.message||'Карточка сейчас не открылась'))}</p>`;return;}
    if(token!==nCardToken)return;
    const v=c.verdict||{kind:'none'},term=v.kind==='sahabi'?'صحابي':String(v.v||'').split(' — ')[0].trim(),reason=v.kind==='sahabi'?'الصحابة عدول — сподвижники надёжны по единогласию учёных (иджма)':((String(v.v||'').match(/\(([^()]*)\)\s*$/)||[])[1]||'');
    const T=c.testimonies||[],mut=T.filter(t=>t.mut),rest=T.filter(t=>!t.mut);
    const tline=t=>`<p lang="ar" dir="rtl"><b>${escape(t.critic)}:</b> ${escape(t.text)} <span class="src-tag src-${t.src}" dir="ltr">${t.src==='sunnah'?'sunnah.com':'Мактаба'}</span></p>`;
    const people=(list,total,label)=>list&&list.length?`<section class="ncard-sec"><h3>${label} <small>${total>list.length?`${list.length} из ${total}, самые частые в наших цепях`:total}</small></h3><div class="ncard-people">${list.map(p=>`<button type="button" class="ncard-person" data-narr-card="${escape(p.id)}"><span lang="ar" dir="rtl">${escape(shortNasab(p.name)||'#'+p.id)}</span>${p.ru?`<em class="narr-ru">${escape(p.ru)}</em>`:''}<small>${[p.death?'ум. '+escape(p.death):'',p.n?escape(p.n)+' в цепях':''].filter(Boolean).join(' · ')}</small></button>`).join('')}</div></section>`:'';
    const fav=favNarrators().some(f=>String(f.id)===String(c.id));
    body.innerHTML=`<article class="ncard narr-${v.kind}"><h1 class="ncard-name" lang="ar" dir="rtl">${escape(c.full||c.name)}</h1>${c.ru?`<p class="narr-ru ncard-ru">${escape(c.ru)}</p>`:''}`
      +`${(c.kunya||c.nisba)?`<p class="narr-sub" lang="ar" dir="rtl">${escape([c.kunya,c.nisba].filter(Boolean).join(' · '))}</p>`:''}`
      +`<p class="narr-meta">${[c.death?'ум. '+escape(c.death):'',c.tabaqa?'табака <bdi lang="ar">'+escape(c.tabaqa)+'</bdi>':''].filter(Boolean).join(' · ')}</p>`
      +`<p class="narr-verdict"><span class="narr-badge">${escape(VERDICT_RU[v.kind]||'')}${term?` <bdi lang="ar">${escape(term)}</bdi>`:''}</span>${v.kind==='sahabi'||v.kind==='none'?'':`<span class="narr-count"><bdi lang="ar">توثيق</bdi> <b>${v.nT}</b> из 48${v.sahihayn?' · в Сахихайн':''}${v.nJ?` · джарх <b>${v.nJ}</b>`:''}</span>`}</p>`
      +`${reason?`<p class="narr-v">Основание: <bdi dir="ltr">${escape(reason)}</bdi></p>`:''}${v.note?`<p class="narr-note">${escape(v.note)}</p>`:''}`
      +`<div class="ncard-actions"><button type="button" class="ncard-fav${fav?' on':''}">${icon('star')}${fav?'В избранном':'В избранное'}</button><button type="button" class="ncard-ctor">${icon('grid')}В конструктор цепи</button></div>`
      +`<p class="narr-cards">Карточки: <a class="src-tag src-maktaba" href="${escape((c.links||{}).maktaba||'')}">Мактаба</a>${c.links&&c.links.sunnah?` <a class="src-tag src-sunnah" href="${escape(c.links.sunnah)}">sunnah.com</a>`:''}</p></article>`
      +(mut.length?`<section class="ncard-sec"><h3>Свидетельства 48 муʿтабаров <small>${mut.length}</small></h3>${mut.map(tline).join('')}</section>`:'')
      +(rest.length?`<details class="ncard-sec ncard-rest"><summary>Другие учёные — справочно, в счёт не идут <small>${rest.length}</small></summary>${rest.map(tline).join('')}</details>`:'')
      +(!T.length?'<p class="notes-hint">Свидетельств о нём в карточках Мактабы и sunnah.com нет.</p>':'')
      +people(c.teachers,c.teachersTotal,'Учителя — от кого передаёт')+people(c.students,c.studentsTotal,'Ученики — кто передаёт от него')
      +((c.teachers||[]).length||(c.students||[]).length?'<p class="notes-hint">Учителя и ученики — по «Тахзиб аль-Камаль» аль-Мизи; число — сколько раз пара встречается в наших размеченных цепях.</p>':'');
    body.scrollTop=0;
    body.querySelector('.ncard-fav').onclick=e=>{const on=toggleFavNarrator({id:c.id,full:c.full,name:c.name,kunya:c.kunya,death:c.death,hajar:c.hajar});e.currentTarget.classList.toggle('on',on);e.currentTarget.lastChild.textContent=on?'В избранном':'В избранное';toast(on?'Передатчик в избранном — он в «Закладках»':'Убрано из избранного');};
    body.querySelector('.ncard-ctor').onclick=()=>{nCardDialog.close();openChainCtor({mode:'any',sel:[{id:String(c.id),name:c.full||c.name,death:c.death||''}],forms:[]});};
  }
  async function openNarratorNamesakes(said){
    const body=nCardDialog.querySelector('.ncard-body'),token=++nCardToken;if(!nCardDialog.open)nCardDialog.showModal();
    body.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Ищу, кто это</span></div>';
    let items=[];try{items=(await state.api.narrCands(said,'')).items||[];}catch(_){}if(token!==nCardToken)return;
    body.innerHTML=`<p class="ncard-said" lang="ar" dir="rtl">${escape(said)}</p><p class="notes-hint">В этой цепи имя не опознано однозначно. ${items.length?'Подходящие передатчики — выберите:':'В нашей базе подходящих не нашлось.'}</p>`
      +items.map(x=>`<button type="button" class="ctor-cand" data-narr-card="${escape(String(x.id))}"><span lang="ar" dir="rtl">${escape(shortNasab(x.name))}</span><small>${escape([x.kunya,x.death?'ум. '+x.death:''].filter(Boolean).join(' · '))}</small></button>`).join('');
  }
  document.addEventListener('click',e=>{const t=e.target.closest&&e.target.closest('[data-narr-said]');if(!t||t.dataset.narrCard)return;e.preventDefault();e.stopPropagation();openNarratorNamesakes(t.dataset.narrSaid);},true);
  // any [data-narr-card] anywhere in the new view opens the card
  document.addEventListener('click',e=>{const t=e.target.closest&&e.target.closest('[data-narr-card]');if(!t||!t.dataset.narrCard)return;e.preventDefault();e.stopPropagation();openNarratorCard(t.dataset.narrCard);},true);
  // ── Справка «?» по странице (owner 29.10: «кнопочка вопроса общей справки по странице — про всё, что может вызывать
  // вопросы»): one dialog, the text depends on where the person is.
  const HELP={
    reader:['Карточка хадиса',[
      ['Текст','Сверху — арабский оригинал. Цепочка передатчиков (иснад) чуть приглушена, слова хадиса (матн) ярче, слова собирателя после хадиса (قال أبو عيسى، وفي الباب…) — голубоватым. Это можно выключить: «Ещё» → «Выделять иснад и матн».'],
      ['Под текстом','▶ — озвучить, затем копировать, поделиться, ⋯ — все инструменты. Ниже — «Где ещё передаётся»: сборник и номера, номер нажимается.'],
      ['Название книги и номер','Название книги вверху открывает книгу с начала, номер — этот хадис на странице книги. То же — «Читать в книге».'],
      ['Перевод ИИ','Если готового перевода нет, «Перевести ИИ» переводит хадис и сохраняет перевод для всех — следующему он откроется сразу. Перевод черновой.'],
      ['Назад','Стрелка вверху и кнопка «назад» Телеграма возвращают к предыдущему хадису, если вы пришли из другого.'],
      ['Имена в иснаде','Подчёркнутое имя — кнопка: откроется карточка передатчика с итогом по 48 муʿтабарам и свидетельствами.'],
      ['Хадис · Читать в книге · О книге','«Читать в книге» открывает этот хадис на странице печатного издания — с соседним текстом и главами. «О книге» — описание и ссылки на источник.'],
      ['Перевод','Кнопка «Перевод» прячет и показывает русский перевод.'],
      ['Инструменты','Передатчики — цепь и итог о каждом звене; Где ещё передаётся — тахридж; Пояснение — ИИ-помощник; Озвучить; Мои заметки; Копировать; Поделиться ссылкой; Без огласовок; страница на sunnah.com.'],
      ['Закладка','Значок вверху справа сохраняет хадис в «Закладки».']]],
    narrators:['Передатчики',[
      ['Итог о звене','Надёжность считается по свидетельствам 48 муʿтабаров — ранних авторитетных критиков: нужно два подтверждения (توثيق). Если передатчик в Сахихайн и нет тяжкого джарха — тоже два. Ибн Хаджар и аз-Захаби — поздние своды, в счёт не идут, показаны справочно. Сподвижники — الصحابة عدول.'],
      ['Цвета','Зелёный — надёжный, жёлтый — спорный, оранжевый — слабый, серый — не установлено. Это оценка звеньев, а не приговор хадису.'],
      ['Сводка сверху','«надёжных», «спорных» и другие — кнопки: нажатие ведёт к этим звеньям, повторное — к следующему.'],
      ['Как передано','Между звеньями — форма передачи: حدّثنا «рассказал нам — слышал», أخبرنا «сообщил — чтение шейху», عن «от» — без уточнения, как получил. Слышание — сплошная линия, «عن» — пунктир. Мудаллис, передающий через «عن», помечен.'],
      ['Сверить с текстом','Звено из готовой разметки цепи, которого нет в тексте иснада или которое не сходится по годам, помечено: итог по нему не учитывайте.'],
      ['Оригинал','«Развернуть иснад» и «Развернуть хадис» показывают оригинал прямо здесь; «Свернуть всё» прячет.'],
      ['Свидетельства','С карточек передатчиков Мактабы и sunnah.com; у каждого — метка источника. Имя передатчика — кнопка его карточки.']]],
    ncard:['Карточка передатчика',[
      ['Итог','Тот же расчёт, что в «Передатчиках»: два подтверждения от 48 муʿтабаров; Сахихайн без тяжкого джарха — тоже два; поздние своды не в счёт.'],
      ['Свидетельства','Сначала — 48 муʿтабаров, ниже — другие учёные, справочно. Метка «Мактаба» или «sunnah.com» — откуда взято свидетельство.'],
      ['Учителя и ученики','По «Тахзиб аль-Камаль» аль-Мизи. Число — сколько раз пара встречается в наших цепях. Имя — кнопка его карточки.'],
      ['В конструктор цепи','Откроет конструктор с этим передатчиком: добавьте второго — и найдутся хадисы, где они вместе.']]],
    quran:['Чтение Корана',[
      ['Сверху','Название суры — открывает всю суру лентой; ‹ › — предыдущий и следующий аят; ⚙ — настройки чтения.'],
      ['Слова','Каждое слово нажимается: перевод в аяте, словарная форма из Арабуса, грамматика, корень. Повторное нажатие закрывает карточку. Отключить — в ⚙.'],
      ['Корень','Нажмите на корень — откроется статья словаря Арабус; рядом — «Места в Коране».'],
      ['Под аятом','▶ — слушать (пауза — тем же значком), подсветка слов идёт по чтению аль-Хусари; затем аят сам переходит к следующему, а кнопка «↩ Вернуться» ведёт назад. Дальше — копировать, поделиться, «Спросить ИИ», ⋯ — тафсир и заметки.'],
      ['Настройки ⚙','Перевод (Кулиев или Абу Адель), чтец, подсветка, «читать дальше», нажатие на слова, листание лентой или свайпами (←→ суры, ↑↓ аяты).'],
      ['Тафсир','Ибн Касир, ас-Саади, Мухтасар — с готовым русским; ат-Табари, аль-Куртуби, аль-Багави — оригинал и «Перевести ИИ».']]],
    grade:['Оценка источника',[
      ['Что это','Эта оценка стоит в самом источнике — в сноске издания, у мухаккика или в своде. Мы показываем её как есть.'],
      ['Проверено ли нами','Нет. Достоверность по этой оценке нами не проверялась. Наш расчёт — в «Передатчиках»: надёжность звеньев по свидетельствам 48 муʿтабаров.']]],
    takhrij:['Где ещё передаётся',[
      ['Что показано','Только тахридж, подтверждённый источником: أطراف и تحفة الأشراف у Бухари, тахкик шейха Шуайба аль-Арнаута у Ахмада и четырёх Сунанов, свод sunnah.one, сноски мухаккиков изданий, аль-Мухаймин. Совпадения «по похожему тексту» не показываем — это были бы догадки.'],
      ['Тот же хадис и шавахид','«Тот же хадис» — тот же текст в других книгах. «Свидетельства (شواهد)» — другие хадисы о том же.'],
      ['Номера','Номер — кнопка. Перед открытием «того же хадиса» текст сверяется: номер из другой печати не откроет чужой хадис.']]],
    ctor:['Конструктор цепи',[
      ['Режимы','«Вместе в иснаде» — все выбранные в одной цепи, в любом порядке. «Рядом» — подряд. «Строго по порядку» — 1-й передаёт от 2-го, 2-й от 3-го…'],
      ['Формы передачи','Между выбранными передатчиками всегда можно задать форму: حدّثنا, أخبرنا, سمعت, عن, «явное слышание — не عن»… Форма — условие между соседними звеньями, поэтому при выборе формы включается «Строго по порядку». Над выдачей видно, какие формы реально встречаются; где форма в своде не размечена, цепь показана с пометкой.'],
      ['Имена','Подбор по-арабски или по-русски; в режиме «по порядку» первыми идут те, кто реально стоит рядом с предыдущим звеном. Имя в выдаче — кнопка карточки передатчика.']]],
    book:['Чтение книги',[
      ['Страница и № хадиса','«Страница» — страница печатного издания. «№ хадиса» — номер хадиса (асара, документа) в книге. Над текстом — номера хадисов, что на этой странице.'],
      ['Оглавление','Разделы книги; у раздела раскрываются главы, есть поиск по главам.'],
      ['Перевод ИИ','Машинный перевод страницы — черновой, сверяйте с оригиналом.'],
      ['Начало и Конец','Первая и последняя страницы издания; стрелки листают.']]],
    main:['Muslimoon',[
      ['Поиск','Пишите слова, фразу или номер: «бухари 1», «2:255». Пример в строке — подсказка, он печатается сам.'],
      ['Во всей Мактабе','Обычный поиск идёт сразу по двум местам: по сборникам хадисов (сверху) и по всем книгам Мактабы — около 8000 (ниже, своим разделом, с кнопкой «Ещё»).'],
      ['Настроить поиск','Где искать (книги, разделы, авторы) и как: по словам, с огласовками, по корню, только матн, передатчик, цепь (конструктор), RAG.'],
      ['ИИ','«Спросить ИИ» превращает строку в вопрос помощнику.'],
      ['Внизу','Библиотека — книги; Закладки — всё избранное; Ещё — настройки.']]]};
  const helpDialog=document.createElement('dialog');helpDialog.className='native-assistant-dialog help-dialog';
  helpDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">?</span><h2></h2><button type="button" class="native-assistant-close help-close" aria-label="Закрыть">×</button></header><div class="notes-body help-body"></div></div>`;
  document.body.appendChild(helpDialog);helpDialog.querySelector('.help-close').onclick=()=>helpDialog.close();
  function openHelp(ctx){const h=HELP[ctx]||HELP.main;helpDialog.querySelector('h2').textContent=h[0];helpDialog.querySelector('.help-body').innerHTML=h[1].map(([t,d])=>`<section class="help-item"><h3>${escape(t)}</h3><p>${escape(d)}</p></section>`).join('');helpDialog.showModal();}
  document.addEventListener('click',e=>{const q=e.target.closest&&e.target.closest('[data-help]');if(!q)return;e.preventDefault();openHelp(q.dataset.help);});
  // «?» in each page's own header, and a quiet one in the corner of the main screen
  (function placeHelp(){
    const add=(sel,ctx,before)=>{const host=document.querySelector(sel);if(!host||host.querySelector('.help-q'))return;const b=document.createElement('button');b.type='button';b.className='help-q';b.dataset.help=ctx;b.setAttribute('aria-label','Справка по этой странице');b.textContent='?';const ref=before?host.querySelector(before):null;ref?host.insertBefore(b,ref):host.appendChild(b);};
    add('#reader .reader-toolbar','reader','#reader-save');document.querySelector('#reader .reader-toolbar .help-q')?.addEventListener('click',e=>{if(state.reader&&state.reader.kind==='quran'){e.stopPropagation();e.preventDefault();openHelp('quran');}},true);
    add('.narr-dialog:not(.takh-dialog):not(.ctor-dialog):not(.ncard-dialog) .native-assistant-head','narrators','.narr-close');
    add('.takh-dialog .native-assistant-head','takhrij','.takh-close');
    add('.ctor-dialog .native-assistant-head','ctor','.ctor-close');
    const corner=document.createElement('button');corner.type='button';corner.className='help-q help-corner';corner.dataset.help='main';corner.setAttribute('aria-label','Справка по странице');corner.textContent='?';document.body.appendChild(corner);
  })();
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
  if(tgBack&&inTelegram){try{tgBack.onClick(()=>{const open=[...document.querySelectorAll('dialog[open]')],top=open[open.length-1];if(top&&top.id==='reader'&&readerBack()){}else if(top)top.close();else showView('search');syncBack();saveSpot();});}catch(_){}}
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
  // «после слов Пророка ﷺ уже другой говорит — это надо выделять» (owner 29.10): the compiler's remark after the matn
  // (قال أبو عيسى، قال هناد في حديثه، وفي الباب عن، هذا حديث حسن…) gets its own colour; nothing is removed or moved.
  const REMARK_DIA='[\\u064B-\\u065F\\u0670\\u0640]*';
  const arPhraseRe=words=>words.split(' ').map(w=>w==='*'?'[^\\s]+':w.split('').map(ch=>(ch==='ا'?'[اأإآ]':ch==='ي'?'[يى]':ch==='ه'?'[هة]':ch)+REMARK_DIA).join('')).join('\\s+');
  const REMARK_RE=new RegExp('('+['قال ابو عيسي','قال ابو داود','قال ابو عبد الرحمن','قال ابو عبد الله','قال ابن ماجه','قال ابو الحسن','وفي الباب عن','هذا حديث حسن','هذا حديث صحيح','هذا حديث غريب','قال * في حديثه'].map(arPhraseRe).join('|')+')');
  function splitRemarks(parts){const out=[];for(const p of parts){if(p.role!=='matn'||!p.text){out.push(p);continue;}
    const m=REMARK_RE.exec(p.text);if(!m||m.index<12){out.push(p);continue;}
    out.push({...p,text:p.text.slice(0,m.index).replace(/\s+$/,'')},{role:'remark',text:p.text.slice(m.index)});}return out;}
  function isnadMarkOn() {try {return localStorage.getItem('muslimoon.isnadMark') !== '0';} catch (_) {return true;}}
  function readerArabicText(record) {
    let parts = Array.isArray(record.parts) ? record.parts.filter(part => part && typeof part.text === 'string' && part.text.trim()) : [];
    if (!parts.length) return record.arabic ? `<div class="reader-arabic" lang="ar" dir="rtl">${textWithNotes(record.arabic,record)}</div>` : '<p class="reader-missing">Арабский текст для этой записи пока недоступен.</p>';
    // The original as one text (owner 29.10: «зачем скрыл иснад? пусть оригинал будет, просто выделяй»): the chain
    // quieter, the words of the hadith brighter; «Выделять иснад и матн» in «Ещё» turns the difference off.
    parts = splitRemarks(parts);
    const roles = new Set(parts.map(part => part.role)), mark = isnadMarkOn() && roles.has('isnad') && roles.has('matn');
    // no labels over the text (owner 29.10: «арабский оригинал лишнее, и так понятно; „иснад приглушённо, матн ярко“ тоже
    // не надо писать тут») — the explanation lives in the page help «?».
    const legend = '';
    const flow = parts.filter(part => part.role !== 'comment').map(part => `<span class="flow-${escape(part.role || 'text')}">${textWithNotes(part.text,record)}</span>`).join(' ');
    const comments = parts.filter(part => part.role === 'comment').map(part => `<section class="comment-block"><p class="part-label">${escape(part.label || 'Комментарий составителя')}</p><div class="reader-arabic" lang="ar" dir="rtl">${textWithNotes(part.text,record)}</div></section>`).join('');
    return legend + `<div class="reader-arabic reader-flow${mark ? ' mark-parts' : ''}" lang="ar" dir="rtl">${flow}</div>` + comments;
  }
  function mountQuranWordsOld(record){
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
  // ── Читалка Корана (owner 29.10 17:30) ─────────────────────────────────────────────────────────────────────────
  const QDEF={words:true,highlight:true,continuous:true,translation:true,nav:'scroll'};
  function quranOpts(){try{return Object.assign({},QDEF,JSON.parse(localStorage.getItem('muslimoon.quranOpts')||'{}'));}catch(_){return {...QDEF};}}
  function saveQuranOpts(o){try{localStorage.setItem('muslimoon.quranOpts',JSON.stringify(o));}catch(_){}}
  const ROMAN=['','I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'];
  // corpus-style tag («V|IMPF|VF:3|3MP|MOOD:IND») → plain Russian lines
  const POSRU={N:'имя (исм)',V:'глагол (фиʿль)',PRON:'местоимение (дамир)',P:'предлог (харф джарр)',CONJ:'союз (харф ʿатф)',ADJ:'прилагательное (сыфа)',PN:'имя собственное',REL:'относительное местоимение',DEM:'указательное местоимение',NEG:'частица отрицания',INTG:'вопросительное слово',T:'наречие времени',LOC:'наречие места',DET:'артикль «аль»',EXP:'частица исключения (истисна)',ACC:'частица «инна» и подобные',REM:'возобновительная частица',SUB:'подчинительная частица',COND:'условная частица',VOC:'звательная частица',EMPH:'усилительная частица',RES:'частица ограничения',FUT:'частица будущего',CERT:'частица утверждения («кад»)',INL:'отдельные буквы (мукаттаʿат)',PRP:'частица цели',SUP:'добавочная частица',ANS:'частица ответа',CAUS:'частица причины',CIRC:'частица состояния',COM:'частица сопровождения',EQ:'частица равенства',EXH:'побудительная частица',EXL:'частица пояснения',INC:'частица начала',INT:'частица толкования',PRO:'частица запрета',RET:'частица отказа',RSLT:'частица следствия',SUR:'частица неожиданности',IMPV:'частица повеления',AMD:'частица поправки',AVR:'частица отвращения',PREV:'частица предотвращения',NV:'имя действия (исм фиʿль)',IMPN:'имя повеления'};
  const plural=(n,one,few,many)=>{const m=n%10,h=n%100;return m===1&&h!==11?one:m>=2&&m<=4&&(h<12||h>14)?few:many;};
  function gramDetail(tag){
    const p=String(tag||'').split('|').filter(Boolean),out=[];if(!p.length)return out;
    // метка разметки по месту: «N|PN|NOM», «P|NEG», «N|MS|NOM|ADJ» — уточнение части речи стоит после N/V/P
    // ACC — и падеж имени, и «частица инна» у харфа: уточнение ищем только среди своих для N и для P (проверка 2:255)
    const SUBN=['PN','PRON','DEM','REL','ADJ','T','LOC','NV','IMPN','INTG','COND'],sub=p.slice(1).find(x=>p[0]==='P'?(POSRU[x]&&!SUBN.includes(x)&&!['NOM','GEN','MS','FS','MP','FP','M','F'].includes(x)):SUBN.includes(x));
    const pos=POSRU[sub]||POSRU[p[0]]||'частица (харф)';out.push(['Часть речи',pos]);
    const has=k=>p.includes(k),val=k=>(p.find(x=>x.startsWith(k+':'))||'').split(':')[1]||'';
    if(has('ACT_PCPL'))out.push(['Вид','действительное причастие (исм фаʿиль)']);if(has('PASS_PCPL'))out.push(['Вид','страдательное причастие (исм мафʿуль)']);if(has('VN'))out.push(['Вид','отглагольное имя (масдар)']);
    if(val('VF'))out.push(['Порода (баб)',ROMAN[+val('VF')]||val('VF')]);
    if(has('PERF'))out.push(['Время','прошедшее (мади)']);if(has('IMPF'))out.push(['Время','настоящее-будущее (мудариʿ)']);if(has('IMPV'))out.push(['Наклонение','повелительное (амр)']);
    if(has('PASS'))out.push(['Залог','страдательный (маджхуль)']);
    const pgn=p.slice(1).find(x=>/^[123]?[MF]?[SDP]?$/.test(x)&&x.length&&/[MFSDP123]/.test(x)&&x!=='P');   // p[0] — часть речи («P» — не «множественное»)
    if(pgn){const per={1:'1-е лицо',2:'2-е лицо',3:'3-е лицо'}[pgn.match(/[123]/)?.[0]]||'',gen={M:'мужской род',F:'женский род'}[pgn.match(/[MF]/)?.[0]]||'',num={S:'единственное число',D:'двойственное число',P:'множественное число'}[pgn.match(/[SDP]/)?.[0]]||'';
      const t=[per,gen,num].filter(Boolean).join(', ');if(t)out.push(['Лицо, род, число',t]);}
    const cs={NOM:'именительный (марфуʿ)',GEN:'родительный (маджрур)',ACC:'винительный (мансуб)'}[p.find(x=>['NOM','GEN','ACC'].includes(x))];if(cs)out.push(['Падеж',cs]);
    const md={IND:'изъявительное (марфуʿ)',SUBJ:'сослагательное (мансуб)',JUS:'усечённое (маджзум)'}[val('MOOD')];if(md)out.push(['Наклонение',md]);
    if(has('INDEF'))out.push(['Определённость','неопределённое (накира, с танвином)']);
    return out;
  }
  function mountQuranWords(record){
    const part=$('.arabic-part',$('#reader-body')),text=$('.reader-arabic',part);if(!part||!text||!record.arabic)return null;
    const panel=document.createElement('aside');panel.className='quran-word-info q-word-sheet';panel.hidden=true;panel.setAttribute('aria-live','polite');part.appendChild(panel);
    let data=null,busy=false,enabled=false,clickable=true,onDisable=()=>{},current=null;
    const close=()=>{panel.hidden=true;current=null;text.querySelectorAll('.quran-word.selected').forEach(w=>w.classList.remove('selected'));};
    async function showWord(item,word){
      if(current===word){close();return;}   // a second tap closes (owner: «нажимаешь второй раз — исчезать должно»)
      current=word;text.querySelectorAll('.quran-word').forEach(w=>w.classList.remove('selected'));word.classList.add('selected');
      const refs=(Array.isArray(item.references)?item.references:[]).filter(ref=>/^\d{1,3}:\d{1,3}$/.test(ref)),g=gramDetail(item.tag);
      panel.hidden=false;
      panel.innerHTML=`<header class="qw-head"><span class="quran-word-name" lang="ar" dir="rtl">${escape(item.text)}</span><button type="button" class="qw-close" aria-label="Закрыть">×</button></header>`
        +(item.translation?`<p class="qw-line"><span>В аяте</span><b>${escape(item.translation)}</b>${item.translationAi?' <span class="src-tag src-ai" dir="ltr">ИИ, черновое</span>':''}</p>`:'')   // нет пословного — строку не показываем (у 770 аятов его нет)
        +`<p class="qw-line qw-dict"><span>Словарная форма</span><b class="qw-lemma" lang="ar" dir="rtl">${escape(item.lemma||'—')}</b><i class="qw-lemma-ru">ищу в Арабусе…</i></p>`
        +(item.root?`<div class="qw-root"><span>Корень</span><button type="button" class="qw-root-btn" lang="ar" dir="rtl">${escape(item.root.split('').join(' '))}</button>${refs.length?`<button type="button" class="qw-refs-btn" aria-expanded="false">Места в Коране · ${refs.length}</button>`:''}</div><div class="qw-refs" hidden>${refs.map(ref=>`<button type="button" data-quran-ref="${escape(ref)}">${escape(ref)}</button>`).join('')}</div><div class="qw-arabus" hidden></div>`:'')
        +(g.length?`<dl class="qw-gram">${g.map(([k,v])=>`<dt>${escape(k)}</dt><dd>${escape(v)}</dd>`).join('')}${Array.isArray(item.parts)&&item.parts.length>1?`<dt>Состав</dt><dd class="qw-parts">${item.parts.map(x=>`<span><b lang="ar" dir="rtl">${escape(x.text)}</b> — ${escape((gramDetail(x.tag)[0]||[])[1]||'')}</span>`).join('')}</dd>`:''}</dl>`:'')
        +`<p class="qw-note"><i>${item.place?'Словарная форма, корень и грамматика — по разметке Quranic Arabic Corpus для этого места аята (как на corpus.quran.com)':'Словарная форма и грамматика — по разметке словоформ Корана (одна на все места этого написания)'}; перевод в аяте сопоставлен по порядку слов; значения — из словаря Арабус, а где его нет — черновые от ИИ.</i></p>`;
      // the word goes up, the card is in view (owner: «камера чуть спускалась, поднимала аят наверх»)
      const scroller=$('#reader-body'),top=word.getBoundingClientRect().top-scroller.getBoundingClientRect().top+scroller.scrollTop-90;
      scroller.scrollTo({top:Math.max(0,top),behavior:reducedMotion.matches?'instant':'smooth'});
      panel.querySelector('.qw-close').onclick=close;
      // владелец 29.10: «места в Коране структурировать как на corpus.quran.com, а не просто цифры»
      const rb=panel.querySelector('.qw-refs-btn');if(rb)rb.onclick=async()=>{const box=panel.querySelector('.qw-refs');box.hidden=!box.hidden;rb.setAttribute('aria-expanded',String(!box.hidden));
        if(box.hidden||box.dataset.forms||!item.place||typeof state.api.rootForms!=='function')return;
        let r=null;try{r=await state.api.rootForms(item.root);}catch(_){}if(current!==word||!r||!r.forms||!r.forms.length)return;box.dataset.forms='1';rb.textContent=`Места в Коране · ${r.total}`;
        const here=`${data.sura}:${data.ayah}:${item.index+1}`;
        box.innerHTML=`<p class="qw-forms-head">Корень <b lang="ar" dir="rtl">${escape(item.root.split('').join(' '))}</b> встречается в Коране ${r.total} ${plural(r.total,'раз','раза','раз')} в ${r.forms.length} ${plural(r.forms.length,'форме','формах','формах')}:</p>`
          +r.forms.map((f,i)=>`<div class="qw-form${f.lemma===item.lemma?' is-this':''}"><button type="button" class="qw-form-btn" data-form="${i}" aria-expanded="false"><span class="qw-form-n">${f.places.length}</span>`
            +`<span class="qw-form-kind">${escape(f.kind)}</span><b lang="ar" dir="rtl">${escape(f.lemma)}</b>${f.sound||f.ru?`<small>${escape([f.sound,f.ru].filter(Boolean).join(' — '))}</small>`:''}</button>`
            +`<div class="qw-form-places" hidden>${f.places.map(pl=>{const [s,a]=pl.split(':');return `<button type="button" data-quran-ref="${s}:${a}" class="${pl===here?'is-here':''}">${escape(pl)}</button>`;}).join('')}</div></div>`).join('');
        box.querySelectorAll('.qw-form-btn').forEach(btn=>btn.onclick=()=>{const pl=btn.nextElementSibling;pl.hidden=!pl.hidden;btn.setAttribute('aria-expanded',String(!pl.hidden));});
        box.querySelectorAll('[data-quran-ref]').forEach(ref=>ref.onclick=async()=>{const [s,a]=ref.dataset.quranRef.split(':').map(Number),token=state.readerToken;ref.disabled=true;try{const verse=await state.api.quranVerse(s,a);if(token===state.readerToken&&$('#reader').open)openReader(verse);}catch(_){toast('Не удалось открыть аят');}finally{ref.disabled=false;}});
      };
      panel.querySelectorAll('[data-quran-ref]').forEach(ref=>ref.onclick=async()=>{const [s,a]=ref.dataset.quranRef.split(':').map(Number),token=state.readerToken;ref.disabled=true;try{const verse=await state.api.quranVerse(s,a);if(token===state.readerToken&&$('#reader').open)openReader(verse);}catch(_){toast('Не удалось открыть аят');}finally{ref.disabled=false;}});
      let arabus=null;const loadArabus=async()=>{if(arabus)return arabus;try{arabus=await state.api.arabus(item.text,item.root,item.lemma);}catch(_){arabus={entries:[]};}return arabus;};
      loadArabus().then(r=>{if(current!==word)return;const e=(r.entries||[])[0],el=panel.querySelector('.qw-lemma-ru');if(!el)return;
        const li=item.lemmaInfo;
        // своя статья по огласованной лемме — первой (коротко: звучание — значение); Арабус — строкой ниже, если его
        // словарная форма совпала с леммой и по огласовке (иначе «سِنَة» дремота получала «سُنَّة» обычай)
        if(li&&li.v&&item.place){panel.querySelector('.qw-lemma').textContent=li.v;el.innerHTML=`${escape(li.t?li.t+' — ':'')}${escape(li.ru||'')}${li.src==='ручная'?'':' <span class="src-tag src-ai" dir="ltr">ИИ, черновое</span>'}`+(e&&e.exact?`<small class="qw-arabus-ru">Арабус: ${escape(cutText(e.ru.replace(/^1\)\s*/,'').split(/;|\d\)/)[0],70))}</small>`:'');}
        else if(e&&e.exact){panel.querySelector('.qw-lemma').textContent=e.ar||item.lemma||'';el.textContent=cutText(e.ru.replace(/^1\)\s*/,''),110)+(li&&li.t?` · звучит: ${li.t}`:'');}
        else if(li&&li.v){panel.querySelector('.qw-lemma').textContent=li.v;el.innerHTML=`${escape(li.t?li.t+' — ':'')}${escape(li.ru||'')}${li.src==='ручная'?'':' <span class="src-tag src-ai" dir="ltr">ИИ, черновое</span>'}`;}
        else if(e&&e.near){panel.querySelector('.qw-lemma').textContent=e.ar||item.lemma||'';el.textContent=cutText(e.ru.replace(/^1\)\s*/,''),110);}
        else el.textContent=(r.entries||[]).length?'статьи этой формы нет — нажмите корень: однокоренные слова':'в Арабусе не нашлось';});
      const root=panel.querySelector('.qw-root-btn');if(root)root.onclick=async()=>{const box=panel.querySelector('.qw-arabus');if(!box.hidden){box.hidden=true;root.classList.remove('on');return;}
        root.classList.add('on');box.hidden=false;box.innerHTML='<p class="notes-hint">Открываю Арабус…</p>';const r=await loadArabus();if(current!==word)return;
        box.innerHTML=(r.entries||[]).length?`<p class="qw-arabus-head">Арабус · словарь</p>${r.entries.map(x=>`<div class="qw-entry"><b lang="ar" dir="rtl">${escape(x.ar)}</b>${x.gram?`<small lang="ar" dir="auto">${escape(x.gram)}</small>`:''}<p>${escape(x.ru)}</p></div>`).join('')}`:'<p class="notes-hint">В Арабусе статьи для этого слова нет.</p>';};
    }
    // владелец 29.10: «предыдущий играл с караоке, переключается на следующий — чтец другой и караоке нету». При автопереходе
    // слова включались дважды разом (mountQuranReader и start), второй вызов видел busy и отвечал false — плеер брал чтеца
    // из настроек без подсветки. Теперь второй вызов ждёт первый.
    let enabling=null;
    async function enable(isClickable){
      clickable=isClickable!==false;if(enabled){text.classList.toggle('words-off',!clickable);return true;}
      if(enabling)return enabling.then(ok=>{if(ok)text.classList.toggle('words-off',!clickable);return ok;});
      const token=state.readerToken;busy=true;let release;enabling=new Promise(r=>release=r);
      try{if(!data)data=await state.api.quranWordData(Number(record.sura),Number(record.ayah),record.arabic);}catch(_){busy=false;enabling=null;release(false);return false;}
      busy=false;enabling=null;if(token!==state.readerToken||!$('#reader').open){release(false);return false;}
      enabled=true;text.replaceChildren();text.classList.toggle('words-off',!clickable);
      for(const item of data.tokens){if(!item.word){text.appendChild(document.createTextNode(item.text));continue;}
        const word=document.createElement('span');word.className='quran-word';word.lang='ar';word.textContent=item.text;word.setAttribute('role','button');word.tabIndex=0;
        word.onclick=()=>{if(clickable)showWord(item,word);};text.appendChild(word);}
      release(true);return true;
    }
    return {enable,words:()=>Array.from(text.querySelectorAll('.quran-word')),onDisable:fn=>{onDisable=fn;},close};
  }
  // ⚙ — all reading settings of the Quran in one place
  const qsDialog=document.createElement('dialog');qsDialog.className='native-assistant-dialog qs-dialog';
  qsDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('settings')}</span><h2>Чтение Корана</h2><button type="button" class="native-assistant-close qs-close" aria-label="Закрыть">×</button></header><div class="notes-body qs-body"></div></div>`;
  document.body.appendChild(qsDialog);qsDialog.querySelector('.qs-close').onclick=()=>qsDialog.close();
  async function openQuranSettings(record){
    const o=quranOpts(),body=qsDialog.querySelector('.qs-body');let srv={qtr:'rus-elmirkuliev',reciter:'',translations:[['rus-elmirkuliev','Кулиев'],['rus-abuadel','Абу Адель']],reciters:[]};
    try{srv=await state.api.quranSettings();}catch(_){}
    const sw=(k,label,sub)=>`<label class="qs-row"><span><b>${label}</b>${sub?`<small>${sub}</small>`:''}</span><button type="button" class="mark-switch" role="switch" data-qs-sw="${k}" aria-checked="${!!o[k]}">${o[k]?'Включено':'Выключено'}</button></label>`;
    body.innerHTML=`<section class="qs-sec"><h3>Перевод</h3><div class="qs-choice">${srv.translations.map(([v,t])=>`<button type="button" data-qs-tr="${v}" class="${srv.qtr===v?'selected':''}">${t}</button>`).join('')}</div>${sw('translation','Показывать перевод','под аятом')}</section>`
      +`<section class="qs-sec"><h3>Чтение вслух</h3><label class="qs-row"><span><b>Чтец</b><small>подсветка слов — по чтению аль-Хусари</small></span><select class="qs-reciter">${srv.reciters.map(([v,t])=>`<option value="${v}"${srv.reciter===v?' selected':''}>${t}</option>`).join('')}</select></label>${sw('highlight','Подсветка слов при чтении','▶ читает голосом аль-Хусари и ведёт по словам')}${sw('continuous','Читать дальше по аятам','с кнопкой «вернуться»')}</section>`
      +`<section class="qs-sec"><h3>Слова и листание</h3>${sw('words','Нажатие на слова','перевод, корень и грамматика слова')}<div class="qs-choice">${[['scroll','Лентой — вверх-вниз'],['swipe','Свайпами — ←→ суры, ↑↓ аяты']].map(([v,t])=>`<button type="button" data-qs-nav="${v}" class="${o.nav===v?'selected':''}">${t}</button>`).join('')}</div></section>`;
    body.onclick=async e=>{const b=e.target.closest('[data-qs-sw],[data-qs-tr],[data-qs-nav]');if(!b)return;const cur=quranOpts();
      if(b.dataset.qsSw){cur[b.dataset.qsSw]=!cur[b.dataset.qsSw];saveQuranOpts(cur);b.setAttribute('aria-checked',String(cur[b.dataset.qsSw]));b.textContent=cur[b.dataset.qsSw]?'Включено':'Выключено';}
      else if(b.dataset.qsNav){cur.nav=b.dataset.qsNav;saveQuranOpts(cur);body.querySelectorAll('[data-qs-nav]').forEach(x=>x.classList.toggle('selected',x===b));}
      else if(b.dataset.qsTr){try{await state.api.quranSettings({qtr:b.dataset.qsTr});}catch(_){}body.querySelectorAll('[data-qs-tr]').forEach(x=>x.classList.toggle('selected',x===b));}
      qsDirty=true;};
    body.querySelector('.qs-reciter').onchange=async e=>{try{await state.api.quranSettings({reciter:e.target.value});}catch(_){}qsDirty=true;};
    qsDirty=false;qsDialog.showModal();
    qsDialog.onclose=()=>{if(qsDirty&&state.reader&&state.reader.kind==='quran'){stopReaderAudio();state.api.quranVerse(Number(state.reader.sura),Number(state.reader.ayah)).then(v=>openReader(v,{fromHistory:true})).catch(()=>{});}};
  }
  let qsDirty=false;
  // the whole sura as one scroll (owner: «название суры — кнопка: открывается вся сура, быстро вниз по аятам»)
  const suraDialog=document.createElement('dialog');suraDialog.className='native-assistant-dialog sura-dialog';
  suraDialog.innerHTML=`<div class="native-assistant-shell"><header class="native-assistant-head"><span class="book-seal">${icon('quran')}</span><h2>Сура</h2><button type="button" class="native-assistant-close sura-close" aria-label="Закрыть">×</button></header><div class="notes-body sura-body"></div></div>`;
  document.body.appendChild(suraDialog);suraDialog.querySelector('.sura-close').onclick=()=>suraDialog.close();
  let suraAudio=null,suraGen=0,suraStopUi=()=>{};
  function suraStop(){suraGen++;if(suraAudio){suraAudio.pause();suraAudio.removeAttribute('src');suraAudio=null;}suraStopUi();}
  const arDigits=n=>String(n).replace(/\d/g,d=>'٠١٢٣٤٥٦٧٨٩'[d]);
  suraDialog.addEventListener('close',()=>suraStop());
  async function openSuraList(sura,ayah){
    const body=suraDialog.querySelector('.sura-body');body.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Открываю суру</span></div>';if(!suraDialog.open)suraDialog.showModal();
    let r=null;try{r=await state.api.suraVerses(sura);}catch(_){body.innerHTML='<p class="notes-hint">Суру сейчас не удалось открыть.</p>';return;}
    suraDialog.querySelector('h2').textContent=`Сура ${r.sura} · ${r.name}`;const showTr=quranOpts().translation;
    body.innerHTML=`<div class="sura-nav">${r.sura>1?`<button type="button" data-sura-go="${r.sura-1}">‹ Сура ${r.sura-1}</button>`:'<span></span>'}${r.sura<114?`<button type="button" data-sura-go="${r.sura+1}">Сура ${r.sura+1} ›</button>`:''}</div>`
      +r.verses.map(v=>`<article class="sura-ayah${v.a===ayah?' current':''}" data-sura-ayah="${v.a}"><p class="sura-ar" lang="ar" dir="rtl"><span class="sura-num">﴿${arDigits(v.a)}﴾</span> ${escape(v.text)}</p>${showTr&&v.ru?`<p class="sura-ru">${v.a}. ${escape(v.ru)}</p>`:''}</article>`).join('');
    const cur=body.querySelector('.sura-ayah.current');if(cur)cur.scrollIntoView({block:'center'});else body.scrollTop=0;
    // ▶ в окне суры (владелец 29.10): тихая круглая кнопка в углу; читает с текущего аята дальше, читаемый аят подсвечен
    suraStop();let sp=suraDialog.querySelector('.sura-play');if(!sp){sp=document.createElement('button');sp.type='button';sp.className='sura-play';suraDialog.querySelector('.native-assistant-shell').appendChild(sp);}
    const spIcon=on=>{sp.innerHTML=on?'<svg class="icon" aria-hidden="true"><path d="M8 5.5h3v13H8zM13 5.5h3v13h-3z" fill="currentColor"/></svg>':icon('play');sp.setAttribute('aria-label',on?'Пауза':'Слушать суру');sp.classList.toggle('playing',!!on);};spIcon(false);
    const playFrom=async i=>{const v=r.verses[i];if(!v){suraStop();return;}const gen=++suraGen;
      body.querySelectorAll('.sura-ayah.playing').forEach(x=>x.classList.remove('playing'));const art=body.querySelector(`[data-sura-ayah="${v.a}"]`);if(art){art.classList.add('playing');art.scrollIntoView({block:'center',behavior:reducedMotion.matches?'instant':'smooth'});}
      let info=null;try{info=await state.api.quranAudioInfo(r.sura,v.a,quranOpts().highlight?'Husary_128kbps':'');}catch(_){toast('Аудио аята не загрузилось');suraStop();return;}if(gen!==suraGen)return;
      suraAudio=new Audio(info.url);suraAudio.onended=()=>{if(gen===suraGen)playFrom(i+1);};suraAudio.onerror=()=>{if(gen===suraGen){toast('Аудио недоступно');suraStop();}};
      try{await suraAudio.play();spIcon(true);}catch(_){suraStop();}};
    sp.onclick=()=>{if(suraAudio&&!suraAudio.paused){suraAudio.pause();spIcon(false);return;}if(suraAudio&&suraAudio.paused&&suraAudio.currentTime>0){suraAudio.play().then(()=>spIcon(true)).catch(()=>{});return;}
      const curA=body.querySelector('.sura-ayah.current'),i=curA?Math.max(0,r.verses.findIndex(v=>v.a===+curA.dataset.suraAyah)):0;playFrom(i);};
    suraStopUi=()=>{spIcon(false);body.querySelectorAll('.sura-ayah.playing').forEach(x=>x.classList.remove('playing'));};
    body.onclick=async e=>{const go=e.target.closest('[data-sura-go]');if(go){openSuraList(+go.dataset.suraGo,0);return;}
      const art=e.target.closest('[data-sura-ayah]');if(!art)return;suraStop();try{const v=await state.api.quranVerse(r.sura,+art.dataset.suraAyah);suraDialog.close();openReader(v);}catch(_){toast('Аят не открылся');}};
  }
  // Тафсир аята — inside the reader, under the translation
  async function openTafsir(record,key,lang){
    const body=$('#reader-body');let box=$('.q-tafsir',body);if(!box){box=document.createElement('section');box.className='q-tafsir';($('.q-return',body)||$('.q-status',body)||$('.reader-actions',body)||$('#reader-translation',body)).after(box);}
    box.innerHTML='<div class="native-chat-pending"><span class="think-dots"><i></i><i></i><i></i></span><span class="think-text">Загружаю тафсир</span></div>';box.scrollIntoView({block:'start',behavior:reducedMotion.matches?'instant':'smooth'});
    const token=state.readerToken;let r=null;try{r=await state.api.tafsir(record.sura,record.ayah,key||'',lang||'ru');}catch(error){if(token===state.readerToken)box.innerHTML=`<p class="notes-hint">${escape(String(error?.message||'Тафсир сейчас не загрузился'))}</p>`;return;}
    if(token!==state.readerToken)return;
    box.innerHTML=`<header class="qt-head"><h3>Тафсир</h3><button type="button" class="qw-close qt-close" aria-label="Свернуть тафсир">×</button></header><div class="qs-choice qt-list">${r.list.map(t=>`<button type="button" data-tf="${t.key}" class="${t.key===r.key?'selected':''}">${escape(t.name)}${t.key===r.recommended?' ✓':''}</button>`).join('')}</div>`
      +`<div class="qs-choice qt-lang"><button type="button" data-tl="ru" class="${r.lang==='ru'?'selected':''}"${r.hasRu?'':' disabled'}>Русский${r.hasRu?'':' — нет готового'}</button><button type="button" data-tl="ar" class="${r.lang==='ar'?'selected':''}">Оригинал</button></div>`
      +`<div class="qt-text"${r.lang==='ar'?' lang="ar" dir="rtl"':''}>${escape(r.text||'Для этого аята в своде текста нет.')}</div>`
      +(r.lang==='ar'&&r.text?'<button type="button" class="ai-tr-again qt-ai">Перевести ИИ (сохранится для всех)</button><div class="qt-tr"></div>':'');
    box.querySelector('.qt-close').onclick=()=>box.remove();
    box.querySelectorAll('[data-tf]').forEach(b=>b.onclick=()=>openTafsir(record,b.dataset.tf,r.lang));
    box.querySelectorAll('[data-tl]').forEach(b=>b.onclick=()=>openTafsir(record,r.key,b.dataset.tl));
    const ai=box.querySelector('.qt-ai');if(ai)ai.onclick=async()=>{ai.disabled=true;ai.textContent='Перевожу…';try{const t=await state.api.translate(r.text,'tafsir_'+r.key,record.sura+':'+record.ayah);box.querySelector('.qt-tr').innerHTML=`<p class="nb-tr-label">Перевод ИИ — черновой, сверяйте с оригиналом</p><div class="qt-text">${escape(allahName(t.translation))}</div>`;ai.remove();}catch(error){ai.disabled=false;ai.textContent='Перевести ИИ';toast(String(error?.message||'Перевод недоступен'));}};
  }
  let stopReaderAudio=()=>{},quranContinuous=false,quranReturn=null;
  function mountQuranReader(record,options){
    const body=$('#reader-body'),o=quranOpts(),s=Number(record.sura),a=Number(record.ayah);
    // header: the sura is a button; ‹ › and ⚙ on the right; nothing else above the ayah
    const src=$('.reader-source',body);src.classList.add('quran-head');
    const t=$('.source-ru',src);if(t){t.classList.add('src-link');t.setAttribute('role','button');t.tabIndex=0;t.title='Вся сура';t.onclick=()=>openSuraList(s,a);}
    src.insertAdjacentHTML('beforeend',`<span class="qh-nav"><button type="button" class="qh-btn" data-qnav="-1" aria-label="Предыдущий аят"${s===1&&a===1?' disabled':''}>‹</button><button type="button" class="qh-btn" data-qnav="1" aria-label="Следующий аят"${s===114&&a===6?' disabled':''}>›</button><button type="button" class="qh-btn qh-gear" aria-label="Настройки чтения">${icon('settings')}</button></span>`);
    const go=async dir=>{stopReaderAudio();try{const next=await state.api.quranNeighbor(s,a,dir);if(next)openReader(next,{fromHistory:true});else toast(dir>0?'Это последний аят Корана':'Это первый аят Корана');}catch(_){toast('Соседний аят не загрузился');}};
    src.querySelectorAll('[data-qnav]').forEach(b=>b.onclick=()=>go(+b.dataset.qnav));src.querySelector('.qh-gear').onclick=()=>openQuranSettings(record);
    $('.reader-translation-control',body)?.remove();
    const tp=$('#reader-translation',body);if(tp){tp.hidden=!o.translation;const lab=$('.reader-language',tp);if(lab)state.api.quranSettings().then(r=>{lab.textContent='ПЕРЕВОД · '+((r.translations.find(x=>x[0]===r.qtr)||[])[1]||'').toUpperCase();}).catch(()=>{});}
    // the row under the ayah: ▶ (prominent), copy, share, ✦ ask AI, ⋯
    const bar=document.createElement('div');bar.className='reader-actions quran-actions';
    bar.innerHTML=`<button type="button" class="q-play" aria-label="Слушать аят">${icon('play')}</button><button type="button" data-act="copy" aria-label="Копировать">${icon('copy')}</button><button type="button" data-act="share" aria-label="Поделиться">${icon('share')}</button><button type="button" data-act="ai" class="q-ai" aria-label="Спросить ИИ об аяте">${icon('spark')}<span>Спросить ИИ</span></button><button type="button" data-act="more" aria-label="Все инструменты" aria-expanded="false">${icon('more')}</button>`;
    // ряд кнопок — в конце текстового блока, после перевода (владелец 29.10)
    ($('#reader-translation',body)||$('.arabic-part',body)).after(bar);const status=document.createElement('p');status.className='q-status';bar.after(status);
    if(quranReturn&&(quranReturn.sura!==s||quranReturn.ayah!==a)){const back=document.createElement('button');back.type='button';back.className='q-return';back.textContent=`↩ Вернуться к аяту ${quranReturn.sura}:${quranReturn.ayah}`;status.after(back);
      back.onclick=async()=>{stopReaderAudio();const r=quranReturn;quranReturn=null;try{openReader(await state.api.quranVerse(r.sura,r.ayah),{fromHistory:true});}catch(_){}};}
    bar.onclick=e=>{const b=e.target.closest('[data-act]');if(!b)return;const act=b.dataset.act;
      if(act==='more'){const d=$('.reader-tools-disclosure',body);if(!d)return;d.open=!d.open;b.setAttribute('aria-expanded',String(d.open));if(d.open)d.scrollIntoView({block:'nearest'});return;}
      if(act==='ai'){invokeTool('askAi',record);return;}invokeTool(act,record);};
    const words=mountQuranWords(record);if(!words)return;
    if(o.words||o.highlight)words.enable(o.words);
    // ▶ / ⏸: highlight by default (al-Husary's timings), then the next ayah, with «вернуться»
    const play=bar.querySelector('.q-play');let audio=null,generation=0,paused=false;
    const setBtn=st=>{play.classList.toggle('playing',st==='playing');play.innerHTML=st==='playing'?'<svg class="icon" aria-hidden="true"><path d="M8 5.5h3v13H8zM13 5.5h3v13h-3z" fill="currentColor"/></svg>':icon('play');play.setAttribute('aria-label',st==='playing'?'Пауза':'Слушать аят');};
    const clearHl=()=>words.words().forEach(w=>w.classList.remove('audio-current'));
    function stop(msg){generation++;if(audio){audio.pause();audio.removeAttribute('src');audio.load();audio=null;}paused=false;clearHl();setBtn('stopped');if(msg!=null)status.textContent=msg;}
    stopReaderAudio=()=>stop('');
    async function finish(id){if(id!==generation)return;const cur=quranOpts();clearHl();
      if(!cur.continuous){stop('Аят прочитан.');return;}
      try{const next=await state.api.quranNeighbor(s,a,1);if(id!==generation)return;if(!next){stop('Это последний аят Корана.');return;}
        if(!quranReturn)quranReturn={sura:s,ayah:a};if(audio){audio.pause();audio=null;}openReader(next,{autoAudio:'play',fromHistory:true});}catch(_){stop('Следующий аят не загрузился.');}}
    async function start(){
      if(audio&&!paused){audio.pause();paused=true;setBtn('paused');status.textContent='Пауза';return;}
      if(audio&&paused){try{await audio.play();paused=false;setBtn('playing');status.textContent=status.dataset.playing||'';}catch(_){}return;}
      stop();const id=++generation,cur=quranOpts();setBtn('playing');status.textContent='Готовлю аудио…';
      try{let info=null,hl=false;
        if(cur.highlight&&await words.enable(cur.words)){try{info=await state.api.quranTimedAudio(s,a,words.words().length);hl=true;}catch(_){info=null;}}
        // с подсветкой читает аль-Хусари; где для аята нет разметки времени — тот же аль-Хусари, только без подсветки
        if(!info)info=await state.api.quranAudioInfo(s,a,cur.highlight?'Husary_128kbps':'');if(id!==generation)return;
        const player=new Audio();audio=player;player.preload='auto';player.src=info.url;
        player.addEventListener('error',()=>{if(id===generation)stop('Аудио недоступно — проверьте соединение.');});
        player.addEventListener('ended',()=>finish(id));
        if(hl){await new Promise((ok,bad)=>{const tm=setTimeout(()=>bad(Error('Аудио не отвечает')),20000);player.addEventListener('loadedmetadata',()=>{clearTimeout(tm);ok();},{once:true});player.addEventListener('error',()=>{clearTimeout(tm);bad(Error('Аудио недоступно'));},{once:true});});
          if(id!==generation)return;player.currentTime=info.start/1000;
          player.addEventListener('timeupdate',()=>{if(id!==generation)return;const now=player.currentTime*1000;if(now>=info.end){finish(id);return;}
            const seg=info.segments.find(([,f,t])=>now>=f&&now<t),idx=seg?seg[0]-1:-1;words.words().forEach((w,i)=>w.classList.toggle('audio-current',i===idx));});}
        await player.play();if(id!==generation)return;
        status.dataset.playing=`${info.reciter}${hl?' · подсветка слов':cur.highlight?' · для этого аята подсветки нет':''}${info.fallback?' · запасной чтец для этой суры':''}`;status.textContent=status.dataset.playing;
      }catch(error){if(id===generation)stop(String(error?.message||'Не удалось воспроизвести')+'.');}
    }
    play.onclick=start;
    if(options&&options.autoAudio)start();
    // swipes (in ⚙): ←→ suras, ↑↓ ayahs
    if(o.nav==='swipe'){let x0=0,y0=0,t0=0;body.ontouchstart=e=>{const p=e.touches[0];x0=p.clientX;y0=p.clientY;t0=Date.now();};
      body.ontouchend=async e=>{const p=e.changedTouches[0],dx=p.clientX-x0,dy=p.clientY-y0;if(Date.now()-t0>600)return;
        if(Math.abs(dx)>70&&Math.abs(dy)<50){const ns=s+(dx<0?1:-1);if(ns<1||ns>114)return;stopReaderAudio();try{openReader(await state.api.quranVerse(ns,1),{fromHistory:true});}catch(_){}return;}
        const atEnd=body.scrollTop+body.clientHeight>=body.scrollHeight-4,atTop=body.scrollTop<=2;
        if(dy<-70&&Math.abs(dx)<50&&atEnd)go(1);else if(dy>70&&Math.abs(dx)<50&&atTop)go(-1);};}
    else{body.ontouchstart=null;body.ontouchend=null;}
  }
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
    $('#reader-body').setAttribute('aria-busy','false');$('#reader-body').classList.toggle('is-quran',record.kind==='quran');
    $('#reader-body').innerHTML = `<div class="reader-source"><span class="book-seal">${icon(record.kind === 'quran' ? 'quran' : 'book')}</span>${sourceLine(bookSource,record.kind==='quran'?'':arabicTitleOf(record),number,'reader-source-text')}</div>${record.kind==='hadith'&&!record.isExcerpt&&record.collection?`<div class="reader-modes" role="group" aria-label="Как читать"><button type="button" class="reader-mode active" aria-pressed="true">Хадис</button><button type="button" class="reader-mode" id="reader-open-page" aria-pressed="false">Читать в книге</button><button type="button" class="text-button reader-about" id="reader-about">О книге</button></div>`:''}<h1 id="reader-title"${distinctTitle ? '' : ' class="visually-hidden"'}>${escape(distinctTitle ? title : `${bookSource}${number ? ' · '+number : ''}`)}</h1><div class="reader-translation-control"><button type="button" id="translation-toggle" class="translation-toggle active" aria-pressed="true" aria-controls="reader-translation">Перевод${icon('check')}</button></div><div class="arabic-part">${readerArabic(record)}</div>${record.kind==='hadith'?`<div class="reader-actions" role="toolbar" aria-label="Действия с хадисом"><button type="button" data-act="audio" aria-label="Озвучить">${icon('play')}</button><button type="button" data-act="copy" aria-label="Копировать">${icon('copy')}</button><button type="button" data-act="share" aria-label="Поделиться">${icon('share')}</button><button type="button" data-act="more" aria-label="Все инструменты" aria-expanded="false">${icon('more')}</button></div><div class="reader-takhrij" hidden></div>`:''}<div class="translation-part" id="reader-translation"><div class="reader-divider"></div><p class="reader-language">РУССКИЙ ПЕРЕВОД</p>${russian ? `<div class="reader-russian">${textWithNotes(russian,record)}</div>` : record.russianAi ? `<div class="reader-ai-tr"><p class="nb-tr-label">Перевод ИИ — черновой, сверяйте с оригиналом</p><div class="reader-russian">${escape(allahName(record.russianAi))}</div><button type="button" class="ai-tr-again">Перевести заново</button></div>` : (record.kind==='hadith'&&record.arabic?'<div class="reader-ai-tr"><p class="reader-missing">Готового русского перевода для этого хадиса у нас нет.</p><button type="button" class="ai-tr-button">Перевести ИИ</button></div>':'<p class="reader-missing">Русский перевод для этой записи пока недоступен.</p>')}</div><aside id="reader-note" class="reader-footnote-preview" hidden aria-live="polite"></aside><div class="reader-tool-actions"><button type="button" class="reader-chain">${icon('grid')}<span>Конструктор передач<small>Исследовать цепочку передатчиков</small></span>${icon('arrow')}</button><button type="button" class="reader-scientific">${icon('source')}<span>Сравнить версии<small>Открыть инструменты исследования источника</small></span>${icon('arrow')}</button></div>`;
    // «Страница в книге»: the same hadith inside its printed page — chapters, neighbours, the author's words, untouched.
    if ($('#reader-open-page')) $('#reader-open-page').onclick = async () => {
      const button = $('#reader-open-page'), label = button.textContent; button.disabled = true; button.textContent = 'Ищем страницу…';
      try {
        // never silent (owner 29.10: «ничего не открывается, ошибки не пришло»): 15 s, then a plain message
        const place = await Promise.race([state.api.locateLeaf(record.collection, record.number, record.arabic || ''), new Promise((_,reject) => setTimeout(() => reject(new Error('Лист издания не нашёлся за 15 секунд — попробуйте ещё раз или откройте книгу через «О книге»')),15000))]);
        openNativeBook(place.bid, place.leaf, bookSource, {mark: record.number, arabicTitle: arabicTitleOf(record)});   // the hadith stays underneath: «назад» returns to it
      } catch (error) {toast(String(error?.message || 'Страница издания не найдена'));}
      finally {button.disabled = false; button.textContent = label;}
    };
    if ($('#reader-about')) $('#reader-about').onclick = () => openBookOfRecord(record);
    $('#translation-toggle').onclick = () => {const button = $('#translation-toggle'), shown = button.getAttribute('aria-pressed') !== 'true'; button.setAttribute('aria-pressed',String(shown)); button.classList.toggle('active',shown); $('#reader-translation').hidden = !shown;};
    if(record.kind==='quran')mountQuranReader(record,options);
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
    const readerTools = record.kind==='quran'?[{id:'tafsir',title:'Тафсир',icon:'book'},{id:'notes',title:'Мои заметки',icon:'pen'}]:record.kind==='book'?[...(record.page?[{id:'bookPage',title:'Открыть страницу книги',icon:'book'}]:[]),{id:'explain',title:'Пояснение',icon:'helper'},{id:'notes',title:'Мои заметки',icon:'pen'}]:[{id:'narrators',title:'Передатчики',icon:'book'},{id:'takhrij',title:'Где ещё передаётся',icon:'source'},{id:'explain',title:'Пояснение',icon:'helper'},{id:'notes',title:'Мои заметки',icon:'pen'},{id:'tashkeel',title:'Без огласовок',icon:'info'},...(SUNNAH_COM[record.collection]?[{id:'source',title:'На sunnah.com',icon:'source'}]:[])];
    $('.reader-tool-actions').innerHTML = `<details class="reader-tools-disclosure"${record.kind==='book'?' open':''}><summary>Инструменты <span>${readerTools.length}</span></summary><div class="reader-tools-grid">${readerTools.map(tool => `<button type="button" data-reader-tool="${tool.id}">${icon(tool.icon)}<span>${tool.title}</span>${icon('arrow')}</button>`).join('')}</div>${record.kind==='book'?'<p>Для этого отрывка доступны перечисленные инструменты. Остальные функции требуют полного текста и проверки источника.</p>':''}</details>`;
    $$('[data-reader-tool]').forEach(button => button.onclick = () => {if (!NATIVE_TOOLS.has(button.dataset.readerTool)) $('#reader').close(); invokeTool(button.dataset.readerTool,record);});
    if(record.kind==='hadith'&&record.arabic){const box=$('.reader-flow .flow-isnad',$('#reader-body'))||$('.reader-flow',$('#reader-body'))||$('.reader-arabic',$('#reader-body'));if(box)linkIsnadNames(box,record,state.readerToken);}
    mountReaderExtras(record);
  }
  // ── Under the hadith: ▶ copy share ⋯; «Где ещё передаётся» as a line; the AI translation; the book and number in the
  // header are buttons; «?» at the source's grades.
  function openBookStart(record){const row=state.collections.find(c=>c.id===record.collection||(record.bid&&String(c.bid)===String(record.bid)));const bid=record.bid||(row&&row.bid);
    if(bid)openNativeBook(bid,1,(row&&row.title)||source(record),{arabicTitle:arabicTitleOf(record)});else openBookOfRecord(record);}
  function mountReaderExtras(record){
    const body=$('#reader-body'),token=state.readerToken;
    const src=$('.reader-source',body);
    if(src&&record.kind==='hadith'){$$('.source-ru,.source-ar',src).forEach(el=>{el.classList.add('src-link');el.setAttribute('role','button');el.tabIndex=0;el.title='Открыть книгу с начала';el.onclick=()=>openBookStart(record);});
      const nb=$('.num-badge',src);if(nb&&$('#reader-open-page')){nb.classList.add('src-link');nb.setAttribute('role','button');nb.tabIndex=0;nb.title='Открыть этот хадис в книге';nb.onclick=()=>$('#reader-open-page').click();}}
    $$('.edition-grade',body).forEach(p=>{if(!p.querySelector('.src-q'))p.insertAdjacentHTML('beforeend','<button type="button" class="src-q" data-help="grade" aria-label="Что это за оценка">?</button>');});
    // у Корана свой ряд кнопок со своим обработчиком (▶ с подсветкой, «Спросить ИИ») — общий хадисный его не трогает
    const bar=record.kind==='quran'?null:$('.reader-actions',body);
    // владелец 29.10: «кнопки — как в нейросетях, в конце текстового блока; между оригиналом и переводом ничего»
    {const tr=$('#reader-translation',body),tk=$('.reader-takhrij',body);if(tr&&bar){tr.after(bar);if(tk)bar.after(tk);}}
    if(bar)bar.onclick=e=>{const b=e.target.closest('[data-act]');if(!b)return;const a=b.dataset.act;
      if(a==='more'){const d=$('.reader-tools-disclosure',body);if(!d)return;d.open=!d.open;b.setAttribute('aria-expanded',String(d.open));if(d.open)d.scrollIntoView({block:'nearest',behavior:reducedMotion.matches?'instant':'smooth'});return;}
      invokeTool(a==='audio'?'audio':a,record);};
    const ai=$('.ai-tr-button',body);
    // the server keeps one translation per hadith for everyone; a stored one much shorter than the original is likely cut
    // off (Tirmidhi 1 had only the start of the isnad) — then «Перевести заново» replaces it for everyone
    const runAi=async(box,button,force)=>{button.disabled=true;button.textContent='Перевожу…';const text=String(record.arabic||'').trim();
      try{const r=await state.api.translate(text,record.collection,String(record.number||''),force);if(token!==state.readerToken)return;
        const tr=allahName(r.translation),cut=tr.length<text.replace(/[ً-ٰٟـ]/g,'').length*0.45;
        box.innerHTML=`<p class="nb-tr-label">Перевод ИИ — черновой, сверяйте с оригиналом${r.cached?' · сохранён ранее':' · сохранён — следующему откроется сразу'}</p><div class="reader-russian">${escape(tr)}</div>${cut?'<p class="reader-missing">Перевод заметно короче оригинала — похоже, оборван.</p>':''}<button type="button" class="ai-tr-again">${cut?'Перевести заново':'Перевести заново'}</button>`;
        box.querySelector('.ai-tr-again').onclick=e=>runAi(box,e.currentTarget,true);}
      catch(error){if(token===state.readerToken){button.disabled=false;button.textContent=force?'Перевести заново':'Перевести ИИ';toast(String(error?.message||'Перевод сейчас недоступен'));}}};
    if(ai)ai.onclick=()=>runAi(ai.closest('.reader-ai-tr'),ai,false);
    const again=$('.reader-ai-tr .ai-tr-again',body);if(again&&!ai)again.onclick=()=>runAi(again.closest('.reader-ai-tr'),again,true);
    const line=$('.reader-takhrij',body);
    if(line&&record.collection&&record.number&&state.api&&typeof state.api.takhrij==='function')state.api.takhrij(record.collection,record.number).then(r=>{
      if(token!==state.readerToken||!line.isConnected)return;const blocks=(r&&r.blocks)||[],rows=[];
      for(const b of blocks)for(const g of (b.groups||[]))if(g.same)for(const row of g.rows)rows.push(row);
      if(!rows.length){const t=blocks.find(b=>b.kind==='text');if(!t){line.hidden=false;line.innerHTML='<p class="takh-line-head">Где ещё передаётся <button type="button" class="src-q" data-help="takhrij" aria-label="Откуда эти сведения">?</button></p><p class="takh-line-none">Проверенного тахриджа для этого хадиса у нас пока нет.</p>';return;}line.hidden=false;line.innerHTML=`<p class="takh-line-head">Где ещё передаётся <button type="button" class="src-q" data-help="takhrij" aria-label="Откуда эти сведения">?</button></p><p class="takh-line-text" lang="ar" dir="rtl">${escape(cutText(t.text,260))}</p><button type="button" class="takh-line-more">Подробно</button>`;line.querySelector('.takh-line-more').onclick=()=>invokeTool('takhrij',record);return;}
      const seen=new Map();for(const row of rows){const k=row.ru||row.ar;if(!seen.has(k))seen.set(k,{name:row.ru||row.ar,places:[]});const s=seen.get(k);for(const p of row.places)if(!s.places.some(x=>x.n===p.n))s.places.push(p);}
      const places=[];line.hidden=false;
      line.innerHTML=`<p class="takh-line-head">Где ещё передаётся <button type="button" class="src-q" data-help="takhrij" aria-label="Откуда эти сведения">?</button></p><p class="takh-line-list">${[...seen.values()].map(s=>`<span class="takh-line-book"><b>${escape(s.name)}</b> ${s.places.slice(0,8).map(p=>{places.push(p);return `<button type="button" class="takh-line-num" data-tl="${places.length-1}">${escape(p.n)}</button>`;}).join(' ')}${s.places.length>8?` <span class="takh-line-rest">+${s.places.length-8}</span>`:''}</span>`).join('<span class="takh-line-sep">·</span>')}</p><button type="button" class="takh-line-more">Подробно — тахридж и оценки</button>`;
      line.querySelector('.takh-line-more').onclick=()=>invokeTool('takhrij',record);
      line.onclick=e=>{const b=e.target.closest('[data-tl]');if(!b)return;openTakhPlace(places[+b.dataset.tl],record,b);};
    }).catch(()=>{});
  }
  // one place of a takhrij opens the same way as in «Где ещё передаётся»: our edition after a text check, else the book
  async function openTakhPlace(p,record,b){
    if(!p)return;
    if(p.code&&state.collections.some(c=>c.id===p.code)){b.disabled=true;let ok=true,target=null;try{const [src,dst]=await Promise.all([record.arabic?record:state.api.read(record),state.api.read({kind:'hadith',collection:p.code,number:p.n})]);target=dst;ok=sameText(src.arabic,dst.arabic);}catch(_){}finally{b.disabled=false;}
      if(!ok){if(p.code==='nasai'){try{const place=await state.api.leafByHadith('8361',Number(p.n));toast('Номер по «ас-Сунан аль-Кубра» ан-Насаи — открываю её');openNativeBook('8361',place.leaf,'Ас-Сунан аль-Кубра ан-Насаи',{mark:p.n});}catch(_){toast('Под этим номером в нашем ан-Насаи другой хадис');}return;}toast('Под этим номером в нашем издании другой хадис — номер дан по другой печати');return;}
      openReader(target&&target.arabic?{kind:'hadith',collection:p.code,number:p.n,...target}:{kind:'hadith',collection:p.code,number:p.n});return;}
    if(p.bid){b.disabled=true;try{const place=await state.api.leafByHadith(p.bid,Number(p.n));const c=collectionForBid(p.bid,'');openNativeBook(p.bid,place.leaf,c.title,{mark:p.n,arabicTitle:c.arabicTitle});}catch(_){toast('Этот номер в издании сейчас не открылся');}finally{b.disabled=false;}}
  }
  // ── «Назад» — универсально (owner 29.10): a hadith opened from another hadith returns to it; windows stack.
  const readerHistory=[];
  function readerBack(){if(readerHistory.length){openReader(readerHistory.pop(),{fromHistory:true});return true;}return false;}
  async function openReader(record,options={}) {
    if(record&&record.kind==='quran'&&record.sura)setQuranPick(record.sura,record.ayah);
    if($('#reader').open&&state.reader&&!options.fromHistory&&String(state.reader.id||state.reader.collection+state.reader.number)!==String(record.id||record.collection+record.number))readerHistory.push(state.reader);
    stopReaderAudio();
    const token = ++state.readerToken; state.reader = record; updateReaderSave();
    const dialog = $('#reader'); if (!dialog.open) dialog.showModal(); document.body.style.overflow = 'hidden';
    loading($('#reader-body'),'Открываем текст','Оригинал и перевод — в одном месте');
    try {const full = state.api ? await state.api.read(record) : record; if (token !== state.readerToken || !dialog.open) return; state.reader = full ? {...record,...full} : record; renderReader(state.reader,options); updateReaderSave(); $('#reader-body').scrollTop = 0;}
    catch (error) {if (token !== state.readerToken) return; empty($('#reader-body'),'Не удалось загрузить текст','Попробуем открыть его ещё раз.','Повторить',() => openReader(record)); console.warn('Muslimoon reader unavailable',error);}
  }
  $('.reader-close').onclick = () => {if(!readerBack())$('#reader').close();};
  $('#reader').addEventListener('close',()=>{readerHistory.length=0;quranReturn=null;});
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
    // silk, not a keyboard (owner 29.10): each letter surfaces softly, an even calm pace, a quiet «например:» before it;
    // the example then dissolves as a whole — it reads as a demonstration, not as someone typing in the field
    let n = 0; const chars = [...text];
    el.innerHTML = '<span class="ex-label">например:</span><span class="ex-text"></span>'; const box = el.querySelector('.ex-text');
    const step = () => {if (exampleIdle()) return; const ch = document.createElement('span'); ch.className = 'ex-ch'; ch.textContent = chars[n++]; box.appendChild(ch);
      if (n < chars.length) {exampleTimer = setTimeout(step, 95); return;}
      exampleTimer = setTimeout(() => {if (exampleIdle()) return; $('#search-submit').classList.add('demo-ready');
        exampleFadeTimer = setTimeout(() => $('#search-submit').classList.remove('demo-ready'), 1100);
        exampleTimer = setTimeout(erase, 2400);}, 250);};
    const erase = () => {if (exampleIdle()) return; el.classList.add('ex-leaving');
      exampleTimer = setTimeout(() => {el.classList.remove('ex-leaving'); el.textContent = ''; exampleIndex = (exampleIndex + 1) % exs().length; exampleTimer = setTimeout(typeExample, 450);}, 520);};
    step();
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
