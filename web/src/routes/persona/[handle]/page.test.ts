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

describe('/persona/[handle]', () => {
	it('loads /api/personas and shows the bio, posts and comments', async () => {
		const body = {
			handle: 'greybeard',
			name: 'Greybeard',
			voice: 'Grumpy senior engineer.',
			bio: 'Has seen every outage twice.',
			posts: [fakeCard({ id: 'c_5', hook: 'Hook five' })],
			comments: [{ card_id: 'c_7', repo: 'gittok', hook: 'Other hook', text: 'Told you so.' }]
		};
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({ params: { handle: 'greybeard' } } as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/personas/greybeard');
		const { container } = render(Page, { data } as never);
		expect(screen.getByRole('heading', { name: 'Greybeard' })).toBeInTheDocument();
		expect(screen.getByText('Has seen every outage twice.')).toBeInTheDocument();
		expect(container.querySelector('header img')!.getAttribute('src')).toBe(
			'/api/avatars/greybeard'
		);
		expect(screen.getByRole('link', { name: /Hook five/ })).toHaveAttribute('href', '/card/c_5');
		expect(screen.getByRole('link', { name: /Told you so/ })).toHaveAttribute('href', '/card/c_7');
	});

	it('falls back to the voice when there is no bio', async () => {
		const body = {
			handle: 'greybeard',
			name: 'Greybeard',
			voice: 'Grumpy senior engineer.',
			bio: null,
			posts: [],
			comments: []
		};
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({ params: { handle: 'greybeard' } } as never);
		render(Page, { data } as never);
		expect(screen.getByText('Grumpy senior engineer.')).toBeInTheDocument();
		expect(screen.getByText('No posts yet')).toBeInTheDocument();
	});
});
