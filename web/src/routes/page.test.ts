import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import { fakeCard } from '#lib/components/fixtures.ts';
import { getAnswer, setAnswer } from '#lib/cardState.ts';

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal('fetch', fetchMock));
afterEach(() => {
	fetchMock.mockReset();
	vi.unstubAllGlobals();
});

describe('feed page', () => {
	it('stops the browser pull-to-refresh at the top of the feed (scrolling back up reloaded it)', async () => {
		const { readFileSync } = await import('node:fs');
		const css = readFileSync(`${process.cwd()}/src/app.css`, 'utf8');
		expect(css).toMatch(/html\s*\{[^}]*overscroll-behavior-y:\s*none/);
	});

	it('has a Saved link in the top bar', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			json: async () => ({ cards: [fakeCard({ hook: 'A hook' })], next_cursor: null })
		});
		render(Page);
		expect(await screen.findByText('A hook')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Saved' })).toHaveAttribute('href', '/saved');
	});

	function route(map: Record<string, unknown>, feedHeaders: Record<string, string> = {}) {
		fetchMock.mockImplementation(async (url: string) => {
			const key = Object.keys(map).find((k) => url.startsWith(k));
			return {
				ok: true,
				headers: {
					get: (h: string) => (url.startsWith('/api/feed') ? (feedHeaders[h] ?? null) : null)
				},
				json: async () => structuredClone(map[key ?? '/api/feed'])
			};
		});
	}
	const feed = { cards: [fakeCard({ hook: 'A hook' })], next_cursor: null };
	const stories = {
		stories: [
			{
				repo: 'storefront',
				mascot: 'otter',
				mascot_image: null,
				seen: false,
				commits: [
					{
						sha: 'a'.repeat(40),
						short: 'aaaaaaa',
						ts: 1,
						author: 'Ann',
						subject: 'Fix it',
						files: 2
					}
				]
			}
		]
	};

	it('loads the next page near the end and appends only new cards', async () => {
		let near: (() => void) | undefined;
		class FakeIO {
			constructor(public cb: (e: Partial<IntersectionObserverEntry>[]) => void) {}
			observe(target: Element) {
				if (target.getAttribute('data-card-id') === 'c_1')
					near = () => this.cb([{ target, isIntersecting: true, intersectionRatio: 0.9 }]);
			}
			disconnect() {}
		}
		vi.stubGlobal('IntersectionObserver', FakeIO);
		const card = (n: number) => fakeCard({ id: `c_${n}`, hook: `Hook ${n}` });
		const first = { cards: [card(1), card(2)], next_cursor: 'cur1' };
		const second = { cards: [card(2), card(3)], next_cursor: null };
		fetchMock.mockImplementation(async (url: string) => ({
			ok: true,
			headers: { get: () => null },
			json: async () =>
				url.startsWith('/api/feed')
					? structuredClone(url.includes('cursor=cur1') ? second : first)
					: { notifications: [], unread: 0, stories: [] }
		}));
		render(Page);
		await screen.findByText('Hook 1');
		near!();
		expect(await screen.findByText('Hook 3')).toBeInTheDocument();
		expect(screen.getAllByRole('article')).toHaveLength(3);
		expect(fetchMock.mock.calls.some(([u]) => String(u).includes('cursor=cur1'))).toBe(true);
	});

	it('keeps the answer of the resumed card and clears the other served ones', async () => {
		setAnswer('c_1', 0);
		setAnswer('c_2', 1);
		const card = (n: number) => fakeCard({ id: `c_${n}`, hook: `Hook ${n}` });
		route({
			'/api/feed': { cards: [card(1), card(2)], next_cursor: null, resume_card_id: 'c_1' }
		});
		render(Page);
		await screen.findByText('Hook 1');
		expect(getAnswer('c_1')).toBe(0);
		expect(getAnswer('c_2')).toBeUndefined();
	});

	it('ends the feed with a caught-up card that says how to make more', async () => {
		route({ '/api/feed': { cards: [fakeCard({ hook: 'Only card' })], next_cursor: null } });
		render(Page);
		const end = await screen.findByRole('region', { name: 'End of feed' });
		expect(end).toHaveTextContent(/caught up/i);
		expect(end).toHaveTextContent('/codescroll-generate');
		const articles = screen.getAllByRole('article');
		expect(articles[articles.length - 1].compareDocumentPosition(end)).toBe(
			Node.DOCUMENT_POSITION_FOLLOWING
		);
	});

	it('shows no end card while more pages remain', async () => {
		route({ '/api/feed': { cards: [fakeCard({ hook: 'A hook' })], next_cursor: 'more' } });
		render(Page);
		await screen.findByText('A hook');
		expect(screen.queryByRole('region', { name: 'End of feed' })).toBeNull();
	});

	describe('returning to the page (e43)', () => {
		const card = (n: number) => fakeCard({ id: `c_${n}`, hook: `Hook ${n}` });
		const order = () => screen.getAllByRole('article').map((a) => a.textContent ?? '');
		beforeEach(() => {
			sessionStorage.clear();
			localStorage.clear();
		});

		// Fires the 60%-visible callback for a card, like a user scrolling it into view.
		function fakeIO() {
			const fire: Record<string, () => void> = {};
			class FakeIO {
				constructor(public cb: (e: Partial<IntersectionObserverEntry>[]) => void) {}
				observe(target: Element) {
					const id = target.getAttribute('data-card-id')!;
					fire[id] = () => this.cb([{ target, isIntersecting: true, intersectionRatio: 0.9 }]);
				}
				disconnect() {}
			}
			vi.stubGlobal('IntersectionObserver', FakeIO);
			return fire;
		}

		it('remembers the card on screen and turns browser scroll restoration off', async () => {
			const fire = fakeIO();
			route({ '/api/feed': { cards: [card(1), card(2), card(3)], next_cursor: 'm' } });
			render(Page);
			await screen.findByText('Hook 1');
			fire['c_2']();
			expect(localStorage.getItem('codescroll.current')).toBe('c_2');
			expect(history.scrollRestoration).toBe('manual');
		});

		it('a reload with a changed feed puts the remembered card first; unseen cards stay below', async () => {
			localStorage.setItem('codescroll.current', 'c_3');
			// The server resumes on c_1 (its event log lags) and serves c_3 again further down.
			route({
				'/api/feed': { cards: [card(1), card(4), card(3), card(5)], next_cursor: 'm', resume_card_id: 'c_1' }
			});
			render(Page);
			await screen.findByText('Hook 3');
			const hooks = order();
			expect(hooks[0]).toContain('Hook 3');
			expect(hooks.filter((h) => h.includes('Hook 3'))).toHaveLength(1);
			expect(hooks.some((h) => h.includes('Hook 4'))).toBe(true);
			expect(hooks.some((h) => h.includes('Hook 5'))).toBe(true);
		});

		it('fetches the remembered card when the new batch does not hold it', async () => {
			localStorage.setItem('codescroll.current', 'c_9');
			fetchMock.mockImplementation(async (url: string) => ({
				ok: true,
				headers: { get: () => null },
				json: async () =>
					url.startsWith('/api/cards/c_9')
						? card(9)
						: url.startsWith('/api/feed')
							? { cards: [card(1), card(4)], next_cursor: null, resume_card_id: 'c_1' }
							: { notifications: [], unread: 0, stories: [] }
			}));
			render(Page);
			await screen.findByText('Hook 9');
			expect(order()[0]).toContain('Hook 9');
		});

		it('going hidden sends the queued events with sendBeacon, which iOS does not cancel', async () => {
			const fire = fakeIO();
			const beacon = vi.fn(() => true);
			vi.stubGlobal('navigator', { ...navigator, sendBeacon: beacon });
			route({ '/api/feed': { cards: [card(1), card(2)], next_cursor: null } });
			render(Page);
			await screen.findByText('Hook 1');
			fire['c_2']();
			const vis = vi.spyOn(document, 'visibilityState', 'get');
			vis.mockReturnValue('hidden');
			document.dispatchEvent(new Event('visibilitychange'));
			vis.mockRestore();
			expect(beacon).toHaveBeenCalledTimes(1);
			const [url, blob] = beacon.mock.calls[0] as unknown as [string, Blob];
			expect(url).toBe('/api/events');
			const body = JSON.parse(await blob.text());
			expect(body.events.some((e: { card_id: string; type: string }) => e.card_id === 'c_2' && e.type === 'impression')).toBe(true);
			const posted = fetchMock.mock.calls.filter(([u]) => String(u) === '/api/events');
			expect(posted).toHaveLength(0);
		});

		it('hidden then visible does not refetch or change the list', async () => {
			route({ '/api/feed': { cards: [card(1), card(2)], next_cursor: null } });
			render(Page);
			await screen.findByText('Hook 1');
			const feedCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).startsWith('/api/feed')).length;
			const before = feedCalls();
			const vis = vi.spyOn(document, 'visibilityState', 'get');
			vis.mockReturnValue('hidden');
			document.dispatchEvent(new Event('visibilitychange'));
			vis.mockReturnValue('visible');
			document.dispatchEvent(new Event('visibilitychange'));
			window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
			expect(feedCalls()).toBe(before);
			expect(order()).toHaveLength(2);
			vis.mockRestore();
		});
	});

	it('the end card checks again and appends only new cards', async () => {
		let calls = 0;
		const old = fakeCard({ id: 'c_old', hook: 'Old card' });
		const fresh = fakeCard({ id: 'c_new', hook: 'New card' });
		fetchMock.mockImplementation(async (url: string) => ({
			ok: true,
			headers: { get: () => null },
			json: async () =>
				url.startsWith('/api/feed')
					? { cards: calls++ === 0 ? [old] : [old, fresh], next_cursor: null }
					: { notifications: [], unread: 0, stories: [] }
		}));
		render(Page);
		await screen.findByText('Old card');
		await fireEvent.click(await screen.findByRole('button', { name: /check for new cards/i }));
		expect(await screen.findByText('New card')).toBeInTheDocument();
		expect(screen.getAllByRole('article')).toHaveLength(2);
	});

	it('shows the end card for an empty feed too', async () => {
		route({ '/api/feed': { cards: [], next_cursor: null } });
		render(Page);
		expect(await screen.findByRole('region', { name: 'End of feed' })).toHaveTextContent(
			'/codescroll-generate'
		);
	});

	it('has a bell linking to /notifications', async () => {
		route({ '/api/feed': feed, '/api/notifications': { notifications: [], unread: 4 } });
		render(Page);
		expect(await screen.findByTestId('badge')).toHaveTextContent('4');
		expect(screen.getByRole('link', { name: /Notifications/ })).toHaveAttribute(
			'href',
			'/notifications'
		);
	});

	it('puts stories, Saved and the bell in one top bar above the feed, not over it', async () => {
		route({
			'/api/feed': feed,
			'/api/stories': stories,
			'/api/notifications': { notifications: [], unread: 0 }
		});
		const { container } = render(Page);
		await screen.findByText('A hook');
		const bar = await screen.findByRole('banner', { name: 'Top bar' });
		expect(bar).toContainElement(await screen.findByRole('list', { name: 'Stories' }));
		expect(bar).toContainElement(screen.getByRole('link', { name: 'Saved' }));
		const feedEl = container.querySelector('.feed')!;
		expect(bar.compareDocumentPosition(feedEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(bar.contains(feedEl)).toBe(false);
	});

	it('tells the first card how tall the top bar is', async () => {
		route({ '/api/feed': feed, '/api/stories': { stories: [] } });
		const { container } = render(Page);
		await screen.findByText('A hook');
		const app = container.querySelector('.app') as HTMLElement;
		expect(app.style.getPropertyValue('--chrome-h')).toMatch(/^\d+px$/);
	});

	it('applies the playback speed from /api/prefs before showing cards', async () => {
		const beats = await import('#lib/beats.ts');
		route({ '/api/feed': feed, '/api/prefs': { playback_speed: 1.5 } });
		render(Page);
		await screen.findByText('A hook');
		expect(beats.playbackSpeed()).toBe(1.5);
		beats.setPlaybackSpeed(1);
	});

	it('still shows the feed when /api/prefs fails', async () => {
		fetchMock.mockImplementation(async (url: string) =>
			url.startsWith('/api/prefs')
				? { ok: false, status: 500, json: async () => ({}) }
				: { ok: true, headers: { get: () => null }, json: async () => structuredClone(feed) }
		);
		render(Page);
		expect(await screen.findByText('A hook')).toBeInTheDocument();
	});

	it('shows no stories row when there are no stories', async () => {
		route({ '/api/feed': feed, '/api/stories': { stories: [] } });
		render(Page);
		await screen.findByText('A hook');
		expect(screen.queryByRole('list', { name: 'Stories' })).toBeNull();
	});

	it('opens the story viewer from the stories row and marks the sha seen', async () => {
		route({ '/api/feed': feed, '/api/stories/seen': {}, '/api/stories': stories });
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'storefront story' }));
		expect(await screen.findByText('Fix it')).toBeInTheDocument();
		const seenCall = fetchMock.mock.calls.find((c) => c[0] === '/api/stories/seen');
		expect(JSON.parse(seenCall![1].body)).toEqual({ repo: 'storefront', shas: ['a'.repeat(40)] });
		await fireEvent.click(screen.getByRole('button', { name: 'Close' }));
		expect(screen.queryByRole('dialog')).toBeNull();
	});

	it('shows an offline banner when the feed came from cache', async () => {
		route({ '/api/feed': feed }, { 'X-From-Cache': '1' });
		render(Page);
		expect(await screen.findByText('Offline \u2014 showing your last batch')).toBeInTheDocument();
	});

	it('shows no offline banner for a fresh feed', async () => {
		route({ '/api/feed': feed });
		render(Page);
		await screen.findByText('A hook');
		expect(screen.queryByText(/Offline/)).toBeNull();
	});

	describe('dir filter', () => {
		afterEach(() => window.history.replaceState({}, '', '/'));
		const feedUrls = () =>
			fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith('/api/feed'));

		it('asks for the filtered feed and shows a chip', async () => {
			window.history.replaceState({}, '', '/?repo=storefront&dir=src%2Fsync');
			route({ '/api/feed': feed });
			render(Page);
			await screen.findByText('A hook');
			expect(feedUrls()[0]).toContain('repo=storefront');
			expect(feedUrls()[0]).toContain('dir=src%2Fsync');
			expect(screen.getByTestId('feed-filter')).toHaveTextContent('storefront/src/sync');
		});

		it('clears the filter and reloads the normal feed', async () => {
			window.history.replaceState({}, '', '/?repo=storefront&dir=src');
			route({ '/api/feed': feed });
			render(Page);
			await screen.findByText('A hook');
			await fireEvent.click(screen.getByRole('button', { name: 'Clear filter' }));
			await vi.waitFor(() => expect(screen.queryByTestId('feed-filter')).toBeNull());
			await vi.waitFor(() => expect(feedUrls().at(-1)).toBe('/api/feed?limit=20'));
			expect(window.location.search).toBe('');
		});

		it('shows no chip without a filter', async () => {
			route({ '/api/feed': feed });
			render(Page);
			await screen.findByText('A hook');
			expect(screen.queryByTestId('feed-filter')).toBeNull();
		});
	});
});
