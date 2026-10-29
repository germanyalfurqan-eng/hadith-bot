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
  const recordNumber = record => record.kind === 'quran' && record.sura && record.ayah ? `Сура ${record.sura}, аят ${record.ayah}` : record.number != null && String(record.number) !== '' ? `№ ${record.number}` : '';
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
    leaveDialog.onclose = () => {if (leaveDialog.returnValue !== 'go') return; const tg = window.Telegram && window.Telegram.WebApp;
      try {if (tg && tg.initData && tg.openLink) tg.openLink(url); else window.open(url,'_blank','noopener');} catch (_) {window.open(url,'_blank','noopener');}};
  }
  document.addEventListener('click',event => {const a = event.target.closest && event.target.closest('a[href]'); if (!a || !isExternal(a.href)) return; event.preventDefault(); askLeave(a.href);},true);
  window.addEventListener('message',event => {if (event.data && typeof event.data.muslimoonLeave === 'string' && isExternal(event.data.muslimoonLeave)) askLeave(event.data.muslimoonLeave);});
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
    if(record.kind==='hadith'&&record.arabic&&record.russian&&!(record.collection==='bukhari'&&['1','321'].includes(String(record.number))))record={...record,russian:'',pairingUnverified:true};
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
      const safeRussian=record.kind==='hadith'&&record.arabic&&record.russian&&!(record.collection==='bukhari'&&['1','321'].includes(String(record.number)))?'':String(record.russian||'');
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
  }
  $$('[data-view]').forEach(button => button.onclick = () => showView(button.dataset.view));
  // The AI button sits in the middle of the bottom bar (owner 29.10).
  $$('[data-ai-open]').forEach(button => button.onclick = () => openNativeAssistant());
  $('#brand-home').onclick = event => {event.preventDefault(); showView('search');};
  $('.rail-mark').onclick = event => {event.preventDefault(); showView('search');};
  function renderBookmarks() {
    $('#bookmark-count').textContent = String(state.bookmarks.length);
    if (!state.bookmarks.length) empty($('#bookmark-results'),'Пока ни одной закладки','Нажмите на значок закладки рядом с текстом, который хотите сохранить.','К поиску',() => showView('search'));
    else renderCards($('#bookmark-results'),state.bookmarks,state.bookmarks.length);
  }
  function applyFont() {
    document.documentElement.style.setProperty('--body-scale',String([1,1.12,1.24][state.font])); $('#font-label').textContent = ['Обычный','Крупный','Очень крупный'][state.font];
    $('#font-down').disabled = state.font === 0; $('#font-up').disabled = state.font === 2;
    try {localStorage.setItem(FONT_STORAGE,String(state.font));} catch (_) {}
  }
  $('#font-down').onclick = () => {state.font = Math.max(0,state.font - 1); applyFont();};
  $('#font-up').onclick = () => {state.font = Math.min(2,state.font + 1); applyFont();}; applyFont();
  $$('[data-theme-option]').forEach(a => a.classList.toggle('active',a.dataset.themeOption === document.documentElement.dataset.theme));
  // «Настроить поиск» → under the field a row of modes, one tap each (owner 29.10); the detailed panel stays below.
  const MODE_CHIPS = [['normal','По словам'],['diac','С огласовками'],['root','По корню'],['matnonly','Только матн'],['rag','RAG'],['narr','Передатчик'],['ctor','Цепь'],['ai','✦ По смыслу · ИИ']];
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
    state.aiMode = !!on; $('.search-field').classList.toggle('ai-mode',state.aiMode); aiSwitch.setAttribute('aria-pressed',String(state.aiMode));
    $('#query').placeholder = state.aiMode ? 'Спросите ИИ-помощника…' : ''; $('#query-example').hidden = state.aiMode;
    $('#search-summary').textContent = state.aiMode ? '✦ Вопрос ИИ-помощнику · ответ откроется в чате' : $('#search-summary').dataset.normal || $('#search-summary').textContent;
    syncModeChips();
  }
  aiSwitch.onclick = () => {setAiMode(!state.aiMode); $('#query').focus();};
  function askAssistant(text) {openNativeAssistant(); const question = String(text || '').trim(); if (question) {assistantInput.value = question; $('#native-assistant-form').requestSubmit();}}
  $('#refine-toggle').onclick = () => {const opened = $('#refine-panel').hidden; $('#refine-panel').hidden = !opened; modeChips.hidden = !opened || state.section === 'quran'; syncModeChips(); $('#refine-toggle').setAttribute('aria-expanded',String(opened));};
  const modeHelp = {normal:'Введите слово или фразу на русском или арабском.',diac:'Совпадение строго с огласовками — так, как вы набрали.',rag:'Ищем по смыслу в подготовленных книгах нашей базы.',root:'Введите арабское слово: найдём также слова с тем же корнем.',matnonly:'Ищем в самом высказывании, без цепочки передатчиков.',narr:'Введите имя человека, который передал хадис.',chain:'Введите арабские имена из цепочки передатчиков — иснада.'};
  const modeNames = {normal:'По словам',diac:'С огласовками',rag:'RAG · по смыслу',root:'По корню слова',matnonly:'Текст хадиса',narr:'По передатчику',chain:'В цепочке передатчиков'};
  const multiScope=[];
  const scopeBox=document.createElement('details');scopeBox.className='multi-scope';
  scopeBox.innerHTML='<summary>Несколько книг и разделов</summary><p>Выберите книгу или раздел выше, затем добавьте или исключите его. Исключения имеют приоритет.</p><div><button type="button" data-scope-action="include">Добавить в поиск</button><button type="button" data-scope-action="exclude">Исключить</button></div><ul class="scope-list"></ul>';
  document.querySelector('label[for="mode-select"]').before(scopeBox);
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
    $('#search-summary').dataset.normal = state.section === 'quran' ? 'Коран · Текст или номер аята' : `${multiScope.length?'Выбрано условий: '+multiScope.length:(state.collections.find(c => String(c.id) === state.collection)?.title || state.categories.find(c => String(c.id) === state.category)?.title || 'Все разделы')} · ${modeNames[state.mode]||'По словам'}`;
    if (!state.aiMode) $('#search-summary').textContent = state.section === 'quran' ? 'Коран · Текст или номер аята' : `${multiScope.length?'Выбрано условий: '+multiScope.length:(chosen?.title || category?.title || 'Все разделы')} · ${modeNames[state.mode]}`;
    renderChips(); syncModeChips(); if (state.section === 'quran') modeChips.hidden = true;
  }
  $('#category-select').onchange = () => {$('#collection-select').value = 'all'; filtersChanged();};
  $('#collection-select').onchange = () => {$('#category-select').value = 'all'; filtersChanged();};
  $('#mode-select').onchange = filtersChanged;
  $('#reset-filters').onclick = () => {$('#category-select').value = 'all'; $('#collection-select').value = 'all'; $('#mode-select').value = 'normal';multiScope.length=0;renderMultiScope(); filtersChanged();};
  $$('[data-section]').forEach(button => button.onclick = () => {
    state.section = button.dataset.section; state.searchToken++;
    $$('[data-section]').forEach(b => {b.classList.toggle('selected',b === button); b.setAttribute('aria-pressed',String(b === button));});
    $('#collection-chips').hidden = state.section === 'quran'; $('#category-select').disabled = state.section === 'quran'; $('#collection-select').disabled = state.section === 'quran'; $('#mode-select').disabled = state.section === 'quran';
    filtersChanged(); showWelcome(); resetPlaceholder();
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
    $('#book-dialog-read').onclick = () => {dialog.close(); showView('library'); browseCollection(collection);};
    $('#book-dialog-favorite').onclick = () => toggleFavoriteBook(String(collection.id)); updateBookFavorite();
    $('#book-dialog-body').scrollTop = 0;
    // «Что за издание» (owner 29.10): the edition card from the library itself — tahqiq, publisher, printing, volumes.
    if (collection.bid && state.api && typeof state.api.bookMeta === 'function') state.api.bookMeta(collection.bid).then(meta => {
      if (token !== bookInfoToken || !dialog.open || !meta?.info || $('#book-edition')) return;
      $('#book-description').insertAdjacentHTML('beforebegin', `<section class="book-edition" id="book-edition"><h2>Издание</h2><p lang="ar" dir="rtl">${escape(meta.info)}</p></section>`);
    }).catch(() => {});
    try {
      if (!state.api || typeof state.api.bookInfo !== 'function') throw new Error('Book information unavailable');
      const info = await state.api.bookInfo(collection.id); if (token !== bookInfoToken || !dialog.open) return;
      const url = safeWebUrl(info?.sourceUrl), description = String(info?.description || '').trim();
      $('#book-description').innerHTML = `<h2>О книге</h2><p class="book-description-text" dir="auto">${escape(description || 'Описание этой книги из источников пока не получено.')}</p>${info?.notice ? `<p class="book-info-notice">${escape(info.notice)}</p>` : ''}${url ? `<a class="book-description-source" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(info.sourceTitle || 'Источник описания')}${info.language ? ` · ${escape(info.language)}` : ''}${icon('source')}</a>` : ''}`;
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
    dialog.innerHTML=`<div class="reader-shell"><header class="reader-toolbar"><button type="button" class="icon-button native-book-close" aria-label="Закрыть книгу">${icon('back')}</button><span>ЧТЕНИЕ КНИГИ</span><button type="button" class="text-button native-book-about">О книге</button></header><div class="reader-body native-book-body"><h1 id="native-book-title"></h1><div class="native-book-location" aria-live="polite"></div><div class="native-book-headings" lang="ar" dir="rtl"></div><div class="native-book-text" lang="ar" dir="rtl"></div><div class="native-book-notes"></div><p class="native-book-status" role="status" aria-live="polite"></p><button type="button" class="native-book-tools">Инструменты книги</button></div><nav class="native-book-bar" aria-label="Листание книги" dir="ltr"><button type="button" class="nb-turn native-book-next" aria-label="Следующая страница">${icon('back')}</button><div class="nb-jump"><button type="button" class="nb-edge nb-end">Конец</button><label>стр.<input class="nb-page" inputmode="numeric" enterkeyhint="go" aria-label="Перейти на страницу"></label><label>№<input class="nb-hadith" inputmode="numeric" enterkeyhint="go" aria-label="Перейти к хадису по номеру"></label><button type="button" class="nb-edge nb-start">Начало</button></div><button type="button" class="nb-turn native-book-prev" aria-label="Предыдущая страница">${icon('arrow')}</button></nav></div>`;
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
  function openNativeBook(bid,leaf,title,options={}){
    const dialog=ensureNativeBook(),safeLeaf=Number(leaf);
    nativeBook={bid:String(bid),leaf:Number.isSafeInteger(safeLeaf)&&safeLeaf>0?safeLeaf:1,title:String(title||'Книга'),mark:options.mark?String(options.mark):''};
    $('#native-book-title',dialog).innerHTML=sourceLine(nativeBook.title,options.arabicTitle||'','','native-book-source');
    $('.native-book-text',dialog).textContent='';$('.native-book-notes',dialog).textContent='';$('.native-book-headings',dialog).textContent='';$('.native-book-location',dialog).textContent='';
    if(!dialog.open)dialog.showModal();loadNativeBookLeaf(nativeBook.leaf);
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
      $('.native-book-location',dialog).textContent=page.printedPage!=null?`${page.volume?'Том '+page.volume+' · ':''}стр. ${page.printedPage}`:`Лист ${page.leaf}`;
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
    try {
      if (!state.api || typeof state.api.tool !== 'function') throw new Error('Tool unavailable');
      const response = await state.api.tool(name,record);
      if (response === false || response?.ok === false || response?.opened === false || response?.error) throw new Error('Tool did not open');
      if (response?.notice && !response?.opened) {$('#assistant-notice').textContent = String(response.notice); $('#assistant-notice').hidden = false;}
    } catch (_) {
      const message = name === 'chain' ? 'В этом макете конструктор передач сейчас недоступен.' : ['assistant','rag'].includes(name) ? 'В этом макете помощник не ответил. Поиск и чтение источников доступны.' : 'В этом макете инструмент сейчас недоступен. Поиск и чтение источников доступны.';
      $('#assistant-notice').textContent = message; $('#assistant-notice').hidden = false;
      if (state.view !== 'assistant') {showView('assistant');}
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
    const clean=String(raw||'').replace(/```[\s\S]*?```/g,'').replace(/^[^\n]*:[ \t]*\n?[ \t]*<?https?:\/\/\S+>?[ \t]*$/gm,'').replace(/\[([^\]\n]+)\]\((?:https?:)?\/\/[^)\s]+\)/g,'$1')
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
    const body=row.role==='user'?escape(row.text||''):chatHtml(row.text||'');
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
    chain:{title:'Конструктор цепей',run:()=>invokeTool('chain',null)}
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
      if((id==='search'||id==='findBooks')&&!arg)return '';
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
  function screenContext(){
    if($('#native-book-reader')?.open)return {key:'book:'+(nativeBook?.bid||''),text:`Вы читаете «${nativeBook?.title||'книгу'}», ${$('.native-book-location')?.textContent||''}. Могу: найти страницу или хадис по номеру, рассказать о книге и издании, сделать текст крупнее.`,actions:[act('fontUp')]};
    if($('#reader')?.open)return {key:'reader:'+(state.reader?.id||''),text:'Вы читаете хадис. Могу: объяснить его, найти, где он ещё передаётся, открыть страницу в книге, сделать текст крупнее.',actions:[act('fontUp')]};
    const v=state.view||'search';
    if(v==='library')return {key:'library',text:'Вы в библиотеке (8 589 книг). Могу: найти книгу по названию или автору, открыть избранные, открыть любой из сборников.',actions:[act('favorites'),act('openBook','bukhari','Открыть «Сахих аль-Бухари»')]};
    if(v==='bookmarks')return {key:'bookmarks',text:'Здесь ваши закладки. Могу: найти сохранённое, открыть библиотеку или поиск.',actions:[act('library')]};
    if(v==='settings')return {key:'settings',text:'Здесь инструменты и настройки. Скажите, что поменять — например «сделай текст крупнее» или «смени оттенок».',actions:[act('fontUp'),act('theme')]};
    return {key:'search:'+(state.section||'hadith'),text:state.section==='quran'?'Вы в поиске по Корану. Напишите слово, тему или номер вроде 2:255 — открою аят, объясню слово, найду по корню.':'Вы в поиске хадисов. Напишите тему, слова или «бухари 1» — найду; могу объяснить хадис, термин или помочь настроить поиск.',actions:[act('settings','','Настроить приложение'),act('chain')]};
  }
  assistantMessages.addEventListener('click',event=>{
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
      const response=await state.api.hermesAsk(asked,ctx.text,Object.keys(ASSIST_ACTIONS)).catch(async error=>{
        if(!/в проверке/.test(String(error?.message||'')))throw error;
        const old=await state.api.assistantAsk(asked);return {answer:old.answer,model:''};});
      const parsed=hermesActions(response.answer);const next=assistantHistory();
      // The helper's own buttons first, then the quick ones read from the question — one row, without repeats.
      const buttons=parsed.actions.concat(proposals.filter(a=>!parsed.actions.some(b=>b.id===a.id&&b.arg===a.arg))).slice(0,6);
      next.push({role:'bot',text:parsed.text.replace(/модель ИИ \(Muslimoon\)/,'модель ИИ: '+(response.model||'Muslimoon')),actions:buttons});saveAssistantHistory(next);}
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
  function readerArabicText(record) {
    const parts = Array.isArray(record.parts) ? record.parts.filter(part => part && typeof part.text === 'string' && part.text.trim()) : [];
    if (!parts.length) return record.arabic ? `<div class="reader-arabic" lang="ar" dir="rtl">${textWithNotes(record.arabic,record)}</div>` : '<p class="reader-missing">Арабский текст для этой записи пока недоступен.</p>';
    const roles = new Set(parts.map(part => part.role));
    const legend = `<div class="parts-legend" aria-label="Разделы текста">${roles.has('matn') ? '<span>Текст хадиса</span>' : ''}${roles.has('isnad') ? '<span class="legend-isnad">Цепь передатчиков</span>' : ''}${roles.has('comment') ? '<span class="legend-comment">Комментарий</span>' : ''}</div>`;
    return legend + parts.map(part => {
      const body = `<div class="reader-arabic" lang="ar" dir="rtl">${textWithNotes(part.text,record)}</div>`;
      if (part.role === 'isnad') return `<details class="isnad-block"><summary><span>${escape(part.label || 'Цепь передатчиков')}</span>${icon('down')}</summary>${body}</details>`;
      if (part.role === 'matn') return `<section class="matn-block"><p class="part-label">${escape(part.label || 'Текст хадиса')}</p>${body}</section>`;
      if (part.role === 'comment') return `<section class="comment-block"><p class="part-label">${escape(part.label || 'Комментарий составителя')}</p>${body}</section>`;
      return body;
    }).join('');
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
        const place = await state.api.locateLeaf(record.collection, record.number, record.arabic || '');
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
    const readerTools = record.kind==='quran'?[{id:'quranReader',title:'Открыть читалку Корана',icon:'book'},{id:'explain',title:'Пояснение',icon:'helper'}]:record.kind==='book'?[...(record.page?[{id:'bookPage',title:'Открыть страницу книги',icon:'book'}]:[]),{id:'explain',title:'Пояснение',icon:'helper'},{id:'notes',title:'Мои заметки',icon:'pen'}]:[{id:'chain',title:'Конструктор передач',icon:'grid'},{id:'versions',title:'Сравнить версии',icon:'source'},{id:'narrators',title:'Передатчики',icon:'book'},{id:'explain',title:'Пояснение',icon:'helper'},{id:'audio',title:'Аудио',icon:'audio'},{id:'notes',title:'Мои заметки',icon:'pen'},{id:'source',title:'Открыть источник',icon:'source'}];
    $('.reader-tool-actions').innerHTML = `<details class="reader-tools-disclosure" open><summary>Инструменты <span>${readerTools.length}</span></summary><div class="reader-tools-grid">${readerTools.map(tool => `<button type="button" data-reader-tool="${tool.id}">${icon(tool.icon)}<span>${tool.title}</span>${icon('arrow')}</button>`).join('')}</div>${record.kind==='book'?'<p>Для этого отрывка доступны перечисленные инструменты. Остальные функции требуют полного текста и проверки источника.</p>':''}</details>`;
    $$('[data-reader-tool]').forEach(button => button.onclick = () => {$('#reader').close(); invokeTool(button.dataset.readerTool,record);});
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
  const examples = ['бухари 1','2:255','дела по намерениям','إنما الأعمال بالنيات'];
  let exampleIndex = 0, exampleTimer, exampleFadeTimer;
  function syncPlaceholder() {
    const hidden = Boolean($('#query').value) || document.activeElement === $('#query');
    $('#clear-query').hidden = !$('#query').value;
    $('#search-submit').disabled = !$('#query').value.trim();
    $('#query-example').hidden = hidden;
    clearTimeout(exampleTimer); clearTimeout(exampleFadeTimer); $('#query-example').classList.remove('leaving');
    if (!hidden && !reducedMotion.matches && !document.hidden) exampleTimer = setTimeout(nextExample,3800);
  }
  function nextExample() {
    if ($('#query').value || document.activeElement === $('#query') || reducedMotion.matches || document.hidden) return;
    $('#query-example').classList.add('leaving');
    exampleFadeTimer = setTimeout(() => {exampleIndex = (exampleIndex+1)%examples.length; const text = examples[exampleIndex]; $('#query-example').textContent = text; $('#query-example').lang = /[\u0600-\u06ff]/.test(text) ? 'ar' : 'ru'; $('#query-example').classList.remove('leaving'); exampleTimer = setTimeout(nextExample,3800);},320);
  }
  function resetPlaceholder() {exampleIndex = state.section === 'quran' ? 1 : 0; $('#query-example').textContent = examples[exampleIndex]; $('#query-example').lang = 'ru'; syncPlaceholder();}
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
      filtersChanged(); renderLibrary(); showWelcome();
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
      state.api = null;
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
