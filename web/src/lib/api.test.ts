import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchCard, fetchFeed, fetchRepo, fetchSaved, postAnswer, postEvents } from './api';

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

describe('fetchRepo / fetchCard', () => {
	it('fetches an encoded repo profile', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ name: 'a b' }) });
		const res = await fetchRepo('a b');
		expect(fetchMock.mock.calls[0][0]).toBe('/api/repos/a%20b');
		expect(res).toEqual({ name: 'a b' });
	});
	it('throws on 404', async () => {
		fetchMock.mockResolvedValue({ ok: false, status: 404 });
		await expect(fetchRepo('x')).rejects.toThrow('404');
	});
	it('fetches a card', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ id: 'c_1' }) });
		await fetchCard('c_1');
		expect(fetchMock.mock.calls[0][0]).toBe('/api/cards/c_1');
	});
});

describe('postAnswer', () => {
	it('posts card_id and choice and returns the reveal', async () => {
		const reveal = { correct: true, answer_index: 1, explanation: 'because' };
		fetchMock.mockResolvedValue({ ok: true, json: async () => reveal });
		expect(await postAnswer('c_1', 1)).toEqual(reveal);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toBe('/api/answer');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ card_id: 'c_1', choice: 1 });
	});
	it('throws on non-ok', async () => {
		fetchMock.mockResolvedValue({ ok: false, status: 404 });
		await expect(postAnswer('c_1', 0)).rejects.toThrow('404');
	});
});

describe('fetchSaved', () => {
	it('gets /api/saved and returns the cards', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ cards: [{ id: 'c_1' }] }) });
		expect(await fetchSaved()).toEqual([{ id: 'c_1' }]);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/saved');
	});
});
