// const CACHE_NAME = 'skillpulse-v1';
// const ASSETS = [
//   '/',
//   '/templates/stylesheet/style.css',
//   '/templates/js/main.js'
// ];

// // Install: Cache essential assets
// self.addEventListener('install', (event) => {
//   event.waitUntil(
//     caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
//   );
// });

// // Fetch: Serve from cache if offline
// self.addEventListener('fetch', (event) => {
//   event.respondWith(
//     caches.match(event.request).then((response) => {
//       return response || fetch(event.request);
//     })
//   );
// });