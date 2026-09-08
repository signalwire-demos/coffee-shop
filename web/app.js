// Front-end for the demo: guest token from /get_token, then dial the agent.

const els = {
  viz: document.getElementById('viz'),
  decisionFeed: document.getElementById('decisionFeed'),
  status: document.getElementById('status'),
  statusText: document.getElementById('statusText'),
  connect: document.getElementById('connectBtn'),
  hangup: document.getElementById('hangupBtn'),
  hint: document.getElementById('hint'),
  orderList: document.getElementById('orderList'),
  total: document.getElementById('panelTotal'),
  callId: document.getElementById('callId'),
  mute: document.getElementById('muteBtn'),
  muteLabel: document.getElementById('muteLabel'),
  menuBoard: document.getElementById('menuBoard'),
  toolStrip: document.getElementById('toolStrip'),
  boardTitle: document.getElementById('boardTitle'),
  optionHint: document.getElementById('optionHint'),
  ticketStatus: document.getElementById('ticketStatus'),
  ticketFoot: document.getElementById('ticketFoot'),
  ticketCount: document.getElementById('ticketCount'),
  ticketNumber: document.getElementById('ticketNumber'),
  signature: document.getElementById('signature'),
  panelHeading: document.getElementById('panelHeading'),
};

let client = null;
let currentCall = null;
let currentToken = null;
let pollTimer = null;
let remoteMedia = null;
let audioCtx = null;
let meterFrame = null;
let analysers = {};
const voiceEl = document.querySelector('.voice');
let subscriptions = [];
let muted = false;
let lastItemCount = 0;
let placedLogged = false;

function setState(state, text) {
  if (voiceEl) voiceEl.dataset.state = state;
  els.status.dataset.state = ['speaking', 'listening'].includes(state) ? 'live' : state;
  if (text) els.statusText.textContent = text;
}
function setStatus(text) { els.statusText.textContent = text; }

// Lifecycle notes share the decisions feed, muted, so there is one place to
// look rather than two competing logs.
function logEvent(text, kind) {
  if (!els.decisionFeed) return;
  const empty = els.decisionFeed.querySelector('.empty');
  if (empty) empty.remove();
  const li = document.createElement('li');
  li.className = 'dec note';
  const t = new Date().toLocaleTimeString([], { hour12: false });
  li.innerHTML = `<div class="dec-top"><span class="dec-note-text">${text}</span>` +
                 `<span class="dec-time">${t}</span></div>`;
  els.decisionFeed.prepend(li);
  while (els.decisionFeed.children.length > 24) els.decisionFeed.lastChild.remove();
}

function setMuted(on) {
  if (!currentCall) return;
  try {
    if (on && typeof currentCall.audioMute === 'function') currentCall.audioMute();
    else if (!on && typeof currentCall.audioUnmute === 'function') currentCall.audioUnmute();
    else return logEvent('mute not supported by this SDK build', 'error');
    muted = on;
    els.mute.dataset.on = String(on);
    els.muteLabel.textContent = on ? 'Unmute' : 'Mute';
    logEvent(on ? 'microphone muted' : 'microphone live');
  } catch (e) {
    logEvent(`mute failed: ${e.message}`, 'error');
  }
}

// A tiny icon guess so a menu reads like a menu. Purely cosmetic, and it
// degrades to a neutral dot rather than guessing wrong loudly.
const ICONS = [
  [/latte|cappuccino|macchiato|mocha|coffee|espresso|americano|brew/i, '☕'],
  [/tea|chai|matcha/i, '🍵'],
  [/muffin|scone|croissant|pastry|cookie|cake|donut|bagel/i, '🥐'],
  [/juice|soda|lemonade|smoothie|water/i, '🥤'],
  [/pizza/i, '🍕'],
  [/taco|burrito/i, '🌮'],
  [/burger|sandwich|wrap/i, '🍔'],
  [/salad|bowl/i, '🥗'],
  [/ice|cold|frozen/i, '🧊'],
];
function iconFor(name) {
  for (const [re, ch] of ICONS) if (re.test(name)) return ch;
  return '•';
}

function money(n) { return `$${Number(n || 0).toFixed(2)}`; }

// The board mirrors the agent's catalog exactly, including the option values it
// will accept -- so what you see is what it can actually do.
function renderMenu(catalog, options, order) {
  const counts = {};
  for (const line of (order.items || [])) counts[line.sku] = (counts[line.sku] || 0) + (line.qty || 1);

  // Group into sections in first-seen order. Items with no section fall into
  // one unnamed group so a flat catalog still renders.
  const groups = [];
  for (const item of catalog) {
    const key = item.section || '';
    let g = groups.find((x) => x.name === key);
    if (!g) groups.push((g = { name: key, items: [] }));
    g.items.push(item);
  }

  const widest = Math.max(0, ...catalog.map((i) => (i.variants || []).length));
  els.menuBoard.style.setProperty('--cols', widest || 1);

  els.menuBoard.innerHTML = groups.map((g) => {
    // A size header belongs only to a section whose items are priced by size:
    // pastries do not come in small/medium/large.
    const sizes = (g.items.find((i) => (i.variants || []).length) || {}).variants || [];
    const head = g.name
      ? `<li class="menu-section"><span>${g.name}</span>${
          sizes.map((v) => `<span class="col">${v.label}</span>`).join('')}</li>`
      : (sizes.length
          ? `<li class="menu-section"><span></span>${
              sizes.map((v) => `<span class="col">${v.label}</span>`).join('')}</li>`
          : '');

    const rows = g.items.map((item) => {
      const variants = item.variants || [];
      const cells = variants.length
        ? variants.map((v) => `<span class="col price">${Number(v.price).toFixed(2)}</span>`).join('')
        : `<span class="col price single">${Number(item.price).toFixed(2)}</span>`;
      const n = counts[item.sku];
      return `
        <li class="menu-item" data-sku="${item.sku}" data-hit="${order.last_sku === item.sku}">
          <span class="mi-name">
            <span class="mi-icon">${iconFor(item.name)}</span>${item.name}
            ${n ? `<span class="mi-qty">${n}</span>` : ''}
          </span>
          ${cells}
          ${item.description ? `<span class="mi-desc">${item.description}</span>` : ''}
        </li>`;
    }).join('');
    return head + rows;
  }).join('');

  const optNames = Object.keys(options || {});
  els.optionHint.textContent = optNames.length && !widest
    ? optNames.map((k) => `${k}: ${Object.keys(options[k] || {}).join(' / ')}`).join('   ')
    : '';
}

function renderTools(tools) {
  els.toolStrip.innerHTML = (tools || []).map((t) =>
    `<li data-active="${t.active}" title="${(t.description || '').replace(/"/g, '&quot;')}">${t.name}</li>`
  ).join('');
}

let signedName = null;
let myCallId = null;

// Tool calls arrive pushed, not polled: the agent emits swml_user_event the
// moment a handler runs, so the feed is in step with the voice rather than up
// to a second behind it.
const toolTimes = [];

function renderDecision(ev) {
  if (typeof ev.ms === 'number') {
    toolTimes.push(ev.ms);
    const sorted = [...toolTimes].sort((a, b) => a - b);
    const med = sorted[Math.floor(sorted.length / 2)];
    const el = document.getElementById('decMedian');
    if (el) el.textContent = `median ${Math.round(med)}ms`;
  }
  const empty = els.decisionFeed.querySelector('.empty');
  if (empty) empty.remove();
  const li = document.createElement('li');
  li.className = 'dec' + (ev.refused ? ' refused' : '');
  const t = new Date().toLocaleTimeString([], { hour12: false });
  li.innerHTML =
    `<div class="dec-top"><code>${ev.tool}</code>` +
    `<span class="dec-verdict">${ev.refused ? 'refused by code' : 'accepted'}</span>` +
    (ev.ms != null ? `<span class="dec-ms">${Math.round(ev.ms)}ms</span>` : '') +
    `<span class="dec-time">${t}</span></div>` +
    `<div class="dec-said">${(ev.spoken || '').slice(0, 180)}</div>`;
  els.decisionFeed.prepend(li);
  while (els.decisionFeed.children.length > 24) els.decisionFeed.lastChild.remove();

  // A refusal is the interesting beat: it is the software overruling the model.
  if (ev.refused) {
    document.body.classList.add('flash-refusal');
    setTimeout(() => document.body.classList.remove('flash-refusal'), 700);
  }
  // Light the capability chip that just fired.
  const chip = [...els.toolStrip.children].find(c => c.textContent.trim() === ev.tool);
  if (chip) {
    chip.dataset.active = 'true';
    setTimeout(() => { chip.dataset.active = 'false'; }, 2200);
  }
}

function onUserEvent(payload) {
  const ev = (payload && (payload.params || payload)) || {};
  const body = ev.event || ev.data || ev;
  if (!body || body.type !== 'tool') return;
  // Latch this browser onto its own call so any polling stays scoped to it.
  if (body.call_id && myCallId !== body.call_id) myCallId = body.call_id;
  renderDecision(body);
  if (body.order) { renderTicket(body.order); markMenu(body.order); }
}

// The barista writing your name on the cup. Re-rendered only when the name
// actually changes, otherwise every poll would restart the animation.
function renderSignature(name) {
  if (name === signedName) return;
  signedName = name;
  if (!name) { els.signature.innerHTML = ''; return; }
  els.signature.innerHTML =
    `<span class="sig-for">for</span><span class="sig-name">${name}</span>`;
  const pen = els.signature.querySelector('.sig-name');
  if (pen) requestAnimationFrame(() => pen.classList.add('writing'));
  logEvent(`ticket signed for ${name}`, 'tool');
}

function markMenu(order) {
  const counts = {};
  for (const l of (order.items || [])) counts[l.sku] = (counts[l.sku] || 0) + (l.qty || 1);
  for (const row of els.menuBoard.querySelectorAll('.menu-item')) {
    const n = counts[row.dataset.sku];
    row.dataset.hit = String(order.last_sku === row.dataset.sku);
    let badge = row.querySelector('.mi-qty');
    if (n && !badge) {
      badge = document.createElement('span');
      badge.className = 'mi-qty';
      row.querySelector('.mi-name').appendChild(badge);
    }
    if (badge) { badge.textContent = n || ''; badge.style.display = n ? '' : 'none'; }
  }
}

function renderTicket(order) {
  const items = order.items || [];
  renderSignature(order.customer || null);
  els.total.textContent = money(order.total);
  els.ticketStatus.textContent = order.placed ? 'placed' : (items.length ? 'building' : 'empty');
  els.ticketStatus.dataset.state = order.placed ? 'placed' : 'building';

  if (!items.length) {
    els.orderList.innerHTML = '<li class="empty">Nothing yet — the ticket fills in as you talk.</li>';
    els.ticketFoot.hidden = true;
    return;
  }
  els.orderList.innerHTML = items.map((i) => `
    <li>
      <span class="li-main">
        <span><span class="li-qty">${i.qty || 1}</span><span class="item-name">${i.name}</span></span>
        ${i.options ? `<span class="item-meta">${i.options}</span>` : ''}
      </span>
      <span class="item-price">${money(Number(i.price) * (i.qty || 1))}</span>
    </li>`).join('');

  els.ticketFoot.hidden = false;
  els.ticketCount.textContent = `${order.count} item${order.count === 1 ? '' : 's'}`;
  els.ticketNumber.textContent = order.order_number ? `order #${order.order_number}` : '';
}

let lastTicketSig = '';
let lastToolSeen = null;

function startPolling(ms) {
  stopPolling();
  pollTimer = setInterval(refresh, ms || 1000);
  refresh();
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function refresh() {
  try {
    // Never ask for state without a call: the server would have to guess which
    // session we mean, and with two callers it would guess wrong.
    const res = await fetch('/api/state' + (myCallId ? `?call_id=${encodeURIComponent(myCallId)}` : ''));
    if (!res.ok) return;
    const s = await res.json();

    if (s.shop && s.shop.name) {
      els.boardTitle.textContent = 'Menu';
      els.panelHeading.textContent = 'Your order';
    }
    renderMenu(s.catalog || [], s.options || {}, s.order || {});
    renderTools(s.tools);
    renderTicket(s.order || {});

    // Narrate changes rather than re-logging the same state every poll.
    const order = s.order || {};
    const sig = JSON.stringify((order.items || []).map((i) => [i.sku, i.qty, i.options]));
    if (sig !== lastTicketSig && lastTicketSig !== '') {
      logEvent(`ticket: ${order.count} item(s), ${money(order.total)}`, 'tool');
    }
    lastTicketSig = sig;
    if (order.last_tool && order.last_tool !== lastToolSeen) {
      lastToolSeen = order.last_tool;
      logEvent(`tool: ${order.last_tool}`, 'tool');
    }
    if (order.order_number && !placedLogged) {
      placedLogged = true;
      logEvent(`order placed — #${order.order_number}`, 'tool');
    }
  } catch (_) { /* transient */ }
}

async function getToken() {
  const res = await fetch('/get_token');
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || `token request failed (${res.status})`);
  if (!data.token || !data.address) throw new Error('token response missing token/address');
  return data;
}

// isConnected$ replays its current value synchronously on subscribe, so resolve
// via a flag and defer the unsubscribe. Time out rather than hang: bad
// credentials never raise, they just never connect.
function waitForConnection(c, ms = 15000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) { settled = true; reject(new Error('Timed out connecting to SignalWire')); }
    }, ms);
    const sub = c.isConnected$.subscribe({
      next: (connected) => {
        if (connected && !settled) {
          settled = true;
          clearTimeout(timer);
          setTimeout(() => sub.unsubscribe(), 0);
          resolve();
        }
      },
      error: (err) => { if (!settled) { settled = true; clearTimeout(timer); reject(err); } },
    });
  });
}

// v4 has NO rootElement: the app renders remote media itself. Without this the
// call connects and stays silent -- there is simply no audio sink. The SDK
// re-emits the same MediaStream object as tracks arrive, so re-attach whenever
// the track set changes, not only when the stream identity changes.
// The element stays unmuted: it carries the agent's voice, and connect() is
// user-gesture-initiated so autoplay with sound is permitted.
function setupRemoteMedia(activeCall) {
  if (!remoteMedia) {
    remoteMedia = document.createElement('video');
    remoteMedia.id = 'remoteMedia';
    remoteMedia.autoplay = true;
    remoteMedia.playsInline = true;
    remoteMedia.setAttribute('playsinline', '');
    remoteMedia.style.display = 'none';   // audio-only demo: nothing to show
    document.body.appendChild(remoteMedia);
  }

  let lastSignature = '';
  const sub = activeCall.remoteStream$.subscribe((stream) => {
    if (!stream || !remoteMedia) return;
    const signature = stream.getTracks().map((t) => `${t.kind}:${t.id}`).sort().join('|');
    if (remoteMedia.srcObject === stream && signature === lastSignature) return;
    lastSignature = signature;
    console.log('Attaching remote stream, tracks:', signature);
    logEvent(`audio attached (${stream.getAudioTracks().length} track)`);
    remoteMedia.srcObject = stream;
    remoteMedia.play().catch((e) => {
      console.warn('play() blocked:', e);
      els.hint.textContent = 'Your browser blocked audio — click anywhere on the page.';
      document.addEventListener('click', () => remoteMedia.play().catch(() => {}), { once: true });
    });

    // Drive the orb from the agent's own audio, so it reacts to speech.
    attachAnalyser(stream, 'remote');
  });
  subscriptions.push(sub);
}

// The agent's real voice, drawn.
//
// Every "AI voice" site fakes this with a looping animation. This is the actual
// remote audio stream through an AnalyserNode: a radial waveform whose radius
// follows the waveform and whose glow follows loudness. The caller's own mic
// gets a second, dimmer ring, so turn-taking is visible rather than implied.
function attachAnalyser(stream, slot) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx || !stream || !stream.getAudioTracks().length) return;
    audioCtx = audioCtx || new AudioCtx();
    if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.72;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    analysers[slot] = { node: analyser, data: new Uint8Array(analyser.fftSize) };
    if (!meterFrame) drawViz();
  } catch (e) {
    console.warn('analyser unavailable', e);
  }
}

function ringFor(slot) {
  const a = analysers[slot];
  if (!a) return null;
  a.node.getByteTimeDomainData(a.data);
  let peak = 0, sum = 0;
  for (let i = 0; i < a.data.length; i++) {
    const v = Math.abs(a.data[i] - 128) / 128;
    sum += v; if (v > peak) peak = v;
  }
  return { data: a.data, level: sum / a.data.length, peak };
}

function drawViz() {
  const c = els.viz; if (!c) return;
  const ctx = c.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (c.width !== 440 * dpr) { c.width = 440 * dpr; c.height = 440 * dpr; }
  const W = c.width, H = c.height, cx = W / 2, cy = H / 2;
  const css = getComputedStyle(document.documentElement);
  const accent = (css.getPropertyValue('--accent') || '#d08a4e').trim();
  const accent2 = (css.getPropertyValue('--accent-2') || accent).trim();

  const loop = () => {
    ctx.clearRect(0, 0, W, H);
    const agent = ringFor('remote');
    const mine = ringFor('local');

    // caller ring: dimmer, inside
    if (mine) drawRing(ctx, cx, cy, 96 * dpr, mine, accent2, 0.34, 1.6 * dpr);
    // agent ring: the main event
    if (agent) drawRing(ctx, cx, cy, 132 * dpr, agent, accent, 0.95, 2.4 * dpr);

    // Speaking state comes from the audio itself, so it can never disagree
    // with what you are hearing.
    const speaking = agent && agent.level > 0.035;
    const listening = mine && mine.level > 0.045;
    if (voiceEl.dataset.state !== 'idle' && voiceEl.dataset.state !== 'connecting') {
      const next = speaking ? 'speaking' : (listening ? 'listening' : 'live');
      if (voiceEl.dataset.state !== next) {
        voiceEl.dataset.state = next;
        setStatus(next === 'speaking' ? 'Speaking' : next === 'listening' ? 'Listening' : 'Connected');
      }
    }
    meterFrame = requestAnimationFrame(loop);
  };
  loop();
}

function drawRing(ctx, cx, cy, radius, sig, color, alpha, width) {
  const N = 180, step = Math.floor(sig.data.length / N);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = 'round';
  ctx.shadowColor = color;
  ctx.shadowBlur = 14 * sig.level * 12;
  ctx.beginPath();
  for (let i = 0; i <= N; i++) {
    const v = (sig.data[(i % N) * step] - 128) / 128;
    const r = radius + v * radius * 0.30;
    const a = (i / N) * Math.PI * 2 - Math.PI / 2;
    const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.closePath();
  ctx.stroke();
  ctx.restore();
}

async function connect() {
  els.connect.disabled = true;
  setState('connecting', 'Getting token…');
  try {
    // The v4 CDN bundle exposes the client as a CLASS: construct it with `new`.
    // Calling it gives "class constructors must be invoked with 'new'".
    if (!window.SignalWire || typeof window.SignalWire.SignalWire !== 'function') {
      console.error('SignalWire SDK structure:', window.SignalWire);
      throw new Error('SignalWire SDK failed to load');
    }

    const tokenData = await getToken();
    currentToken = tokenData.token;
    const destination = tokenData.address;
    setState('connecting', 'Connecting…');

    // v4 wants a credential provider, not a bare token: authenticate() is
    // called again whenever the SDK needs a fresh one.
    let usedInitial = false;
    client = new window.SignalWire.SignalWire({
      authenticate: async () => {
        if (!usedInitial) { usedInitial = true; return { token: currentToken }; }
        const fresh = await getToken();
        currentToken = fresh.token;
        return { token: fresh.token };
      },
    });

    logEvent('token acquired');
    client.errors$.subscribe((err) => { console.error('SignalWire error:', err); logEvent(String(err && err.message || err), 'error'); });
    client.warnings$.subscribe((w) => console.warn('SignalWire warning:', w && w.code, w && w.message));

    await waitForConnection(client);

    // dial() connects. There is no start() step, and the destination is
    // positional. Video is receive-only so the browser never asks for a camera.
    currentCall = await client.dial(destination, {
      audio: true,
      video: false,
      receiveAudio: true,
      receiveVideo: true,
      userVariables: { interface: 'web-ui', timestamp: new Date().toISOString() },
    });

    // Must happen before we claim to be connected: this is what makes sound.
    setupRemoteMedia(currentCall);

    els.callId.textContent = currentCall && currentCall.id
      ? `call ${String(currentCall.id).slice(0, 8)}` : '';
    els.connect.hidden = true;
    els.hangup.hidden = false;
    els.mute.hidden = false;
    els.mute.dataset.on = 'false';
    // A fresh call shows a fresh ticket: never inherit the previous caller's.
    lastTicketSig = ''; lastToolSeen = null; placedLogged = false;
    renderTicket({ items: [], total: 0, count: 0 });
    els.hint.textContent = 'You are connected — just start talking.';
    logEvent('call connected', 'tool');
    setState('live', 'Connected');
    // Push carries the updates; this is only a safety net in case an
    // event is dropped, so it stays slow.
    startPolling(5000);

    // The agent pushes every tool call here.
    try {
      const sub = currentCall.subscribe('user_event');
      subscriptions.push(sub.subscribe(onUserEvent));
      logEvent('listening for agent events');
    } catch (e) {
      console.warn('user_event unavailable, falling back to polling', e);
      startPolling(900);
    }
    // The caller's own audio, for the inner ring and the listening state.
    try {
      if (currentCall.localStream$) {
        subscriptions.push(currentCall.localStream$.subscribe(
          (st) => st && attachAnalyser(st, 'local')));
      }
    } catch (_) {}

    if (currentCall && typeof currentCall.on === 'function') {
      currentCall.on('destroy', () => hangup(true));
    }
  } catch (err) {
    console.error(err);
    setState('error', err.message || 'Could not connect');
    els.hint.textContent = 'Check the browser console, and that SIGNALWIRE_* credentials are set on the server.';
  } finally {
    els.connect.disabled = false;
  }
}

async function hangup(remote) {
  startPolling(4000);
  subscriptions.forEach((s) => { try { s.unsubscribe(); } catch (_) {} });
  subscriptions = [];
  if (meterFrame) { cancelAnimationFrame(meterFrame); meterFrame = null; }
  if (audioCtx) { try { audioCtx.close(); } catch (_) {} audioCtx = null; }
  if (remoteMedia) {
    if (remoteMedia.srcObject) {
      remoteMedia.srcObject.getTracks().forEach((t) => t.stop());
      remoteMedia.srcObject = null;
    }
    remoteMedia.remove();
    remoteMedia = null;
  }
  try { if (currentCall && !remote) await currentCall.hangup(); } catch (_) {}
  try { if (client) await client.disconnect(); } catch (_) {}
  client = null; currentCall = null;
  els.hangup.hidden = true;
  els.mute.hidden = true;
  els.connect.hidden = false;
  muted = false; lastItemCount = 0; placedLogged = false;
  logEvent('call ended');
  els.callId.textContent = '';
  myCallId = null;
  renderTicket({ items: [], total: 0, count: 0 });
  els.hint.textContent = 'Click Start call and talk to the agent in your browser.';
  setState('idle', 'Ready to talk');
}

els.connect.addEventListener('click', connect);
els.hangup.addEventListener('click', () => hangup(false));
els.mute.addEventListener('click', () => setMuted(!muted));

// Render the shop immediately: the menu and the agent's capabilities are worth
// seeing before anyone picks up the phone. Polling speeds up during a call.
refresh();
startPolling(4000);
