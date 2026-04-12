// Service worker — enables PWA install and handles push notifications
const CACHE = 'bowl-tracker-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

// Push: show notification from server-sent payload
self.addEventListener('push', e => {
    let data = {};
    try { data = e.data ? e.data.json() : {}; } catch (_) {}
    const title = data.title || 'MLC Bowling';
    const options = {
        body: data.body || '',
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        tag: data.tag || 'bowling',      // collapse duplicate notifications
        renotify: false,
        data: { url: data.url || '/m/' },
    };
    e.waitUntil(self.registration.showNotification(title, options));
});

// Tap notification → focus or open the app
self.addEventListener('notificationclick', e => {
    e.notification.close();
    const url = e.notification.data?.url || '/m/';
    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
            for (const c of list) {
                if (c.url.includes('/m') && 'focus' in c) return c.focus();
            }
            return clients.openWindow(url);
        })
    );
});
