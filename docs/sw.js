/* 砺行集 PWA Service Worker
 *
 * 策略：
 *  - 导航请求（HTML）：Network First，失败回退缓存 → 保证能拿到新版
 *  - 静态资源（图标/manifest）：Cache First → 快
 *  - 不做激进预缓存，避免拿旧内容
 *
 * 版本号由构建脚本注入（CACHE_VERSION 会被替换），
 * 每次构建变化都会让浏览器判定为新 SW，从而触发更新。
 */
const CACHE_VERSION = '20261020173523';
const CACHE_NAME = 'lishi-' + CACHE_VERSION;
const PRECACHE = [
  './',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png'
];

// 安装：预缓存核心资源，立即激活（不等旧页面关闭）
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then((c) => c.addAll(PRECACHE).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// 激活：清理旧版本缓存
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith('lishi-') && k !== CACHE_NAME)
            .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// 请求拦截
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // 只处理同源
  if (url.origin !== self.location.origin) return;

  // HTML 导航：Network First
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match('./')))
    );
    return;
  }

  // 静态资源：Cache First
  e.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => cached);
    })
  );
});

// 允许页面主动要求跳过等待
self.addEventListener('message', (e) => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
});
