const MAX_ITEMS = 300;

function isInterestingMediaUrl(url) {
  const u = url.toLowerCase();
  if (u.includes('.m3u8') || u.includes('.mpd')) return true;
  if (u.match(/\.(mp4|m4v|webm|mov)(\?|$)/)) return true;
  if (u.includes('master.m3u8') || u.includes('playlist.m3u8')) return true;
  if (u.includes('/hls/') && u.includes('m3u8')) return true;
  if (u.includes('/dash/') && u.includes('mpd')) return true;
  if (u.includes('videoplayback') && (u.includes('mime=video') || u.includes('mime=audio'))) return true;
  return false;
}

function cleanTitle(title, fallback) {
  let t = (title || fallback || 'captured').replace(/\s+/g, ' ').trim();
  t = t.replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_').replace(/[\[\]{}()]+/g, '').trim();
  return t.substring(0, 60) || 'captured';
}

async function addCapture(details) {
  const url = details.url || '';
  if (!isInterestingMediaUrl(url)) return;

  let tabTitle = 'captured';
  let pageUrl = '';

  try {
    if (details.tabId >= 0) {
      const tab = await chrome.tabs.get(details.tabId);
      tabTitle = cleanTitle(tab.title, 'captured');
      pageUrl = tab.url || '';
    }
  } catch (e) {}

  const item = {
    url,
    pageUrl,
    title: tabTitle,
    time: new Date().toISOString()
  };

  const data = await chrome.storage.local.get({captures: []});
  let captures = data.captures || [];

  if (captures.some(x => x.url === item.url)) return;
  captures.unshift(item);
  captures = captures.slice(0, MAX_ITEMS);

  await chrome.storage.local.set({captures});
}

chrome.webRequest.onBeforeRequest.addListener(
  addCapture,
  {urls: ["<all_urls>"]}
);
