/*
 * The push half of the service worker.
 *
 * Workbox generates the caching worker; `importScripts` appends these two
 * listeners to it. A notification carries a pointer and a URL, never employee
 * data -- the lock screen is not an access-controlled surface.
 */
self.addEventListener('push', (event) => {
  let payload = {}
  if (event.data) {
    try {
      payload = event.data.json()
    } catch {
      // A malformed payload still gets the generic notification.
    }
  }
  const title = typeof payload.title === 'string' ? payload.title : 'HRAgents'
  const options = {
    body: typeof payload.body === 'string' ? payload.body : '',
    icon: '/app/pwa-192x192.png',
    badge: '/app/favicon.svg',
    data: { url: typeof payload.url === 'string' ? payload.url : '/app/' },
  }
  if (typeof payload.tag === 'string') {
    options.tag = payload.tag
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data
  const url = data && typeof data.url === 'string' ? data.url : '/app/'
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true,
      })
      for (const client of windows) {
        if ('navigate' in client) {
          await client.navigate(url)
          return client.focus()
        }
      }
      return self.clients.openWindow(url)
    })(),
  )
})
