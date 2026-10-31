import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import { fakeCard } from '#lib/components/fixtures.ts';

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal('fetch', fetchMock));
afterEach(() => {
	fetchMock.mockReset();
	vi.unstubAllGlobals();
});

describe('feed page', () => {
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
				headers: { get: (h: string) => (url.startsWith('/api/feed') ? feedHeaders[h] ?? null : null) },
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
				commits: [{ sha: 'a'.repeat(40), short: 'aaaaaaa', ts: 1, author: 'Ann', subject: 'Fix it', files: 2 }]
			}
		]
	};

	it('has a bell linking to /notifications', async () => {
		route({ '/api/feed': feed, '/api/notifications': { notifications: [], unread: 4 } });
		render(Page);
		expect(await screen.findByTestId('badge')).toHaveTextContent('4');
		expect(screen.getByRole('link', { name: /Notifications/ })).toHaveAttribute('href', '/notifications');
	});

	it('puts stories, Saved and the bell in one top bar above the feed, not over it', async () => {
		route({ '/api/feed': feed, '/api/stories': stories, '/api/notifications': { notifications: [], unread: 0 } });
		const { container } = render(Page);
		await screen.findByText('A hook');
		const bar = await screen.findByRole('banner', { name: 'Top bar' });
		expect(bar).toContainElement(await screen.findByRole('list', { name: 'Stories' }));
		expect(bar).toContainElement(screen.getByRole('link', { name: 'Saved' }));
		const feedEl = container.querySelector('.feed')!;
		expect(bar.compareDocumentPosition(feedEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(bar.contains(feedEl)).toBe(false);
	});

	it('gives the feed an exact height below the top bar, not a percentage', async () => {
		route({ '/api/feed': feed, '/api/stories': { stories: [] } });
		const { container } = render(Page);
		await screen.findByText('A hook');
		const app = container.querySelector('.app') as HTMLElement;
		expect(app.style.getPropertyValue('--feed-h')).toMatch(/^calc\(100dvh - \d+px\)$/);
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
});
