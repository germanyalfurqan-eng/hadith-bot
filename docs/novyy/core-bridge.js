/* Narrow presentation bridge to the genuine v1807 search/reading functions. */
(function(){
  'use strict';
  const source='muslimoon-v1807-core';
  const records=new Map();
  // Numbering differs across editions. Do not join independently sourced
  // Arabic and Russian texts by collection+number alone. These two pairs were
  // checked against the actual texts during the current preview session.
  const verifiedTextPairs=new Set(['bukhari|1','bukhari|321']);
  // 29.10 (owner: «как это арабский недоступен?»): for al-Bukhari and Abu Dawud our Russian numbering is the Arabic one —
  // the old app pairs them the same way; 9 of 9 sampled pairs matched by meaning. Muslim differs and stays unpaired.
  const pairedCollections=new Set(['bukhari','abudawud']);
  const canPairText=row=>pairedCollections.has(String(row.collection))||verifiedTextPairs.has(String(row.collection)+'|'+String(row.number));
  const names={bukhari:'Сахих аль-Бухари',muslim:'Сахих Муслим',abudawud:'Сунан Абу Дауда',tirmidhi:'Сунан ат-Тирмизи',nasai:'Сунан ан-Насаи',ibnmajah:'Сунан Ибн Маджи',ibnmaja:'Сунан Ибн Маджи',malik:'Муватта имама Малика',ahmad:'Муснад имама Ахмада',nawawi:'40 хадисов ан-Навави',muhaymin:'Мухэймин'};
  const send=(id,payload,error)=>parent.postMessage({source,id,payload,error},location.origin);
  let ruPromise=null;
  let quranWordAssets=null;
  const modelData={};
  function modelFile(name){if(!modelData[name])modelData[name]=fetch('./novyy/data/'+name).then(r=>r.ok?r.json():{}).catch(()=>({}));return modelData[name];}
  // Готовая цепь хадиса из базы цепей (dz). У сборника бывает несколько изданий, и опознание в них разное: у ат-Тирмизи
  // в 1435 №1 — «Абу Авана» = Якуб ибн Исхак (ум. 316) и «Ибн Умар» = Ибн Умар ибн Аби Салама, в 7895 — аль-Ваддах и
  // Абдуллах ибн Умар. Берём запись, чьи передатчики лучше совпадают с текстом иснада (совпало +2, нет −1).
  // Замер 29.10 по ат-Тирмизи: 7895 опознаёт 23 837 звеньев (91% в тексте), 1435 — 10 807 (94%), 1363 — 7 012 (20%).
  async function bestChain(collection,number,text){
    if(typeof dzChainFull!=='function')return null;
    const n=String(number||'').replace(/\D.*$/,'');if(!collection||!n)return null;
    const bids=new Set();
    try{const book=(await catalog()).collections.find(c=>String(c.id)===String(collection));if(book&&book.bid)bids.add(String(book.bid));}catch(e){}
    try{if(typeof _BID2READ==='object')for(const [b,c] of Object.entries(_BID2READ))if(c===String(collection))bids.add(String(b));}catch(e){}
    const fold=t=>String(t||'').replace(/[ً-ٰٟـ]/g,'').replace(/[أإآ]/g,'ا');
    const T=fold(text),STOP=new Set(['بن','ابن','ابو','ابي','عبد','بنت','ام','الله']);
    let best=null,bestScore=-Infinity;
    for(const b of bids){
      let r=null;try{r=await dzChainFull(+b,n);}catch(e){}if(!r||!r.seq||!r.seq.length)continue;
      let hit=0,cnt=0;
      for(const id of r.seq){if(typeof id!=='number')continue;cnt++;let c=null;try{c=await _narrCard(id);}catch(e){}
        const w=fold(c&&c[1]).split(/\s+/).filter(t=>t.length>2&&!STOP.has(t));if(T&&w.length&&w.slice(0,2).some(t=>T.includes(t)))hit++;}
      const score=T?hit*2-(cnt-hit):cnt;
      if(score>bestScore){bestScore=score;best=Object.assign({bid:b,ratio:cnt?hit/cnt:0},r);}
    }
    // Заслон: у Муслима нумерация базы цепей не наша — на 50 случайных хадисах с текстом сошлось 11% имён (цепи от других
    // хадисов). Цепь, где с иснадом сходится меньше половины имён, не показываем: лучше имена из самого текста, чем чужая цепь.
    if(best&&T&&best.ratio<0.5)return null;
    return best;
  }
  async function quranWordData(sura,ayah,displayedText){
    if(!Number.isSafeInteger(sura)||sura<1||sura>114||!Number.isSafeInteger(ayah)||ayah<1)throw Error('Неверный номер аята');
    const verses=await loadQuran(),verse=verses.find(v=>Number(v.s)===sura&&Number(v.a)===ayah);
    if(!verse||String(verse.text||'').trim()!==String(displayedText||'').trim())throw Error('Текст аята отличается от источника; разбор не показан.');
    if(!quranWordAssets)quranWordAssets=Promise.all(['./quran_roots.json','./quran_wbw_ru.json'].map(url=>fetch(url).then(r=>{if(!r.ok)throw Error('Данные слов недоступны');return r.json();}))).catch(e=>{quranWordAssets=null;throw e;});
    const [roots,translations]=await quranWordAssets;
    const tokens=String(verse.text).split(/(\s+)/).filter(Boolean),words=tokens.filter(t=>/[ء-ي]/.test(t));
    // у 770 аятов в quran_wbw_ru.json пословного нет — дописан моделью (data/quran_wbw_dop.json, черновой)
    let dop=null;if(!Array.isArray(translations[`${sura}:${ayah}`])){try{dop=(await modelFile('quran_wbw_dop.json'))[`${sura}:${ayah}`]||null;}catch(e){}}
    const gloss=translations[`${sura}:${ayah}`]||dop,glossAi=!!dop,aligned=Array.isArray(gloss)&&gloss.length===words.length;
    const lemmas=await modelFile('quran_lemmas_ru.json'),lemmas2=await modelFile('quran_lemmas_v2.json'),pl=t=>String(t||'').replace(/[\u064B-\u065F\u0670\u0640]/g,'').trim();
    // Разметка по МЕСТУ слова (Quranic Arabic Corpus, data/morph/<сура>.json): корень, огласованная лемма, падеж — свои у
    // каждого слова аята. Прежняя (quran_roots.json) была по написанию — одна на весь Коран, отсюда «ٱللَّهُ» в 2:255
    // «родительный» и «سِنَةٌ» — «год». Нет аята в разметке или не сошлось число слов — берём прежнюю.
    let place=null;try{const m=await modelFile('morph/'+sura+'.json');const rows=m&&m[String(ayah)];if(Array.isArray(rows)&&rows.length===words.length)place=rows;}catch(e){}
    let index=0;return {sura,ayah,aligned,byPlace:!!place,tokens:tokens.map(token=>{
      if(!/[ء-ي]/.test(token))return {text:token};
      const p=place?place[index]:null,e=p?[p[0],p[1],p[2]]:roots.f?.[rootKey(token)],root=Array.isArray(e)&&e[0]?String(e[0]):'';
      const refs=root&&Array.isArray(roots.r?.[root])?roots.r[root]:[];
      const lemma=Array.isArray(e)&&e[1]?String(e[1]):'',info=lemma?(lemmas2[lemma]||(p?null:lemmas[pl(lemma)])||null):null;
      return {text:token,word:true,index:index++,place:!!p,translation:aligned?String(gloss[index-1]||''):'',translationAi:glossAi,root,lemma,lemmaInfo:info,tag:Array.isArray(e)&&e[2]?String(e[2]):'',grammar:Array.isArray(e)&&e[2]?gramRu(String(e[2])):'',parts:p&&Array.isArray(p[3])?p[3].map(x=>({text:String(x[0]),tag:String(x[1]),grammar:gramRu(String(x[1]))})):[],references:refs,referenceCount:refs.length};
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
  // Library search (chosen books and sections) — its finds as new-look cards, not the old window (owner П-46).
  let mkRows=null;
  try{if(typeof maktabaCard==='function'){const draw=maktabaCard;window.maktabaCard=function(x){try{if(mkRows&&x&&x.book_id!=null)mkRows.push(x);}catch(e){}return draw.apply(this,arguments);};}}catch(e){}
  async function libraryResults(){
    // the library pass draws its cards after runSearch returns: wait until they appear and stop growing (≤10 s)
    // When the first page of the whole library has nothing in the chosen books, the core waits for «Ещё из Мактабы»
    // (in a visible window scrolling pressed it); here it is pressed for the person, up to six pages.
    let seen=-1,steady=0,more=0;for(let i=0;i<40&&mkRows;i++){await new Promise(r=>setTimeout(r,500));
      if(!mkRows.length&&more<6&&i%3===2){const b=[...document.querySelectorAll('#res button')].find(x=>/Ещё из Мактабы/.test(x.textContent||''));if(b){b.click();more++;continue;}}
      if(mkRows.length&&mkRows.length===seen){if(++steady>=2)break;}else steady=0;seen=mkRows.length;}
    const rows=mkRows||[];mkRows=null;
    const status=document.getElementById('status');
    if(!rows.length)return {items:[],total:0,notice:String(status&&status.textContent||'В выбранных книгах совпадений не найдено')};
    const items=rows.slice(0,120).map(x=>{
      const bid=String(x.book_id),pid=x.page_id||x.page||1,snip=typeof _cleanMaktabaSnip==='function'?_cleanMaktabaSnip(x.snip||''):String(x.snip||'');
      const row={id:'b:'+bid+':'+pid,kind:'book',bid,page:pid,collection:'book:'+bid,title:x.book_name||('Книга № '+bid),bookTitle:x.book_name||('Книга № '+bid),
        number:(x.vol?'т. '+x.vol+' · ':'')+(x.page!=null?'стр. '+x.page:''),arabic:cleanText(snip),russian:'',author:x.author||''};
      records.set(row.id,{original:x,row});return row;});
    return {items,total:rows.length,notice:'',heading:'В книгах библиотеки · '+(_scopeName||'выбранные')};
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
      const pad=n=>String(n).padStart(3,'0'),forced=args.reciter==='Husary_128kbps';   // тот же чтец, что у подсветки
      const selected=forced?'Husary_128kbps':_чтец(),effective=selected===OMAR_ID&&!OMAR_SURY.has(s)?'Hudhaify_128kbps':selected,url=new URL(forced?`https://everyayah.com/data/Husary_128kbps/${pad(s)}${pad(a)}.mp3`:_ayahURL(s,a));
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
      // the reciter may repeat a phrase (40:40 — words 17–19 twice): a word may come back; time only moves forward
      let maxWord=0;for(const segment of segments){const [n,f,t]=segment||[];if(!Number.isSafeInteger(n)||n<1||n>count||!Number.isFinite(f)||!Number.isFinite(t)||f<last-50||t<=f||t>end+50)throw Error('Разметка слов неполная');last=t;lastWord=n;maxWord=Math.max(maxWord,n);}
      // первый аят суры в тексте приложения начинается с басмалы (4 слова), а разметка считает только сам аят — сдвигаем
      let shift=0;if(a===1&&s!==1&&s!==9&&maxWord+4===count)shift=4;
      if(maxWord+shift!==count)throw Error('Разметка не совпала с количеством слов аята');
      const url=new URL(data.audio);if(url.protocol!=='https:'||url.hostname!=='download.quranicaudio.com')throw Error('Источник аудио недоступен');
      return {url:url.href,start,end,segments:shift?segments.map(([n,f,t])=>[n+shift,f,t]):segments,reciter:'Махмуд аль-Хусари'};
    }
    // Arabus (our downloaded dictionary): the dictionary form of a Quran word and its meanings — by lemma, then the word itself.
    if(action==='arabus'){
      if(typeof loadArabusLocal!=='function'||typeof arabusLocalLookup!=='function')return {entries:[]};
      await loadArabusLocal();const plain=t=>String(t||'').replace(/[\u064B-\u065F\u0670\u0640]/g,'').trim();
      let hit=null;for(const w of [args.lemma,args.word].map(plain).filter(Boolean)){try{hit=arabusLocalLookup(w,plain(args.root));}catch(e){}if(hit&&hit.entries&&hit.entries.length)break;}
      // the entry that IS the word's dictionary form comes first (سَيِّئَة — «зло», not the verb سَوَّأَ of the same root)
      // exact — буква в букву, с хамзой: при свёрнутой хамзе имя إِلَٰه «совпадало» с глаголом أَلَّهَ (проверка 29.10);
      // near — совпало лишь со свёрнутой хамзой: берётся, только если у слова нет своей статьи словаря лемм
      const strict=t=>plain(t).replace(/ة$/,'ه').replace(/[ٌٍٓ]/g,''),fold=t=>strict(t).replace(/[أإآ]/g,'ا');
      // с огласовкой: без танвина, сукуна и падежной гласной в конце; шадда и гласная — в одном порядке
      const vk=t=>String(t||'').replace(/[\u064B-\u064D\u0652\u0640]/g,'').replace(/ٱ/g,'ا').replace(/\u0670/g,'ا').replace(/([\u064E\u064F\u0650])\u0651/g,'\u0651$1').replace(/[\u064E\u064F\u0650]$/,'').replace(/ة$/,'ه');
      const voweled=/[\u064E\u064F\u0650]/.test(String(args.lemma||''));
      const lem=strict(args.lemma);
      const list=((hit&&hit.entries)||[]).map(x=>({ar:String(x.ar||''),gram:String(x.gram||''),ru:String(x.ru||''),exact:!!lem&&strict(x.ar)===lem&&(!voweled||vk(x.ar)===vk(args.lemma)),near:!!lem&&fold(x.ar)===fold(args.lemma)}));
      list.sort((x,y)=>(y.exact?2:y.near?1:0)-(x.exact?2:x.near?1:0));
      return {entries:list.slice(0,8),matched:String((hit&&(hit.matched||hit.word))||''),exact:list.some(x=>x.exact)};
    }
    // Тафсир аята — те же своды, что у прежнего вида (Ибн Касир, ас-Саади, Мухтасар, ат-Табари, аль-Куртуби, аль-Багави).
    if(action==='tafsir'){
      const s=Number(args.sura),a=Number(args.ayah);if(!Number.isSafeInteger(s)||s<1||s>114||!Number.isSafeInteger(a)||a<1)throw Error('Неверный номер аята');
      const list=typeof TAFSIRS!=='undefined'?TAFSIRS:[],tf=list.find(t=>t.key===args.key)||list[0];if(!tf)throw Error('Тафсиры недоступны');
      const lang=args.lang==='ru'&&tf.ru?'ru':'ar',ed=lang==='ru'?tf.ru:tf.ar;
      const j=await fetchJSON(TAFSIR_CDN+ed+'/'+s+'/'+a+'.json',15000,{silent:true});
      let text=String((j&&j.text)||'').replace(/\[\[[^\]]*\]\]/g,'').trim();
      let ours=null;try{const ot=await loadOurTafsir();ours=ot&&ot[s+':'+a]||null;}catch(e){}
      return {text,lang,key:tf.key,name:tf.nm,hasRu:!!tf.ru,list:list.map(t=>({key:t.key,name:t.nm,ru:!!t.ru})),recommended:ours&&ours.tafk||''};
    }
    // Настройки чтения Корана, общие с прежним видом: перевод (Кулиев / Абу Адель) и чтец.
    if(action==='quranSettings'){
      if(args.qtr&&['rus-elmirkuliev','rus-abuadel'].includes(args.qtr)){cfg.qtr=args.qtr;saveCfg(cfg);try{quranRu=null;}catch(e){}}
      if(args.reciter&&/^[A-Za-z0-9_]+$/.test(args.reciter)){cfg.reciter=args.reciter;saveCfg(cfg);}
      return {qtr:cfg.qtr||'rus-elmirkuliev',reciter:_чтец(),translations:[['rus-elmirkuliev','Кулиев'],['rus-abuadel','Абу Адель']],
        reciters:[['OmarHisham','Омар Хишам'],['Husary_128kbps','Махмуд аль-Хусари'],['Alafasy_128kbps','Мишари аль-Афаси'],['Abdul_Basit_Murattal_192kbps','Абд аль-Басит'],['Minshawi_Murattal_128kbps','Мухаммад аль-Миншави'],['Hudhaify_128kbps','Али аль-Хузайфи']]};
    }
    // Вся сура лентой: арабский и перевод каждого аята.
    if(action==='suraVerses'){
      const s=Number(args.sura);if(!Number.isSafeInteger(s)||s<1||s>114)throw Error('Неверный номер суры');
      const verses=(await loadQuran()).filter(v=>Number(v.s)===s);let tr={};try{tr=await loadQuranRu();}catch(e){}
      return {sura:s,name:(typeof SURA_RU!=='undefined'&&SURA_RU[s])||'',verses:verses.map(v=>({a:Number(v.a),text:String(v.text||''),ru:cleanText(tr[s+':'+v.a]||'')}))};
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
    // Конструктор цепи: подбор передатчика по имени (тот же narrCandidates, что у прежнего вида) и поиск по реестру цепей.
    // Корень по формам — как «Quran Dictionary» на corpus.quran.com: ذ ك ر — 292 раза в 14 формах (84 — глагол I породы
    // ذَكَرَ, 76 — масдар ذِكْر…). Указатель собран из разметки по месту: data/morph_roots/<код первой буквы>.json.
    if(action==='rootForms'){
      const root=String(args.root||'').trim();if(!root)return {forms:[]};
      const idx=await modelFile('morph_roots/'+root.codePointAt(0)+'.json'),lem2=await modelFile('quran_lemmas_v2.json');
      const ROM=['','I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'];
      const kindOf=tag=>{const t=String(tag||'').split('|'),vf=+((t.find(x=>x.startsWith('VF:'))||'').split(':')[1]||0),r=vf>1?` ${ROM[vf]||vf} породы`:'';
        if(t[0]==='V')return 'глагол '+(ROM[vf]||'I')+' породы';if(t.includes('VN'))return 'масдар (отглагольное имя)'+r;
        if(t.includes('ACT_PCPL'))return 'действительное причастие'+r;if(t.includes('PASS_PCPL'))return 'страдательное причастие'+r;
        if(t.includes('PN'))return 'имя собственное';if(t.includes('ADJ'))return 'прилагательное';return t[0]==='N'?'имя':'частица';};
      const forms=((idx&&idx[root])||[]).map(g=>{const d=lem2[g[0]]||{};return {lemma:String(g[0]),kind:kindOf(g[1]),sound:String(d.t||''),ru:String(d.ru||''),
        places:(g[2]||[]).map(String)};});
      return {root,total:forms.reduce((n,f)=>n+f.places.length,0),forms};
    }
    if(action==='narrCands'){
      const q=String(args.q||'').trim().replace(/^["'«»\s]+|["'«»\s]+$/g,'');if(q.length<2)return {items:[]};
      let c=[];try{c=await narrCandidates(q)||[];}catch(e){}
      if(!c.length){const w=q.split(/\s+/).filter(Boolean);for(const k of [4,3,2]){if(w.length>k){try{const c2=await narrCandidates(w.slice(0,k).join(' '));if(c2&&c2.length){c=c2;break;}}catch(e){}}}}
      const seen=new Set(),pick=[];
      for(const x of c){if(x.id==null||seen.has(String(x.id)))continue;seen.add(String(x.id));
        if(/(?:^|\s)(?:عن|حدثنا|حدثني|سمعت|أخبرنا|أخبرني|قال|ثنا|أنبأنا)(?:\s|$)/.test(String(x.nm||'')))continue;   // two people glued by «عن» — not one link
        pick.push(x);if(pick.length>=12)break;}
      const prev=args.prev!=null&&args.prev!==''?+args.prev:null;
      const items=await Promise.all(pick.map(async x=>{let card=null;try{card=await _narrCard(x.id);}catch(e){}let pairs=0;
        if(prev!=null){try{const p=await _pchGet(prev,+x.id);pairs=p?p.length:0;}catch(e){}}
        return {id:String(x.id),name:String(x.nm||(card&&card[1])||''),kunya:card?String(card[2]||''):'',death:card&&card[4]?String(card[4]):(x.y?String(x.y):''),pairs};}));
      // in «строго по порядку» those who really stand next to the previous link come first (as the old view suggested neighbours)
      if(prev!=null)items.sort((a,b)=>b.pairs-a.pairs);
      return {items};
    }
    if(action==='chainFind'){
      const ids=(Array.isArray(args.ids)?args.ids:[]).map(Number).filter(n=>n>0).slice(0,5);if(ids.length<2)throw Error('Выберите минимум двух передатчиков');
      const mode=['any','adj','seq'].includes(args.mode)?args.mode:'any';
      const groups=await Promise.all(ids.map(id=>_aliasGroup(id)));
      try{await loadBooksMap();}catch(e){}
      const B2C=typeof _BID2READ!=='undefined'?_BID2READ:{},bname=b=>{try{return _refBookName(b);}catch(e){return 'книга '+b;}};
      const place=p=>({bid:String(p[0]),n:String(p[1]),leaf:p[2]!=null?Number(p[2]):null,code:B2C[String(p[0])]||''});
      const prio=(a,b)=>(_srcPrio(a[0])-_srcPrio(b[0]))||((parseInt(a[1],10)||0)-(parseInt(b[1],10)||0));
      if(mode!=='seq'){
        const parts=await Promise.all(groups.map(async g=>(await Promise.all(g.map(id=>dzPart(id).catch(()=>null)))).filter(Boolean).flat()));
        const missing=ids.filter((id,i)=>!parts[i]||!parts[i].length).map(String);if(missing.length)return {mode,missing,books:[],found:0};
        let ai=0;parts.forEach((p,i)=>{if(p.length<parts[ai].length)ai=i;});
        const anchor=parts[ai].slice().sort(prio),found=[],t0=Date.now();let k=0;
        for(;k<anchor.length&&found.length<400&&Date.now()-t0<60000;k++){const [bid,num]=anchor[k];let ch=null;try{ch=await dzChain(bid,num);}catch(e){}if(!ch)continue;
          const idx=groups.map(g=>{for(const id of g){const j=ch.indexOf(id);if(j>=0)return j;}return -1;});if(idx.some(x=>x<0))continue;
          if(mode==='adj'){const s=[...idx].sort((a,b)=>a-b);let ok=true;for(let t=1;t<s.length;t++)if(s[t]-s[t-1]!==1){ok=false;break;}if(!ok)continue;}
          found.push(anchor[k]);}
        const by={};found.forEach(p=>{(by[p[0]]=by[p[0]]||[]).push(place(p));});
        return {mode,found:found.length,scanned:k,total:anchor.length,books:Object.keys(by).sort((a,b)=>_srcPrio(a)-_srcPrio(b)).map(b=>({bid:b,name:bname(b),places:by[b]}))};
      }
      let cids=null;
      for(let i=0;i<groups.length-1;i++){let lst=[];for(const a of groups[i])for(const b of groups[i+1]){try{lst=lst.concat(await _pchGet(a,b)||[]);}catch(e){}}
        const s2=new Set(lst);cids=cids?new Set([...cids].filter(x=>s2.has(x))):s2;if(!cids.size)break;}
      const arr=[...(cids||[])];if(!arr.length)return {mode,chains:[],total:0,hadiths:0,avail:[]};
      const pre=[...new Set(arr.map(c=>String(c).slice(1,3)))];for(let i=0;i<pre.length;i+=12)await Promise.all(pre.slice(i,i+12).map(p=>_regRec('C'+p).catch(()=>null)));
      const recs=[];for(const cid of arr){let r=null;try{r=await _regRec(cid);}catch(e){}if(r)recs.push({cid:String(cid),n:r.n||1,s:r.s||[],f:r.f||null,ex:r.ex||[]});}
      const align=seq=>{for(let st=0;st+groups.length<=seq.length;st++){let ok=true;for(let k=0;k<groups.length;k++){if(groups[k].indexOf(seq[st+k])<0){ok=false;break;}}if(ok)return st;}return -1;};
      const forms=Array.isArray(args.forms)?args.forms.map(String):[],any=forms.some(Boolean),avail=Array.from({length:groups.length-1},()=>({}));
      recs.forEach(rc=>{if(!rc.f)return;const st=align(rc.s);if(st<0)return;for(let k=0;k<groups.length-1;k++){const g=rc.f[st+k+1]||'';avail[k][g]=(avail[k][g]||0)+rc.n;}});
      // no forms marked in the registry (most of the six books) → the chain stays, flagged «form not confirmed»: not a guess, not a loss
      const kept=recs.filter(rc=>{if(!any)return true;if(!rc.f){rc.unk=true;return true;}const st=align(rc.s);if(st<0){rc.unk=true;return true;}
        for(let k=0;k<forms.length;k++){if(forms[k]&&!_formMatch(rc.f[st+k+1]||'',forms[k]))return false;}return true;});
      kept.sort((a,b)=>b.n-a.n);
      const top=kept.slice(0,40),nids=[...new Set(top.flatMap(r=>r.s))].slice(0,240),names={};
      await Promise.all(nids.map(async id=>{try{const c=await _narrCard(id);if(c)names[id]=String(c[1]||'');}catch(e){}}));
      return {mode,total:kept.length,hadiths:kept.reduce((s,r)=>s+r.n,0),
        avail:avail.map(m=>Object.entries(m).filter(([g])=>g).sort((a,b)=>b[1]-a[1]).map(([g,c])=>({form:g,ar:_FORM_RU[g]||g,count:c}))),
        chains:top.map(rc=>({cid:rc.cid,n:rc.n,unk:!!rc.unk,links:rc.s.map((id,i)=>({id:String(id),name:names[id]||'',form:rc.f?String(rc.f[i]||''):'',ar:rc.f&&rc.f[i]?(_FORM_RU[rc.f[i]]||''):''})),
          places:rc.ex.slice().sort(prio).slice(0,120).map(p=>({...place(p),book:bname(p[0])}))}))};
    }
    // «Где ещё передаётся» — тахридж прежнего вида, только подтверждённый источником (указ владельца С39).
    if(action==='takhrij'){
      let code=String(args.collection||'');if(code==='ibnmaja')code='ibnmajah';
      const num=parseInt(String(args.number||'').replace(/[^0-9]/g,''),10);if(!code||!num)return {blocks:[]};
      const ref={source:code,num:String(num)},blocks=[],B2C=typeof _BID2READ!=='undefined'?_BID2READ:{};
      const ru={};try{Object.values(_TT_BOOK).forEach(b=>{if(b.b)ru[String(b.b)]=b.ru;});}catch(e){}
      const place=(bid,n)=>({bid:String(bid),n:String(n),code:B2C[String(bid)]||''});
      try{
        if(code==='bukhari'){
          const sh=await _ttLoad('bukhari_atraf',Math.floor(num/1000)),e=sh&&sh[String(num)];
          const atraf=e&&e.a?[...new Set(e.a.map(Number))].filter(n=>n!==num).sort((a,b)=>a-b):[];
          let cross={};try{await loadBooksMap();cross=await _ttCrossPlaces({source:'bukhari',num:String(num),bid:'1681'});}catch(_e){}
          const ks=Object.keys(cross).sort((x,y)=>((_TT_RANK[x]||90)-(_TT_RANK[y]||90))||(x-y));
          const groups=[];
          if(atraf.length)groups.push({label:'В самом Сахихе — в других главах (أطراف)',same:true,rows:[{ar:'صحيح البخاري',ru:'Сахих аль-Бухари',places:atraf.map(n=>place('1681',n))}]});
          if(ks.length)groups.push({label:'В других сборниках',same:true,rows:ks.map(bb=>({ar:_refBookName(bb),ru:ru[bb]||'',places:[...new Set(cross[bb].map(Number))].sort((a,b)=>a-b).map(n=>place(bb,n))}))});
          if(groups.length)blocks.push({kind:'places',title:'Тот же хадис',source:'أطراف Сахиха аль-Бухари'+(e&&e.t?' · تحفة الأشراف '+e.t+' (аль-Мизи)':'')+' · наш указатель по 64 печатям',groups});
        }else{
          const src=_ttSrcOf(ref);
          if(src){const cfg=_TT_SRC[src],sh=await _ttLoad(cfg.slug,Math.floor(num/1000)),e=sh&&sh[String(num)];
            if(e){const order=['Бухари','Муслим','Абу Давуд','Тирмизи','Насаи','Ибн Маджа','Малик','Дарими'];
              const zone=z=>z?[...order.filter(k=>z[k]),...Object.keys(z).filter(k=>!order.includes(k))].map(k=>{const bk=_TT_BOOK[k]||{};return {ar:bk.ar||k,ru:bk.ru||k,places:z[k].map(n=>bk.b?place(bk.b,n):{bid:'',n:String(n),code:''})};}):[];
              const groups=[{label:'Тот же хадис (أخرجه)',same:true,rows:zone(e.d)},{label:'Свидетельства — другие хадисы о том же (شواهد)',rows:zone(e.s)}];
              if(e.i&&e.i.length)groups.push({label:'В этом же сборнике',same:true,rows:[{ar:(_TT_BOOK[{ahmad:'Ахмад',abudawud:'Абу Давуд',ibnmajah:'Ибн Маджа',nasai:'Насаи',tirmidhi:'Тирмизи'}[src]]||{}).ar||'',ru:'',places:e.i.map(n=>place(cfg.bid,n))}]});
              blocks.push({kind:'places',title:'Тахридж мухаккика',source:cfg.label.replace('تحقيق','тахкик'),hukm:String(e.g||''),groups:groups.filter(g=>g.rows.length)});}}
        }
      }catch(e){}
      try{const pl=_codifPlace(ref);if(pl&&pl.bid&&pl.num!=null){const m=await _tsLoad(),v=m[pl.bid+':'+String(pl.num)];if(v&&v.t)blocks.push({kind:'text',title:'Где ещё выведен этот хадис',text:String(v.t),hukm:String(v.h||''),source:'свод sunnah.one — тахридж и оценка источника, не наши'});}}catch(e){}
      try{const o=_ТАХРИДЖ_МУХ[code];if(o){const host=document.createElement('div');if(await renderMuhTakhrij(ref,host)){const t=host.querySelector('[dir="rtl"]');if(t&&t.textContent.trim())blocks.push({kind:'text',title:'Сноски мухаккика этого издания',text:t.textContent.trim(),source:o.кто+' — тахридж и суждение мухаккика, не наши'});}}}catch(e){}
      try{await loadReverse();const mu=reverse&&(reverse[code+' '+num]||reverse[code+' '+toAr(String(num))]);if(mu&&mu.length)blocks.push({kind:'muhaymin',title:'В аль-Мухаймин (Муршид ибн Юсуф)',nums:[...new Set(mu.map(x=>String(x.m)))],source:'по метке источника у автора'});}catch(e){}
      return {blocks};
    }
    // Вся Мактаба (≈8000 книг) — тот же /maktaba прежнего вида, без выбора книги; страницы книг как карточки нового вида.
    if(action==='maktabaSearch'){
      const q=String(args.query||'').trim().slice(0,300);if(!q)return {items:[],total:0,page:1};
      const page=Math.max(1,Math.min(50,+args.page||1));
      const r=await fetch(BACKEND_URL+'/maktaba?q='+encodeURIComponent(q)+'&page='+page+'&initData='+encodeURIComponent(INITDATA));
      if(r.status===429)throw Error('Слишком часто — повторите через минуту');
      if(r.status===403)throw Error('Поиск по всей библиотеке пока не открыт');
      const j=await r.json().catch(()=>({})),data=(j&&j.data)||[];
      const items=data.slice(0,40).map(x=>{const bid=String(x.book_id),pid=x.page_id||x.page||1,snip=typeof _cleanMaktabaSnip==='function'?_cleanMaktabaSnip(x.snip||''):String(x.snip||'');
        const row={id:'b:'+bid+':'+pid,kind:'book',bid,page:pid,collection:'book:'+bid,title:x.book_name||('Книга № '+bid),bookTitle:x.book_name||('Книга № '+bid),
          number:(x.vol?'т. '+x.vol+' · ':'')+(x.page!=null?'стр. '+x.page:''),arabic:cleanText(snip),russian:'',author:x.author||''};
        records.set(row.id,{original:x,row});return row;});
      return {items,total:Number(j&&j.count)||items.length,page};
    }
    // Оглавление книги (جدول المحتويات) — тот же /book_toc, что у прежнего вида: [{t: глава, l: уровень, p: лист}].
    if(action==='bookToc'){
      const bid=String(args.bid||'');if(!/^\d+$/.test(bid))throw Error('Некорректный номер книги');
      const j=await bjson(BACKEND_URL+'/book_toc?id='+bid+'&initData='+encodeURIComponent(INITDATA),60000);
      return {headings:((j&&j.headings)||[]).slice(0,30000).map(h=>({t:String(h.t||'').trim(),l:Number(h.l)||1,p:Number(h.p)||1}))};
    }
    // Перевод ИИ там, где своего перевода нет — /translate прежнего вида (кэш на сервере, повтор бесплатен).
    if(action==='translate'){
      const text=String(args.text||'').trim().slice(0,12000);if(!text)throw Error('Нечего переводить');   // the server takes a whole hadith (up to 12 000)
      const r=await fetch(BACKEND_URL+'/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,source:String(args.source||'maktaba'),num:String(args.num||''),force:!!args.force,initData:INITDATA})});
      const j=await r.json().catch(()=>({}));const tr=j&&(j.translation||j.ru);
      if(!r.ok||!tr)throw Error((j&&j.message)||(r.status===429?'Лимит переводов исчерпан. Попробуйте позже.':'Перевод сейчас недоступен'));
      return {translation:String(tr),cached:!!j.cached};
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
    // Передатчики хадиса: имена из иснада и карточки из нашей базы (19 106 равиев) — [id,имя,кунья,нисба,смерть,Ибн Хаджар,аз-Захаби,табака].
    // Итог о передатчике — формулой прежнего вида (_ttNeuro, владелец: «48 муʿтабаров дают два свидетельства, а не Ибн
    // Хаджар»): توثيق = свидетельства двух ранних муʿтабаров из 48; Сахихайн без тяжкого джарха = два; поздние
    // (Ибн Хаджар, аз-Захаби, аль-Мизи…) не в счёт; сподвижники — الصحابة عدول. Между звеньями — форма передачи из текста.
    // sunnah.com opinions on its narrator card (collected earlier: sunverd_full/<sid%60>.json)
    const sunnahOf=async sid=>{if(!sid||!/^\d+$/.test(String(sid)))return [];const sh=+sid%60;window._sunverdFull=window._sunverdFull||{};
      if(window._sunverdFull[sh]===undefined)window._sunverdFull[sh]=await fetch('./sunverd_full/'+sh+'.json?v='+APPVER).then(r=>r.ok?r.json():null).catch(()=>null);
      return (window._sunverdFull[sh]&&window._sunverdFull[sh][String(sid)])||[];};
    const narrEnrich=async(items,how,text)=>{
      try{const ru=await modelFile('narr_ru_fix.json');for(const it of items)if(it.id!=null&&ru[String(it.id)])it.ru=String(ru[String(it.id)]);}catch(e){}
      let flags={},mud={},m2s={};try{flags=await loadNarrFlags()||{};}catch(e){}try{mud=await _loadMudallisin()||{};}catch(e){}try{m2s=await loadMid2Sid()||{};}catch(e){}
      for(const it of items){if(it.id==null)continue;const n=+it.id,sid=m2s[String(n)];
        it.links={maktaba:'https://shamela.ws/narrator/'+n,sunnah:sid&&/^\d+$/.test(String(sid))?'https://sunnah.com/narrator/'+sid:''};
        try{if(typeof _isSahById==='function'&&await _isSahById(n)){it.verdict={kind:'sahabi',v:'صحابي — сподвижник',nT:0,nJ:0};continue;}}catch(e){}
        let list=null;try{list=await _testimGet(n);}catch(e){}
        // critics sunnah.com has and the Maktaba card lacks — taken too (owner 29.10), same matching as the old reconciliation
        let added=[];try{const ours=[...new Set((list||[]).map(c=>_mCanon(c[0])))];
          added=(await sunnahOf(sid)).filter(x=>{const c=_mCanon(x.s);return c&&!ours.some(oc=>oc===c||oc.indexOf(c)>=0||c.indexOf(oc)>=0);}).map(x=>[String(x.s),String(x.q||''),'sunnah']);}catch(e){}
        const all=(list||[]).concat(added);
        if(how==='card')it.testimonies=all.filter(c=>c&&c[0]&&String(c[1]||'').trim()).map(c=>({critic:String(c[0]),text:String(c[1]).slice(0,500),src:c[2]==='sunnah'?'sunnah':'maktaba',mut:!!(_critOk(c[0])&&_isMut(c[0]))}));
        const inSah=flags[String(n)]==='bm';let r=null;try{r=all.length?_ttNeuro(all,inSah):null;}catch(e){}
        if(!r&&inSah)r=_ttNeuro([],true);
        if(r){const kind=r.em==='🟢'?'sound':r.em==='🟡'?'mixed':r.em==='🟠'?'weak':r.em==='🔴'?'rejected':'unknown';
          const muts=all.filter(c=>c&&c[0]&&_critOk(c[0])&&_isMut(c[0])&&String(c[1]||'').trim()).slice(0,10).map(c=>[String(c[0]),String(c[1]).slice(0,180),c[2]==='sunnah'?'sunnah':'maktaba']);
          it.verdict={kind,v:String(r.v||''),nT:r.nT|0,nJ:r.nJ|0,jah:r.jah|0,sahihayn:!!r.sahihayn,note:String(r.note||''),cnt:all.length,muts,fromSunnah:added.length};}
        else it.verdict={kind:'none',v:'',nT:0,nJ:0,cnt:all.length};
        if(mud[String(n)])it.mudallis=String((mud[String(n)]||{}).s||'');
      }
      // each link of the ready chain is checked against the isnad text itself: the chain markup sometimes names a person
      // who is not in this isnad (Tirmidhi 1: «يعقوب بن إسحاق» where the text has Qutayba) — such a link is flagged
      const fold0=t=>String(t||'').replace(/[ً-ٰٟـ]/g,'').replace(/[أإآ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه').replace(/\s+/g,' ').trim().replace(/(^| )اب[يا](?= )/g,'$1ابو');   // «أبي سلمة» in the text = «أبو سلمة» in the card
      if(how==='chain'&&text){const ft=fold0(text);
        // names of the isnad as the text says them («الأعمش», «الزهري», «ابن شهاب»), identified the way the old view does
        const txtIds=new Set();try{if(typeof loadNarrNames==='function')await loadNarrNames();for(const nm of (isnadNarrators(text)||[]).slice(0,40)){try{const id=await _narrLookup(nm);if(id!=null)txtIds.add(String(id));}catch(e){}}}catch(e){}
        for(const it of items){if(it.id==null)continue;const nm=fold0(it.full||it.name).split(' '),toks=[];
          toks.push(['عبد','ابن','ابو','ام'].includes(nm[0])?nm.slice(0,2).join(' '):nm[0]);
          if(it.kunya)toks.push(fold0(it.kunya).split(/\s*[·،,]\s*/)[0]);
          {const k=nm.indexOf('بن');if(k>0&&nm[k+1])toks.push('ابن '+(nm[k+1]==='عبد'&&nm[k+2]?nm[k+1]+' '+nm[k+2]:nm[k+1]));}   // «ابن القاسم» for عبد الرحمن بن القاسم
          fold0(it.nisba).split(/[\s·،,]+/).filter(w=>w.length>=5&&w.startsWith('ال')).forEach(w=>toks.push(w));
          it.textOk=txtIds.has(String(it.id))||toks.some(t=>t&&t.length>=3&&ft.includes(t));
          // «عن أبيه»: the link is the father of the previous one (Salim ← his father 'Abd Allah; Suhayl ← Abu Salih Dhakwan)
          const ix=items.indexOf(it);if(!it.textOk&&ix>0&&/عن ابيه|عن ابيها/.test(ft)){const pn=fold0(items[ix-1].full||items[ix-1].name).split(' '),k=pn.indexOf('بن');
            const fa=k>=0?(['عبد','ابو','ابي'].includes(pn[k+1])?pn.slice(k+1,k+3).join(' '):pn[k+1]||'').replace(/^ابي /,'ابو '):'';
            if(fa&&(fold0(it.full||it.name).startsWith(fa)||fold0(it.kunya).startsWith(fa)))it.textOk=true;}if(!it.textOk)it.doubt='name';}
        // the collector's own sheikh cannot have died decades after the collector — a namesake by kunya (Tirmidhi 1:
        // «أبو عوانة» taken for Ya'qub al-Isfarayini, d. 316, while al-Tirmidhi died in 279)
        const died={bukhari:256,muslim:261,abudawud:275,tirmidhi:279,nasai:303,ibnmajah:273,malik:179,ahmad:241,darimi:255}[String(args&&args.collection||'')];
        const d0=items[0]&&parseInt(String(items[0].death||'').replace(/[^0-9]/g,''),10);
        if(died&&d0&&d0>died+20&&!items[0].doubt)items[0].doubt='late:'+d0+':'+died;}
      // forms: the isnad text read from the compiler upwards; link i = how item i-1 (or the compiler) received from item i
      let toProphet=null;
      try{const p=typeof _parseIsnad==='function'?_parseIsnad(String(text||'').slice(0,6000)):null,links=(p&&p.links)||[];
        const fold=t=>String(t||'').replace(/[\u064B-\u065F\u0670\u0640]/g,'').replace(/[أإآ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه').trim();
        const isProphet=l=>/رسول الله|النبي|رسول اللة/.test(fold(l.name));
        const chain=links.filter(l=>!isProphet(l)),last=links.find(isProphet);
        const label=f=>f?{form:f,ar:(typeof _FORM_RU!=='undefined'&&_FORM_RU[f])||'',tip:(typeof _FORM_TIP!=='undefined'&&_FORM_TIP[f])||'',cls:(typeof _FORM_CLASS!=='undefined'&&_FORM_CLASS[f])||''}:null;
        if(chain.length===items.length)items.forEach((it,i)=>{it.via=label(chain[i].form);it.said=chain[i].name;});
        else{let j=0;for(const it of items){const full=fold(it.full||it.name);for(let k=j;k<chain.length;k++){const w=fold(chain[k].name).replace(/^(ال|ب|و)/,'').split(/\s+/).slice(0,2).join(' ');if(w&&full.includes(w)){it.via=label(chain[k].form);it.said=chain[k].name;j=k+1;break;}}}}
        if(last)toProphet=label(last.form);
      }catch(e){}
      return {items,how,toProphet};
    };
    // Карточка передатчика в новом виде: тот же итог по 48, все свидетельства (Мактаба + sunnah.com) с источником,
    // учителя и ученики по «Тахзиб аль-Камаль» аль-Мизи (с числом передач в наших цепях).
    if(action==='narrCard'){
      const id=+args.id;if(!(id>0))throw Error('Нет номера передатчика');
      let c=null;try{c=await _narrCard(id);}catch(e){}if(!c)throw Error('Передатчик не найден в нашей базе');
      const it={name:String(c[1]||''),id:String(id),full:String(c[1]||''),kunya:String(c[2]||''),nisba:String(c[3]||''),death:String(c[4]||''),hajar:String(c[5]||''),dhahabi:String(c[6]||''),tabaqa:String(c[7]||'')};
      await narrEnrich([it],'card','');
      if(it.verdict&&it.verdict.kind==='sahabi'&&!it.testimonies){let list=[];try{list=await _testimGet(id)||[];}catch(e){}
        it.testimonies=list.filter(x=>x&&x[0]&&String(x[1]||'').trim()).map(x=>({critic:String(x[0]),text:String(x[1]).slice(0,500),src:'maktaba',mut:!!(_critOk(x[0])&&_isMut(x[0]))}));}
      const tea=[],stu=[];
      try{const rec=await _tlinkGet(id)||{};let edg={};try{edg=await _edgesGet(id)||{};}catch(e){}
        for(const k in rec){const v=String(rec[k]||'');(v[0]==='T'?tea:stu).push({id:String(k),n:edg[String(k)]||0});}
        tea.sort((a,b)=>b.n-a.n);stu.sort((a,b)=>b.n-a.n);}catch(e){}
      const top=[...tea.slice(0,16),...stu.slice(0,16)];
      await Promise.all(top.map(async x=>{try{const k=await _narrCard(+x.id);x.name=k?String(k[1]||''):'';x.death=k&&k[4]?String(k[4]):'';}catch(e){}}));
      try{const ru=await modelFile('narr_ru_fix.json');[...tea.slice(0,16),...stu.slice(0,16)].forEach(x=>{if(ru[x.id])x.ru=ru[x.id];});}catch(e){}
      return {...it,teachers:tea.slice(0,16),students:stu.slice(0,16),teachersTotal:tea.length,studentsTotal:stu.length};
    }
    // Имена иснада, как они стоят в тексте, с номером передатчика — чтобы имя в тексте открывало его карточку.
    if(action==='isnadLinks'){
      const text=String(args.text||'').slice(0,6000);if(!text||typeof _parseIsnad!=='function')return {links:[]};
      let p=null;try{p=_parseIsnad(text);}catch(e){}
      const plain=t=>String(t||'').replace(/[\u064B-\u065F\u0670\u0640]/g,'');
      const links=((p&&p.links)||[]).filter(l=>l&&l.name&&!/رسول الله|النبي|رسول اللة/.test(plain(l.name)));
      try{if(typeof loadNarrNames==='function')await loadNarrNames();}catch(e){}
      let seq=null,chainIds=[];try{const r=await bestChain(args.collection,args.number,text);seq=r&&r.seq&&r.seq.length===links.length?r.seq:null;chainIds=r&&r.seq?r.seq.filter(x=>typeof x==='number'):[];}catch(e){}
      // З-144 (владелец 30.10: ни один передатчик без отметки): имя не опознано — пробуем часть до «مولى» и сверяем
      // с готовой цепью хадиса по значимому слову («سمى مولى أبي بكر» → Сумайй, вольноотпущенник Абу Бакра)
      const foldN=t=>plain(t).replace(/[أإآ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه'),STOPN=new Set(['بن','ابن','ابو','ابي','عبد','بنت','ام','الله','مولي']);
      const byChain=async said=>{const w=foldN(said).split(/\s+/).filter(t=>t.length>2&&!STOPN.has(t));if(!w.length)return null;
        for(const cid of chainIds){let c=null;try{c=await _narrCard(cid);}catch(e){}const cw=foldN(c&&c[1]).split(/\s+/);if(c&&w.slice(0,2).some(t=>cw.includes(t)))return cid;}return null;};
      const out=[];for(let i=0;i<links.length&&i<30;i++){let id=seq&&seq[i]!=null?seq[i]:null;if(id==null){try{id=await _narrLookup(links[i].name);}catch(e){}}
        if(id==null){const cut=String(links[i].name).split(/\s+مَ?وْ?لَ?ى\S*\s+/)[0];if(cut&&cut!==links[i].name){try{id=await _narrLookup(cut);}catch(e){}}}
        if(id==null)id=await byChain(links[i].name);
        out.push({said:String(links[i].name),id:id==null?null:String(id)});}
      // the parse stops at «ح» (a second chain): the names after it come from the old view's own name finder
      try{const seen=new Set(out.map(x=>plain(x.said).replace(/\s+/g,' ').trim()));
        for(const nm of (typeof isnadNarrators==='function'?isnadNarrators(text)||[]:[]).slice(0,40)){const k=plain(nm).replace(/\s+/g,' ').trim();if(!k||seen.has(k))continue;seen.add(k);
          let id=null;try{id=await _narrLookup(nm);}catch(e){}out.push({said:String(nm),id:id==null?null:String(id)});}}catch(e){}   // без номера тоже: выделяется, по нажатию — тёзки
      // «حدثنا قتيبة، وهناد، قالا»: два учителя через запятую приходили одним звеном и не выделялись (ат-Тирмизи №5) —
      // каждый идёт своим именем; «و» перед вторым снимается, только если без неё имя опознаётся (или с ней — нет)
      const TAIL=new Set(['قالا','قالوا','قال','كلاهما','جميعا']),expanded=[];
      for(const x of out){const parts=String(x.said).split(/\s*[،,]\s*/).map(t=>{const w=t.trim().split(/\s+/);while(w.length&&TAIL.has(plain(w[w.length-1])))w.pop();return w.join(' ');}).filter(t=>plain(t).replace(/\s/g,'').length>=2);
        if(parts.length<2){expanded.push(x);continue;}
        for(let k=0;k<parts.length;k++){let said=parts[k],id=null;try{id=await _narrLookup(said);}catch(e){}
          if(k>0&&id==null&&/^و/.test(plain(said))){const bare=said.replace(/^و[ً-ٟ]*/,'');try{id=await _narrLookup(bare);}catch(e){}said=bare;}
          expanded.push({said,id:id==null?null:String(id)});}}
      // З-144, разбор пропусков 30.10: к имени прилипали служебные слова («وكيع و», «جرير و», «عكرمة يقول», «وحدثنا قتيبة»)
      // — подсветка искала их вместе с именем и промахивалась; куски матна («أما بعد أيها الناس…») шли звеном без номера и
      // могли выделиться пунктиром как передатчик. Чистим края, длинное без номера выбрасываем, «отца/деда/дядю»
      // опознаём по готовой цепи: это следующий в ней после предыдущего звена.
      const HEAD=/^(?:و?حدثنا|و?حدثني|و?أخبرنا|و?أخبرني|و?اخبرنا|و?اخبرني|أنبأنا|ح|و)$/,TAIL2=/^(?:و|يقول|قال|قالا|قالوا|قالت|جميعا|كلهم|كلاهما|ح|أنه|انه)$/;
      const KIN=/^(?:أبي|ابي|أبيه|ابيه|والدي|أبيها|جده|جدي|عمه|عمي|أمه|خاله|أخيه)$/,cleaned=[];let prevId=null;
      for(const x of expanded){let w=String(x.said).split(/\s+/).filter(Boolean);
        while(w.length>1&&HEAD.test(plain(w[0])))w.shift();while(w.length>1&&TAIL2.test(plain(w[w.length-1])))w.pop();
        let said=w.join(' '),id=x.id;
        if(said!==x.said&&id==null){try{id=await _narrLookup(said);}catch(e){}id=id==null?null:String(id);}
        if(id==null&&KIN.test(plain(said))&&prevId!=null){const k=chainIds.indexOf(+prevId);if(k>=0&&typeof chainIds[k+1]==='number')id=String(chainIds[k+1]);}
        if(id==null&&(w.length>5||/صلى|رسول|النبي/.test(plain(said))))continue;   // не имя — кусок матна
        cleaned.push({said,id});if(id!=null)prevId=id;}
      return {links:cleaned};
    }
    if(action==='narrators'){
      const card=async id=>{let c=null;try{c=await _narrCard(id);}catch(e){}return c?{name:String(c[1]||''),id:String(id),full:String(c[1]||''),kunya:String(c[2]||''),nisba:String(c[3]||''),death:String(c[4]||''),hajar:String(c[5]||''),dhahabi:String(c[6]||''),tabaqa:String(c[7]||'')}:null;};
      // 1) the hadith's own chain from our base — narrators by id, no namesakes
      try{const r=await bestChain(args.collection,args.number,args.text),seq=r&&r.seq;
        if(seq&&seq.length){const items=[];for(const id of seq.slice(0,30)){const c=await card(id);if(c)items.push(c);}if(items.length)return await narrEnrich(items,'chain',args.text);}
      }catch(e){}
      // 2) no ready chain: names from the isnad text, matched by spelling — namesakes may be confused
      const text=String(args.text||'').slice(0,6000);if(!text||typeof isnadNarrators!=='function')return {items:[]};
      let names=[];try{names=isnadNarrators(text)||[];}catch(e){}
      try{if(typeof loadNarrNames==='function')await loadNarrNames();}catch(e){}
      const items=[];
      for(const name of names.slice(0,30)){
        let id=null,c=null;try{id=await _narrLookup(name);}catch(e){}
        if(id!=null){try{c=await _narrCard(id);}catch(e){}}
        items.push({name,id:id==null?null:String(id),full:c?String(c[1]||''):'',kunya:c?String(c[2]||''):'',nisba:c?String(c[3]||''):'',death:c?String(c[4]||''):'',hajar:c?String(c[5]||''):'',dhahabi:c?String(c[6]||''):'',tabaqa:c?String(c[7]||''):''});
      }
      return await narrEnrich(items,'names',text);
    }
    if(action==='suraInfo'){return {names:(typeof SURA_RU!=='undefined'?SURA_RU.slice(1):[]),ayahs:(typeof SURA_AYAHS!=='undefined'?SURA_AYAHS.slice():[]),meanings:(typeof SURA_MEANING!=='undefined'?SURA_MEANING.slice(1):[]),arabic:(typeof SURA_NAMES!=='undefined'?SURA_NAMES.slice():[])};}
    if(action==='hermesAsk'){
      const question=String(args.question||'').trim();if(!question)throw Error('Введите вопрос');
      const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),150000);
      try{
        const response=await fetch(BACKEND_URL+'/hermes',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
          body:JSON.stringify({q:question,initData:INITDATA,ekran:String(args.screen||'').slice(0,400),opora:String(args.opora||'').slice(0,2600),deystviya:Array.isArray(args.actions)?args.actions.slice(0,30):[]})});
        const data=await response.json().catch(()=>({}));
        if(!response.ok||!data.answer)throw Error(data.error||data.message||(response.status===429?'Лимит запросов исчерпан. Попробуйте позже.':'Помощник сейчас недоступен.'));
        return {answer:String(data.answer),model:String(data.model||''),session:String(data.session||'')};
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
      // RAG по смыслу — без экрана прежнего приложения (владелец 29.10: «RAG тупо переводит в старую версию»).
      // Считаем тем же, чем ragSearch: книга и векторы из _ragLoad, вектор вопроса с сервера, та же планка порога.
      if(mode==='rag'&&wanted==='hadith'){
        if(typeof _ragLoad!=='function'||typeof _RAG==='undefined')return {items:[],total:0,notice:'Поиск по смыслу в этой версии недоступен.'};
        // the meaning index holds only Sahih al-Bukhari so far: «без: Бухари» or other books chosen → say so, not search it anyway
        const sc=Array.isArray(args.scope)?args.scope:[],bukOut=sc.some(x=>x.kind==='book'&&String(x.id)==='bukhari'&&x.exclude),inc=sc.filter(x=>!x.exclude);
        if(bukOut||(inc.length&&!inc.some(x=>x.kind==='book'&&String(x.id)==='bukhari')))return {items:[],total:0,notice:'По смыслу (RAG) пока ищем только в «Сахих аль-Бухари» — а он в ваших условиях '+(bukOut?'исключён':'не выбран')+'. База по смыслу для других книг строится. Сейчас — обычный поиск или уберите «без: Бухари».'};
        if(!await _ragLoad())return {items:[],total:0,notice:'Не удалось загрузить книгу для поиска по смыслу. Попробуйте ещё раз.'};
        const qv=await _ragQueryVec(query);
        if(!qv){const j=_RAG.ответ;return {items:[],total:0,notice:j&&j['сообщение']?String(j['сообщение']).slice(0,300):j&&j['квота_выбита']?'Запросы по смыслу на сегодня исчерпаны — это лимит, а не поломка. Обычный поиск работает.':'Сервер поиска по смыслу сейчас не ответил. Обычный поиск работает.'};}
        let nq=0;for(let i=0;i<qv.length;i++)nq+=qv[i]*qv[i];nq=Math.sqrt(nq)||1;
        const Q=new Float32Array(qv.length);for(let i=0;i<qv.length;i++)Q[i]=qv[i]/nq;
        const dim=_RAG.dim,body=_RAG.body,S=_RAG.s,ids=_RAG.ids,best=Object.create(null);
        for(let i=0;i<_RAG.n;i++){const off=i*dim,k=S[i];let s=0;for(let j=0;j<dim;j++)s+=Q[j]*body[off+j]*k;const cid=ids[i];if(!(cid in best)||s>best[cid])best[cid]=s;}
        const rank=Object.keys(best).map(k=>[k,best[k]]).sort((a,b)=>b[1]-a[1]);
        const words=(query.match(/\S+/g)||[]).length,porog=words<=1?Math.max(0.55,_RAG.порог):_RAG.порог,picked=[];
        for(const [cid,s] of rank){if(s<porog||picked.length>=40)break;const z=_RAG.карта?_RAG.карта[cid]:null;if(z)picked.push([cid,s,z[0]]);}
        const textsOk=await _ragТексты(picked.map(x=>x[0]));
        const kinds={0:'хадис',1:'глава',2:'вне нумерации'},count={},items=[];
        for(const [cid,s,kind] of picked){
          const c=_RAG.мета[cid];if(!c)continue;
          const label=c.n?String(c.n):('стр. '+(c.p||'—'));count[kinds[kind]||'глава']=(count[kinds[kind]||'глава']||0)+1;
          const row=convert({s:'bukhari',n:label,arabic:c.a||c.g||'',ru:c.r||''});row.ragScore=Math.round(s*1000)/1000;items.push(row);
        }
        const parts=Object.entries(count).map(([k,n])=>k+' '+n).join(' · ');
        return {items,total:items.length,notice:items.length?(textsOk?'':'Часть текстов не догрузилась — показано не всё. Повторите вопрос.'):'В Сахих аль-Бухари по смыслу ничего не нашлось (близость ниже порога '+porog.toFixed(2)+'). Попробуйте другие слова или обычный поиск.',
          heading:items.length?'По смыслу · Сахих аль-Бухари · '+parts:''};
      }
      document.querySelectorAll('.chip[data-mode]').forEach(chip=>{
        const should=chip.dataset.mode===mode;
        if(chip.classList.contains('on')!==should)chip.click();
      });
      // Only our main collections chosen (owner П-46: «Два Сахиха», «Шесть сборников», «без Бухари»…): the ordinary
      // hadith search covers several collections at once and its results come back as new-look cards. The whole-library
      // path below is for other books and sections only.
      let mainBooks=null;
      if(wanted==='hadith'&&Array.isArray(args.scope)&&args.scope.length&&(!args.category||args.category==='all')&&(!args.collection||args.collection==='all')){
        const codes=(typeof READABLE!=='undefined'?READABLE:[]).map(x=>String(x.code));
        if(codes.length&&args.scope.every(x=>x.kind==='book'&&codes.includes(String(x.id)))){
          const inc=args.scope.filter(x=>!x.exclude).map(x=>String(x.id)),exc=new Set(args.scope.filter(x=>x.exclude).map(x=>String(x.id)));
          mainBooks=(inc.length?inc:codes).filter(c=>!exc.has(c));
          if(!mainBooks.length)return {items:[],total:0,notice:'После исключений не осталось книг для поиска.'};
          args.scope=[];
        }
      }
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
        mkRows=[];if(numberMode)startNumberWatch(query);await runSearch(true);
        if(numberMode){mkRows=null;return numberSnapshot();}
        return await libraryResults();
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
        mkRows=[];if(numberMode)startNumberWatch(query);
        await runSearch(true);
        if(numberMode){mkRows=null;return numberSnapshot();}
        return await libraryResults();
      }
      _scopeIds=null;_scopeName='';
      const tabEl=document.querySelector('.tab[data-tab="'+wanted+'"]');
      if(tabEl&&!tabEl.classList.contains('active'))tabEl.click();
      if(typeof selCols!=='undefined'){
        selCols.clear();if(args.collection&&args.collection!=='all')selCols.add(String(args.collection));
        if(mainBooks)mainBooks.forEach(code=>selCols.add(code));
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
      if(!row.russian&&row.collection&&row.number&&['tirmidhi','nasai','ibnmajah','malik'].includes(String(row.collection))){try{const t=(await modelFile('perevod_ii/'+row.collection+'.json'))[String(row.number).replace(/\D.*$/,'')];if(t)row.russianAi=String(t);}catch(e){}}
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
  const SERIAL_ONLY=new Set(['ready','search','browse','scientific','library','tool','toolsCatalog','openOriginalTool','showOriginalHome','numberMore','assistantAsk','catalog']);
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin||event.source!==parent||event.data?.source!=='muslimoon-design-ui')return;
    const {id,action,args}=event.data;
    if(typeof id!=='string'||!['ready','suraInfo','narrators','bookToc','translate','takhrij','narrCands','rootForms','chainFind','narrCard','isnadLinks','maktabaSearch','arabus','tafsir','quranSettings','suraVerses','catalog','bookInfo','bookPageData','locateLeaf','bookMeta','leafByHadith','lastLeaf','hermesAsk','quranWordData','quranAudioInfo','quranTimedAudio','quranVerse','quranNeighbor','search','read','browse','scientific','library','tool','toolsCatalog','openOriginalTool','showOriginalHome','numberMore','assistantAsk'].includes(action))return;
    // Only the actions that drive the old screen (search, browse, its tools) must wait their turn; data-only requests run
    // at once (owner 29.10: «очень долго грузится») — the hadith search no longer waits for the library, cards for each other.
    if(!SERIAL_ONLY.has(action)){request(action,args||{}).then(payload=>send(id,payload)).catch(e=>send(id,null,String(e&&e.message||e)));return;}
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

// Прогрев (владелец 29.10: «очень долго грузится — загрузка должна быть моментальной»): первый поиск качал целиком семь
// сборников и шёл ~6 с. Тянем их заранее, по одному, когда первый экран уже нарисован; прежний вид сам кладёт их в
// кэш браузера, так что при следующем открытии это мгновенно.
(function(){
  if(window.top===window||typeof loadCollection!=='function')return;
  // only the six books and Malik: their files exist as editions/ara-<code>.min.json. Прогрев всего READABLE звал и
  // ara-ahmad.min.json, которого на сайте нет — журнал ошибок получил A-261 «HTTP 404» ×22 (29.10)
  const codes=['bukhari','muslim','abudawud','tirmidhi','nasai','ibnmajah','malik'];
  const idle=fn=>(window.requestIdleCallback?requestIdleCallback(fn,{timeout:4000}):setTimeout(fn,300));
  setTimeout(()=>{let i=0;const next=()=>{if(i>=codes.length)return;const c=codes[i++];Promise.resolve().then(()=>loadCollection(c)).catch(()=>{}).finally(()=>idle(next));};idle(next);},2500);
})();
