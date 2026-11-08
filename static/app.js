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
  function ask({ title, text, ok = 'OK', input, danger }) {
    const dlg = $('dlg'), field = $('dlg-input');
    $('dlg-title').textContent = title;
    $('dlg-text').textContent = text || '';
    $('dlg-ok').textContent = ok;
    $('dlg-ok').className = 'btn ' + (danger ? 'danger' : 'primary');
    field.classList.toggle('hidden', input == null);
    if (input != null) field.value = input;
    return new Promise((resolve) => {
      dlg.addEventListener('close', () => {
        resolve(dlg.returnValue === 'ok' ? (input != null ? field.value : true) : false);
      }, { once: true });
      dlg.returnValue = 'cancel';
      dlg.showModal();
      if (input != null) { field.focus(); field.select(); }
    });
  }

  // -------------------------------------------------------------------- API
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
          onclick: () => { location.hash = '#/' + s.id; },
        },
        h('b', {}, s.name),
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
    $('queue').replaceChildren();
    $('filter').value = '';
    try {
      const [status, systems, roms] = await Promise.all(
        [api('/api/status'), api('/api/systems'), api('/api/roms/' + enc(id))]);
      renderDisk(status);
      current = systems.find((s) => s.id === id);
      if (!current) { location.hash = '#/'; return; }
      $('roms-title').textContent = current.name;
      $('accepted').textContent = current.configured
        ? 'Extensões aceitas: ' + current.extensions.join(' ')
        : 'Este sistema não tem extensões em systems.json, então o envio está desativado.';
      $('file').disabled = !current.configured;
      $('file').accept = current.extensions.join(',');
      items = roms;
      renderRoms();
    } catch (err) {
      if (err.status === 404) { location.hash = '#/'; return; }
      if (err.status !== 401 && err.status !== 429) toast(err.message, true);
    }
  }

  function renderRoms() {
    const q = $('filter').value.trim().toLowerCase();
    const shown = items.filter((r) => r.name.toLowerCase().includes(q));
    const empty = $('roms-empty');
    empty.classList.toggle('hidden', shown.length > 0);
    empty.textContent = items.length
      ? 'Nenhuma ROM com esse nome.'
      : 'Nenhuma ROM aqui ainda. Toque em "Enviar ROMs" para começar.';
    $('count').textContent = items.length
      ? `${plural(shown.length, 'ROM', 'ROMs')}${q ? ` de ${items.length}` : ''}`
      : '';
    $('roms-list').replaceChildren(...shown.map((r) =>
      h('li', {},
        h('div', {},
          h('div', { class: 'name' }, r.name),
          h('div', { class: 'meta' }, `${fmtSize(r.size)} · ${fmtDate(r.mtime)}`)),
        h('div', { class: 'actions' },
          h('button', { class: 'btn small', type: 'button', onclick: () => renameRom(r) }, 'Renomear'),
          h('button', { class: 'btn small danger', type: 'button', onclick: () => deleteRom(r) }, 'Apagar')))));
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

  $('filter').addEventListener('input', renderRoms);

  // ----------------------------------------------------------------- upload
  // Envia o arquivo cru por XHR (progresso real). O servidor grava em blocos de 1 MB.
  function sendFile(file, overwrite, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/roms/${enc(current.id)}?name=${enc(file.name)}${overwrite ? '&overwrite=1' : ''}`);
      xhr.setRequestHeader('X-Admin-PIN', pin);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      xhr.onerror = () => reject(new ApiError('Conexão perdida durante o envio', 0));
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* sem corpo */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new ApiError((data && data.error) || `Erro ${xhr.status}`, xhr.status));
      };
      xhr.send(file);
    });
  }

  async function uploadOne(file, system) {
    const state = h('div', { class: 'state muted' }, 'Verificando…');
    const fill = h('div');
    const li = h('li', {}, h('div', { class: 'name' }, file.name), state, h('div', { class: 'bar' }, fill));
    $('queue').prepend(li);
    const fail = (msg) => { state.textContent = msg; state.className = 'state err'; li.querySelector('.bar').remove(); };

    try {
      // Pré-checagem: nome, extensão, tamanho e espaço, antes de gastar banda.
      const chk = await api(`/api/check/${enc(system)}?name=${enc(file.name)}&size=${file.size}`);
      let overwrite = false;
      if (chk.exists) {
        overwrite = await ask({
          title: 'Sobrescrever?', text: `"${chk.name}" já existe. Substituir pelo arquivo enviado?`,
          ok: 'Sobrescrever', danger: true,
        });
        if (!overwrite) { fail('Cancelado: o arquivo já existe'); return; }
      }
      state.textContent = '0%';
      await sendFile(file, overwrite, (p) => {
        fill.style.width = Math.round(p * 100) + '%';
        state.textContent = Math.round(p * 100) + '% · ' + fmtSize(file.size);
      });
      fill.style.width = '100%';
      state.textContent = 'Enviado · ' + fmtSize(file.size);
      state.className = 'state done';
    } catch (err) {
      fail(err.message);
    }
  }

  $('file').addEventListener('change', async (ev) => {
    const files = [...ev.target.files];
    ev.target.value = '';
    const system = current.id;
    for (const f of files) await uploadOne(f, system);   // um por vez: o Pi agradece
    if (current && current.id === system) {
      try { await refreshRoms(); } catch (_) { /* tela já mudou */ }
    }
  });

  // ------------------------------------------------------------------ rotas
  function route() {
    if (!pin) { showLogin(); return; }
    const id = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
    if (id) loadRoms(id); else loadSystems();
  }
  window.addEventListener('hashchange', route);
  $('back').addEventListener('click', () => { location.hash = '#/'; });

  // ------------------------------------------------------------------- tema
  // Claro ou escuro. Sem escolha salva, segue o sistema. A escolha vale também para o controle.
  const root = document.documentElement;
  const isDark = () => root.dataset.theme
    ? root.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  function paintThemeButton() {
    $('theme').textContent = isDark() ? '☾' : '☀';
    $('theme').title = isDark() ? 'Modo escuro (toque para o claro)' : 'Modo claro (toque para o escuro)';
  }
  const saved = store.get('localStorage', 'rp_theme');
  if (saved) root.dataset.theme = saved;
  paintThemeButton();
  $('theme').addEventListener('click', () => {
    root.dataset.theme = isDark() ? 'light' : 'dark';
    store.set('localStorage', 'rp_theme', root.dataset.theme);
    paintThemeButton();
  });

  route();
})();
