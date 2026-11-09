/* Configurações do RetroPad, guardadas no IndexedDB deste aparelho.
 *
 * Usado pelo controle (index.html) e pelo gerenciador (admin). API:
 *   await RPConfig.load()        lê tudo do IndexedDB (chamar uma vez ao abrir a página)
 *   RPConfig.get('tema')         valor atual (síncrono, vem da memória)
 *   RPConfig.set('tema', 'dark') muda e grava (devolve uma Promise)
 *   await RPConfig.clear()       apaga o IndexedDB e volta aos padrões
 *   RPConfig.applyTheme()        aplica o tema salvo na página
 *
 * Se o navegador não tiver IndexedDB (ou estiver em modo privado que o bloqueia), as
 * preferências ficam só na memória da página e nada quebra.
 */
(() => {
  'use strict';
  const DB_NAME = 'retropad', STORE = 'config', DB_VERSION = 1;
  const DEFAULTS = {
    theme: 'auto',        // auto | light | dark
    mode: 'gamepad',      // gamepad | mouse | screen
    player: 1,            // último jogador usado no gamepad
    stream: false,        // mostrar a tela do sistema ao entrar
    vibrate: true,        // vibrar ao tocar nos botões (Android)
    sensitivity: 1.7,     // velocidade do cursor do mouse
  };
  const VALID = {
    theme: (v) => ['auto', 'light', 'dark'].includes(v),
    mode: (v) => ['gamepad', 'mouse', 'screen'].includes(v),
    player: (v) => v === 1 || v === 2,
    stream: (v) => typeof v === 'boolean',
    vibrate: (v) => typeof v === 'boolean',
    sensitivity: (v) => typeof v === 'number' && v >= 0.5 && v <= 4,
  };
  // Chaves antigas do localStorage (versões anteriores) e a cópia do tema que o script
  // do <head> lê antes da página pintar, para não piscar no tema errado.
  const LEGACY = ['rp_mode', 'rp_stream', 'rp_theme', 'rp_system'];

  let cache = Object.assign({}, DEFAULTS);
  let db = null;

  const ls = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* privado */ } },
    del(k) { try { localStorage.removeItem(k); } catch (_) { /* idem */ } },
  };

  function openDb() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error('IndexedDB indisponível')); return; }
      let req;
      try { req = indexedDB.open(DB_NAME, DB_VERSION); } catch (err) { reject(err); return; }
      req.onupgradeneeded = () => { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE); };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error('IndexedDB bloqueado'));
    });
  }

  function readAll(database) {
    return new Promise((resolve, reject) => {
      const out = {};
      const req = database.transaction(STORE, 'readonly').objectStore(STORE).openCursor();
      req.onsuccess = () => {
        const cur = req.result;
        if (cur) { out[cur.key] = cur.value; cur.continue(); } else resolve(out);
      };
      req.onerror = () => reject(req.error);
    });
  }

  function writeKey(key, value) {
    if (!db) return Promise.resolve();
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(value, key);
        tx.oncomplete = () => resolve();
        tx.onerror = tx.onabort = () => resolve();     // falhar ao gravar não pode quebrar o app
      } catch (_) { resolve(); }
    });
  }

  function accept(values) {
    for (const key of Object.keys(DEFAULTS)) {
      if (key in values && VALID[key](values[key])) cache[key] = values[key];
    }
  }

  // Traz para o IndexedDB o que versões anteriores guardavam no localStorage.
  function migrateLegacy() {
    const old = {};
    const mode = ls.get('rp_mode'); if (mode) old.mode = mode === 'keyboard' ? 'mouse' : mode;
    const stream = ls.get('rp_stream'); if (stream) old.stream = stream === '1';
    const theme = ls.get('rp_theme'); if (theme === 'light' || theme === 'dark') old.theme = theme;
    return old;
  }

  function mirrorTheme() {
    if (cache.theme === 'light' || cache.theme === 'dark') ls.set('rp_theme', cache.theme); else ls.del('rp_theme');
  }

  function applyTheme() {
    const root = document.documentElement;
    if (cache.theme === 'light' || cache.theme === 'dark') root.dataset.theme = cache.theme;
    else delete root.dataset.theme;
  }

  async function load() {
    try {
      db = await openDb();
      const saved = await readAll(db);
      if (Object.keys(saved).length === 0) {
        const legacy = migrateLegacy();
        accept(legacy);
        for (const [k, v] of Object.entries(legacy)) await writeKey(k, v);
      } else accept(saved);
    } catch (_) {
      db = null;                                 // sem IndexedDB: segue com os padrões
      accept(migrateLegacy());
    }
    mirrorTheme();
    applyTheme();
    return Object.assign({}, cache);
  }

  function get(key) { return cache[key]; }

  function set(key, value) {
    if (!(key in DEFAULTS) || !VALID[key](value)) return Promise.resolve();
    cache[key] = value;
    if (key === 'theme') { mirrorTheme(); applyTheme(); }
    return writeKey(key, value);
  }

  // Apaga o banco inteiro e as cópias no localStorage. As preferências voltam ao padrão.
  async function clear() {
    if (db) { try { db.close(); } catch (_) { /* já fechado */ } db = null; }
    if (window.indexedDB) {
      await new Promise((resolve) => {
        let req;
        try { req = indexedDB.deleteDatabase(DB_NAME); } catch (_) { resolve(); return; }
        req.onsuccess = req.onerror = req.onblocked = () => resolve();
      });
    }
    LEGACY.forEach(ls.del);
    cache = Object.assign({}, DEFAULTS);
    applyTheme();
    try { db = await openDb(); } catch (_) { db = null; }   // recria vazio para as próximas gravações
  }

  window.RPConfig = { load, get, set, clear, applyTheme, defaults: Object.assign({}, DEFAULTS) };
})();
