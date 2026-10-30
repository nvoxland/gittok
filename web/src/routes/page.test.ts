import { render, screen } from '@testing-library/svelte';
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
});
