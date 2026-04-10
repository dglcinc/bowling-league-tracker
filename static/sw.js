// Minimal service worker — enables beforeinstallprompt on Android/desktop Chrome
const CACHE = 'bowl-tracker-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
