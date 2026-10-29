/* Экспериментальная компоновка. Подключать после кода приложения. */
(function () {
  'use strict';
  if (typeof openNarratorRijal !== 'function' || window.__narrExperiment) return;
  window.__narrExperiment = true;
  const original = openNarratorRijal;
  let generation = 0;
  function section(node, title) {
    if (!node || !node.parentNode || node.closest('.narr-exp-section')) return;
    const box = document.createElement('section');
    box.className = 'narr-exp-section';
    const heading = document.createElement('h3');
    heading.className = 'narr-exp-heading';
    heading.textContent = title;
    node.parentNode.insertBefore(box, node);
    box.appendChild(heading);
    box.appendChild(node); // переносим существующий узел со всеми обработчиками
  }
  function arrange(body) {
    const hero = body.querySelector('.ourId');
    if (!hero) return;
    const host = Array.from(body.children).find(x => x.contains(hero));
    if (!host) return;
    const heroBox = Array.from(host.children).find(x => x.contains(hero));
    if (heroBox) {
      heroBox.classList.add('narr-exp-identity');
      const title = document.getElementById('narrTitle');
      if (title) title.textContent = 'Передатчик';
      const actions = heroBox.querySelector('.ourId')?.parentElement;
      if (actions) actions.classList.add('narr-exp-actions');
      const notice = Array.from(heroBox.children).find(x => /^🔧\s*В работе:/.test((x.textContent || '').trim()));
      if (notice) {
        const details = document.createElement('details');
        details.className = 'narr-exp-notice';
        const summary = document.createElement('summary');
        summary.textContent = 'О написании имени';
        notice.before(details); details.append(summary, notice);
      }
      const next = heroBox.nextElementSibling;
      if (next && /Что сказали о нём|оценк|критик/i.test(next.textContent || '')) section(next, 'Мнения учёных');
    }
    Array.from(body.children).forEach(node => {
      if (node === host || node.id === 'narrAnch' || node.classList.contains('narr-exp-section')) return;
      const text = (node.textContent || '').trim();
      if (node.querySelector('.tlHdr')) section(node, 'Учители и ученики');
      else if (node.querySelector('.covHdr')) section(node, 'Участие в хадисах');
      else if (node.querySelector('.ntHdr')) section(node, 'Источники и чтение');
      else if (/^📗 В Сахихайн/.test(text)) section(node, 'Места в Сахихайн');
    });
  }
  openNarratorRijal = async function (...args) {
    const turn = ++generation;
    const result = await original.apply(this, args);
    const body = document.getElementById('narrBody');
    if (turn === generation && body) arrange(body);
    return result;
  };
})();
