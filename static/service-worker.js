// This is a minimal service worker for installability.
// It doesn't cache anything, it just satisfies the PWA requirement.

self.addEventListener('fetch', event => {
  // The service worker is not intercepting any requests.
  return;
});