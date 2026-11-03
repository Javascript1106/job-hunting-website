// Offline shell for public PathForge pages and versioned static assets.
const CACHE_NAME = "pathforge-shell-20261103-v145";
const ASSET_VERSION = "20261103-v145";
// Cache only the public application shell. Account data and API responses
// remain network-backed so private or stale records are never served offline.
const SHELL_FILES = [
  "./", "./index.html", "./jobs.html", "./search-history.html", "./login.html", "./register.html",
  "./offline.html", "./offline.js", `./style.css?v=${ASSET_VERSION}`, `./pathforge-core.js?v=${ASSET_VERSION}`, `./script.js?v=${ASSET_VERSION}`, "./manifest.webmanifest",
  "./assets/branding/pathforge-logo.svg", "./assets/branding/pathforge-logo-dark.svg",
  "./assets/branding/pathforge-mark.svg", "./assets/branding/pathforge-mark-dark.svg",
  "./assets/branding/pathforge-favicon.svg"
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  // A version change removes the previous shell atomically after installation.
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    // Prefer a fresh page, falling back to a cached route or the offline screen.
    event.respondWith(
      fetch(request).catch(async () => (
        await caches.match(request, { ignoreSearch: true })
        || await caches.match("./offline.html")
      ))
    );
    return;
  }

  if (["style", "script", "image", "font", "manifest"].includes(request.destination)) {
    // Prefer current assets while retaining an offline fallback.
    event.respondWith(
      fetch(request).then(async response => {
        // Clone immediately, before the browser begins consuming the response
        // returned to the page. Cloning later can throw "body is already used".
        const responseForCache = response.ok ? response.clone() : null;
        if (responseForCache) {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(request, responseForCache);
        }
        return response;
      }).catch(() => caches.match(request))
    );
  }
});
