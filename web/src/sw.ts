/// <reference lib="webworker" />
// Service worker entry. Built into build/sw.js by scripts/build-sw.mjs (see that file).
// All decisions live in lib/sw/logic.ts; this file only wires them to the worker APIs.
import {
	cacheKey,
	classifyRequest,
	evictOldest,
	isCacheableAsset,
	markFromCache,
	replayQueue,
	singleFlight,
	staleCaches,
	statusOutcome,
	type QueueRow
} from './lib/sw/logic.ts';

declare const __PRECACHE__: string[];
declare const __VERSION__: string;
declare const self: ServiceWorkerGlobalScope;

const CACHE = `gittok-${__VERSION__}`;
// Hashed build files stay in CACHE (precache); /assets/ (card images) is bounded on its own.
const ASSET_CACHE = 'gittok-assets';
const MAX_ASSETS = 300;
const SYNC_TAG = 'replay-events';

// ---- offline event queue (IndexedDB) ----
function openDb(): Promise<IDBDatabase> {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open('gittok-sw', 1);
		req.onupgradeneeded = () => req.result.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});
}
async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
	const db = await openDb();
	return new Promise((resolve, reject) => {
		const req = fn(db.transaction('queue', mode).objectStore('queue'));
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});
}
const queueStore = {
	all: () => tx<QueueRow[]>('readonly', (s) => s.getAll() as IDBRequest<QueueRow[]>),
	remove: (id: number) => tx('readwrite', (s) => s.delete(id)).then(() => {}),
	add: (body: string) => tx('readwrite', (s) => s.add({ body })).then(() => {})
};

// Page load, the online event and Background Sync can all ask for a replay. One run at a time.
const replay = singleFlight(() =>
	replayQueue(queueStore, async (body) => {
		try {
			const res = await fetch('/api/events', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body
			});
			// done and drop both leave the queue; retry keeps the row and stops this run.
			return statusOutcome(res.status) !== 'retry';
		} catch {
			return false;
		}
	})
);

// ---- lifecycle ----
self.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((c) => Promise.all(__PRECACHE__.map((u) => c.add(u).catch(() => {}))))
			.then(() => self.skipWaiting())
	);
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(staleCaches(keys.filter((k) => k !== ASSET_CACHE), CACHE).map((k) => caches.delete(k))))
			.then(() => self.clients.claim())
	);
});

self.addEventListener('message', (event) => {
	if (event.data?.type === 'replay') event.waitUntil(replay());
});
self.addEventListener('sync', (event) => {
	const e = event as ExtendableEvent & { tag: string };
	if (e.tag === SYNC_TAG) e.waitUntil(replay());
});

// ---- fetch ----
async function cacheFirst(req: Request, key: string): Promise<Response> {
	const isAsset = new URL(req.url).pathname.startsWith('/assets/');
	const cache = await caches.open(isAsset ? ASSET_CACHE : CACHE);
	// Also look in the previous build's cache (kept on activate) for pages that are still open.
	const hit = (await cache.match(key)) ?? (await caches.match(key));
	if (hit) return hit;
	const res = await fetch(req);
	if (isCacheableAsset(new URL(req.url).pathname, { ok: res.ok, contentType: res.headers.get('content-type') })) {
		await cache.put(key, res.clone());
		if (isAsset) {
			for (const k of evictOldest((await cache.keys()).map((r) => r.url), MAX_ASSETS)) await cache.delete(k);
		}
	}
	return res;
}

async function networkFirst(req: Request, key: string | null): Promise<Response> {
	const cache = await caches.open(CACHE);
	try {
		const res = await fetch(req);
		if (res.ok && key) await cache.put(key, res.clone());
		return res;
	} catch (err) {
		const hit = key ? await cache.match(key) : undefined;
		if (hit) return markFromCache(hit);
		throw err;
	}
}

async function navigate(req: Request): Promise<Response> {
	try {
		return await fetch(req);
	} catch (err) {
		const cache = await caches.open(CACHE);
		const shell = (await cache.match('/index.html')) ?? (await cache.match('/'));
		if (shell) return shell;
		throw err;
	}
}

async function queueEvents(req: Request): Promise<Response> {
	const copy = req.clone();
	let res: Response | null = null;
	try {
		res = await fetch(req);
	} catch {
		// offline: queue below
	}
	if (res && statusOutcome(res.status) !== 'retry') return res;
	await queueStore.add(await copy.text());
	// 202 so the page does not requeue the batch itself.
	return new Response(JSON.stringify({ stored: 0, queued: true }), {
		status: 202,
		headers: { 'Content-Type': 'application/json' }
	});
}

self.addEventListener('fetch', (event) => {
	const req = event.request;
	const url = new URL(req.url);
	if (url.origin !== self.location.origin) return;
	const strategy = classifyRequest({ method: req.method, pathname: url.pathname, mode: req.mode });
	const key = cacheKey(url.pathname, url.search);
	switch (strategy) {
		case 'queue-events':
			event.respondWith(queueEvents(req));
			break;
		case 'cache-first':
			event.respondWith(cacheFirst(req, key ?? url.pathname));
			break;
		case 'network-first':
			event.respondWith(networkFirst(req, key));
			break;
		case 'navigate':
			event.respondWith(navigate(req));
			break;
		default:
			break;
	}
});
