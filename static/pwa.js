/* Registro do service worker e botão "Instalar app". Usado por / e /admin. */
(() => {
  'use strict';
  const standalone = matchMedia('(display-mode: standalone)').matches
    || matchMedia('(display-mode: fullscreen)').matches || navigator.standalone === true;
  const buttons = [...document.querySelectorAll('[data-install]')];
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  let deferred = null;

  // O service worker exige HTTPS (ou localhost). Pelo IP do Raspberry em http, o app
  // funciona normalmente, só não instala como PWA completo: use o túnel ngrok (README).
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((e) => console.warn('SW:', e));
  }

  const showButtons = () => { if (!standalone) buttons.forEach((b) => b.classList.remove('hidden')); };
  window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e; showButtons(); });
  window.addEventListener('appinstalled', () => buttons.forEach((b) => b.classList.add('hidden')));
  if (ios) showButtons();   // iOS não tem prompt: mostramos a instrução

  buttons.forEach((b) => b.addEventListener('click', async () => {
    if (deferred) { deferred.prompt(); await deferred.userChoice; deferred = null; buttons.forEach((x) => x.classList.add('hidden')); }
    else alert('Para instalar: toque em Compartilhar e depois em "Adicionar à Tela de Início".');
  }));
})();
