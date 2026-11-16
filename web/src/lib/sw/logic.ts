// Pure logic for the service worker (src/sw.ts). No DOM or worker globals, so vitest can test it.

export type Strategy = 'queue-events' | 'cache-first' | 'network-first' | 'navigate' | 'passthrough';

export function classifyRequest(req: { method: string; pathname: string; mode?: string }): Strategy {
	const { method, pathname } = req;
	if (method === 'POST' && pathname === '/api/events') return 'queue-events';
	if (method !== 'GET') return 'passthrough';
	if (pathname === '/api/feed' || pathname.startsWith('/api/cards/')) return 'network-first';
	if (pathname.startsWith('/api/')) return 'passthrough';
	if (pathname.startsWith('/assets/') || pathname.startsWith('/_app/') || pathname === '/manifest.webmanifest') {
		return 'cache-first';
	}
	if (req.mode === 'navigate') return 'navigate';
	return 'passthrough';
}

// The cache key for a request, or null when the response must not be cached.
export function cacheKey(pathname: string, search: string): string | null {
	if (pathname === '/api/feed') {
		// Only the first page is "the last batch"; later pages would overwrite it.
		const q = new URLSearchParams(search);
		if (q.has('cursor')) return null;
		// Each filter (repo, dir, ...) has its own "last batch"; the page size does not matter.
		q.delete('limit');
		q.sort();
		const rest = q.toString();
		return rest ? `${pathname}?${rest}` : pathname;
	}
	if (pathname.startsWith('/api/cards/')) return pathname;
	return pathname + search;
}

// A static asset answer that is safe to cache: ok, and not an HTML page (the SPA fallback
// answers an unknown file with index.html and status 200).
export function isCacheableAsset(pathname: string, res: { ok: boolean; contentType: string | null }): boolean {
	if (!res.ok) return false;
	const html = (res.contentType ?? '').toLowerCase().startsWith('text/html');
	return !html || pathname.endsWith('.html');
}

// The keys to delete so that at most `max` stay. `keys` is in insertion order, oldest first.
export function evictOldest(keys: string[], max: number): string[] {
	return keys.length > max ? keys.slice(0, keys.length - max) : [];
}

export function selectPrecache(files: { path: string; size: number }[], maxBytes: number): string[] {
	const urls = ['/'];
	for (const f of files) {
		if (f.path === 'sw.js' || f.size > maxBytes) continue;
		urls.push('/' + f.path);
	}
	return urls;
}

export function markFromCache(res: Response): Response {
	const headers = new Headers(res.headers);
	headers.set('X-From-Cache', '1');
	return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

export type QueueRow = { id: number; body: string };
export type QueueStore = {
	all(): Promise<QueueRow[]>;
	remove(id: number): Promise<void>;
};

// Sends queued bodies in order. Stops at the first failure so order is kept. Returns how many were sent.
export async function replayQueue(store: QueueStore, send: (body: string) => Promise<boolean>): Promise<number> {
	let sent = 0;
	for (const row of await store.all()) {
		let ok = false;
		try {
			ok = await send(row.body);
		} catch {
			ok = false;
		}
		if (!ok) break;
		await store.remove(row.id);
		sent += 1;
	}
	return sent;
}

// What to do with a queued batch after the server answered with this status.
// done: sent. retry: keep it queued (5xx, 408, 425, 429). drop: it will never succeed (other 4xx).
export function statusOutcome(status: number): 'done' | 'retry' | 'drop' {
	if (status >= 200 && status < 300) return 'done';
	if (status >= 500 || status === 408 || status === 425 || status === 429) return 'retry';
	return status >= 400 ? 'drop' : 'done';
}

// Overlapping calls share one in-flight run. Used so replay never runs twice at once.
export function singleFlight<T>(fn: () => Promise<T>): () => Promise<T> {
	let inflight: Promise<T> | null = null;
	return () => {
		inflight ??= fn().finally(() => {
			inflight = null;
		});
		return inflight;
	};
}

// Caches to delete on activate. Keep the current cache and the newest older one: a page from
// the previous build may still ask for its /_app/ chunks. Relies on caches.keys() creation order.
export function staleCaches(keys: string[], current: string, prefix = 'gittok-'): string[] {
	const others = keys.filter((k) => k.startsWith(prefix) && k !== current);
	return others.slice(0, -1);
}
