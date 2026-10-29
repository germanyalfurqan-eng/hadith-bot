/* Narrow presentation bridge to the genuine v1807 search/reading functions. */
(function(){
  'use strict';
  const source='muslimoon-v1807-core';
  const records=new Map();
  // Numbering differs across editions. Do not join independently sourced
  // Arabic and Russian texts by collection+number alone. These two pairs were
  // checked against the actual texts during the current preview session.
  const verifiedTextPairs=new Set(['bukhari|1','bukhari|321']);
  const canPairText=row=>verifiedTextPairs.has(String(row.collection)+'|'+String(row.number));
  const names={bukhari:'Сахих аль-Бухари',muslim:'Сахих Муслим',abudawud:'Сунан Абу Дауда',tirmidhi:'Сунан ат-Тирмизи',nasai:'Сунан ан-Насаи',ibnmajah:'Сунан Ибн Маджи',ibnmaja:'Сунан Ибн Маджи',malik:'Муватта имама Малика',ahmad:'Муснад имама Ахмада',nawawi:'40 хадисов ан-Навави',muhaymin:'Мухэймин'};
  const send=(id,payload,error)=>parent.postMessage({source,id,payload,error},location.origin);
  let ruPromise=null;
  let quranWordAssets=null;
  async function quranWordData(sura,ayah,displayedText){
    if(!Number.isSafeInteger(sura)||sura<1||sura>114||!Number.isSafeInteger(ayah)||ayah<1)throw Error('Неверный номер аята');
    const verses=await loadQuran(),verse=verses.find(v=>Number(v.s)===sura&&Number(v.a)===ayah);
    if(!verse||String(verse.text||'').trim()!==String(displayedText||'').trim())throw Error('Текст аята отличается от источника; разбор не показан.');
    if(!quranWordAssets)quranWordAssets=Promise.all(['./quran_roots.json','./quran_wbw_ru.json'].map(url=>fetch(url).then(r=>{if(!r.ok)throw Error('Данные слов недоступны');return r.json();}))).catch(e=>{quranWordAssets=null;throw e;});
    const [roots,translations]=await quranWordAssets;
    const tokens=String(verse.text).split(/(\s+)/).filter(Boolean),words=tokens.filter(t=>/[ء-ي]/.test(t));
    const gloss=translations[`${sura}:${ayah}`],aligned=Array.isArray(gloss)&&gloss.length===words.length;
    let index=0;return {sura,ayah,aligned,tokens:tokens.map(token=>{
      if(!/[ء-ي]/.test(token))return {text:token};
      const e=roots.f?.[rootKey(token)],root=Array.isArray(e)&&e[0]?String(e[0]):'';
      const refs=root&&Array.isArray(roots.r?.[root])?roots.r[root]:[];
      return {text:token,word:true,index:index++,translation:aligned?String(gloss[index-1]||''):'',root,grammar:Array.isArray(e)&&e[2]?gramRu(String(e[2])):'',references:refs,referenceCount:refs.length};
    })};
  }
  let catalogPromise=null,fullCatalog=null;
  async function catalog(){
    if(!catalogPromise)catalogPromise=(async()=>{
      const data=await loadCatalog();
      await Promise.all([loadBookTr(),_ensureFirstSrcRank(data)]);
      const firstSources=await loadFirstSrc();
      const authorNames=new Map(firstSources.filter(s=>s.author_key&&s.author_ru).map(s=>[_dial(s.author_key),s.author_ru]));
      const authorLabel=b=>{const ru=authorNames.get(_dial(b?.a||''));return ru?ru+' | '+b.a:(b?.a||'');};
      const primary=collections().collections.map(row=>{
        const ids=(typeof COLL_BIDS!=='undefined'&&COLL_BIDS[row.id])||((typeof EXTRA_BIDS!=='undefined'&&EXTRA_BIDS[row.id])?[EXTRA_BIDS[row.id]]:[]);
        const candidates=data.filter(b=>ids.map(String).includes(String(b.i))).sort((a,b)=>(_firstSrcRank[String(a.i)]??999)-(_firstSrcRank[String(b.i)]??999));
        const book=candidates[0];
        return Object.assign(row,{readable:true,bid:book?String(book.i):null,author:authorLabel(book),arabicTitle:book?.n||'',category:book?.c||''});
      });
      const primaryIds=new Set(primary.map(x=>x.bid).filter(Boolean));
      const categoryDefs=typeof CATS_INFO!=='undefined'?CATS_INFO:[];
      const categories=categoryDefs.map(([id,ar,ru])=>({id,title:ru+' | '+ar,count:data.filter(b=>b.c===id).length})).filter(c=>c.count);
      for(const id of new Set(data.map(b=>b.c)))if(id&&!categories.some(c=>c.id===id))categories.push({id,title:id,count:data.filter(b=>b.c===id).length});
      const categoryNames=new Map(categories.map(c=>[c.id,c.title]));
      const categoryOrder=new Map(categories.map((c,i)=>[c.id,i]));
      const others=data.filter(b=>!primaryIds.has(String(b.i))).map((book,index)=>({book,index})).sort((a,b)=>{
        const ap=_browsePrio(a.book),bp=_browsePrio(b.book);
        if(ap>=1900||bp>=1900)return bp-ap;
        return (categoryOrder.get(a.book.c)??999)-(categoryOrder.get(b.book.c)??999)||bp-ap||a.index-b.index;
      }).map(({book:b})=>{
        const translation=_catTr.map[b.n]?.ru||'';
        return {id:'book:'+b.i,bid:String(b.i),title:translation||b.n,arabicTitle:b.n,author:authorLabel(b),category:b.c,categoryLabel:categoryNames.get(b.c)||b.c,subtitle:(translation?b.n+' · ':'')+(authorLabel(b)||categoryNames.get(b.c)||''),readable:false};
      });
      fullCatalog={...collections(),collections:primary.concat(others),categories,catalogCount:data.length};
      return fullCatalog;
    })().catch(error=>{catalogPromise=null;throw error;});
    return catalogPromise;
  }
  async function ruIndex(){
    if(!ruPromise)ruPromise=fetch('./hadith_ru.json').then(r=>{if(!r.ok)throw Error('Переводы недоступны');return r.json();}).then(rows=>new Map(rows.map(x=>[x.s+'|'+x.n,x.t])));
    return ruPromise;
  }
  function cleanText(s){const d=document.createElement('div');d.innerHTML=String(s||'');return (d.textContent||'').replace(/\\n/g,'\n');}
  async function sourceParts(row){
    if(!row.arabic||typeof _applyIsnadMatn!=='function')return;
    // Reuse the app's existing edition markup, never infer chains in translation.
    const holder=document.createElement('div'),body=document.createElement('div');
    holder.appendChild(body);body.textContent=row.arabic;
    await _applyIsnadMatn(body,row.collection,row.number,row.arabic);
    if(!body.querySelector('.mkp-isnad'))return;
    const definitions=[['.mkp-isnad','isnad','Иснад · цепочка передатчиков'],['.mkp-matn','matn','Матн · текст хадиса'],['.mkp-author','comment','Слова автора сборника'],['.mkp-sharh','comment','Пояснение издания']];
    const parts=[];
    for(const [selector,role,label] of definitions){
      const element=body.querySelector(selector);if(!element)continue;
      const copy=element.cloneNode(true);copy.querySelectorAll('.mkp-lbl').forEach(x=>x.remove());
      const text=copy.textContent.trim();if(text)parts.push({role,label,text});
    }
    // The source text wins if markup has lost or introduced any content.
    const compact=t=>String(t).replace(/\s/g,'');
    if(parts.length&&compact(parts.map(p=>p.text).join(''))===compact(row.arabic))row.parts=parts;
  }
  async function wikiPage(url){
    const target=new URL(url);
    if(!/^(ru|en|ar)\.wikipedia\.org$/.test(target.hostname)||!target.pathname.startsWith('/wiki/'))return null;
    const api=new URL('/w/api.php',target.origin);
    const params={action:'query',origin:'*',format:'json',redirects:'1',prop:'extracts|langlinks|info',titles:decodeURIComponent(target.pathname.slice(6)),exintro:'1',explaintext:'1',exsentences:'4',lllimit:'500',llprop:'url',inprop:'url'};
    for(const [key,value] of Object.entries(params))api.searchParams.set(key,value);
    const control=new AbortController(),timer=setTimeout(()=>control.abort(),10000);
    try{
      const response=await fetch(api.href,{credentials:'omit',signal:control.signal});if(!response.ok)return null;
      const data=await response.json(),page=Object.values(data.query?.pages||{}).find(p=>p.pageid>0&&!p.missing);
      return page?{...page,lang:target.hostname.split('.')[0]}:null;
    }catch(e){return null;}finally{clearTimeout(timer);}
  }
  async function bookInfo(id){
    const row=(await catalog()).collections.find(c=>c.id===String(id));if(!row)throw Error('Книга не найдена');
    let verified={};try{const response=await fetch('./wiki_titles_verified.json');if(response.ok)verified=await response.json();}catch(e){}
    const known=verified[row.bid];
    const original=known?.url||'https://ar.wikipedia.org/wiki/'+encodeURIComponent((row.arabicTitle||row.title).split(' - ')[0]);
    let page=await wikiPage(original);
    if(page){
      const links=new Map((page.langlinks||[]).map(x=>[x.lang,x.url]));links.set(page.lang,page.fullurl||original);
      const preferred=['ru','en','ar'].find(lang=>links.has(lang));
      if(preferred&&preferred!==page.lang){const translated=await wikiPage(links.get(preferred));if(translated)page=translated;}
    }
    return {description:page?.extract||'',sourceUrl:page?.fullurl||known?.url||'',sourceTitle:page?'Википедия · '+page.title:'',language:page?.lang||'',notice:page?.extract?'':'Связанная справка из Википедии пока недоступна. Название, автор и раздел показаны по каталогу.'};
  }
  function convert(d){
    const q=d.type==='q',h=d.h||{},v=d.v||{};
    const collection=q?'quran':d.s||d.code||(d.type==='m'?'muhaymin':'');
    const number=q?String(v.s)+':'+v.a:String(d.n??h.num??h.n??d.num??'');
    const id=(q?'q:':'h:')+collection+':'+number;
    const title=q?('Сура '+v.s+' · '+((typeof SURA_RU!=='undefined'&&SURA_RU[v.s])||'')):(names[collection]||collection||'Хадис');
    // Shamela notes glued to the matn («…فَانْتَهُوا»P<байт> صحيح», О-0426): split with the app's own
    // _сноскиШамилы, then its display cleanup. Notes travel separately, the stored text is untouched.
    let arabic=cleanText(v.text||h.text||d.arabic||''),editionNotes=[];
    if(!q&&arabic){
      try{const split=typeof _сноскиШамилы==='function'?_сноскиШамилы(arabic):null;if(split){arabic=split.матн;editionNotes=split.сноски;}}catch(e){}
      try{if(typeof _матнДляПоказа==='function')arabic=_матнДляПоказа(arabic,collection,number);}catch(e){}
    }
    const row={id,kind:q?'quran':'hadith',collection,title,number,
      russian:cleanText(d.ru||d.russian||v.ru||''),arabic,editionNotes,sura:v.s,ayah:v.a};
    records.set(id,{original:d,row});return row;
  }
  function collections(){
    let books=[];
    if(typeof READABLE!=='undefined')books=READABLE.map(x=>({id:x.code,title:names[x.code]||x.ru||x.code,subtitle:'Читать сборник'}));
    if(!books.length)books=Object.keys(names).filter(x=>!['nawawi','ibnmaja'].includes(x)).map(id=>({id,title:names[id],subtitle:'Читать сборник'}));
    return {version:typeof APPVER!=='undefined'?APPVER:'v1807',collections:books};
  }
  let serial=Promise.resolve(),lastLeafCache=null;
  let numberObserver=null, numberTimer=null, numberContext=null, numberRu=null;
  function stopNumberWatch(){if(numberObserver)numberObserver.disconnect();numberObserver=null;clearTimeout(numberTimer);numberContext=null;}
  function numberSnapshot(){
    if(!numberContext)return {items:[],total:0,hasMore:false};
    const items=[];const result=document.getElementById('res');
    for(const node of result.querySelectorAll('.card')){
      const meta=node.__mlNumberRecord;if(!meta)continue;
      if(_scopeIds&&_scopeIds.size&&(meta.kind==='canonical'||!_scopeIds.has(String(meta.bid))))continue;
      const hiddenEdition=node.closest('.canonEd');if(hiddenEdition&&hiddenEdition.style.display==='none'&&!(_scopeIds&&_scopeIds.size))continue;
      let row;
      if(meta.kind==='canonical'){
        row=convert({code:meta.code,h:meta.h});
        if(numberRu&&!row.russian&&canPairText(row))row.russian=cleanText(numberRu.get(row.collection+'|'+row.number)||'');
        if(!canPairText(row))row.pairingUnverified=true;
      }else{
        const known=fullCatalog?.collections.find(c=>String(c.bid)===String(meta.bid));
        const unknown=/^книга №\d+$/i.test(String(meta.title||''));
        row={id:`mk:${meta.bid}:${meta.n}:${meta.page}`,kind:'book',collection:'book:'+meta.bid,number:String(meta.n),
          title:String((unknown&&known?.title)||meta.title||meta.arabicTitle||'Книга'),bookTitle:String((unknown&&known?.title)||meta.title||meta.arabicTitle||'Книга'),arabicTitle:String((unknown&&known?.arabicTitle)||meta.arabicTitle||''),
          arabic:String(meta.text||''),russian:'',bid:String(meta.bid),page:String(meta.page||''),
          author:String(meta.author||''),isExcerpt:!meta.full};
        const codes=typeof COLL_BIDS!=='undefined'?Object.entries(COLL_BIDS):[];
        const match=codes.find(([,ids])=>Array.isArray(ids)&&ids.map(String).includes(String(meta.bid)));
        if(match)row.relatedCollection=match[0];
        records.set(row.id,{node,numberBook:true});
      }
      items.push(row);
    }
    const order=collections().collections.map(c=>c.id);
    items.sort((a,b)=>{const ai=order.indexOf(a.relatedCollection||a.collection),bi=order.indexOf(b.relatedCollection||b.collection);return (ai<0?999:ai)-(bi<0?999:bi);});
    const more=result.querySelector('[data-ml-number-more]');
    const missing=/не нашёл/i.test(result.textContent||'');
    return {query:numberContext.query,items,total:items.length,hasMore:!!(more&&!more.disabled),numeric:true,empty:missing};
  }
  function publishNumber(){if(numberContext)send('number-update',numberSnapshot());}
  function startNumberWatch(query){
    stopNumberWatch();numberContext={query};
    numberObserver=new MutationObserver(()=>{clearTimeout(numberTimer);numberTimer=setTimeout(publishNumber,250);});
    numberObserver.observe(document.getElementById('res'),{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
    ruIndex().then(index=>{numberRu=index;publishNumber();}).catch(()=>{});
  }
  function originalTools(){
    const menu=document.getElementById('menuModal');if(!menu)throw Error('Меню приложения не найдено');
    let section='Инструменты';const rows=[];
    for(const node of menu.querySelector('.panel').children){
      if(node.classList.contains('hint')&&node.textContent.trim()&&node.style.fontWeight==='700'){section=node.textContent.trim();continue;}
      if(!node.classList.contains('row')||node.style.display==='none'||node.hidden)continue;
      const description=(node.querySelector('span')?.textContent||'').trim();
      const buttons=Array.from(node.querySelectorAll('button[id]')).filter(b=>b.style.display!=='none'&&!b.hidden);
      for(const button of buttons){
        const label=buttons.length>1?description+' — '+button.textContent.trim():description;
        if(label&&button.id)rows.push({id:button.id,label,section});
      }
    }
    return rows;
  }
  function closeCoreDialogs(){
    document.querySelectorAll('.modal').forEach(modal=>{modal.style.display='none';});
  }
  async function request(action,args){
    if(action==='ready')return collections();
    if(action==='catalog')return catalog();
    if(action==='quranWordData')return quranWordData(Number(args.sura),Number(args.ayah),args.text);
    if(action==='quranAudioInfo'){
      const s=Number(args.sura),a=Number(args.ayah);if(!Number.isSafeInteger(s)||s<1||s>114||!Number.isSafeInteger(a)||a<1)throw Error('Неверный номер аята');
      const verses=await loadQuran();if(!verses.some(v=>Number(v.s)===s&&Number(v.a)===a))throw Error('Аят не найден');
      const selected=_чтец(),effective=selected===OMAR_ID&&!OMAR_SURY.has(s)?'Hudhaify_128kbps':selected,url=new URL(_ayahURL(s,a));
      if(url.protocol!=='https:'||!['everyayah.com','cdn.jsdelivr.net'].includes(url.hostname))throw Error('Источник аудио недоступен');
      const labels={OmarHisham:'Омар Хишам',Hudhaify_128kbps:'Али аль-Хузайфи',Alafasy_128kbps:'Мишари аль-Афаси',Husary_128kbps:'Махмуд аль-Хусари',Abdul_Basit_Murattal_192kbps:'Абд аль-Басит',Minshawi_Murattal_128kbps:'Мухаммад аль-Миншави'};
      return {url:url.href,reciter:labels[effective]||effective,fallback:effective!==selected};
    }
    if(action==='quranTimedAudio'){
      const s=Number(args.sura),a=Number(args.ayah),count=Number(args.wordCount);
      if(!Number.isSafeInteger(s)||s<1||s>114||!Number.isSafeInteger(a)||a<1||!Number.isSafeInteger(count)||count<1)throw Error('Неверные данные аята');
      const response=await fetch('./wordtimings/'+s+'.json');if(!response.ok)throw Error('Пословная разметка для суры недоступна');
      const data=await response.json(),verse=data?.v?.[String(a)],segments=verse?.s;
      if(data.rec!=='husary'||!Array.isArray(segments)||!segments.length)throw Error('Разметка не совпала с количеством слов аята');
      const start=Number(verse.f),end=Number(verse.t);let last=start,lastWord=0;
      if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start)throw Error('Неверная разметка времени');
      for(const segment of segments){const [n,f,t]=segment||[];if(!Number.isSafeInteger(n)||n<1||n>count||(n!==lastWord&&n!==lastWord+1)||!Number.isFinite(f)||!Number.isFinite(t)||f<last||t<=f||t>end)throw Error('Разметка слов неполная');last=t;lastWord=n;}
      if(lastWord!==count)throw Error('Разметка не совпала с количеством слов аята');
      const url=new URL(data.audio);if(url.protocol!=='https:'||url.hostname!=='download.quranicaudio.com')throw Error('Источник аудио недоступен');
      return {url:url.href,start,end,segments,reciter:'Махмуд аль-Хусари'};
    }
    if(action==='quranVerse'){
      const s=Number(args.sura),a=Number(args.ayah);
      if(!Number.isSafeInteger(s)||s<1||s>114||!Number.isSafeInteger(a)||a<1)throw Error('Неверный номер аята');
      const verses=await loadQuran(),verse=verses.find(v=>Number(v.s)===s&&Number(v.a)===a);
      if(!verse)throw Error('Аят не найден');
      const row=convert({type:'q',v:verse});try{const translations=await loadQuranRu();row.russian=cleanText(translations[s+':'+a]||row.russian);}catch(_){}
      return row;
    }
    if(action==='quranNeighbor'){
      const s=Number(args.sura),a=Number(args.ayah),direction=Number(args.direction);
      if(!Number.isSafeInteger(s)||s<1||s>114||!Number.isSafeInteger(a)||a<1||![-1,1].includes(direction))throw Error('Неверные данные аята');
      const verses=await loadQuran(),index=verses.findIndex(v=>Number(v.s)===s&&Number(v.a)===a);
      if(index<0)throw Error('Аят не найден');
      const neighbor=verses[index+direction];if(!neighbor)return null;
      const row=convert({type:'q',v:neighbor});
      try{const translations=await loadQuranRu();row.russian=cleanText(translations[neighbor.s+':'+neighbor.a]||row.russian);}catch(_){}
      return row;
    }
    if(action==='bookPageData'){
      const bid=String(args.bid||''),leaf=Number(args.leaf);
      if(!/^\d+$/.test(bid)||!Number.isSafeInteger(leaf)||leaf<1)throw Error('Некорректный номер книги или листа');
      const data=await bjson(BACKEND_URL+'/book_page?id='+encodeURIComponent(bid)+'&pg='+leaf+'&initData='+encodeURIComponent(INITDATA),30000);
      if(!data||data.err)throw Error(String(data?.err||'Страница недоступна').slice(0,180));
      const text=_bkDecodeEnt(String(data.text||'').replace(/<[^>]*>/g,'').replace(/ /g,' '));
      if(!text.trim())throw Error('На этом листе нет текста.');
      const meta=data.meta||{};
      return {bid,leaf,text,printedPage:typeof meta.page==='number'?meta.page:null,volume:meta.vol!=null&&String(meta.vol).trim()?String(meta.vol).replace(/[^0-9]/g,'')||String(meta.vol):null,headings:Array.isArray(meta.headings)?meta.headings.filter(x=>typeof x==='string'):[]};
    }
    // The hadith's own leaf in the printed edition (owner 29.10: «читалка — оригинал книги»). Same search the app's
    // openMaktabaPage does: «N -» in the collection's book, checked against the matn, then the matn itself.
    if(action==='locateLeaf'){
      let code=String(args.collection||'');if(code==='ibnmaja')code='ibnmajah';
      const num=String(args.number||'').replace(/[^0-9]/g,''),text=String(args.text||'');
      let bid=String((typeof COLL_BIDS!=='undefined'&&COLL_BIDS[code]&&COLL_BIDS[code][0])||(typeof EXTRA_BIDS!=='undefined'&&EXTRA_BIDS[code])||'');
      if(!/^\d+$/.test(bid))throw Error('Для этой книги страница издания пока не связана');
      if(bid==='1727')bid='711';
      const ask=async q=>{const j=await bjson(BACKEND_URL+'/maktaba?q='+encodeURIComponent(q)+'&book='+bid+'&page=1&initData='+encodeURIComponent(INITDATA),20000);return (j&&j.data)||[];};
      let leaf=null;
      // Muslim: our edition's numbers are not the Turkish edition's (nor muslim_lists.json's, keyed by Abd al-Baqi),
      // so a number would land on another hadith. Find it by the matn and accept only a leaf that carries it.
      if(bid==='711'){const snip=_matnSnippet(text);if(snip){const hit=(await ask(snip)).find(x=>String(x.book_id)===bid&&_листПодходит(x.snip,text));if(hit)leaf=hit.page_id||hit.page;}
        if(!leaf)throw Error('Этот хадис в издании Муслима по тексту не найден');}
      if(!leaf&&num){const hit=(await ask(num.replace(/[0-9]/g,d=>'٠١٢٣٤٥٦٧٨٩'[+d])+' -')).find(x=>String(x.book_id)===bid&&_листПодходит(x.snip,text));if(hit)leaf=hit.page_id||hit.page;}
      if(!leaf){const snip=_matnSnippet(text);if(snip){const hit=(await ask(snip)).find(x=>String(x.book_id)===bid);if(hit)leaf=hit.page_id||hit.page;}}
      if(!leaf)throw Error('Этот хадис в издании не найден');
      // Strict: show a leaf only if it really carries this hadith — its printed number, or 6 of 10 matn words.
      const norm=s=>String(s||'').replace(/<[^>]*>/g,'').replace(/[ً-ْٰـ]/g,'').replace(/[إأآٱ]/g,'ا');
      const carries=async l=>{const p=await bjson(BACKEND_URL+'/book_page?id='+encodeURIComponent(bid)+'&pg='+l+'&initData='+encodeURIComponent(INITDATA),30000);const t=norm(p&&p.text);if(!t)return false;
        if(num&&bid!=='711'&&new RegExp('(^|[\\s(])('+num.replace(/[0-9]/g,d=>'٠١٢٣٤٥٦٧٨٩'[+d])+'|'+num+')\\s*-','m').test(t))return true;
        const words=norm(text).split(/\s+/).filter(w=>w.length>3).slice(6,16);return words.length>=4&&words.filter(w=>t.includes(w)).length>=Math.ceil(words.length*.6);};
      if(await carries(leaf))return {bid,leaf:Number(leaf)};
      if(await carries(Number(leaf)+1))return {bid,leaf:Number(leaf)+1};
      throw Error('Точная страница этого хадиса в издании не найдена');
    }
    // Edition data as the library card gives it (tahqiq, publisher, printing) — the source's own words, not ours.
    if(action==='bookMeta'){
      const bid=String(args.bid||'');if(!/^\d+$/.test(bid))throw Error('Некорректный номер книги');
      const bm=await bjson(BACKEND_URL+'/book_meta?id='+bid+'&initData='+encodeURIComponent(INITDATA),15000);
      return {info:String(bm&&bm.info||'').trim()};
    }
    // № хадиса inside one book: the edition prints «N -» at its start (as رقم الحديث in Maktaba).
    if(action==='leafByHadith'){
      const bid=String(args.bid||''),num=String(args.number||'').replace(/[^0-9]/g,'');
      if(!/^\d+$/.test(bid)||!num)throw Error('Введите номер хадиса');
      const arabic=num.replace(/[0-9]/g,d=>'٠١٢٣٤٥٦٧٨٩'[+d]);
      const j=await bjson(BACKEND_URL+'/maktaba?q='+encodeURIComponent(arabic+' -')+'&book='+bid+'&page=1&initData='+encodeURIComponent(INITDATA),20000);
      const starts=x=>new RegExp('^\\s*(?:\\(?[٠-٩]+\\)?\\s*)?'+arabic+'\\s*-').test(String(x.snip||'').replace(/<[^>]*>/g,''));
      const hit=((j&&j.data)||[]).filter(x=>String(x.book_id)===bid).find(starts);
      if(!hit)throw Error('Хадис №'+num+' в этой книге не найден');
      return {leaf:Number(hit.page_id||hit.page)};
    }
    // Last leaf of a book: grow until the server says «no page», then halve back. Remembered per book.
    if(action==='lastLeaf'){
      const bid=String(args.bid||'');if(!/^\d+$/.test(bid))throw Error('Некорректный номер книги');
      lastLeafCache=lastLeafCache||{};if(lastLeafCache[bid])return {leaf:lastLeafCache[bid]};
      const has=async l=>{try{const d=await bjson(BACKEND_URL+'/book_page?id='+bid+'&pg='+l+'&initData='+encodeURIComponent(INITDATA),20000);return !!(d&&!d.err&&String(d.text||'').trim());}catch(e){return false;}};
      let lo=Math.max(1,Number(args.from)||1),hi=lo*2;while(await has(hi)){lo=hi;hi*=2;if(hi>200000)break;}
      while(hi-lo>1){const mid=Math.floor((lo+hi)/2);if(await has(mid))lo=mid;else hi=mid;}
      lastLeafCache[bid]=lo;return {leaf:lo};
    }
    if(action==='bookInfo')return bookInfo(args.collection);
    if(action==='toolsCatalog')return originalTools();
    // Помощник мини-аппа на отдельном Гермесе (владелец #4302): своя сессия на пользователя, экран и белый список действий.
    if(action==='hermesAsk'){
      const question=String(args.question||'').trim();if(!question)throw Error('Введите вопрос');
      const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),150000);
      try{
        const response=await fetch(BACKEND_URL+'/hermes',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
          body:JSON.stringify({q:question,initData:INITDATA,ekran:String(args.screen||'').slice(0,400),deystviya:Array.isArray(args.actions)?args.actions.slice(0,30):[]})});
        const data=await response.json().catch(()=>({}));
        if(!response.ok||!data.answer)throw Error(data.error||data.message||(response.status===429?'Лимит запросов исчерпан. Попробуйте позже.':'Помощник сейчас недоступен.'));
        return {answer:String(data.answer),model:String(data.model||'')};
      }finally{clearTimeout(timeout);}
    }
    if(action==='assistantAsk'){
      const question=String(args.question||'').trim();if(!question)throw Error('Введите вопрос');
      const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),60000);
      try{
        const response=await fetch(BACKEND_URL+'/assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q:question,initData:INITDATA}),signal:controller.signal});
        const data=await response.json().catch(()=>({}));
        if(!response.ok)throw Error(data.message||(response.status===429?'Лимит запросов исчерпан. Попробуйте позже.':'Помощник сейчас недоступен.'));
        if(!data.answer)throw Error(data.error||'Сервер не вернул ответ.');
        return {answer:String(data.answer),cached:!!data.cached};
      }finally{clearTimeout(timeout);}
    }
    if(action==='showOriginalHome'){
      document.body.classList.remove('ml-tool-only');closeCoreDialogs();
      const app=document.getElementById('app');if(app)app.style.display='block';
      window.scrollTo(0,0);return {ok:true};
    }
    if(action==='openOriginalTool'){
      const toolId=String(args.id||'');
      if(!originalTools().some(item=>item.id===toolId))throw Error('Инструмент недоступен');
      document.body.classList.remove('ml-tool-only');closeCoreDialogs();
      const menu=document.getElementById('menuBtn');if(!menu)throw Error('Меню приложения не найдено');
      menu.click();
      const target=document.getElementById(toolId);if(!target||target.disabled)throw Error('Инструмент недоступен');
      target.click();return {ok:true};
    }
    if(action==='search'){
      const query=String(args.query||'').trim().slice(0,2000);
      if(!query)return {items:[],total:0,notice:''};
      stopNumberWatch();
      const wanted=args.section==='quran'?'quran':'hadith';
      const field=document.getElementById('q');field.value='';
      const mode=['root','diac','rag','matnonly','narr','chain'].includes(args.mode)?args.mode:'normal';
      document.querySelectorAll('.chip[data-mode]').forEach(chip=>{
        const should=chip.dataset.mode===mode;
        if(chip.classList.contains('on')!==should)chip.click();
      });
      if(wanted==='hadith'&&Array.isArray(args.scope)&&args.scope.length){
        if(args.scope.length>100)throw Error('Слишком много условий выбора');
        const info=await catalog(),data=await loadCatalog(),all=new Set(data.map(b=>String(b.i))),included=new Set(),excluded=new Set();let hasIncludes=false;
        const conditions=args.scope.slice();
        if(args.collection&&args.collection!=='all')conditions.push({kind:'book',id:String(args.collection),exclude:false});
        if(args.category&&args.category!=='all')conditions.push({kind:'category',id:String(args.category),exclude:false});
        for(const item of conditions){
          let ids;
          if(item.kind==='book'){
            const book=info.collections.find(c=>String(c.id)===String(item.id));
            if(!book||!book.bid)throw Error('Для выбранной книги не найдено издание в каталоге');
            ids=[String(book.bid)];
          }else if(item.kind==='category'){
            if(!info.categories.some(c=>String(c.id)===String(item.id)))throw Error('Раздел не найден в каталоге');
            ids=data.filter(b=>String(b.c)===String(item.id)).map(b=>String(b.i));
          }else throw Error('Неизвестное условие поиска');
          const target=item.exclude?excluded:included;if(!item.exclude)hasIncludes=true;ids.forEach(id=>target.add(id));
        }
        const selected=hasIncludes?included:all;excluded.forEach(id=>selected.delete(id));
        if(!selected.size)return {items:[],total:0,notice:'После исключений не осталось книг для поиска.'};
        document.body.classList.remove('ml-tool-only');document.querySelector('.tab[data-tab="hadith"]').click();
        _scopeIds=selected;_scopeName='Выбранные книги и разделы';document.getElementById('q').value=query;
        const numeric=query.replace(/[٠-٩]/g,d=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(d))).replace(/[№#\s]/g,''),numberMode=/^\d{1,5}$/.test(numeric)&&Number(numeric)>=1;
        if(numberMode)startNumberWatch(query);await runSearch(true);
        if(numberMode)return numberSnapshot();
        return {opened:true,items:[],total:0,notice:''};
      }
      if(wanted==='hadith'&&((args.category&&args.category!=='all')||String(args.collection||'').startsWith('book:'))){
        const info=await catalog(),category=info.categories.find(c=>c.id===args.category),book=info.collections.find(c=>c.id===args.collection);
        if(!category&&!book)throw Error('Книга или раздел не найдены в каталоге');
        const data=await loadCatalog();
        document.body.classList.remove('ml-tool-only');
        document.querySelector('.tab[data-tab="hadith"]').click();
        _scopeIds=book?new Set([String(book.bid)]):new Set(data.filter(b=>b.c===category.id).map(b=>String(b.i)));_scopeName=book?book.title:category.title;
        document.getElementById('q').value=query;
        const numeric=query.replace(/[٠-٩]/g,d=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(d))).replace(/[№#\s]/g,'');
        const numberMode=/^\d{1,5}$/.test(numeric)&&Number(numeric)>=1;
        if(numberMode)startNumberWatch(query);
        await runSearch(true);
        if(numberMode)return numberSnapshot();
        return {opened:true,items:[],total:0,notice:''};
      }
      _scopeIds=null;_scopeName='';
      const tabEl=document.querySelector('.tab[data-tab="'+wanted+'"]');
      if(tabEl&&!tabEl.classList.contains('active'))tabEl.click();
      if(typeof selCols!=='undefined'){
        selCols.clear();if(args.collection&&args.collection!=='all')selCols.add(String(args.collection));
        if(typeof renderCols==='function')renderCols();
      }
      field.value=query;
      const numeric=query.replace(/[٠-٩]/g,d=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(d))).replace(/[№#\s]/g,'');
      const numberMode=wanted==='hadith'&&/^\d{1,5}$/.test(numeric)&&Number(numeric)>=1;
      if(numberMode)startNumberWatch(query);
      // runSearch is explicit here. Dispatching input also schedules the core's
      // debounced live search, which cancels this request and returns an empty list.
      await runSearch(true);
      if(numberMode)return numberSnapshot();
      const results=typeof _results!=='undefined'?_results:[];
      const items=Array.from(results).slice(0,120).map(convert);
      if(wanted==='quran'){
        try{const translations=await loadQuranRu();for(const row of items)row.russian=cleanText(translations[row.sura+':'+row.ayah]||row.russian);}catch(e){}
      }
      if(items.some(row=>row.kind==='hadith'&&!row.russian)){
        try{const index=await ruIndex();for(const row of items)if(row.kind==='hadith'&&!row.russian&&canPairText(row))row.russian=cleanText(index.get(row.collection+'|'+row.number)||'');}catch(e){}
      }
      for(const row of items)if(row.kind==='hadith'&&!canPairText(row)){row.pairingUnverified=true;if(row.arabic&&row.russian)row.russian='';}
      const status=document.getElementById('status');
      return {items,total:results.length,notice:items.length?'':String(status&&status.textContent||'Совпадений не найдено')};
    }
    if(action==='read'){
      const row=Object.assign({},args.record||{});
      if(row.kind==='book'){
        // Search snippets are not full verified hadiths. The legacy expansion
        // falls back to an unrelated page fragment if the exact marker is absent.
        // Keep the excerpt labelled and let the reader open the source page.
        return row;
      }
      if(row.kind==='quran'){
        // The primary Quran record always carries the original Arabic text.
        if(!row.russian){try{const translations=await loadQuranRu();row.russian=cleanText(translations[row.sura+':'+row.ayah]||'');}catch(e){}}
        return row;
      }
      if(!row.arabic&&row.collection&&row.number&&(!row.russian||canPairText(row))){try{row.arabic=await getArabicHadith(row.collection,row.number);}catch(e){}}
      if(!row.russian&&row.collection&&row.number&&canPairText(row)){try{const index=await ruIndex();row.russian=cleanText(index.get(row.collection+'|'+row.number)||'');}catch(e){}}
      if(!canPairText(row)){row.pairingUnverified=true;if(row.arabic&&row.russian)row.russian='';}
      try{await sourceParts(row);}catch(e){}
      return row;
    }
    if(action==='browse'){
      const code=String(args.collection||'');
      if(code.startsWith('book:')){
        const book=(await catalog()).collections.find(c=>c.id===code);if(!book)throw Error('Книга отсутствует в каталоге');
        document.body.classList.remove('ml-tool-only');openBook(book.bid);return {opened:true,items:[],total:0};
      }
      if(!collections().collections.some(x=>x.id===code))throw Error('Выберите сборник из библиотеки');
      const arr=await _читалкаМассив(code);
      const rows=arr.filter(h=>h&&h.num!=null&&String(h.num)!=='0'&&(!h.вид||h.вид==='хадис'));
      let index;try{index=await ruIndex();}catch(e){}
      const items=rows.slice(0,100).map(h=>{
        const r=convert({code,h});if(index&&canPairText(r))r.russian=cleanText(index.get(code+'|'+h.num)||'');if(!canPairText(r))r.pairingUnverified=true;return r;
      });
      return {items,total:rows.length,notice:''};
    }
    if(action==='numberMore'){
      if(!numberContext||args.query!==numberContext.query)throw Error('Поиск уже изменился');
      const more=document.querySelector('#res [data-ml-number-more]');
      if(more&&!more.disabled&&typeof more.onclick==='function')await more.onclick();
      return numberSnapshot();
    }
    if(action==='scientific'){
      const row=args.record||{},cached=records.get(row.id);
      document.body.classList.add('ml-tool-only');
      const app=document.getElementById('app');app.style.display='block';
      const res=document.getElementById('res');res.innerHTML='';
      if(cached)res.appendChild(makeCard(cached.original));
      else if(row.kind==='hadith')res.appendChild(cardHadithRu({s:row.collection,n:row.number,ru:row.russian||'',rq:''}));
      else if(row.kind==='quran'&&typeof openQuranReader==='function')openQuranReader(row.sura,row.ayah);
      window.scrollTo(0,0);return {ok:true};
    }
    if(action==='tool'){
      const tool=String(args.tool||''),row=args.record||{};
      document.body.classList.remove('ml-tool-only');closeCoreDialogs();
      if(tool==='quranReader'&&row.kind==='quran'&&row.sura&&row.ayah){await openQuranReader(row.sura,row.ayah);return {ok:true};}
      if(tool==='assistant'){openAssistant(row.arabic?'Вопрос по тексту: '+row.arabic:'');return {ok:true};}
      if(tool==='bookPage'&&row.kind==='book'&&row.bid&&row.page){openBook(row.bid,row.page,false,'');return {ok:true};}
      if(tool==='explain'&&row.kind==='book'){openAssistant(row.arabic?'Вопрос по тексту: '+row.arabic:'');return {ok:true};}
      if(tool==='notes'&&row.kind==='book'){openNotes();return {ok:true};}
      if(tool==='rag'){
        const tab=document.querySelector('.tab[data-tab="hadith"]');if(tab&&!tab.classList.contains('active'))tab.click();
        const chip=document.querySelector('.chip[data-mode="rag"]');if(!chip)throw Error('RAG-поиск недоступен');
        if(!chip.classList.contains('on'))chip.click();document.getElementById('q')?.focus();return {ok:true};
      }
      if(tool==='chain'){
        document.getElementById('q').value='';
        const tabEl=document.querySelector('.tab[data-tab="hadith"]');if(tabEl&&!tabEl.classList.contains('active'))tabEl.click();
        document.getElementById('res').innerHTML='';_results=[];_scopeIds=null;_scopeName='';
        openIsnadCtor();return {ok:true};
      }
      if(!['versions','narrators','explain','audio','notes','source'].includes(tool))throw Error('Инструмент не найден');
      await request('scientific',{record:row});
      const labels={versions:/Версии|где расходятся/i,narrators:/Передатчики|Разобрать цепочку/i,explain:/Объяснить/i,audio:/Озвуч|Прослуш|Слушать/i,notes:/Замет/i,source:/Страница в Мактабе/i};
      const controls=Array.from(document.querySelectorAll('#res button,#res [role="button"]'));
      const button=controls.find(b=>labels[tool].test((b.textContent||'')+' '+(b.title||'')));
      if(button)button.click();
      else if(tool==='versions'){
        const card=document.querySelector('#res .card');if(card&&row.arabic){const out=document.createElement('div');card.appendChild(out);await openIsnadVersions(row.arabic,out,{coll:row.collection,num:row.number});}
      }else if(tool==='notes'){openNotes();}
      else throw Error('Инструмент не доступен для этой записи');
      return {ok:true};
    }
    if(action==='library'){
      document.body.classList.remove('ml-tool-only');
      document.getElementById('maktabaTopBtn').click();return {ok:true};
    }
    throw Error('Неизвестное действие');
  }
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin||event.source!==parent||event.data?.source!=='muslimoon-design-ui')return;
    const {id,action,args}=event.data;
    if(typeof id!=='string'||!['ready','catalog','bookInfo','bookPageData','locateLeaf','bookMeta','leafByHadith','lastLeaf','hermesAsk','quranWordData','quranAudioInfo','quranTimedAudio','quranVerse','quranNeighbor','search','read','browse','scientific','library','tool','toolsCatalog','openOriginalTool','showOriginalHome','numberMore','assistantAsk'].includes(action))return;
    serial=serial.then(()=>request(action,args||{})).then(payload=>send(id,payload)).catch(e=>send(id,null,String(e&&e.message||e)));
  });
  let attempts=0;
  const timer=setInterval(()=>{
    attempts++;
    if(document.documentElement.dataset.jsok&&typeof runSearch==='function'){
      clearInterval(timer);send('ready',collections());
    }else if(attempts>300){clearInterval(timer);send('ready',null,'Не удалось запустить поисковое ядро');}
  },100);
})();

// Уход из приложения из ядра (владелец 29.10): окно «Выйти из приложения?» ядра рисуется в скрытой рамке, и человек его
// не видит. Поэтому ядро ничего не открывает само — отдаёт адрес странице, а та спрашивает и открывает.
(function(){
  if(window.top===window)return;
  const external=u=>{try{const x=new URL(String(u),location.href);return /^https?:$/.test(x.protocol)&&x.host!==location.host;}catch(_){return false;}};
  const handOver=u=>{try{parent.postMessage({muslimoonLeave:String(u)},'*');}catch(_){}};
  try{window.openLink=function(u){const url=String(u||'');if(!url)return;if(external(url))handOver(url);};}catch(_){}
  const nativeOpen=window.open;window.open=function(u){if(u&&external(u)){handOver(u);return null;}return nativeOpen.apply(window,arguments);};
  document.addEventListener('click',event=>{const a=event.target.closest&&event.target.closest('a[href]');if(!a||!external(a.href))return;event.preventDefault();event.stopPropagation();handOver(a.href);},true);
})();
