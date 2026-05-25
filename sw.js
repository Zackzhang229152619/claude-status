// claude-status Service Worker — handles Web Push notifications

const CACHE_NAME = 'claude-status-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'Claude Status', body: event.data ? event.data.text() : '' };
  }

  const title = data.title || 'Claude Status';
  const opts = {
    body: data.body || '',
    icon: data.icon || 'icon-192.png',
    badge: 'icon-192.png',
    tag: data.tag || 'claude-status',
    renotify: data.renotify !== false,
    requireInteraction: data.requireInteraction !== false,
    data: { url: data.url || './' },
  };

  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Focus an existing window if one is open
      for (const c of clientList) {
        if ('focus' in c) {
          c.navigate(url).catch(() => {});
          return c.focus();
        }
      }
      // Otherwise open new
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
