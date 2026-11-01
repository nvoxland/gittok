import { render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import { load } from './+page.ts';

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal('fetch', fetchMock));
afterEach(() => {
	fetchMock.mockReset();
	vi.unstubAllGlobals();
});

describe('/repo/[name]/map', () => {
	it('loads the map via /api/repos/<name>/map and renders it', async () => {
		const body = {
			name: 'storefront',
			dirs: [
				{
					dir: 'src',
					cards_seen: 1,
					cards_available: 0,
					quiz_right: 0,
					quiz_wrong: 0,
					novelty: 0.5,
					verdicts: {}
				}
			]
		};
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({ params: { name: 'storefront' } } as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/repos/storefront/map');
		render(Page, { data } as never);
		expect(screen.getByTestId('map-src')).toHaveTextContent('50% known');
		expect(screen.getByRole('link', { name: /storefront/ })).toHaveAttribute(
			'href',
			'/repo/storefront'
		);
	});
});
