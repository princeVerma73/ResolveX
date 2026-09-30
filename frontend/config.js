/**
 * ResolveX — Dynamic Runtime Environment Configuration
 * Provides dynamic REST and WebSocket endpoints for local development and Netlify/Cloud production.
 */
(function () {
  const isLocal =
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1' ||
      window.location.hostname === 'file:');

  const defaultBackend = isLocal
    ? 'http://localhost:8000'
    : 'https://resolvex-bd8o.onrender.com';

  window.__APP_CONFIG__ = {
    BACKEND_URL: window.ENV_BACKEND_URL || defaultBackend,
    get WS_URL() {
      try {
        const url = new URL(this.BACKEND_URL);
        const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${url.host}`;
      } catch (err) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host || 'localhost:8000';
        return `${protocol}//${host}`;
      }
    },
  };
})();