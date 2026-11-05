/*
 * Kalchas service worker: shows goal alerts for pinned matches.
 * The bot sends { title, body, tag, url }; we show it as-is. No caching.
 */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const tag = data.tag || undefined;
  event.waitUntil(
    self.registration.showNotification(data.title || "Kalchas", {
      body: data.body || "",
      tag,
      // A second goal in the same match replaces the first and still buzzes.
      renotify: Boolean(tag),
      icon: "/icon-192.png",
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin !== target.origin) continue;
        try {
          await client.focus();
          if ("navigate" in client) await client.navigate(target.href);
          return;
        } catch {
          // Not ours to steer (uncontrolled tab): open a fresh one below.
        }
      }
      await self.clients.openWindow(target.href);
    })(),
  );
});
