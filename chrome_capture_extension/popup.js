function domainFromUrl(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return 'captured'; }
}

function cleanTitle(title, pageUrl) {
  let t = (title || domainFromUrl(pageUrl) || 'captured').replace(/\s+/g, ' ').trim();
  t = t.replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_').replace(/[\[\]{}()]+/g, '').trim();
  return t.substring(0, 60) || 'captured';
}

async function getCaptures() {
  const data = await chrome.storage.local.get({captures: []});
  return data.captures || [];
}

function render(captures) {
  const list = document.getElementById('list');
  const status = document.getElementById('status');
  status.textContent = `${captures.length} link yakalandı.`;
  list.innerHTML = '';
  captures.slice(0, 25).forEach(item => {
    const div = document.createElement('div');
    div.className = 'item';
    div.innerHTML = `<div class="title">${cleanTitle(item.title, item.pageUrl)}</div><div class="url">${item.url}</div><div class="small">referer: ${item.pageUrl || '-'}</div>`;
    list.appendChild(div);
  });
}

async function copyForChartshunter() {
  const captures = await getCaptures();
  const groups = new Map();
  captures.slice().reverse().forEach(item => {
    const title = cleanTitle(item.title, item.pageUrl);
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(item);
  });

  let lines = [];
  for (const [title, items] of groups.entries()) {
    lines.push(title);
    items.forEach(item => {
      const ref = item.pageUrl ? ` # referer=${item.pageUrl}` : '';
      lines.push(`${item.url}${ref}`);
    });
    lines.push('');
  }

  const text = lines.join('\n').trim();
  await navigator.clipboard.writeText(text);
  document.getElementById('status').textContent = 'Kopyalandı. Uygulamada Panodan Ekle veya Ctrl+V yap.';
}

document.getElementById('copy').addEventListener('click', copyForChartshunter);
document.getElementById('clear').addEventListener('click', async () => {
  await chrome.storage.local.set({captures: []});
  render([]);
});
document.getElementById('refresh').addEventListener('click', async () => render(await getCaptures()));

getCaptures().then(render);
