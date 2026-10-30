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

describe('/card/[id]', () => {
	it('loads one card and renders it', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			json: async () => fakeCard({ id: 'c_7', hook: 'Single card hook' })
		});
		const data = await load({ params: { id: 'c_7' } } as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/cards/c_7');
		const { container } = render(Page, { data } as never);
		expect(screen.getByText('Single card hook')).toBeInTheDocument();
		expect(container.querySelector('[data-card-id="c_7"]')).not.toBeNull();
	});
});
