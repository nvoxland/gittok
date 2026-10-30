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

describe('/saved', () => {
	it('lists saved cards as links to /card/{id}', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			json: async () => ({
				cards: [fakeCard({ id: 'c_1', hook: 'First saved' }), fakeCard({ id: 'c_2', hook: 'Second saved' })]
			})
		});
		const data = await load({} as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/saved');
		render(Page, { data } as never);
		expect(screen.getByRole('link', { name: /First saved/ })).toHaveAttribute('href', '/card/c_1');
		expect(screen.getByRole('link', { name: /Second saved/ })).toHaveAttribute('href', '/card/c_2');
		expect(screen.getByRole('link', { name: /Feed/ })).toHaveAttribute('href', '/');
	});

	it('shows an empty state', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ cards: [] }) });
		const data = await load({} as never);
		render(Page, { data } as never);
		expect(screen.getByText('Nothing saved yet')).toBeInTheDocument();
	});
});
