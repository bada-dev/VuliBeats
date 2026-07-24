// without caching the API......1!12r1irj1290r
const VER = 'vulibeats-v1';
const EXT = 'vulibeats-ext-v1';
const SHELL = ['/', '/static/manifest.json', '/static/icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VER).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VER && k !== EXT).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/pc' || url.hostname === 'lrclib.net') return;

  if (url.origin === self.location.origin) {
    // Stale-while-revalidate: instant offline opens, updates land next launch.
    e.respondWith(
      caches.open(VER).then(async (c) => {
        const key = e.request.mode === 'navigate' ? '/' : e.request;
        const cached = await c.match(key, { ignoreSearch: true });
        const fresh = fetch(e.request).then((r) => {
          if (r && r.ok) c.put(key, r.clone());
          return r;
        }).catch(() => null);
        return cached || fresh.then((r) => r || c.match('/'));
      })
    );
    return;
  }

  // Fonts etc: cache-first so the design survives offline.
  e.respondWith(
    caches.open(EXT).then(async (c) => {
      const cached = await c.match(e.request);
      if (cached) return cached;
      try {
        const r = await fetch(e.request);
        if (r && (r.ok || r.type === 'opaque')) c.put(e.request, r.clone());
        return r;
      } catch {
        return new Response('', { status: 504 });
      }
    })
  );
});
