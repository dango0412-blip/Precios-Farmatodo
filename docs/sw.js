// Versión nueva si hay internet; si no, la última guardada.
const C = "precios-v1";
const BASE = ["./", "index.html", "manifest.webmanifest",
  "icon-192.png", "icon-512.png"];
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(C).then(c => c.addAll(BASE)));
});
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(k => Promise.all(
        k.filter(x => x !== C).map(x => caches.delete(x))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then(r => {
        const copia = r.clone();
        caches.open(C).then(c => c.put(e.request, copia));
        return r;
      })
      .catch(() => caches.match(e.request)
        .then(m => m || caches.match("index.html")))
  );
});
