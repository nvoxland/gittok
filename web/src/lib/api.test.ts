import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, fetchRepos, fetchCard, fetchFeed, fetchStories, fetchNotifications, markNotificationsRead, markStoriesSeen, fetchRepo, fetchSaved, postAnswer, postEvents } from './api';

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
	it('adds the repo and dir filter', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ cards: [], next_cursor: null }) });
		await fetchFeed(undefined, 20, { repo: 'r', dir: 'a/b' });
		expect(fetchMock.mock.calls[0][0]).toBe('/api/feed?limit=20&repo=r&dir=a%2Fb');
	});
	it('flags responses the service worker served from cache', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			headers: new Headers({ 'X-From-Cache': '1' }),
			json: async () => ({ cards: [], next_cursor: null })
		});
		expect((await fetchFeed()).fromCache).toBe(true);
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
		const body = JSON.parse(init.body);
		expect(body).toMatchObject({ card_id: 'c_1', choice: 1 });
		expect(typeof body.session).toBe('string');
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

describe('fetchStories', () => {
	it('returns the stories array', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ stories: [{ repo: 'a' }] }) });
		const res = await fetchStories();
		expect(fetchMock.mock.calls[0][0]).toBe('/api/stories');
		expect(res).toEqual([{ repo: 'a' }]);
	});
	it('returns [] when the body has no stories', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
		expect(await fetchStories()).toEqual([]);
	});
});

describe('markStoriesSeen', () => {
	it('POSTs repo and shas', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
		await markStoriesSeen('storefront', ['a', 'b']);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toBe('/api/stories/seen');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ repo: 'storefront', shas: ['a', 'b'] });
	});
});

describe('fetchNotifications', () => {
	it('asks for unread only when requested', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ notifications: [], unread: 2 }) });
		const res = await fetchNotifications(true);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/notifications?unread=1');
		expect(res.unread).toBe(2);
	});
	it('lists all by default', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ notifications: [], unread: 0 }) });
		await fetchNotifications();
		expect(fetchMock.mock.calls[0][0]).toBe('/api/notifications');
	});
});

describe('markNotificationsRead', () => {
	it('sends ids', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
		await markNotificationsRead([1, 2]);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toBe('/api/notifications/read');
		expect(JSON.parse(init.body)).toEqual({ ids: [1, 2] });
	});
	it('sends all', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
		await markNotificationsRead('all');
		expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ all: true });
	});
});

describe('errors the page must tell apart', () => {
	it('fetchFeed keeps the HTTP status, so the page can tell "not paired" (401) from a failure', async () => {
		fetchMock.mockResolvedValue({ ok: false, status: 401 });
		const err = await fetchFeed().catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(401);
		expect(err.message).toContain('401');
	});
});

describe('fetchRepos', () => {
	it('returns the configured repos', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			json: async () => ({ repos: [{ name: 'storefront', ref: 'HEAD', head_sha: null, group: null }] })
		});
		const repos = await fetchRepos();
		expect(fetchMock.mock.calls[0][0]).toBe('/api/repos');
		expect(repos.map((r) => r.name)).toEqual(['storefront']);
	});
	it('throws when the body has no repos list', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ cards: [] }) });
		await expect(fetchRepos()).rejects.toThrow();
	});
	it('throws on non-ok', async () => {
		fetchMock.mockResolvedValue({ ok: false, status: 500 });
		await expect(fetchRepos()).rejects.toThrow('500');
	});
});

describe('failed calls carry the status', () => {
	it('fetchCard, fetchRepo, fetchPersona and postFollow throw an ApiError with the HTTP status', async () => {
		const { postFollow, fetchPersona } = await import('./api');
		fetchMock.mockResolvedValue({ ok: false, status: 404 });
		for (const call of [() => fetchCard('x'), () => fetchRepo('x'), () => fetchPersona('x'), () => postFollow('r', 'p', true)]) {
			await expect(call()).rejects.toMatchObject({ status: 404 });
		}
	});
});
