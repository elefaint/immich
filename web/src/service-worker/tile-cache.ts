/**
 * Offline cache for third-party map tiles.
 *
 * Amap serves tiles with `cache-control: max-age=3600`, so the browser only
 * keeps them for an hour. This cache-first handler persists tiles in the
 * Cache API so already-viewed areas stay available (and load instantly)
 * afterwards, including while offline.
 */

const TILE_CACHE_NAME = 'amap-tiles';
const TILE_URL_PATTERN = /appmaptile/i;
const MAX_TILES = 5000;
const KEEP_TILES = 4000;

const isTileRequest = (request: Request) =>
  request.method === 'GET' && TILE_URL_PATTERN.test(request.url);

/** Drop the oldest entries once the cache grows past MAX_TILES. */
const trimCache = async (cache: Cache) => {
  const keys = await cache.keys();
  if (keys.length > MAX_TILES) {
    await Promise.all(
      keys.slice(0, keys.length - KEEP_TILES).map((key) => cache.delete(key)),
    );
  }
};

/**
 * Cache-first for map tiles: serve from the Cache API when present,
 * otherwise fetch from the network and store a copy (fire and forget).
 */
const handleTileFetch = async (request: Request): Promise<Response> => {
  const cache = await caches.open(TILE_CACHE_NAME);

  const cached = await cache.match(request);
  if (cached) {
    return cached;
  }

  const response = await fetch(request);
  if (response.ok || response.type === 'opaque') {
    // Don't block the tile on the cache write or periodic trimming.
    void cache.put(request, response.clone()).then(async () => {
      if (Math.random() < 0.05) {
        await trimCache(cache);
      }
    });
  }
  return response;
};

/**
 * Wire up tile caching on the service worker. Returns true when the fetch
 * event was handled (i.e. the caller should not process it further).
 */
export const handleTileRequest = (event: FetchEvent): boolean => {
  if (!isTileRequest(event.request)) {
    return false;
  }
  event.respondWith(handleTileFetch(event.request));
  return true;
};
