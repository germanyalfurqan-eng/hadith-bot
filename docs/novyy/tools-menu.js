(function(){
  'use strict';
  // «Все инструменты» live in «Ещё» (owner 29.10: no corner button; tools and settings in one tab),
  // drawn in the new style: no old emoji labels, title and a short line, our icons (owner: «смешение стилей недопустимо»).
  const view=document.getElementById('view-settings');
  const list=document.getElementById('lab-tools-list');
  const query=document.getElementById('lab-tools-search');
  const status=document.getElementById('lab-tools-status');
  if(!view||!list||!query||!status)return;
  const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Already on this screen or on the bottom bar — not repeated in the list.
  const SKIP=new Set(['setFromMenu','assistBtn','readBtn2','isnadCtorBtn']);
  const ICONS={howtoBtn:'info',notesBtn:'pen',hadScienceBtn:'book',ourRazboryBtn:'star',narrTblBtn:'grid',mudTblBtn:'grid',redkieBtn:'book',
    isnadCtorBtn:'grid',hadTblV2Btn:'grid',shareAppBtn:'arrow',copyAppLink:'source',ytLink:'source',menuFbBtn:'helper',__full_app__:'back'};
  const clean=s=>String(s||'').replace(/[\p{Extended_Pictographic}️ℹ⃣]/gu,'').replace(/\s{2,}/g,' ').replace(/^[\s—–-]+/,'').trim();
  function parts(label){const text=clean(label),m=/^(.*?)\s*\((.+)\)\s*$/.exec(text);return m?{title:m[1].trim(),note:m[2].trim()}:{title:text,note:''};}
  let catalog=[],loading=null;
  function render(){
    const q=query.value.trim().toLocaleLowerCase('ru');
    const filtered=catalog.filter(x=>(x.label+' '+x.section).toLocaleLowerCase('ru').includes(q));
    let section='';
    list.innerHTML=filtered.map(item=>{
      const name=clean(item.section),heading=item.section!==section?`<h3>${esc(name==='Инструменты'?'Основное':name)}</h3>`:'';section=item.section;
      const {title,note}=parts(item.label);
      return heading+`<button type="button" class="helper-action lab-tool-card" data-id="${esc(item.id)}"><span class="book-seal"><svg class="icon"><use href="#i-${ICONS[item.id]||'book'}"/></svg></span><span><strong>${esc(title)}</strong>${note?`<small>${esc(note)}</small>`:''}</span><svg class="icon"><use href="#i-arrow"/></svg></button>`;
    }).join('');
    status.textContent=filtered.length?`${filtered.length}`:'Ничего не найдено';
  }
  function load(){
    if(loading)return loading;
    status.textContent='Загружаем…';
    loading=window.MuslimoonData.toolsCatalog()
      .then(rows=>{catalog=[...rows.filter(r=>!SKIP.has(r.id)),{id:'__full_app__',label:'Прежний вид приложения (все разделы, как было)',section:'Прежний вид'}];render();})
      .catch(e=>{loading=null;status.textContent='Не загрузилось — откройте вкладку ещё раз';console.warn(e);});
    return loading;
  }
  // Load when the tab is first shown, not on every start.
  new MutationObserver(()=>{if(!view.hidden)load();}).observe(view,{attributes:true,attributeFilter:['hidden']});
  if(!view.hidden)load();
  query.addEventListener('input',render);
  list.addEventListener('click',async e=>{
    const button=e.target.closest('button[data-id]');if(!button)return;
    button.disabled=true;
    try{if(button.dataset.id==='__full_app__')await window.MuslimoonData.showOriginalHome();else await window.MuslimoonData.openOriginalTool(button.dataset.id);}
    catch(e){status.textContent='Этот инструмент пока не открылся';console.warn(e);}
    finally{button.disabled=false;}
  });
})();
