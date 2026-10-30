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
  // Native in the new view (owner П-45: «пересмотри все кнопки — каждой продуманный путь»): not taken from the old list.
  const SKIP=new Set(['setFromMenu','assistBtn','readBtn2','notesBtn','shareAppBtn','copyAppLink','ytLink']);
  const APP_LINK='https://t.me/muslimoontt_bot/app',APP_TEXT='Muslimoon — Коран, хадисы и библиотека Мактаба аш-Шамиля (8589 книг) в одном приложении';
  const NATIVE=[{id:'__notes__',title:'Мои заметки',note:'к хадисам и аятам, на этом устройстве',icon:'pen'},
    {id:'__share__',title:'Поделиться приложением',note:'отправить ссылку в Телеграме',icon:'arrow'},
    {id:'__copy__',title:'Скопировать ссылку на приложение',note:'t.me/muslimoontt_bot/app',icon:'source'},
    {id:'__yt__',title:'Наш YouTube-канал',note:'откроется после вашего подтверждения',icon:'source'}];
  const ICONS={howtoBtn:'info',notesBtn:'pen',hadScienceBtn:'book',ourRazboryBtn:'star',narrTblBtn:'grid',mudTblBtn:'grid',redkieBtn:'book',
    isnadCtorBtn:'grid',hadTblV2Btn:'grid',shareAppBtn:'arrow',copyAppLink:'source',ytLink:'source',menuFbBtn:'helper',__full_app__:'back'};
  const clean=s=>String(s||'').replace(/[\p{Extended_Pictographic}️ℹ⃣]/gu,'').replace(/\s{2,}/g,' ').replace(/^[\s—–-]+/,'').trim();
  function parts(label){const text=clean(label),m=/^(.*?)\s*\((.+)\)\s*$/.exec(text);return m?{title:m[1].trim(),note:m[2].trim()}:{title:text,note:''};}
  let catalog=[],loading=null;
  function render(){
    const q=query.value.trim().toLocaleLowerCase('ru');
    const filtered=catalog.filter(x=>(x.label+' '+x.section).toLocaleLowerCase('ru').includes(q));
    let section='';
    const native=NATIVE.filter(x=>(x.title+' '+x.note).toLocaleLowerCase('ru').includes(q));
    const nativeHtml=native.length?'<h3>Основное</h3>'+native.map(x=>`<button type="button" class="helper-action lab-tool-card" data-id="${x.id}"><span class="book-seal"><svg class="icon"><use href="#i-${x.icon}"/></svg></span><span><strong>${esc(x.title)}</strong><small>${esc(x.note)}</small></span><svg class="icon"><use href="#i-arrow"/></svg></button>`).join(''):'';
    list.innerHTML=nativeHtml+filtered.map(item=>{
      // Not yet redrawn: said plainly, so nobody lands in the old look by surprise (owner П-45).
      const name=clean(item.section),heading=item.section!==section?`<h3>${esc(name==='Инструменты'?'Ещё инструменты':name)}</h3>`:'';section=item.section;
      const {title,note}=parts(item.label);
      return heading+`<button type="button" class="helper-action lab-tool-card" data-id="${esc(item.id)}"><span class="book-seal"><svg class="icon"><use href="#i-${ICONS[item.id]||'book'}"/></svg></span><span><strong>${esc(title)}</strong>${note?`<small>${esc(note)}</small>`:''}</span><svg class="icon"><use href="#i-arrow"/></svg></button>`;
    }).join('');
    status.textContent=(filtered.length+native.length)?`${filtered.length+native.length}`:'Ничего не найдено';
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
    const id=button.dataset.id,tg=window.Telegram&&window.Telegram.WebApp;
    try{if(id==='__notes__')window.dispatchEvent(new Event('muslimoon-notes'));
      else if(id==='__share__'){const url='https://t.me/share/url?url='+encodeURIComponent(APP_LINK)+'&text='+encodeURIComponent(APP_TEXT);if(tg&&tg.initData&&tg.openTelegramLink)tg.openTelegramLink(url);else if(navigator.share)await navigator.share({title:'Muslimoon',text:APP_TEXT,url:APP_LINK});else{await navigator.clipboard.writeText(APP_TEXT+'\n'+APP_LINK);status.textContent='Ссылка скопирована';}}
      else if(id==='__copy__'){await navigator.clipboard.writeText(APP_LINK);status.textContent='Ссылка скопирована';}
      else if(id==='__yt__')window.postMessage({muslimoonLeave:'https://www.youtube.com/@MUSLIMOON.TT2024'},'*');
      else if(id==='__full_app__')await window.MuslimoonData.showOriginalHome();else await window.MuslimoonData.openOriginalTool(id);}
    catch(e){status.textContent='Этот инструмент пока не открылся';console.warn(e);}
    finally{button.disabled=false;}
  });
})();
