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
			unobserve() {}
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

	it('a thumbs-down sends the events, then ranks the unseen cards ahead again', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		class FakeIO {
			constructor(public cb: (e: Partial<IntersectionObserverEntry>[]) => void) {}
			observe(target: Element) {
				if (target.getAttribute('data-card-id') === 'c_1')
					this.cb([{ target, isIntersecting: true, intersectionRatio: 0.9 }]);
			}
			unobserve() {}
			disconnect() {}
		}
		vi.stubGlobal('IntersectionObserver', FakeIO);
		const card = (n: number) => fakeCard({ id: `c_${n}`, hook: `Hook ${n}` });
		const first = { cards: [card(1), card(2), card(3)], next_cursor: 'cur1' };
		const fresh = { cards: [card(4), card(2)], next_cursor: 'cur2' };
		const urls: string[] = [];
		fetchMock.mockImplementation(async (url: string) => {
			urls.push(String(url));
			return {
				ok: true,
				headers: { get: () => null },
				json: async () =>
					url.startsWith('/api/feed')
						? structuredClone(url.includes('drop=') ? fresh : first)
						: { notifications: [], unread: 0, stories: [] }
			};
		});
		try {
			render(Page);
			await screen.findByText('Hook 1');
			const less = screen.getAllByRole('button', { name: 'Show less like this' })[0];
			await fireEvent.click(less);
			await vi.advanceTimersByTimeAsync(2000);
			expect(await screen.findByText('Hook 4')).toBeInTheDocument();
			const hooks = screen.getAllByRole('article').map((a) => a.textContent ?? '');
			expect(hooks.findIndex((t) => t.includes('Hook 4'))).toBe(1);
			expect(hooks.some((t) => t.includes('Hook 3'))).toBe(false);
			const refresh = urls.findIndex((u) => u.includes('drop=c_2%2Cc_3'));
			const events = urls.findIndex((u) => u === '/api/events');
			expect(refresh).toBeGreaterThan(-1);
			expect(urls[refresh]).toContain('cursor=cur1');
			expect(events).toBeGreaterThan(-1);
			expect(events).toBeLessThan(refresh);
		} finally {
			vi.useRealTimers();
		}
	});

	it('a thumbs-down taken back at once does not refresh the feed', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		const urls: string[] = [];
		fetchMock.mockImplementation(async (url: string) => {
			urls.push(String(url));
			return {
				ok: true,
				headers: { get: () => null },
				json: async () =>
					url.startsWith('/api/feed')
						? { cards: [fakeCard({ id: 'c_1', hook: 'Hook 1' })], next_cursor: 'cur1' }
						: { notifications: [], unread: 0, stories: [] }
			};
		});
		try {
			render(Page);
			await screen.findByText('Hook 1');
			const less = screen.getByRole('button', { name: 'Show less like this' });
			await fireEvent.click(less);
			await fireEvent.click(less);
			await vi.advanceTimersByTimeAsync(2000);
			expect(urls.some((u) => u.includes('drop='))).toBe(false);
		} finally {
			vi.useRealTimers();
		}
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
		expect(end).toHaveTextContent('"make more cards"');
		const articles = screen.getAllByRole('article');
		expect(articles[articles.length - 1].compareDocumentPosition(end)).toBe(
			Node.DOCUMENT_POSITION_FOLLOWING
		);
	});

	it('the end card says that more cards come by themselves, and how to ask for more now', async () => {
		route({ '/api/feed': { cards: [fakeCard({ hook: 'Only card' })], next_cursor: null, generating: false } });
		render(Page);
		const end = await screen.findByRole('region', { name: 'End of feed' });
		expect(end).toHaveTextContent(
			'GitTok makes more cards by itself while a session of your coding agent is open in your GitTok directory.'
		);
		expect(end).toHaveTextContent('To get more right away, ask the agent there: "make more cards".');
		// What to say, not a tool: no product name and no command.
		expect(end).not.toHaveTextContent('/gittok-generate');
		expect(end).not.toHaveTextContent('Claude Code');
		expect(end).not.toHaveTextContent(/being made now/i);
		expect(screen.getByRole('button', { name: /check for new cards/i })).toBeInTheDocument();
	});

	it('the end card says so when new cards are being made now', async () => {
		route({ '/api/feed': { cards: [fakeCard({ hook: 'Only card' })], next_cursor: null, generating: true } });
		render(Page);
		const end = await screen.findByRole('region', { name: 'End of feed' });
		expect(end).toHaveTextContent(/caught up/i);
		expect(end).toHaveTextContent('New cards are being made now. They will appear here.');
		expect(end).not.toHaveTextContent('/gittok-generate');
		expect(screen.getByRole('button', { name: /check for new cards/i })).toBeInTheDocument();
	});

	it('the check button updates whether cards are being made', async () => {
		localStorage.clear(); // no remembered card: this mock serves only the feed
		let n = 0;
		const only = fakeCard({ id: 'c_only', hook: 'Only card' });
		fetchMock.mockImplementation(async (url: string) => ({
			ok: true,
			headers: { get: () => null },
			json: async () =>
				url.startsWith('/api/feed')
					? { cards: [structuredClone(only)], next_cursor: null, generating: n++ > 0 }
					: { notifications: [], unread: 0, stories: [] }
		}));
		render(Page);
		const end = await screen.findByRole('region', { name: 'End of feed' });
		expect(end).not.toHaveTextContent(/being made now/i);
		await fireEvent.click(screen.getByRole('button', { name: /check for new cards/i }));
		await screen.findByText(/being made now/i);
	});

	it('a cached feed does not claim that cards are being made', async () => {
		route(
			{ '/api/feed': { cards: [fakeCard({ hook: 'Only card' })], next_cursor: null, generating: true } },
			{ 'X-From-Cache': '1' }
		);
		render(Page);
		const end = await screen.findByRole('region', { name: 'End of feed' });
		expect(end).not.toHaveTextContent(/being made now/i);
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
			expect(localStorage.getItem('gittok.current')).toBe('c_2');
			expect(history.scrollRestoration).toBe('manual');
		});

		it('a reload with a changed feed puts the remembered card first; unseen cards stay below', async () => {
			localStorage.setItem('gittok.current', 'c_3');
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
			localStorage.setItem('gittok.current', 'c_9');
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
			// Not at the end of the feed: coming back changes nothing.
			route({ '/api/feed': { cards: [card(1), card(2)], next_cursor: 'more' } });
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

	function feedRoutes(responses: (url: string) => unknown) {
		const urls: string[] = [];
		fetchMock.mockImplementation(async (url: string) => {
			urls.push(String(url));
			return {
				ok: true,
				headers: { get: () => null },
				json: async () =>
					url.startsWith('/api/feed')
						? responses(String(url))
						: { notifications: [], unread: 0, stories: [] }
			};
		});
		return urls;
	}

	it('while cards are being made, the end card adds them as they come', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
		const one = fakeCard({ id: 'c_1', hook: 'Hook 1' });
		const two = fakeCard({ id: 'c_2', hook: 'Hook 2' });
		const urls = feedRoutes((u) =>
			u.includes('cursor=sent1')
				? { cards: [two], next_cursor: null, cursor: 'sent2', generating: false }
				: { cards: [one], next_cursor: null, cursor: 'sent1', generating: true }
		);
		try {
			render(Page);
			await screen.findByText('Hook 1');
			await vi.advanceTimersByTimeAsync(11_000);
			expect(await screen.findByText('Hook 2')).toBeInTheDocument();
			expect(urls.some((u) => u.includes('cursor=sent1'))).toBe(true);
			// The run is over: no more checks.
			const asked = urls.filter((u) => u.startsWith('/api/feed')).length;
			await vi.advanceTimersByTimeAsync(60_000);
			expect(urls.filter((u) => u.startsWith('/api/feed')).length).toBe(asked);
		} finally {
			vi.useRealTimers();
		}
	});

	it('coming back to the app at the end of the feed checks for new cards', async () => {
		const one = fakeCard({ id: 'c_1', hook: 'Hook 1' });
		const two = fakeCard({ id: 'c_2', hook: 'Hook 2' });
		const urls = feedRoutes((u) =>
			u.includes('cursor=sent1')
				? { cards: [two], next_cursor: null, cursor: 'sent2' }
				: { cards: [one], next_cursor: null, cursor: 'sent1' }
		);
		render(Page);
		await screen.findByText('Hook 1');
		const vis = vi.spyOn(document, 'visibilityState', 'get');
		vis.mockReturnValue('hidden');
		document.dispatchEvent(new Event('visibilitychange'));
		vis.mockReturnValue('visible');
		document.dispatchEvent(new Event('visibilitychange'));
		expect(await screen.findByText('Hook 2')).toBeInTheDocument();
		expect(urls.some((u) => u.includes('cursor=sent1'))).toBe(true);
		vis.mockRestore();
	});

	it('Check for new cards asks with the cursor of what was sent', async () => {
		const urls = feedRoutes(() => ({
			cards: [fakeCard({ id: 'c_1', hook: 'Hook 1' })],
			next_cursor: null,
			cursor: 'sent1'
		}));
		render(Page);
		await screen.findByText('Hook 1');
		await fireEvent.click(await screen.findByRole('button', { name: /check for new cards/i }));
		await screen.findByText('No new cards yet.');
		expect(urls.filter((u) => u.startsWith('/api/feed')).at(-1)).toContain('cursor=sent1');
	});

	it('shows the end card for an empty feed too', async () => {
		route({ '/api/feed': { cards: [], next_cursor: null } });
		render(Page);
		expect(await screen.findByRole('region', { name: 'End of feed' })).toHaveTextContent(
			'"make more cards"'
		);
	});

	describe('errors, empty and unpaired states', () => {
		const card = (n: number) => fakeCard({ id: `c_${n}`, hook: `Hook ${n}` });
		beforeEach(() => localStorage.clear());

		type Reply = { status?: number; body?: unknown };
		/** `feed(url, n)` answers the n-th /api/feed call; other routes get `rest` or an empty body. */
		function serve(feed: (url: string, n: number) => Reply, rest: Record<string, Reply> = {}) {
			let n = 0;
			fetchMock.mockImplementation(async (url: string) => {
				const key = Object.keys(rest).find((k) => url.startsWith(k));
				const r: Reply = url.startsWith('/api/feed')
					? feed(url, n++)
					: key
						? rest[key]
						: { body: { notifications: [], unread: 0, stories: [] } };
				const status = r.status ?? 200;
				return {
					ok: status < 400,
					status,
					headers: { get: () => null },
					json: async () => structuredClone(r.body ?? {})
				};
			});
		}
		function nearEnd() {
			let near: (() => void) | undefined;
			class FakeIO {
				constructor(public cb: (e: Partial<IntersectionObserverEntry>[]) => void) {}
				observe(target: Element) {
					if (target.getAttribute('data-card-id') === 'c_1')
						near = () => this.cb([{ target, isIntersecting: true, intersectionRatio: 0.9 }]);
				}
				unobserve() {}
				disconnect() {}
			}
			vi.stubGlobal('IntersectionObserver', FakeIO);
			return () => near!();
		}

		it('says so when the next page fails, and Try again loads it', async () => {
			const fire = nearEnd();
			let fail = true;
			serve((url) => {
				if (!url.includes('cursor=cur1')) return { body: { cards: [card(1), card(2)], next_cursor: 'cur1' } };
				return fail ? { status: 500 } : { body: { cards: [card(3)], next_cursor: null } };
			});
			render(Page);
			await screen.findByText('Hook 1');
			fire();
			const alert = await screen.findByRole('alert');
			expect(alert).toHaveTextContent(/could not load more cards/i);
			expect(alert).toHaveTextContent('500');
			expect(screen.getAllByRole('article')).toHaveLength(2); // the cards on screen stay
			fail = false;
			await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
			expect(await screen.findByText('Hook 3')).toBeInTheDocument();
			expect(screen.queryByRole('alert')).toBeNull();
		});

		it('says so when Check for new cards fails; it is not "no new cards"', async () => {
			let fail = true;
			serve((_url, n) => {
				if (n === 0) return { body: { cards: [card(1)], next_cursor: null } };
				return fail ? { status: 503 } : { body: { cards: [card(1), card(2)], next_cursor: null } };
			});
			render(Page);
			await screen.findByText('Hook 1');
			await fireEvent.click(screen.getByRole('button', { name: /check for new cards/i }));
			const alert = await screen.findByRole('alert');
			expect(alert).toHaveTextContent(/could not check for new cards/i);
			expect(alert).toHaveTextContent('503');
			expect(screen.queryByText('No new cards yet.')).toBeNull();
			fail = false;
			await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
			expect(await screen.findByText('Hook 2')).toBeInTheDocument();
			expect(screen.queryByRole('alert')).toBeNull();
		});

		it('with no repos configured, says how to add one instead of "all caught up"', async () => {
			serve(() => ({ body: { cards: [], next_cursor: null } }), { '/api/repos': { body: { repos: [] } } });
			render(Page);
			const empty = await screen.findByRole('region', { name: 'No repos configured' });
			expect(empty).toHaveTextContent(/no repos are configured/i);
			expect(empty).toHaveTextContent(/ask Claude to add one/i);
			expect(empty).toHaveTextContent('add the repo at ~/src/myapp');
			expect(empty).toHaveTextContent('gittok repos add <name> <path-or-url>');
			const text = empty.textContent ?? '';
			expect(text.indexOf('add the repo at')).toBeLessThan(text.indexOf('gittok repos add'));
			expect(empty).toHaveTextContent(/Claude then makes the first cards/i);
			expect(screen.queryByText(/caught up/i)).toBeNull();
			expect(screen.queryByRole('note')).toBeNull(); // no swipe hints with nothing to swipe
		});

		it('with repos but no cards, keeps the caught-up card', async () => {
			serve(() => ({ body: { cards: [], next_cursor: null } }), {
				'/api/repos': { body: { repos: [{ name: 'storefront', ref: 'HEAD', head_sha: null, group: null }] } }
			});
			render(Page);
			expect(await screen.findByRole('region', { name: 'End of feed' })).toHaveTextContent(/caught up/i);
			expect(screen.queryByRole('region', { name: 'No repos configured' })).toBeNull();
		});

		it('keeps the caught-up card when the repos call fails', async () => {
			serve(() => ({ body: { cards: [], next_cursor: null } }), { '/api/repos': { status: 500 } });
			render(Page);
			expect(await screen.findByRole('region', { name: 'End of feed' })).toBeInTheDocument();
		});

		it('the empty state checks again, and shows the feed once a repo has cards', async () => {
			let repos: unknown[] = [];
			serve((_url, n) => ({ body: { cards: n === 0 ? [] : [card(1)], next_cursor: null } }), {
				'/api/repos': { get body() { return { repos }; } }
			});
			render(Page);
			await screen.findByRole('region', { name: 'No repos configured' });
			repos = [{ name: 'storefront', ref: 'HEAD', head_sha: null, group: null }];
			await fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
			expect(await screen.findByText('Hook 1')).toBeInTheDocument();
			expect(screen.queryByRole('region', { name: 'No repos configured' })).toBeNull();
		});

		it('on 401, says the device is not paired and how to pair it; Try again reloads', async () => {
			let paired = false;
			serve(() => (paired ? { body: { cards: [card(1)], next_cursor: null } } : { status: 401 }));
			render(Page);
			const alert = await screen.findByRole('alert');
			expect(alert).toHaveTextContent(/this device is not paired/i);
			expect(alert).toHaveTextContent(/ask Claude for the pairing QR code/i);
			expect(alert).toHaveTextContent(/scan it with this device/i);
			expect(alert).toHaveTextContent(/on the computer that runs GitTok/i);
			expect(alert).not.toHaveTextContent('pair:');
			expect(alert).not.toHaveTextContent(/failed to load feed/i);
			paired = true;
			await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
			expect(await screen.findByText('Hook 1')).toBeInTheDocument();
			expect(screen.queryByRole('alert')).toBeNull();
		});

		it('another first-load failure shows the error with a Try again button', async () => {
			let fail = true;
			serve(() => (fail ? { status: 500 } : { body: { cards: [card(1)], next_cursor: null } }));
			render(Page);
			const alert = await screen.findByRole('alert');
			expect(alert).toHaveTextContent(/failed to load feed/i);
			expect(alert).toHaveTextContent('500');
			fail = false;
			await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
			expect(await screen.findByText('Hook 1')).toBeInTheDocument();
		});

		it('a 401 on a later page also says the device is not paired', async () => {
			const fire = nearEnd();
			serve((url) =>
				url.includes('cursor=cur1')
					? { status: 401 }
					: { body: { cards: [card(1), card(2)], next_cursor: 'cur1' } }
			);
			render(Page);
			await screen.findByText('Hook 1');
			fire();
			expect(await screen.findByRole('alert')).toHaveTextContent(/this device is not paired/i);
		});
	});

	describe('gesture hints', () => {
		beforeEach(() => localStorage.clear());

		it('shows the one-time swipe hints over the feed, and not after they were dismissed', async () => {
			route({ '/api/feed': { cards: [fakeCard({ hook: 'A hook' })], next_cursor: 'more' } });
			const first = render(Page);
			await screen.findByText('A hook');
			expect(screen.getByRole('note', { name: 'How to use the feed' })).toBeInTheDocument();
			await fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
			first.unmount();
			render(Page);
			await screen.findByText('A hook');
			expect(screen.queryByRole('note')).toBeNull();
		});

		it('shows no hints while the feed is loading or failed', async () => {
			fetchMock.mockResolvedValue({ ok: false, status: 500, headers: { get: () => null } });
			render(Page);
			await screen.findByRole('alert');
			expect(screen.queryByRole('note')).toBeNull();
		});
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

	it('opens on the first card, a full screen, with the top bar scrolled away above it', async () => {
		const into = vi.fn();
		const real = Element.prototype.scrollIntoView;
		Element.prototype.scrollIntoView = into;
		try {
			route({ '/api/feed': feed, '/api/stories': { stories: [] } });
			const { container } = render(Page);
			await screen.findByText('A hook');
			await vi.waitFor(() => expect(into).toHaveBeenCalled());
			const first = container.querySelector('[data-card-id]');
			expect(into.mock.contexts[0]).toBe(first);
			expect(into.mock.calls[0][0]).toMatchObject({ block: 'start', behavior: 'instant' });
		} finally {
			Element.prototype.scrollIntoView = real;
		}
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
