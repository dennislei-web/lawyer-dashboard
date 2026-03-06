const CACHE_NAME = 'zhelv-dashboard-v1';
const URLS_TO_CACHE = [
  '/lawyer-dashboard/',
  '/lawyer-dashboard/index.html',
  '/lawyer-dashboard/dashboard.html',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(URLS_TO_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // 網路優先：先嘗試網路，失敗才用快取
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 更新快取
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          if (event.request.method === 'GET') {
            cache.put(event.request, responseClone);
          }
        });
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
