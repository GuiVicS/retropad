/* Service worker do RetroPad: guarda a "casca" do app para abrir rápido e funcionar
 * como PWA instalado. Nunca guarda /api nem /ws (dados e controle são sempre ao vivo).
 * Servido em /sw.js (raiz) pelo server.py para poder controlar "/" e "/admin". */
const VERSION = 'retropad-v1';
const SHELL = [
  '/', '/admin',
  '/static/theme.css', '/static/admin.css', '/static/app.js', '/static/pwa.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png', '/static/icons/icon-512.png', '/static/icons/apple-touch-icon.png',
];

// Só guarda respostas que vieram do RetroPad (o servidor marca com X-RetroPad).
// Assim, a página de aviso do ngrok ou uma página de erro nunca entram no cache.
const ours = (res) => res && res.ok && res.headers.get('X-RetroPad') === '1';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION)
      .then((cache) => Promise.all(SHELL.map((url) =>
        fetch(url, { cache: 'reload' }).then((res) => (ours(res) ? cache.put(url, res) : null)).catch(() => null))))
      .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws' || url.pathname === '/sw.js') return;

  if (req.mode === 'navigate') {
    // Páginas: rede primeiro (pega atualizações); sem rede, usa a cópia guardada.
    event.respondWith(
      fetch(req).then((res) => {
        if (ours(res)) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(url.pathname, copy)); }
        return res;
      }).catch(() => caches.match(url.pathname, { ignoreSearch: true }).then((hit) => hit || caches.match('/'))));
    return;
  }

  // Arquivos estáticos: responde do cache e atualiza em segundo plano.
  event.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req).then((res) => {
        if (ours(res)) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => hit);
      return hit || net;
    }));
});
