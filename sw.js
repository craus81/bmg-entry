const CACHE_NAME = 'bmg-checkin-v1';
const urlsToCache = [
  '/widget',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  'https://unpkg.com/tesseract.js@4/dist/tesseract.min.js',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Outfit:wght@400;500;600;700&display=swap'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        return fetch(event.request);
      })
  );
});
