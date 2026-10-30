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
		return new URLSearchParams(search).has('cursor') ? null : pathname;
	}
	if (pathname.startsWith('/api/cards/')) return pathname;
	return pathname + search;
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
