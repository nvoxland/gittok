import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchFeed, postEvents } from './api';

const fetchMock = vi.fn();

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('fetchFeed', () => {
	it('builds the default url', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ cards: [], next_cursor: null }) });
		const res = await fetchFeed();
		expect(fetchMock.mock.calls[0][0]).toBe('/api/feed?limit=20');
		expect(res).toEqual({ cards: [], next_cursor: null });
	});
	it('includes cursor', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ cards: [], next_cursor: null }) });
		await fetchFeed('abc');
		expect(fetchMock.mock.calls[0][0]).toBe('/api/feed?limit=20&cursor=abc');
	});
	it('throws on non-ok', async () => {
		fetchMock.mockResolvedValue({ ok: false, status: 500 });
		await expect(fetchFeed()).rejects.toThrow('500');
	});
});

describe('postEvents', () => {
	it('POSTs JSON {events}', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ stored: 1 }) });
		const events = [{ card_id: 'c_1', type: 'impression' as const, ts: 1 }];
		await postEvents(events);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toBe('/api/events');
		expect(init.method).toBe('POST');
		expect(init.headers['Content-Type']).toBe('application/json');
		expect(JSON.parse(init.body)).toEqual({ events });
	});
});
