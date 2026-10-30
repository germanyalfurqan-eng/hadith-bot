/* The experimental frontend bridges to a v1808 copy with the real configured backend. */
(function(){
  'use strict';
  let sequence=0,resolveReady,rejectReady,numberListener=null;
  const pending=new Map();
  const readiness=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
  const frame=document.createElement('iframe');
  frame.title='Научные инструменты Muslimoon';
  frame.src='core.html?v=20261030035017&design='+encodeURIComponent(document.documentElement.dataset.theme||'gold')+(location.hash||'');
  frame.style.cssText='width:100%;height:100%;border:0;display:block;background:#111';
  const shell=document.createElement('section');
  shell.setAttribute('role','dialog');shell.setAttribute('aria-label','Научные инструменты');
  shell.style.cssText='position:fixed;inset:0;z-index:10000;background:#111;color:#eee;display:none;flex-direction:column';
  const header=document.createElement('header');header.style.cssText='display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid #ffffff22;background:#171717;font:14px system-ui';
  const title=document.createElement('span');title.textContent='Первоисточники и разбор';
  const close=document.createElement('button');close.type='button';close.textContent='Вернуться  ×';close.style.cssText='background:transparent;color:inherit;border:1px solid #ffffff33;border-radius:12px;padding:9px 12px;cursor:pointer;font:inherit';
  close.onclick=()=>{shell.style.display='none';shell.setAttribute('aria-hidden','true');};
  header.append(title,close);shell.append(header,frame);
  // A hidden frame still runs the original, unmodified search functions.
  document.addEventListener('DOMContentLoaded',()=>document.body.append(shell),{once:true});
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin||event.source!==frame.contentWindow||event.data?.source!=='muslimoon-v1807-core')return;
    const {id,payload,error}=event.data;
    if(id==='number-update'){if(numberListener)numberListener(payload);return;}
    if(id==='ready'){if(error)rejectReady(Error(error));else resolveReady(payload);return;}
    const item=pending.get(id);if(!item)return;pending.delete(id);clearTimeout(item.timer);
    if(error)item.reject(Error(error));else item.resolve(payload);
  });
  async function ask(action,args){
    await readiness;
    const id=String(++sequence);
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{pending.delete(id);reject(Error('Загрузка заняла больше времени. Попробуйте ещё раз.'));},90000);
      pending.set(id,{resolve,reject,timer});
      frame.contentWindow.postMessage({source:'muslimoon-design-ui',id,action,args},location.origin);
    });
  }
  function show(label){title.textContent=label||'Первоисточники и разбор';shell.style.display='flex';shell.setAttribute('aria-hidden','false');close.focus();}
  window.MuslimoonData={
    ready:()=>ask('catalog',{}),
    onNumberUpdate:callback=>{numberListener=callback;},
    numberMore:query=>ask('numberMore',{query}),
    assistantAsk:question=>ask('assistantAsk',{question}),
    suraInfo:()=>ask('suraInfo',{}),narrators:(text,collection,number)=>ask('narrators',{text,collection,number}),hermesAsk:(question,screen,actions,opora)=>ask('hermesAsk',{question,screen,actions,opora}),
    bookPageData:(bid,leaf)=>ask('bookPageData',{bid,leaf}),
    locateLeaf:(collection,number,text)=>ask('locateLeaf',{collection,number,text}),
    bookMeta:bid=>ask('bookMeta',{bid}),bookToc:bid=>ask('bookToc',{bid}),takhrij:(collection,number)=>ask('takhrij',{collection,number}),narrCands:(q,prev)=>ask('narrCands',{q,prev}),rootForms:root=>ask('rootForms',{root}),chainFind:(ids,mode,forms)=>ask('chainFind',{ids,mode,forms}),narrCard:id=>ask('narrCard',{id}),maktabaSearch:(query,page)=>ask('maktabaSearch',{query,page}),arabus:(word,root,lemma)=>ask('arabus',{word,root,lemma}),tafsir:(sura,ayah,key,lang)=>ask('tafsir',{sura,ayah,key,lang}),quranSettings:(set)=>ask('quranSettings',set||{}),suraVerses:sura=>ask('suraVerses',{sura}),isnadLinks:(text,collection,number)=>ask('isnadLinks',{text,collection,number}),translate:(text,source,num,force)=>ask('translate',{text,source,num,force}),
    leafByHadith:(bid,number)=>ask('leafByHadith',{bid,number}),
    lastLeaf:(bid,from)=>ask('lastLeaf',{bid,from}),
    quranWordData:(sura,ayah,text)=>ask('quranWordData',{sura,ayah,text}),
    quranAudioInfo:(sura,ayah,reciter)=>ask('quranAudioInfo',{sura,ayah,reciter}),
    quranTimedAudio:(sura,ayah,wordCount)=>ask('quranTimedAudio',{sura,ayah,wordCount}),
    quranVerse:(sura,ayah)=>ask('quranVerse',{sura,ayah}),
    quranNeighbor:(sura,ayah,direction)=>ask('quranNeighbor',{sura,ayah,direction}),
    search:async args=>{const result=await ask('search',args);if(result.opened)show('Результаты поиска');return result;},read:record=>ask('read',{record}),
    browse:async collection=>{const result=await ask('browse',{collection});if(result.opened)show();return result;},
    bookInfo:collection=>ask('bookInfo',{collection}),
    tool:async (tool,record)=>{await ask('tool',{tool,record});show();},
    scientific:async record=>{await ask('scientific',{record});show();},
    toolsCatalog:()=>ask('toolsCatalog',{}),
    openOriginalTool:async id=>{await ask('openOriginalTool',{id});show();},
    showOriginalHome:async()=>{await ask('showOriginalHome',{});show();},
    library:async()=>{await ask('library',{});show();}
  };
})();
