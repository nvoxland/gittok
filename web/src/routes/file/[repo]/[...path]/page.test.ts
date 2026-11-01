import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import { load } from './+page.ts';
import { fakeCard } from '#lib/components/fixtures.ts';

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal('fetch', fetchMock));
afterEach(() => {
	fetchMock.mockReset();
	vi.unstubAllGlobals();
});

const body = {
	repo: 'gittok',
	path: 'src/shipping.clj',
	history: {
		commits: 41,
		last_touched: '2026-10-30',
		authors: [{ name: 'Ada', commits: 30 }]
	},
	cards: [fakeCard({ id: 'c_9', hook: 'Hook nine' })],
	followed: false
};

describe('/file/[repo]/[...path]', () => {
	it('loads /api/files and shows history and the cards about the path', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({
			params: { repo: 'gittok', path: 'src/shipping.clj' }
		} as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/files/gittok/src/shipping.clj');
		render(Page, { data } as never);
		expect(screen.getByText('src/shipping.clj')).toBeInTheDocument();
		expect(screen.getByText('41')).toBeInTheDocument();
		expect(screen.getByText('2026-10-30')).toBeInTheDocument();
		expect(screen.getByText(/Ada/)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Hook nine/ })).toHaveAttribute('href', '/card/c_9');
	});

	it('Follow posts to /api/follows and flips to Following', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({
			params: { repo: 'gittok', path: 'src/shipping.clj' }
		} as never);
		render(Page, { data } as never);
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ followed: true }) });
		await fireEvent.click(screen.getByRole('button', { name: 'Follow' }));
		const [url, init] = fetchMock.mock.calls[1];
		expect(url).toBe('/api/follows');
		expect(JSON.parse(init.body)).toEqual({
			repo: 'gittok',
			path: 'src/shipping.clj',
			on: true
		});
		expect(await screen.findByRole('button', { name: 'Following' })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
	});
});
