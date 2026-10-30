import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import { load } from './+page.ts';

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal('fetch', fetchMock));
afterEach(() => {
	fetchMock.mockReset();
	vi.unstubAllGlobals();
});

const body = {
	notifications: [
		{ id: 3, kind: 'new_kind', text: 'A new Spot the Bug', card_id: 'c_9', created_at: 300, read: false },
		{ id: 2, kind: 'new_cards', text: '12 new cards', card_id: null, created_at: 200, read: false },
		{ id: 1, kind: 'hot_file', text: 'auth.py was hot', card_id: null, created_at: 100, read: true }
	],
	unread: 2
};

async function setup() {
	fetchMock.mockResolvedValue({ ok: true, json: async () => body });
	const data = await load({} as never);
	render(Page, { data } as never);
	fetchMock.mockClear();
	fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
}

describe('/notifications', () => {
	it('loads all notifications and lists them in order, unread bold', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => body });
		const data = await load({} as never);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/notifications');
		render(Page, { data } as never);
		const items = screen.getAllByRole('listitem');
		expect(items.map((i) => i.textContent)).toEqual([
			expect.stringContaining('A new Spot the Bug'),
			expect.stringContaining('12 new cards'),
			expect.stringContaining('auth.py was hot')
		]);
		expect(items[0]).toHaveAttribute('data-unread', 'true');
		expect(items[2]).toHaveAttribute('data-unread', 'false');
	});

	it('shows an empty state', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({ notifications: [], unread: 0 }) });
		render(Page, { data: await load({} as never) } as never);
		expect(screen.getByText('No notifications')).toBeInTheDocument();
	});

	it('card notifications link to /card/{id} and mark read on tap', async () => {
		await setup();
		const link = screen.getByRole('link', { name: /Spot the Bug/ });
		expect(link).toHaveAttribute('href', '/card/c_9');
		link.addEventListener('click', (e) => e.preventDefault());
		await fireEvent.click(link);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toBe('/api/notifications/read');
		expect(JSON.parse(init.body)).toEqual({ ids: [3] });
	});

	it('tapping a notification without a card marks it read', async () => {
		await setup();
		await fireEvent.click(screen.getByRole('button', { name: /12 new cards/ }));
		expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ids: [2] });
		await waitFor(() =>
			expect(screen.getByRole('button', { name: /12 new cards/ }).closest('li')).toHaveAttribute('data-unread', 'false')
		);
	});

	it('Mark all read posts all and clears unread styling', async () => {
		await setup();
		await fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
		expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ all: true });
		await waitFor(() => expect(document.querySelectorAll('[data-unread="true"]')).toHaveLength(0));
	});
});
