/* «Наверх» и «Вернуться» (владелец 29.10.2026): когда начало ушло из вида — мягко появляется стрелка вверх;
   после подъёма — кнопка «Вернуться» к прежнему месту; если ею не воспользовались, через несколько секунд она
   аккуратно гаснет. Работает на странице и в открытом окне чтения (берётся то, что сейчас прокручивается). */
(function(){
  'use strict';
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  const make=(cls,label,html)=>{const b=document.createElement('button');b.type='button';b.className='scroll-fab '+cls;b.setAttribute('aria-label',label);b.innerHTML=html;return b;};
  const up=make('scroll-up','Наверх','<svg class="icon"><use href="#i-down"/></svg>');
  const back=make('scroll-back','Вернуться к месту чтения','<svg class="icon"><use href="#i-down"/></svg><span>Вернуться</span>');
  let saved=null,savedIn=null,restoring=false,hideTimer=0;
  // The open dialog wins (reader, book); otherwise the page itself.
  function host(){return [...document.querySelectorAll('dialog[open]')].pop()||null;}
  function scroller(){const d=host();return d?(d.querySelector('.reader-body')||d):document.scrollingElement;}
  function mount(){const parent=host()||document.body;for(const b of [up,back])if(b.parentNode!==parent)parent.appendChild(b);
    up.classList.toggle('in-dialog',!!host());back.classList.toggle('in-dialog',!!host());
    const bar=host()&&host().querySelector('.native-book-bar');up.classList.toggle('over-bar',!!bar);back.classList.toggle('over-bar',!!bar);}
  function hideBack(){clearTimeout(hideTimer);back.classList.remove('show');saved=null;savedIn=null;}
  function onScroll(){
    mount();const s=scroller();if(!s)return;const y=s.scrollTop;
    up.classList.toggle('show',y>s.clientHeight*0.9&&!back.classList.contains('show'));
    // The reader went down by hand again — the way back is no longer needed.
    if(back.classList.contains('show')&&!restoring&&y>Math.max(160,s.clientHeight*0.4))hideBack();
  }
  up.onclick=()=>{
    const s=scroller();saved=s.scrollTop;savedIn=s;restoring=true;up.classList.remove('show');
    s.scrollTo({top:0,behavior:reduce.matches?'auto':'smooth'});
    setTimeout(()=>{restoring=false;back.classList.add('show');clearTimeout(hideTimer);hideTimer=setTimeout(hideBack,6000);},reduce.matches?0:450);
  };
  back.onclick=()=>{
    const s=savedIn||scroller(),to=saved;hideBack();if(to==null)return;restoring=true;
    s.scrollTo({top:to,behavior:reduce.matches?'auto':'smooth'});setTimeout(()=>{restoring=false;onScroll();},500);
  };
  document.addEventListener('scroll',onScroll,{capture:true,passive:true});
  // Opening or closing a dialog changes what scrolls: hide both and re-measure.
  new MutationObserver(()=>{hideBack();up.classList.remove('show');setTimeout(onScroll,60);}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
})();
