import { render, screen } from '@testing-library/svelte';
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

describe('/repo/[name]', () => {
	it('loads the profile via /api/repos and renders stats and cards', async () => {
		const body = {
			name: 'storefront',
			mascot: 'otter',
			mascot_image: null,
			group: null,
			stats: {
				commits_365: 12,
				authors_365: 2,
				last_commit_ts: 1761826800,
				top_files: [{ path: 'a.clj', commits: 5 }],
				top_dirs: [{ path: 'src', commits: 9 }]
			},
			cards: [fakeCard({ id: 'c_9', hook: 'Hook nine' })]
		};
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({ params: { name: 'storefront' } } as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/repos/storefront');
		render(Page, { data } as never);
		expect(screen.getByText('12')).toBeInTheDocument();
		expect(screen.getByText('a.clj')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Hook nine/ })).toHaveAttribute('href', '/card/c_9');
	});
});
