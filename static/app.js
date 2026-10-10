'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const token = $('meta[name="local-token"]').content;

const ACTIVE = new Set(['queued', 'inspecting', 'downloading', 'processing', 'cancelling']);
const ATTENTION = new Set(['failed', 'cancelled', 'interrupted']);
const AUDIO_MODES = new Set(['audio', 'mp3', 'm4a', 'flac', 'wav']);
// Fields that change every progress tick; rows update them in place instead of re-rendering.
const VOLATILE = new Set(['progress', 'speed', 'eta', 'downloaded', 'total', 'updated', 'stage']);
const STATUS = {queued:'Queued', inspecting:'Finding the best source', downloading:'Downloading', processing:'Finishing the file', cancelling:'Stopping after this step', completed:'Saved', failed:'Failed', cancelled:'Cancelled', interrupted:'Interrupted'};
const VIEWS = {download:'Download', library:'Library', platforms:'Sources', agents:'Agents', settings:'Settings'};
const FORMATS = {original:'Original', mp4:'MP4', 'mp4-best':'MP4', mkv:'MKV', webm:'WebM', audio:'Audio', mp3:'MP3', m4a:'M4A', flac:'FLAC', wav:'WAV'};
const MODE_HINTS = {
  original:'Keeps the best source without re-encoding. Separate video and audio streams are combined into MKV.',
  mp4:'H.264 video with AAC audio, for TVs, phones and editors. The compatible stream can have a lower resolution.',
  'mp4-best':'The highest-quality MP4 source, which may use AV1 or HEVC. Your player needs to support that codec.',
  mkv:'The best video and audio in an MKV container, without re-encoding.',
  webm:'WebM video and audio streams, where the platform offers them.',
  audio:'The original audio track, without a lossy conversion.',
  mp3:'Converts the best audio to high-quality MP3. Conversion can’t improve the original.',
  m4a:'AAC audio in M4A. Converts only when needed.',
  flac:'Stores the decoded source losslessly. It can’t restore detail the platform already removed.',
  wav:'Uncompressed audio for editing. Large files; the source still sets the quality.'
};
const PLATFORM_NAMES = {youtube:'YouTube', twitter:'X', tiktok:'TikTok', instagram:'Instagram', facebook:'Facebook', vimeo:'Vimeo', reddit:'Reddit', twitch:'Twitch', soundcloud:'SoundCloud', bluesky:'Bluesky', spotify:'Spotify', dailymotion:'Dailymotion', pinterest:'Pinterest', snapchat:'Snapchat', generic:'Web'};
const HOSTS = [
  [/(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$/, 'YouTube'], [/(^|\.)tiktok\.com$/, 'TikTok'], [/(^|\.)(x\.com|twitter\.com)$/, 'X'],
  [/(^|\.)instagram\.com$/, 'Instagram'], [/(^|\.)(facebook\.com|fb\.watch|fb\.com)$/, 'Facebook'], [/(^|\.)(open\.spotify\.com|spotify\.link|spotify\.app\.link)$/, 'Spotify'],
  [/(^|\.)vimeo\.com$/, 'Vimeo'], [/(^|\.)(reddit\.com|redd\.it)$/, 'Reddit'], [/(^|\.)bsky\.app$/, 'Bluesky'], [/(^|\.)twitch\.tv$/, 'Twitch'],
  [/(^|\.)(pinterest\.[a-z.]+|pin\.it)$/, 'Pinterest'], [/(^|\.)snapchat\.com$/, 'Snapchat'], [/(^|\.)soundcloud\.com$/, 'SoundCloud'], [/(^|\.)dailymotion\.com$/, 'Dailymotion']
];
const SPOTIFY_HOSTS = ['open.spotify.com', 'www.open.spotify.com', 'spotify.link', 'spotify.app.link'];

let state = {jobs: [], counts: null};
let view = 'download';
let kind = 'all';
let ready = false;
let refreshSeq = 0;
let appliedSeq = 0;
let previewController;
let previewRevision = 0;
let previewRequest = 0;
let folderDirty = false;
let platformTimer;
let platformSeq = 0;
let queuePositions = new Map();
let exportingFiles = false;

/* Formatting */
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
function safeImage(value) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? escape(url.href) : ''; } catch { return ''; } }
function size(bytes) { bytes = Number(bytes); if (!bytes || bytes < 0) return ''; const units = ['B', 'KB', 'MB', 'GB', 'TB']; let index = 0; while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index++; } return `${bytes.toFixed(index > 1 ? 1 : 0)} ${units[index]}`; }
function duration(seconds) {
  seconds = Number(seconds); if (!Number.isFinite(seconds) || seconds < 0) return '';
  const total = Math.round(seconds), hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), rest = String(total % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}
function ordinal(n) { const tens = n % 100; if (tens >= 11 && tens <= 13) return `${n}th`; return n + ({1:'st', 2:'nd', 3:'rd'}[n % 10] || 'th'); }
function when(iso) {
  const date = new Date(iso); if (Number.isNaN(date.getTime())) return '';
  const today = new Date(); const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  const time = date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  if (date.toDateString() === today.toDateString()) return `Today ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`;
  return date.toLocaleDateString([], {day:'numeric', month:'short', ...(date.getFullYear() === today.getFullYear() ? {} : {year:'numeric'})});
}
function shortPath(path) {
  path = String(path || '');
  const parts = path.split(/[\\/]+/).filter(Boolean);
  if (parts.length <= 3) return path;
  const separator = path.includes('\\') ? '\\' : '/';
  return (path.startsWith('/') ? separator : '') + [parts[0], '…', ...parts.slice(-2)].join(separator);
}
function hostName(value) { try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return ''; } }
function platformFor(hostname) { const host = hostname.toLowerCase(); return (HOSTS.find(([pattern]) => pattern.test(host)) || [, host.replace(/^www\./, '')])[1]; }
function platformName(job) { const name = String(job.platform || '').trim(); const host = hostName(job.url); return PLATFORM_NAMES[name.toLowerCase()] || name || (host && platformFor(host)) || 'Web'; }
function modeOf(job) { return job.options?.mode || job.output_mode || ''; }
function isAudio(job) { return AUDIO_MODES.has(modeOf(job)) || job.platform === 'Spotify'; }
function mediaFiles(job) { return (job.files || []).filter((name) => !/\.(vtt|srt|ass|ttml)$/i.test(name)); }
function formatOf(job) { const file = mediaFiles(job)[0]; const extension = file && file.includes('.') ? file.split('.').pop().toUpperCase() : ''; return extension || FORMATS[modeOf(job)] || ''; }
function resolutionOf(job) { const width = Number(job.width), height = Number(job.height); if (!width || !height || isAudio(job)) return ''; const short = Math.min(width, height); return short >= 4320 ? '8K' : short >= 2160 ? '4K' : `${short}p`; }
function statusText(job) {
  if (job.status === 'queued') { const position = queuePositions.get(job.id); return position === 1 ? 'Up next' : position ? `${ordinal(position)} in line` : STATUS.queued; }
  return (ACTIVE.has(job.status) && job.stage) || STATUS[job.status] || job.status;
}
function liveText(job) {
  const parts = [];
  if (job.downloaded && job.total) parts.push(`${size(job.downloaded)} of ${size(job.total)}`);
  else if (job.progress) parts.push(`${Math.floor(job.progress)}%`);
  else parts.push('Starting');
  if (job.speed) parts.push(`${size(job.speed)}/s`);
  if (job.eta) parts.push(`${duration(job.eta)} left`);
  return parts.join(' · ');
}

/* Network */
async function api(path, body, {signal} = {}) {
  const init = {signal, headers:{'X-Local-Token':token}};
  if (body !== undefined) { init.method = 'POST'; if (body instanceof FormData) init.body = body; else { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); } }
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const reference = data.error_id || response.headers.get('X-Spool-Request-ID');
    const error = new Error((data.error || 'Something went wrong. Try again.') + (reference ? ` (reference ${reference})` : ''));
    error.requestId = response.headers.get('X-Spool-Request-ID');
    throw error;
  }
  return data;
}

/* Toasts */
function toast(message, {action, onAction, tone = 'info', duration: lifetime} = {}) {
  const region = $('#toasts');
  const node = document.createElement('div');
  node.className = `toast toast-${tone}`;
  if (tone === 'error') node.setAttribute('role', 'alert');
  const text = document.createElement('span'); text.className = 'toast-msg'; text.textContent = message; node.append(text);
  if (action) { const button = document.createElement('button'); button.type = 'button'; button.className = 'toast-action'; button.textContent = action; button.addEventListener('click', () => { dismiss(node); onAction?.(); }); node.append(button); }
  const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-btn'; close.setAttribute('aria-label', 'Dismiss'); close.innerHTML = icon('x'); close.addEventListener('click', () => dismiss(node)); node.append(close);
  region.append(node);
  while (region.children.length > 3) region.firstElementChild.remove();
  let timer;
  const start = () => { clearTimeout(timer); timer = setTimeout(() => dismiss(node), lifetime ?? (action ? 9000 : tone === 'error' ? 8000 : 4500)); };
  node.addEventListener('mouseenter', () => clearTimeout(timer));
  node.addEventListener('mouseleave', start);
  node.addEventListener('focusin', () => clearTimeout(timer));
  node.addEventListener('focusout', start);
  start();
}
function dismiss(node) { if (!node.isConnected || node.classList.contains('is-leaving')) return; node.classList.add('is-leaving'); setTimeout(() => node.remove(), 200); }
function formError(message) { $('#form-error').textContent = message; $('#form-error').hidden = !message; }

/* Markup. Every value from media metadata goes through escape(). */
function thumbMarkup(job, {ring = false, badge = ''} = {}) {
  const url = safeImage(job.thumbnail);
  const index = (job.files || []).findIndex((name) => !/\.(vtt|srt|ass|ttml)$/i.test(name));
  const drag = job.status === 'completed' && index >= 0 ? ` draggable="true" data-drag-id="${escape(job.id)}" data-file-index="${index}" title="Drag this file to another app or folder"` : '';
  return `<div class="thumb"${drag}>${icon(isAudio(job) ? 'music' : 'video')}${url ? `<img src="${url}" alt="" draggable="false" loading="lazy" referrerpolicy="no-referrer" data-fallback>` : ''}${badge ? `<span class="thumb-badge">${escape(badge)}</span>` : ''}${ring ? '<div class="ring-wrap"><div class="ring"></div><span class="ring-label" data-pct></span></div>' : ''}</div>`;
}
function fileLinks(job) {
  return (job.files || []).map((name, index) => {
    const label = /\.(vtt|srt|ass|ttml)$/i.test(name) ? 'Save subtitles' : 'Save a copy';
    const drag = label === 'Save a copy' ? `<button class="btn btn-quiet btn-sm file-drag" type="button" draggable="true" data-drag-id="${escape(job.id)}" data-file-index="${index}" title="Drag file: ${escape(name)}" aria-label="Drag file: ${escape(name)}">${icon('drag')}Drag</button><button class="icon-btn" type="button" data-action="copy-path" data-id="${escape(job.id)}" data-file-index="${index}" title="Copy path: ${escape(name)}" aria-label="Copy path: ${escape(name)}">${icon('copy')}</button>` : '';
    return `${drag}<a class="icon-btn" draggable="false" href="/api/jobs/${encodeURIComponent(job.id)}/files/${index}" title="${label}: ${escape(name)}" aria-label="${label}: ${escape(name)}" download>${icon(label === 'Save a copy' ? 'download' : 'captions')}</a>`;
  }).join('');
}
const removeButton = (job, label) => `<button class="icon-btn" type="button" data-action="remove" data-id="${escape(job.id)}" aria-label="${label}" title="${label}">${icon('x')}</button>`;
function rowMarkup(job) {
  const id = escape(job.id);
  const active = ACTIVE.has(job.status);
  const meta = [platformName(job), formatOf(job), resolutionOf(job), job.status === 'completed' ? size(job.size) : ''].filter(Boolean);
  let actions;
  if (active) actions = `<button class="btn btn-quiet btn-sm" type="button" data-action="cancel" data-id="${id}" ${job.status === 'cancelling' ? 'disabled' : ''}>${icon('stop')}Cancel</button>`;
  else if (job.status === 'completed') actions = `<button class="btn btn-quiet btn-sm" type="button" data-action="open" data-id="${id}">${icon('folder')}Show</button>${fileLinks(job)}${removeButton(job, 'Remove from the list. The file stays on disk.')}`;
  else actions = `<button class="btn btn-secondary btn-sm" type="button" data-action="retry" data-id="${id}">${icon('retry')}Retry</button>${removeButton(job, 'Remove from the list. Partial files are kept.')}`;
  if (ATTENTION.has(job.status)) actions = `<button class="btn btn-quiet btn-sm" type="button" data-action="diagnostics" data-id="${id}">Details</button>` + actions;
  return `<article class="job${active ? ' is-active' : ''}${job.status === 'queued' ? ' is-queued' : ''}">
    ${thumbMarkup(job, {ring: active, badge: active ? '' : duration(job.duration)})}
    <div class="job-main">
      <h4 class="job-title" title="${escape(job.title)}">${escape(job.title)}</h4>
      <div class="job-meta"><span class="state ${active ? 'state-active' : `state-${escape(job.status)}`}" data-stage>${escape(statusText(job))}</span>${meta.map((part) => `<span>${escape(part)}</span>`).join('')}</div>
      ${job.status === 'downloading' ? '<p class="job-live" data-live></p>' : ''}
      ${job.matched_source_title ? `<p class="job-note">Matched on YouTube: ${escape(job.matched_source_title)}</p>` : ''}
      ${job.error && !active ? `<p class="${job.status === 'cancelled' ? 'job-note' : 'job-error'}">${escape(job.error)}</p>` : ''}
      ${job.warning ? `<p class="job-warn">${escape(job.warning)}</p>` : ''}
    </div>
    <div class="job-actions">${actions}</div>
  </article>`;
}
function cardMarkup(job) {
  const meta = [platformName(job), formatOf(job), resolutionOf(job), size(job.size)].filter(Boolean).join(' · ');
  const byline = [when(job.updated || job.created), job.uploader].filter(Boolean).join(' · ');
  return `<article class="card">
    ${thumbMarkup(job, {badge: duration(job.duration)})}
    <div class="card-body">
      <h3 class="card-title" title="${escape(job.title)}">${escape(job.title)}</h3>
      <p class="card-meta" title="${escape(meta)}">${escape(meta)}</p>
      ${byline ? `<p class="card-meta" title="${escape(byline)}">${escape(byline)}</p>` : ''}
      ${job.matched_source_title ? `<p class="card-meta" title="Matched on YouTube: ${escape(job.matched_source_title)}">YouTube match: ${escape(job.matched_source_title)}</p>` : ''}
      <div class="card-actions"><button class="btn btn-secondary btn-sm" type="button" data-action="open" data-id="${escape(job.id)}">${icon('folder')}Show in folder</button>${fileLinks(job)}${removeButton(job, 'Remove from the library. The file stays on disk.')}</div>
    </div>
  </article>`;
}
function emptyMarkup(symbol, title, text) { return `${symbol}<h3>${escape(title)}</h3><p>${escape(text)}</p>`; }

/* Keyed rendering: rows keep their DOM between polls, so focus, hover and thumbnails survive. */
function signature(job) { return JSON.stringify(job, (key, value) => VOLATILE.has(key) ? undefined : value); }
function sync(container, jobs, render, {extra = () => '', live} = {}) {
  container._seen ||= new Set();
  const nodes = new Map([...container.children].map((node) => [node._key, node]));
  let previous = null;
  for (const job of jobs) {
    const sig = signature(job) + '|' + extra(job);
    let node = nodes.get(job.id);
    if (!node || node._sig !== sig) {
      const template = document.createElement('template');
      template.innerHTML = render(job).trim();
      const fresh = template.content.firstElementChild;
      fresh._key = job.id; fresh._sig = sig;
      if (node) {
        const focused = node.contains(document.activeElement) ? document.activeElement.dataset.action : null;
        node.replaceWith(fresh);
        if (focused) fresh.querySelector(`[data-action="${focused}"]`)?.focus();
      } else if (container._ready && !container._seen.has(job.id)) fresh.classList.add('is-new');
      node = fresh;
    }
    nodes.delete(job.id);
    container._seen.add(job.id);
    live?.(node, job);
    const expected = previous ? previous.nextElementSibling : container.firstElementChild;
    if (node !== expected) container.insertBefore(node, expected);
    previous = node;
  }
  nodes.forEach((node) => node.remove());
  container._ready = true;
}
function updateLive(node, job) {
  if (!ACTIVE.has(job.status)) return;
  const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
  const determinate = job.status === 'downloading' && progress > 0;
  node.style.setProperty('--p', progress.toFixed(1));
  node.classList.toggle('is-indeterminate', !determinate && job.status !== 'queued');
  const percent = $('[data-pct]', node);
  if (percent) percent.textContent = job.status === 'queued' ? `#${queuePositions.get(job.id) || ''}` : determinate ? `${Math.floor(progress)}%` : '';
  const stage = $('[data-stage]', node); if (stage) stage.textContent = statusText(job);
  const live = $('[data-live]', node); if (live) live.textContent = liveText(job);
}

/* Rendering */
function counts() {
  if (state.counts) return state.counts;
  const by = {}; state.jobs.forEach((job) => { by[job.status] = (by[job.status] || 0) + 1; });
  return {active:state.jobs.filter((job) => ACTIVE.has(job.status)).length, attention:state.jobs.filter((job) => ATTENTION.has(job.status)).length, completed:by.completed || 0, by_status:by};
}
function renderActivity() {
  const totals = counts();
  const jobs = state.jobs;
  const running = jobs.filter((job) => ACTIVE.has(job.status) && job.status !== 'queued');
  // queued_at is reset by Retry, so it reflects the real FIFO position; created is the original history time.
  const queuedAt = (job) => String(job.queued_at || job.created || '');
  const queued = jobs.filter((job) => job.status === 'queued').sort((a, b) => queuedAt(a).localeCompare(queuedAt(b)));
  queuePositions = new Map(queued.map((job, index) => [job.id, index + 1]));
  const attention = jobs.filter((job) => ATTENTION.has(job.status));
  const recent = jobs.filter((job) => job.status === 'completed').sort((a, b) => String(b.updated).localeCompare(String(a.updated))).slice(0, 4);
  const active = [...running, ...queued];
  sync($('#list-active'), active, rowMarkup, {extra:(job) => queuePositions.get(job.id) || '', live:updateLive});
  sync($('#list-attention'), attention, rowMarkup);
  sync($('#list-recent'), recent, rowMarkup);
  $('#group-active').hidden = !active.length;
  $('#group-attention').hidden = !attention.length;
  $('#group-recent').hidden = !recent.length;
  $('#activity-empty').hidden = !ready || Boolean(active.length || attention.length || recent.length);
  $('#count-active').textContent = totals.active ?? active.length;
  $('#count-attention').textContent = totals.attention ?? attention.length;
  const retryable = (totals.by_status?.failed || 0) + (totals.by_status?.interrupted || 0);
  $('#retry-failed').hidden = !retryable;
  $('#queue-note').textContent = running.length ? `One at a time${queued.length ? ` · ${queued.length} waiting` : ''}` : queued.length ? `${queued.length} waiting` : '';
  $('#nav-active').hidden = !active.length;
  $('#nav-attention').hidden = !totals.attention;
  $('#nav-attention').textContent = totals.attention || '';
  $('#nav-attention').title = totals.attention ? `${plural(totals.attention, 'download')} need attention` : '';
  $('#library-count').textContent = totals.completed ?? 0;
}
function renderLibrary() {
  const done = state.jobs.filter((job) => job.status === 'completed');
  const term = $('#search').value.trim().toLowerCase();
  let list = done.filter((job) => kind === 'all' || (kind === 'audio') === isAudio(job));
  if (term) list = list.filter((job) => [job.title, job.uploader, platformName(job), job.url].join(' ').toLowerCase().includes(term));
  const order = $('#sort').value;
  if (order === 'oldest') list.reverse();
  else if (order === 'largest') list.sort((a, b) => (b.size || 0) - (a.size || 0));
  else if (order === 'title') list.sort((a, b) => String(a.title).localeCompare(String(b.title), undefined, {sensitivity:'base'}));
  sync($('#library'), list, cardMarkup);
  const total = counts().completed ?? done.length;
  const bytes = done.reduce((sum, job) => sum + (Number(job.size) || 0), 0);
  $('#library-summary').textContent = !done.length ? 'Finished downloads appear here.' : list.length === done.length ? `${plural(total, 'download')}${bytes ? ` · ${size(bytes)}` : ''}` : `Showing ${list.length} of ${plural(done.length, 'download')}`;
  $('#clear-library').hidden = !done.length;
  const empty = $('#library-empty');
  empty.hidden = !ready || list.length > 0;
  if (!empty.hidden) empty.innerHTML = done.length ? emptyMarkup(icon('search'), 'Nothing matches', 'Try another search, or switch the filter back to All.') : emptyMarkup('<svg class="empty-mark" aria-hidden="true"><use href="#mark"/></svg>', 'Your library is empty', `Finished downloads land here. Choose one folder or separate subfolders when you download. Default: ${state.folder || 'your download folder'}.`);
}
function renderSettings() {
  const logging = state.diagnostics;
  $('#diagnostic-status').textContent = logging?.available === false ? `Logging needs attention (${logging.last_error || 'storage unavailable'}). ${logging.dropped_events || 0} events could not be saved.` : 'Local diagnostics are active.';
  $('#save-folder').textContent = shortPath(state.folder);
  $('#batch-folder').placeholder = state.folder || 'Use the default download folder';
  $('#file-drag-hint').textContent = window.pywebview?.api?.drag_files && state.native_drag ? 'Drag a thumbnail or the Drag handle into an editor or folder. Copy path is also available.' : 'File dragging works in the Windows desktop app. Here, use Copy path or Save a copy.';
  $('#save-folder').parentElement.title = `New downloads go to ${state.folder}. Click to change.`;
  if (!folderDirty && document.activeElement !== $('#folder-path')) $('#folder-path').value = state.folder;
  $('#disk-space').textContent = state.free_bytes ? `${size(state.free_bytes)} free on that drive.${window.pywebview?.api?.choose_folder ? '' : ' Browse works in the desktop app; here, paste a path.'}` : '';
  $('#engine-version').textContent = `yt-dlp ${state.engine}${state.version ? ` · Spool ${state.version}` : ''}`;
  $('#cookie-status').textContent = state.cookies ? 'A cookie file is imported on this computer' : 'No cookie file imported';
  const dependencies = Object.entries(state.dependencies || {});
  $('#engine-status').innerHTML = `<span class="pill">yt-dlp ${escape(state.engine)}</span>` + dependencies.map(([name, exists]) => `<span class="pill ${exists ? 'pill-ok' : 'pill-err'}">${icon(exists ? 'check' : 'alert')}${escape(name)} ${exists ? 'ready' : 'missing'}</span>`).join('');
  $('#spotify-status').textContent = state.spotify?.available ? 'Song matcher ready. Public track links work.' : 'The song matcher isn’t available in this build. Install the latest version to use Spotify links.';
  const missing = dependencies.filter(([, exists]) => !exists).map(([name]) => name);
  $('#dependency-error').hidden = !missing.length;
  $('#dependency-error').textContent = `Spool can’t find ${missing.join(', ')}. Downloads that need ${missing.length === 1 ? 'it' : 'them'} will fail until it’s installed; see README.md.`;
}
function setOnline(online) {
  $('#connection-error').hidden = online;
  $('#local-status').classList.toggle('is-offline', !online);
  $('#local-status-text').textContent = online ? 'Running on this computer' : 'Not connected';
}
async function refresh() {
  const seq = ++refreshSeq;
  try {
    const data = await api('/api/state');
    if (seq < appliedSeq) return;
    appliedSeq = seq;
    state = data;
    ready = true;
    setOnline(true);
    renderSettings();
    renderActivity();
    renderLibrary();
  } catch { if (seq >= appliedSeq) setOnline(false); }
}

/* Navigation */
function setView(next) {
  if (!VIEWS[next]) return;
  const changed = next !== view;
  view = next;
  $$('.view').forEach((node) => {
    const show = node.id === `view-${next}`;
    node.hidden = !show;
    if (show && changed) { node.classList.remove('is-entering'); void node.offsetWidth; node.classList.add('is-entering'); }
  });
  $$('.nav-item').forEach((item) => { const on = item.dataset.view === next; item.classList.toggle('active', on); if (on) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); });
  $('#view-title').textContent = VIEWS[next];
  if (changed) window.scrollTo({top:0});
  if (next === 'platforms') loadPlatforms();
  if (next === 'agents') loadIntegrations();
}
document.addEventListener('click', (event) => {
  const target = event.target.closest('[data-view]');
  if (!target) return;
  event.preventDefault();
  setView(target.dataset.view);
  if (target.dataset.focus) $(`#${target.dataset.focus}`)?.focus();
});

/* Links */
const isEditable = (node) => !!node?.closest?.('input, textarea, select, [contenteditable="true"]');
const lines = () => $('#urls').value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
function parseLink(text) { try { const url = new URL(text); return ['http:', 'https:'].includes(url.protocol) ? url : null; } catch { return null; } }
function isCollection(url) {
  const host = url.hostname.toLowerCase();
  if (SPOTIFY_HOSTS.includes(host)) return /\/(playlist|album|artist|show)\//.test(url.pathname);
  return /(^|\.)youtube\.com$/.test(host) && url.pathname === '/playlist';
}
function analyze() { return lines().map((text) => { const url = parseLink(text); return {text, url, platform:url ? platformFor(url.hostname) : null}; }); }
function autosize() { const field = $('#urls'); field.style.height = 'auto'; field.style.height = `${Math.min(field.scrollHeight, 260)}px`; }
function updateLinks() {
  const items = analyze();
  const valid = items.filter((item) => item.url);
  const summary = $('#link-summary');
  $('#spotify-hint').hidden = !valid.some((item) => SPOTIFY_HOSTS.includes(item.url.hostname.toLowerCase()));
  if (!items.length) { summary.innerHTML = '<span class="muted">Ctrl+V anywhere in the window, or drop links here.</span>'; return; }
  const groups = new Map();
  valid.forEach((item) => groups.set(item.platform, (groups.get(item.platform) || 0) + 1));
  const tokens = [...groups].map(([name, count]) => `<span class="tok">${escape(name)}${count > 1 ? ` ×${count}` : ''}</span>`);
  const invalid = items.length - valid.length;
  const duplicates = valid.length - new Set(valid.map((item) => item.url.href)).size;
  const collections = valid.filter((item) => isCollection(item.url)).length;
  if (invalid) tokens.push(`<span class="tok tok-err">${invalid === 1 ? '1 line isn’t a link' : `${invalid} lines aren’t links`}</span>`);
  if (collections) tokens.push(`<span class="tok tok-warn">${collections === 1 ? 'Playlists and albums aren’t supported' : `${collections} playlists or albums aren’t supported`}</span>`);
  if (duplicates) tokens.push(`<span class="tok">${plural(duplicates, 'duplicate')}</span>`);
  if (items.length > 30) tokens.push('<span class="tok tok-err">30 links per batch at most</span>');
  summary.innerHTML = `<span>${plural(valid.length, 'link')}</span>${tokens.join('')}`;
}
function addLinks(text) {
  const found = String(text || '').replace(/^#.*$/gm, '').split(/\s+/).map((part) => part.trim()).filter((part) => parseLink(part));
  if (!found.length) return 0;
  const field = $('#urls');
  const existing = lines();
  field.value = [...existing, ...found.filter((link) => !existing.includes(link))].join('\n');
  field.dispatchEvent(new Event('input'));
  setView('download');
  field.focus();
  field.setSelectionRange(field.value.length, field.value.length);
  return found.length;
}
function invalidatePreview() { previewRevision++; previewController?.abort(); $('#preview').hidden = true; formError(''); }
$('#urls').addEventListener('input', () => { autosize(); updateLinks(); invalidatePreview(); });
$('#urls').addEventListener('keydown', (event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('#download-form').requestSubmit(); } });
$('#paste').addEventListener('click', async () => {
  try { const text = await navigator.clipboard.readText(); if (!addLinks(text)) toast('There’s no web link on the clipboard.'); }
  catch { $('#urls').focus(); toast('Press Ctrl+V to paste into the link field.'); }
});
document.addEventListener('paste', (event) => {
  if (isEditable(event.target)) return;
  if (addLinks(event.clipboardData?.getData('text'))) event.preventDefault();
});
let dragDepth = 0;
const carriesText = (event) => !exportingFiles && !(event.dataTransfer?.types || []).includes('application/x-spool-file') && [...(event.dataTransfer?.types || [])].some((type) => type === 'text/uri-list' || type === 'text/plain');
function endDrag() { dragDepth = 0; document.body.classList.remove('is-dragging'); $('#drop').classList.remove('is-over'); }
document.addEventListener('dragenter', (event) => { if (!carriesText(event)) return; event.preventDefault(); dragDepth++; document.body.classList.add('is-dragging'); $('#drop').classList.add('is-over'); });
document.addEventListener('dragover', (event) => { if (!carriesText(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; });
document.addEventListener('dragleave', (event) => { if (!carriesText(event)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) endDrag(); });
document.addEventListener('drop', (event) => {
  if (!carriesText(event)) return;
  event.preventDefault();
  endDrag();
  if (!addLinks(event.dataTransfer.getData('text/uri-list') || event.dataTransfer.getData('text/plain'))) toast('That didn’t contain a web link.');
});

/* Options */
try { $('#flat-folder').checked = localStorage.getItem('flat-folder') === 'true'; } catch { /* Optional preference. */ }
$('#flat-folder').addEventListener('change', () => { try { localStorage.setItem('flat-folder', String($('#flat-folder').checked)); } catch { /* Optional preference. */ } });
$('#reset-batch-folder').addEventListener('click', () => { $('#batch-folder').value = ''; });
function options() { return {mode:$('#mode').value, quality:$('#quality').value, browser:$('#browser').value, clean:$('#clean').checked, subtitles:$('#subtitles').checked}; }
function updateMode() {
  const audio = AUDIO_MODES.has($('#mode').value);
  $('#quality').disabled = audio;
  $('#subtitles').disabled = audio;
  $('#quality-field').classList.toggle('is-disabled', audio);
  $('#subtitles-field').classList.toggle('is-disabled', audio);
  $('#mode-hint').textContent = MODE_HINTS[$('#mode').value] || '';
}
$$('#mode,#quality,#browser,#clean,#subtitles').forEach((node) => node.addEventListener('change', () => {
  invalidatePreview();
  try { localStorage.setItem('download-options', JSON.stringify(options())); } catch { /* Storage can be unavailable; options still apply. */ }
  updateMode();
}));

/* Preview and download */
function setBusy(button, busy, label) { button.disabled = busy; const text = $('span', button); if (label && text) text.textContent = label; }
$('#preview-button').addEventListener('click', async () => {
  formError('');
  const items = analyze();
  if (items.length !== 1 || !items[0].url) return formError(items.length > 1 ? 'Preview checks one link at a time. For a batch, just press Download.' : 'Paste a link to preview it.');
  const button = $('#preview-button');
  const revision = previewRevision;
  const request = ++previewRequest;
  previewController?.abort();
  previewController = new AbortController();
  setBusy(button, true, 'Checking…');
  try {
    const info = await api('/api/inspect', {url:items[0].text, options:options()}, {signal:previewController.signal});
    if (revision !== previewRevision) return;
    const meta = [platformName(info), info.uploader, duration(info.duration), info.width && info.height ? `${info.width} × ${info.height}` : '', info.size ? `about ${size(info.size)}` : ''].filter(Boolean);
    const watermarked = /watermark/i.test(info.source || '');
    const best = (info.resolutions || [])[0];
    const tags = [info.source ? `<span class="tag ${watermarked ? 'tag-warn' : 'tag-ok'}">${icon(watermarked ? 'alert' : 'shield')}${escape(info.source)}</span>` : '', best && !info.matched_source_title ? `<span class="tag">Up to ${escape(best >= 2160 ? (best >= 4320 ? '8K' : '4K') : `${best}p`)}</span>` : ''].filter(Boolean);
    const notes = [
      info.matched_source_title ? `<p class="preview-note">Matched recording: ${escape(info.matched_source_title)}${info.output_mode ? ` · saves as ${escape(String(info.output_mode).toUpperCase())}` : ''}</p>` : '',
      info.matched_source_url ? `<p class="preview-note muted">${escape(info.matched_source_url)}</p>` : '',
      ...(info.warnings || []).map((warning) => `<p class="preview-note is-warn">${escape(warning)}</p>`)
    ].join('');
    $('#preview').innerHTML = `${thumbMarkup(info, {badge:duration(info.duration)})}<div><h3>${escape(info.title)}</h3><p class="preview-meta">${meta.map(escape).join(' · ')}</p>${tags.length ? `<div class="preview-tags">${tags.join('')}</div>` : ''}${notes}</div>`;
    $('#preview').hidden = false;
  } catch (error) { if (error.name !== 'AbortError' && revision === previewRevision) formError(error.message); }
  finally { if (request === previewRequest) setBusy(button, false, 'Preview'); }
});
$('#download-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  formError('');
  const items = analyze();
  const field = $('#urls');
  if (!items.length) { field.focus(); return formError('Paste a link first.'); }
  const invalid = items.filter((item) => !item.url).length;
  if (invalid) { field.focus(); return formError(invalid === 1 ? 'One line isn’t a web link. Fix or remove it, then try again.' : `${invalid} lines aren’t web links. Fix or remove them, then try again.`); }
  if (items.length > 30) { field.focus(); return formError(`That’s ${items.length} links. Add up to 30 at a time.`); }
  const button = $('#download-button');
  setBusy(button, true, 'Adding…');
  try {
    const destination = $('#batch-folder').value.trim();
    const result = await api('/api/jobs', {urls:items.map((item) => item.text), options:options(), flat:$('#flat-folder').checked, ...(destination ? {folder:destination} : {})});
    const added = result.jobs.length;
    const skipped = new Set(items.map((item) => item.text)).size - added;
    field.value = '';
    field.dispatchEvent(new Event('input'));
    if (!added) toast(skipped === 1 ? 'That link is already in the queue.' : 'Those links are already in the queue.');
    else toast(`${added === 1 ? 'Added to the queue' : `${added} downloads added to the queue`}${skipped > 0 ? `; ${skipped} already there` : ''}.`);
    await refresh();
  } catch (error) { formError(error.message); }
  finally { setBusy(button, false, 'Download'); }
});

/* Job actions and history cleanup */
async function restore(ids) {
  try { const result = await api('/api/jobs/restore', {ids}); toast(result.count === 1 ? 'Restored.' : `Restored ${result.count} entries.`); await refresh(); }
  catch (error) { toast(error.message, {tone:'error'}); }
}
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const {action, id} = button.dataset;
  const job = state.jobs.find((item) => item.id === id);
  button.disabled = true;
  try {
    if (action === 'diagnostics') { await showDiagnostics(id); return; }
    if (action === 'copy-path') {
      const result = await api(`/api/jobs/${encodeURIComponent(id)}/file-paths`, {indexes:[Number(button.dataset.fileIndex)]});
      await navigator.clipboard.writeText(result.file_paths.join('\n'));
      toast('File path copied.');
      return;
    }
    const result = await api(`/api/jobs/${encodeURIComponent(id)}/${action}`, {});
    if (action === 'remove' && result.count) toast(job?.status === 'completed' ? 'Removed from the list. The file is still on disk.' : 'Removed from the list. Partial files are kept.', {action:'Undo', onAction:() => restore(result.removed_ids)});
    await refresh();
  } catch (error) { toast(error.message, {tone:'error'}); }
  finally { button.disabled = false; }
});
async function bulk(button, run) { button.disabled = true; try { await run(); await refresh(); } catch (error) { toast(error.message, {tone:'error'}); } finally { button.disabled = false; } }
$('#retry-failed').addEventListener('click', (event) => bulk(event.currentTarget, async () => {
  const result = await api('/api/jobs/retry-failed', {});
  toast(result.jobs.length ? `${result.jobs.length === 1 ? 'One download' : `${result.jobs.length} downloads`} queued again${result.skipped ? `; ${result.skipped} didn’t fit in the queue` : ''}.` : 'Nothing to retry. Cancelled downloads only restart individually.');
}));
$('#clear-attention').addEventListener('click', (event) => bulk(event.currentTarget, async () => {
  const result = await api('/api/jobs/clear', {});
  if (result.count) toast(`Cleared ${plural(result.count, 'entry', 'entries')}. Partial files are kept.`, {action:'Undo', onAction:() => restore(result.removed_ids)});
}));
$('#clear-library').addEventListener('click', (event) => bulk(event.currentTarget, async () => {
  const result = await api('/api/jobs/clear', {statuses:['completed']});
  if (result.count) toast(`Cleared ${plural(result.count, 'entry', 'entries')} from the library. Files stay on disk.`, {action:'Undo', onAction:() => restore(result.removed_ids)});
}));
$('#open-folder').addEventListener('click', async () => { try { await api('/api/open-folder', {}); } catch (error) { toast(error.message, {tone:'error'}); } });

let diagnosticJob = null;
async function showDiagnostics(jobId = null) {
  diagnosticJob = jobId;
  setView('settings');
  const report = await api('/api/diagnostics', {job_id:jobId, limit:300});
  const output = $('#diagnostic-output');
  output.textContent = JSON.stringify(report, null, 2);
  output.hidden = false;
  $('#diagnostic-summary').textContent = `${jobId ? `Download ${jobId}: ` : ''}${report.events.length} recent events. Older jobs may predate diagnostic logging.`;
  $('#diagnostic-panel').scrollIntoView({block:'start', behavior:'smooth'});
}
$('#view-diagnostics').addEventListener('click', () => showDiagnostics().catch(error => toast(error.message, {tone:'error'})));
$('#export-diagnostics').addEventListener('click', async () => {
  try {
    const report = await api('/api/diagnostics', {job_id:diagnosticJob, limit:2000});
    const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = `spool-diagnostics-${diagnosticJob || 'recent'}-${new Date().toISOString().slice(0,10)}.json`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    toast('Diagnostic report prepared. Nothing was uploaded.');
  } catch (error) { toast(error.message, {tone:'error'}); }
});
// No form values, cookies or page HTML enter the error report.
let clientErrorCount = 0;
let clientErrorWindow = Date.now();
function reportClientError(error, line = null) {
  if (Date.now()-clientErrorWindow > 60000) { clientErrorCount = 0; clientErrorWindow = Date.now(); }
  if (clientErrorCount++ >= 10) return;
  api('/api/diagnostics/client-error', {message:String(error?.message || error || 'Unknown UI error').slice(0,2000), stack:String(error?.stack || '').slice(0,6000), line, request_id:error?.requestId || null}).catch(() => {});
}
window.addEventListener('error', event => reportClientError(event.error || event.message, event.lineno));
window.addEventListener('unhandledrejection', event => reportClientError(event.reason));
document.addEventListener('error', (event) => { if (event.target.matches?.('img[data-fallback]')) event.target.remove(); }, true);

/* Library controls */
$('#search').addEventListener('input', renderLibrary);
$('#search').addEventListener('keydown', (event) => { if (event.key === 'Escape' && event.target.value) { event.target.value = ''; renderLibrary(); } });
$('#sort').addEventListener('change', renderLibrary);
$$('.segment').forEach((segment) => segment.addEventListener('click', () => {
  kind = segment.dataset.kind;
  $$('.segment').forEach((other) => { other.classList.toggle('active', other === segment); other.setAttribute('aria-pressed', String(other === segment)); });
  renderLibrary();
}));
document.addEventListener('keydown', (event) => {
  if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || isEditable(event.target)) return;
  const target = view === 'library' ? $('#search') : view === 'platforms' ? $('#platform-search') : null;
  if (target) { event.preventDefault(); target.focus(); }
});

/* Settings */
$('#folder-path').addEventListener('input', () => { folderDirty = true; });
$('#folder-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await api('/api/settings', {folder:$('#folder-path').value}); folderDirty = false; toast('Download folder saved. New downloads go there.'); await refresh(); }
  catch (error) { toast(error.message, {tone:'error'}); }
});
function enableNativePicker() { if (window.pywebview?.api?.choose_folder) { $$('#browse-folder,#browse-batch-folder').forEach((button) => { button.disabled = false; button.title = 'Choose a download folder'; }); } }
window.addEventListener('pywebviewready', enableNativePicker);
enableNativePicker();
$('#browse-folder').addEventListener('click', async () => {
  try { const folder = await window.pywebview.api.choose_folder(); if (folder) { $('#folder-path').value = folder; folderDirty = true; $('#folder-path').focus(); } }
  catch (error) { toast(error.message, {tone:'error'}); }
});
$('#browse-batch-folder').addEventListener('click', async () => {
  try { const folder = await window.pywebview.api.choose_folder(); if (folder) $('#batch-folder').value = folder; }
  catch (error) { toast(error.message, {tone:'error'}); }
});

/* Outward drags are separate from dropping source links into the composer. */
document.addEventListener('dragstart', (event) => {
  const handle = event.target.closest('[data-drag-id]');
  if (!handle) return;
  const job = state.jobs.find((item) => item.id === handle.dataset.dragId);
  const index = Number(handle.dataset.fileIndex);
  if (job?.status !== 'completed' || !job.files?.[index]) { event.preventDefault(); return; }
  exportingFiles = true;
  endDrag();
  if (window.pywebview?.api?.drag_files && state.native_drag) {
    event.preventDefault();
    window.pywebview.api.drag_files(job.id, [index]).then((result) => {
      if (!result.started) toast('Keep the mouse button held while dragging.');
    }).catch((error) => toast(error.message, {tone:'error'})).finally(() => { exportingFiles = false; });
    return;
  }
  const separator = job.folder.includes('\\') ? '\\' : '/';
  const path = job.folder.replace(/[\\/]+$/, '') + separator + job.files[index];
  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData('application/x-spool-file', job.id);
  event.dataTransfer.setData('text/plain', path);
  const normalized = path.replace(/\\/g, '/');
  event.dataTransfer.setData('text/uri-list', 'file://' + (normalized.startsWith('/') ? '' : '/') + normalized.split('/').map((part, index) => index === 0 && /^[A-Za-z]:$/.test(part) ? part : encodeURIComponent(part)).join('/'));
});
document.addEventListener('dragend', () => { exportingFiles = false; endDrag(); });
document.addEventListener('click', (event) => {
  if (event.target.closest('.file-drag')) toast(window.pywebview?.api?.drag_files && state.native_drag ? 'Hold and drag this handle into another app or folder.' : 'Use the Windows desktop app to drag the file, or use Copy path here.');
});
$('#cookie-file').addEventListener('change', async () => {
  const file = $('#cookie-file').files[0];
  if (!file) return;
  const body = new FormData();
  body.append('file', file);
  try { await api('/api/cookies', body); toast('Cookies imported. Choose “Imported cookies.txt” under Sign-in when you download.'); await refresh(); }
  catch (error) { toast(error.message, {tone:'error'}); }
  $('#cookie-file').value = '';
});

/* Sources and agents */
async function loadPlatforms() {
  const seq = ++platformSeq;
  try {
    const data = await api('/api/platforms?q=' + encodeURIComponent($('#platform-search').value));
    if (seq !== platformSeq) return;
    $('#platform-count').textContent = `${data.total.toLocaleString()} sites and services your installed engine can read. Search to check a specific one.`;
    if (!$('#featured-platforms').childElementCount) $('#featured-platforms').innerHTML = data.featured.map((platform) => {
      const name = platform.name === 'Twitter' ? 'X / Twitter' : platform.name;
      return `<article class="source"><span class="monogram" aria-hidden="true">${escape(name.charAt(0))}</span><h3>${escape(name)}</h3><span>${escape(platform.domain)}</span><p>${escape(platform.description)}</p></article>`;
    }).join('');
    const more = data.matched > data.results.length ? `<p>Showing ${data.results.length} of ${data.matched.toLocaleString()}. Narrow the search to see the rest.</p>` : '';
    $('#platform-results').innerHTML = data.results.map((platform) => `<div class="extractor${platform.available ? '' : ' is-broken'}"><span>${escape(platform.name)}</span><span>${platform.available ? 'Supported' : 'Marked broken by the engine'}</span></div>`).join('') + more || '<p>No matching sites. The generic extractor may still read direct media links.</p>';
  } catch (error) { if (seq === platformSeq) toast(error.message, {tone:'error'}); }
}
$('#platform-search').addEventListener('input', () => { clearTimeout(platformTimer); platformTimer = setTimeout(loadPlatforms, 220); });
async function loadIntegrations() { try { const data = await api('/api/integrations'); $('#mcp-config').textContent = JSON.stringify(data.mcp, null, 2); } catch (error) { toast(error.message, {tone:'error'}); } }
$$('[data-copy]').forEach((button) => button.addEventListener('click', async () => {
  const source = $(`#${button.dataset.copy}`);
  try { await navigator.clipboard.writeText(source.textContent); toast('Copied to the clipboard.'); }
  catch { const range = document.createRange(); range.selectNodeContents(source); getSelection().removeAllRanges(); getSelection().addRange(range); toast('Selected. Press Ctrl+C to copy.'); }
}));

/* Start */
try {
  const saved = JSON.parse(localStorage.getItem('download-options') || 'null');
  if (saved) {
    for (const key of ['mode', 'quality', 'browser']) if ([...$(`#${key}`).options].some((option) => option.value === saved[key])) $(`#${key}`).value = saved[key];
    for (const key of ['clean', 'subtitles']) if (typeof saved[key] === 'boolean') $(`#${key}`).checked = saved[key];
  }
} catch { /* Ignore corrupt or unavailable browser storage. */ }
updateMode();
updateLinks();
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
(async function poll() { await refresh(); setTimeout(poll, document.hidden ? 5000 : 1200); })();
