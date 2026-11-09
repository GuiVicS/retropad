/* Gerenciador de ROMs do RetroPad. JavaScript puro, sem dependências. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const enc = encodeURIComponent;

  // ------------------------------------------------------------- utilidades
  const store = {
    get(area, key) { try { return window[area].getItem(key) || ''; } catch (_) { return ''; } },
    set(area, key, val) { try { window[area].setItem(key, val); } catch (_) { /* modo privado */ } },
    del(area, key) { try { window[area].removeItem(key); } catch (_) { /* idem */ } },
  };

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid);
    return el;
  }

  // Ícones Lucide (sprite local em /static/lucide.svg, funciona offline)
  function icon(name) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'i'); svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(NS, 'use');
    use.setAttribute('href', '/static/lucide.svg#' + name);
    svg.append(use);
    return svg;
  }

  function fmtSize(n) {
    if (n < 1024) return `${n} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < units.length - 1);
    return `${n.toFixed(n >= 100 ? 0 : 1)} ${units[i]}`;
  }
  const fmtDate = (t) => new Date(t * 1000).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function toast(text, isError) {
    const el = h('div', { class: isError ? 'err' : '' }, text);
    $('toast').append(el);
    setTimeout(() => el.remove(), isError ? 6000 : 3000);
  }

  // Diálogo reutilizável: resolve com true/false (ou com o texto, se houver campo).
  // Com `checkbox`, mostra uma caixa de marcação e resolve com { yes, checked }.
  function ask({ title, text, ok = 'OK', input, danger, checkbox }) {
    const dlg = $('dlg'), field = $('dlg-input');
    $('dlg-title').textContent = title;
    $('dlg-text').textContent = text || '';
    $('dlg-ok').textContent = ok;
    $('dlg-ok').className = 'btn ' + (danger ? 'danger' : 'primary');
    field.classList.toggle('hidden', input == null);
    if (input != null) field.value = input;
    $('dlg-check-wrap').classList.toggle('hidden', !checkbox);
    $('dlg-check').checked = false;
    if (checkbox) $('dlg-check-text').textContent = checkbox;
    return new Promise((resolve) => {
      dlg.addEventListener('close', () => {
        const yes = dlg.returnValue === 'ok';
        if (checkbox) resolve({ yes, checked: $('dlg-check').checked });
        else resolve(yes ? (input != null ? field.value : true) : false);
      }, { once: true });
      dlg.returnValue = 'cancel';
      dlg.showModal();
      if (input != null) { field.focus(); field.select(); }
    });
  }

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }
  let pin = store.get('sessionStorage', 'rp_pin');

  async function api(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, { ...opts, headers: { ...(opts.headers || {}), 'X-Admin-PIN': pin } });
    } catch (_) {
      throw new ApiError('Sem conexão com o RetroPad', 0);
    }
    let data = null;
    try { data = await res.json(); } catch (_) { /* sem corpo */ }
    if (res.status === 401 || res.status === 429) { showLogin(data && data.error); }
    if (!res.ok) throw new ApiError((data && data.error) || `Erro ${res.status}`, res.status);
    return data;
  }

  // ------------------------------------------------------------------ telas
  const views = ['login', 'systems', 'roms'];
  function show(name) { for (const v of views) $(v).classList.toggle('hidden', v !== name); }

  function showLogin(message) {
    pin = '';
    store.del('sessionStorage', 'rp_pin');
    $('login-msg').textContent = message || '';
    show('login');
    $('pin').value = '';
    $('pin').focus();
  }

  $('login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    pin = $('pin').value.trim();
    $('login-msg').textContent = '';
    try {
      await api('/api/status');
      store.set('sessionStorage', 'rp_pin', pin);
      route();
    } catch (err) {
      if (err.status !== 401 && err.status !== 429) $('login-msg').textContent = err.message;
    }
  });

  let disk = null;
  function renderDisk(status) {
    disk = status;
    const { free, total } = status.disk;
    const usedPct = Math.round(((total - free) / total) * 100);
    $('disk-text').textContent = `${fmtSize(free)} livres de ${fmtSize(total)}`;
    $('disk-bar').style.width = usedPct + '%';
    $('disk-bar').parentElement.classList.toggle('low', free < status.min_free * 2);
    const tun = $('tunnel');
    tun.classList.toggle('hidden', !status.tunnel_url);
    tun.textContent = status.tunnel_url ? 'Túnel ngrok: ' + status.tunnel_url : '';
    $('disk-mini').textContent = `${fmtSize(free)} livres · limite ${fmtSize(status.max_upload)} por arquivo`;
  }

  async function loadSystems() {
    show('systems');
    const list = $('systems-list');
    list.replaceChildren(h('p', { class: 'muted' }, 'Carregando…'));
    try {
      const [status, systems] = await Promise.all([api('/api/status'), api('/api/systems')]);
      renderDisk(status);
      if (!systems.length) {
        list.replaceChildren(h('p', { class: 'empty' },
          `Nenhuma pasta de sistema encontrada em ${status.roms_dir}.`));
        return;
      }
      list.replaceChildren(...systems.map((s) =>
        h('button', {
          class: 'sys' + (s.configured ? '' : ' unconfigured'), type: 'button',
          onclick: () => go('/roms/' + enc(s.id)),
        },
        h('b', {}, icon('gamepad-2'), ' ', s.name),
        h('span', { class: 'muted' }, s.configured
          ? `${plural(s.count, 'arquivo', 'arquivos')} · ${fmtSize(s.size)}`
          : 'sem extensões em systems.json'))));
    } catch (err) {
      if (err.status !== 401 && err.status !== 429) list.replaceChildren(h('p', { class: 'empty' }, err.message));
    }
  }

  // ----------------------------------------------------------- ROMs/sistema
  let current = null;   // { id, name, extensions }
  let items = [];

  async function loadRoms(id) {
    show('roms');
    $('roms-title').textContent = id;
    $('filter').value = '';
    try {
      const [status, systems, roms] = await Promise.all(
        [api('/api/status'), api('/api/systems'), api('/api/roms/' + enc(id))]);
      renderDisk(status);
      current = systems.find((s) => s.id === id);
      if (!current) { go('/roms', true); return; }
      $('roms-title').textContent = current.name;
      $('accepted').textContent = current.configured
        ? 'Extensões aceitas: ' + current.extensions.join(' ')
        : 'Este sistema não tem extensões em systems.json, então o envio está desativado.';
      for (const id of ['file', 'folder']) $(id).disabled = !current.configured;
      $('file').accept = current.extensions.join(',');
      $('drop').classList.toggle('disabled', !current.configured);
      limit = PAGE;
      items = roms;
      renderRoms();
    } catch (err) {
      if (err.status === 404) { go('/roms', true); return; }
      if (err.status !== 401 && err.status !== 429) toast(err.message, true);
    }
  }

  const PAGE = 300;          // quantas linhas desenhar por vez (listas de milhares de ROMs continuam leves)
  let limit = PAGE;
  const extOf = (name) => { const i = name.lastIndexOf('.'); return i > 0 ? name.slice(i + 1).toUpperCase() : ''; };

  function renderRoms() {
    const q = $('filter').value.trim().toLowerCase();
    const shown = items.filter((r) => r.name.toLowerCase().includes(q));
    const empty = $('roms-empty');
    empty.classList.toggle('hidden', shown.length > 0);
    empty.textContent = items.length
      ? 'Nenhuma ROM com esse nome.'
      : 'Nenhuma ROM aqui ainda. Arraste os jogos para a área acima.';
    const total = shown.reduce((n, r) => n + r.size, 0);
    $('count').textContent = items.length
      ? `${plural(shown.length, 'ROM', 'ROMs')}${q ? ` de ${items.length}` : ''} · ${fmtSize(total)}`
      : '';
    const rows = shown.slice(0, limit).map((r) =>
      h('li', {},
        h('div', { class: 'rom-ico' }, icon('file'), h('span', {}, extOf(r.name))),
        h('div', { class: 'rom-main' },
          h('div', { class: 'name' }, r.name),
          h('div', { class: 'meta' }, `${fmtSize(r.size)} · ${fmtDate(r.mtime)}`)),
        h('div', { class: 'actions' },
          h('button', { class: 'btn small', type: 'button', onclick: () => renameRom(r) }, icon('pencil'), h('span', {}, 'Renomear')),
          h('button', { class: 'btn small danger', type: 'button', onclick: () => deleteRom(r) }, icon('trash-2'), h('span', {}, 'Apagar')))));
    if (shown.length > limit) {
      rows.push(h('li', { class: 'more' },
        h('button', { class: 'btn', type: 'button', onclick: () => { limit += PAGE; renderRoms(); } },
          `Mostrar mais ${Math.min(PAGE, shown.length - limit)} de ${shown.length - limit} restantes`)));
    }
    $('roms-list').replaceChildren(...rows);
  }

  async function refreshRoms() {
    items = await api('/api/roms/' + enc(current.id));
    renderRoms();
    renderDisk(await api('/api/status'));
  }

  async function deleteRom(r) {
    const yes = await ask({
      title: 'Apagar ROM?', text: `"${r.name}" será removida do cartão. Isso não pode ser desfeito.`,
      ok: 'Apagar', danger: true,
    });
    if (!yes) return;
    try {
      await api(`/api/roms/${enc(current.id)}/${enc(r.name)}`, { method: 'DELETE' });
      toast('ROM apagada');
      await refreshRoms();
    } catch (err) { toast(err.message, true); }
  }

  async function renameRom(r) {
    const name = await ask({ title: 'Renomear ROM', text: 'Mantenha a extensão do arquivo.', input: r.name, ok: 'Renomear' });
    if (!name || name === r.name) return;
    try {
      await api(`/api/roms/${enc(current.id)}/${enc(r.name)}/rename`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
      });
      toast('ROM renomeada');
      await refreshRoms();
    } catch (err) { toast(err.message, true); }
  }

  $('filter').addEventListener('input', () => { limit = PAGE; renderRoms(); });

  // ----------------------------------------------------------------- envio
  // Uma fila só para a remessa inteira (arquivos, pastas, arrastar e soltar). Ela guarda números, não
  // elementos: 1000 jogos continuam leves. Envia um arquivo por vez (o cartão SD agradece) e mostra
  // o progresso total em cima ("533/1000") e o do arquivo atual embaixo.
  const U = {
    items: [], next: 0, total: 0, done: 0, ok: 0, skipped: 0, failed: [],
    bytesTotal: 0, bytesDone: 0, curBytes: 0, curPct: 0, cur: null,
    running: false, cancelled: false, xhr: null, system: null, policy: null, started: 0, finished: false,
  };
  const fmtTime = (sec) => {
    if (!isFinite(sec) || sec < 0) return '';
    if (sec < 60) return `${Math.ceil(sec)} s`;
    const m = Math.floor(sec / 60);
    return m < 60 ? `${m} min ${Math.round(sec % 60)} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };
  const accepted = (name) => current.extensions.some((e) => name.toLowerCase().endsWith(e.toLowerCase()));

  // Envia o arquivo cru por XHR (progresso real). O servidor grava em blocos de 1 MB.
  function sendFile(file, overwrite, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      U.xhr = xhr;
      xhr.open('POST', `/api/roms/${enc(U.system)}?name=${enc(file.name)}${overwrite ? '&overwrite=1' : ''}`);
      xhr.setRequestHeader('X-Admin-PIN', pin);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
      xhr.onerror = () => reject(new ApiError('Conexão perdida durante o envio', 0));
      xhr.onabort = () => reject(new ApiError('Cancelado', 0));
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* sem corpo */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new ApiError((data && data.error) || `Erro ${xhr.status}`, xhr.status));
      };
      xhr.send(file);
    });
  }

  let paintQueued = false;
  function paint() { if (!paintQueued) { paintQueued = true; requestAnimationFrame(() => { paintQueued = false; paintNow(); }); } }
  function paintNow() {
    const total = U.total;
    if (!total) { $('uploader').classList.add('hidden'); return; }
    $('uploader').classList.remove('hidden');
    const frac = total ? Math.min(1, (U.done + (U.cur ? U.curPct : 0)) / total) : 0;
    $('upCount').textContent = `${U.done}/${total}`;
    $('upLabel').textContent = U.finished ? (U.cancelled ? 'cancelado' : 'concluído') : 'processados';
    $('upBar').style.width = (frac * 100).toFixed(1) + '%';
    $('upBar').parentElement.setAttribute('aria-valuenow', String(Math.round(frac * 100)));
    $('upBar').parentElement.classList.toggle('finished', U.finished && !U.failed.length);
    const sent = U.bytesDone + U.curBytes, secs = (performance.now() - U.started) / 1000;
    $('upBytes').textContent = `${fmtSize(sent)} de ${fmtSize(U.bytesTotal)}`;
    $('upSpeed').textContent = !U.finished && secs > 1 && sent ? `${fmtSize(sent / secs)}/s` : '';
    $('upEta').textContent = !U.finished && secs > 2 && frac > 0.01 ? `faltam ~${fmtTime(secs * (1 - frac) / frac)}` : '';
    const chip = (id, n, text) => { $(id).classList.toggle('hidden', !n); $(id).textContent = text; };
    chip('upOk', U.ok, `${U.ok} enviados`);
    chip('upSkip', U.skipped, `${U.skipped} ignorados`);
    chip('upErr', U.failed.length, `${U.failed.length} falhas`);
    $('upNow').classList.toggle('hidden', !U.cur);
    if (U.cur) {
      $('upName').textContent = U.cur.file.name;
      $('upItemBar').style.width = (U.curPct * 100).toFixed(1) + '%';
      $('upState').textContent = U.curState || '';
    }
    $('upFails').classList.toggle('hidden', !U.failed.length);
    if (U.failed.length && paintedFails !== U.failed.length) {
      paintedFails = U.failed.length;
      $('upFailTitle').textContent = `Falhas (${U.failed.length})`;
      $('upFailList').replaceChildren(...U.failed.slice(0, 100).map((f) => h('li', {}, h('b', {}, f.file.name), h('span', { class: 'muted' }, ' — ' + f.error))),
        ...(U.failed.length > 100 ? [h('li', { class: 'muted' }, `…e mais ${U.failed.length - 100}`)] : []));
    }
    $('upCancel').classList.toggle('hidden', U.finished);
    $('upClose').classList.toggle('hidden', !U.finished);
  }
  let paintedFails = -1;
  // As últimas linhas entram uma a uma (sem recriar as que já estão na tela), senão os ícones piscam.
  function note(cls, icn, text) {
    const list = $('upRecent');
    list.prepend(h('li', { class: cls }, icon(icn), h('span', {}, text)));
    while (list.children.length > 4) list.lastChild.remove();
  }

  async function processOne(item) {
    const file = item.file;
    U.cur = item; U.curPct = 0; U.curBytes = 0; U.curState = 'Verificando…'; paint();
    try {
      // Pré-checagem: nome, extensão, tamanho e espaço, antes de gastar banda.
      const chk = await api(`/api/check/${enc(U.system)}?name=${enc(file.name)}&size=${file.size}`);
      let overwrite = false;
      if (chk.exists) {
        if (U.policy === null) {
          const r = await ask({
            title: 'Sobrescrever?', text: `"${chk.name}" já existe. Substituir pelo arquivo enviado?`,
            ok: 'Sobrescrever', danger: true, checkbox: 'Fazer o mesmo com todos os arquivos repetidos desta remessa',
          });
          overwrite = r.yes;
          if (r.checked) U.policy = r.yes;
        } else overwrite = U.policy;
        if (!overwrite) { U.skipped++; U.bytesTotal -= file.size; note('skip', 'circle-alert', `${file.name} já existe (mantido)`); return; }
      }
      U.curState = '0%';
      await sendFile(file, overwrite, (loaded, tot) => {
        U.curPct = loaded / tot; U.curBytes = loaded;
        U.curState = `${Math.round(U.curPct * 100)}% · ${fmtSize(loaded)} de ${fmtSize(tot)}`; paint();
      });
      U.bytesDone += file.size; U.ok++;
      note('ok', 'circle-check', file.name);
    } catch (err) {
      if (U.cancelled) return;
      U.failed.push({ file, error: err.message }); U.bytesTotal -= file.size;
      note('err', 'circle-alert', `${file.name}: ${err.message}`);
    } finally {
      U.done++; U.cur = null; U.curBytes = 0; paint();
    }
  }

  async function runQueue() {
    if (U.running) return;
    U.running = true; U.finished = false;
    while (U.next < U.items.length && !U.cancelled) { await processOne(U.items[U.next++]); }
    U.running = false; U.finished = true; U.cur = null;
    if (U.cancelled) { const left = U.items.length - U.next; U.skipped += left; U.done += left; }
    paintNow();
    toast(U.cancelled ? 'Envio cancelado' : (U.failed.length ? `Envio terminou com ${U.failed.length} falhas` : `${U.ok} ROMs enviadas`), !!U.failed.length && !U.cancelled);
    if (current && current.id === U.system) { try { await refreshRoms(); } catch (_) { /* tela já mudou */ } }
  }

  // Coloca arquivos na fila. Se já houver um envio em andamento, eles entram no fim da mesma fila.
  function enqueue(files) {
    if (!current || !current.configured || !files.length) return;
    if (!U.running) {
      $('upRecent').replaceChildren(); paintedFails = -1;
      Object.assign(U, { items: [], next: 0, total: 0, done: 0, ok: 0, skipped: 0, failed: [], bytesTotal: 0, bytesDone: 0,
        curBytes: 0, curPct: 0, cur: null, cancelled: false, policy: null, finished: false, system: current.id, started: performance.now() });
    } else if (U.system !== current.id) { toast('Espere o envio atual terminar para trocar de sistema', true); return; }
    let ignored = 0;
    for (const file of files) {
      if (file.name.startsWith('.') || !accepted(file.name)) { ignored++; continue; }   // arquivos ocultos e de outros tipos
      U.items.push({ file }); U.bytesTotal += file.size;
    }
    // Os ignorados contam como processados, para a barra chegar a 100%.
    U.total += files.length; U.skipped += ignored; U.done += ignored;
    if (!U.total) return;
    paint(); runQueue();
  }

  $('upCancel').addEventListener('click', () => { U.cancelled = true; if (U.xhr) U.xhr.abort(); });
  $('upClose').addEventListener('click', () => { U.items = []; U.total = 0; U.done = 0; paintNow(); });
  $('upRetry').addEventListener('click', () => {
    const again = U.failed.map((f) => f.file); U.failed = [];
    U.items = []; U.next = 0; U.total = 0; U.done = 0; U.ok = 0; U.skipped = 0; U.bytesTotal = 0; U.bytesDone = 0; U.started = performance.now();
    enqueue(again);
  });
  window.addEventListener('beforeunload', (e) => { if (U.running) { e.preventDefault(); e.returnValue = ''; } });

  $('file').addEventListener('change', (ev) => { const files = [...ev.target.files]; ev.target.value = ''; enqueue(files); });
  $('folder').addEventListener('change', (ev) => { const files = [...ev.target.files]; ev.target.value = ''; enqueue(files); });

  // Arrastar e soltar (arquivos e pastas, em qualquer lugar da página de um sistema)
  async function filesFromDrop(dt) {
    const entries = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
    if (!entries.length) return [...dt.files];
    const out = [];
    const walk = async (entry) => {
      if (entry.isFile) out.push(await new Promise((res, rej) => entry.file(res, rej)));
      else if (entry.isDirectory) {
        const reader = entry.createReader();
        let batch;
        do {
          batch = await new Promise((res, rej) => reader.readEntries(res, rej));
          for (const e of batch) await walk(e);
        } while (batch.length);
      }
    };
    for (const e of entries) await walk(e);
    return out;
  }
  let dragDepth = 0;
  const canDrop = (e) => !$('roms').classList.contains('hidden') && current && current.configured && e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files');
  window.addEventListener('dragenter', (e) => { if (!canDrop(e)) return; e.preventDefault(); dragDepth++; $('dropveil').classList.remove('hidden'); });
  window.addEventListener('dragover', (e) => { if (canDrop(e)) e.preventDefault(); });
  window.addEventListener('dragleave', (e) => { if (!canDrop(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('dropveil').classList.add('hidden'); });
  window.addEventListener('drop', async (e) => {
    if (!canDrop(e)) return;
    e.preventDefault(); dragDepth = 0; $('dropveil').classList.add('hidden');
    enqueue(await filesFromDrop(e.dataTransfer));
  });

  // ------------------------------------------------------------------ rotas
  // /roms lista os sistemas e /roms/<sistema> abre um deles. /admin continua valendo como apelido.
  function go(path, replace) {
    if (location.pathname !== path) history[replace ? 'replaceState' : 'pushState']({}, '', path);
    route();
  }
  function route() {
    if (!pin) { showLogin(); return; }
    const m = location.pathname.match(/^\/roms\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : '';
    if (id) loadRoms(id); else loadSystems();
  }
  window.addEventListener('popstate', route);
  $('back').addEventListener('click', (e) => { e.preventDefault(); go('/roms'); });

  // ------------------------------------------------------------------- tema
  // Claro ou escuro. Sem escolha salva, segue o sistema. A escolha vale também para o controle.
  const root = document.documentElement;
  const isDark = () => root.dataset.theme
    ? root.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  function paintThemeButton() {
    $('theme').replaceChildren(icon(isDark() ? 'moon' : 'sun'));
    $('theme').title = isDark() ? 'Modo escuro (toque para o claro)' : 'Modo claro (toque para o escuro)';
  }
  // O tema fica salvo no IndexedDB (settings.js), o mesmo do controle.
  paintThemeButton();
  RPConfig.load().then(paintThemeButton);
  $('theme').addEventListener('click', async () => {
    await RPConfig.set('theme', isDark() ? 'light' : 'dark');
    paintThemeButton();
  });

  route();
})();
