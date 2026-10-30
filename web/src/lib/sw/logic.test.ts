import { describe, expect, it, vi } from 'vitest';
import {
	cacheKey,
	classifyRequest,
	markFromCache,
	replayQueue,
	selectPrecache,
	type QueueStore
} from './logic.ts';

describe('classifyRequest', () => {
	const c = (method: string, path: string, mode = 'cors') => classifyRequest({ method, pathname: path, mode });
	it('queues POST /api/events', () => expect(c('POST', '/api/events')).toBe('queue-events'));
	it('never caches other POSTs', () => {
		expect(c('POST', '/api/answer')).toBe('passthrough');
		expect(c('POST', '/api/stories/seen')).toBe('passthrough');
	});
	it('serves /assets/* cache-first', () => expect(c('GET', '/assets/mascots/otter.png')).toBe('cache-first'));
	it('serves built app files cache-first', () => {
		expect(c('GET', '/_app/immutable/entry/start.abc.js')).toBe('cache-first');
		expect(c('GET', '/manifest.webmanifest')).toBe('cache-first');
	});
	it('serves feed and cards network-first', () => {
		expect(c('GET', '/api/feed')).toBe('network-first');
		expect(c('GET', '/api/cards/c_1')).toBe('network-first');
	});
	it('does not touch other API reads', () => {
		expect(c('GET', '/api/notifications')).toBe('passthrough');
		expect(c('GET', '/api/stories')).toBe('passthrough');
	});
	it('serves navigations network-first with the shell as fallback', () =>
		expect(c('GET', '/saved', 'navigate')).toBe('navigate'));
});

describe('cacheKey', () => {
	it('keys the first feed page without its query', () =>
		expect(cacheKey('/api/feed', '?limit=20')).toBe('/api/feed'));
	it('does not cache later feed pages', () =>
		expect(cacheKey('/api/feed', '?limit=20&cursor=abc')).toBeNull());
	it('keys cards by path', () => expect(cacheKey('/api/cards/c_1', '')).toBe('/api/cards/c_1'));
	it('keys everything else by path and query', () =>
		expect(cacheKey('/assets/a.png', '?v=2')).toBe('/assets/a.png?v=2'));
});

describe('selectPrecache', () => {
	it('keeps small files and the shell, skips big chunks and the worker itself', () => {
		const files = [
			{ path: 'index.html', size: 900 },
			{ path: 'sw.js', size: 5000 },
			{ path: '_app/immutable/a.js', size: 1000 },
			{ path: '_app/immutable/mermaid.js', size: 900_000 },
			{ path: 'manifest.webmanifest', size: 300 }
		];
		expect(selectPrecache(files, 200_000)).toEqual([
			'/',
			'/index.html',
			'/_app/immutable/a.js',
			'/manifest.webmanifest'
		]);
	});
});

describe('markFromCache', () => {
	it('adds X-From-Cache and keeps body and status', async () => {
		const res = markFromCache(new Response('{"a":1}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
		expect(res.headers.get('X-From-Cache')).toBe('1');
		expect(res.headers.get('Content-Type')).toBe('application/json');
		expect(await res.json()).toEqual({ a: 1 });
	});
});

function memoryStore(items: string[]): QueueStore & { left: () => string[] } {
	const rows = items.map((body, i) => ({ id: i + 1, body }));
	return {
		all: async () => [...rows],
		remove: async (id) => void rows.splice(rows.findIndex((r) => r.id === id), 1),
		left: () => rows.map((r) => r.body)
	};
}

describe('replayQueue', () => {
	it('sends queued bodies in order and empties the queue', async () => {
		const store = memoryStore(['a', 'b']);
		const send = vi.fn(async (_body: string) => true);
		expect(await replayQueue(store, send)).toBe(2);
		expect(send.mock.calls.map((c) => c[0])).toEqual(['a', 'b']);
		expect(store.left()).toEqual([]);
	});
	it('stops at the first failure and keeps the rest', async () => {
		const store = memoryStore(['a', 'b', 'c']);
		const send = vi.fn(async (b: string) => b !== 'b');
		expect(await replayQueue(store, send)).toBe(1);
		expect(store.left()).toEqual(['b', 'c']);
	});
	it('treats a thrown send as a failure', async () => {
		const store = memoryStore(['a']);
		expect(await replayQueue(store, async () => { throw new Error('offline'); })).toBe(0);
		expect(store.left()).toEqual(['a']);
	});
});
