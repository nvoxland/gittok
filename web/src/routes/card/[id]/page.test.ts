import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Page from './+page.svelte';
import { load } from './+page.ts';
import { fakeCard } from '#lib/components/fixtures.ts';
import { setAnswer, setFlag } from '#lib/cardState.ts';

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

	it('sends like and save events to the server when the page goes away', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
		const { unmount } = render(Page, { data: { card: fakeCard({ id: 'c_7' }) } } as never);
		await fireEvent.click(screen.getByLabelText('Like'));
		await fireEvent.click(screen.getByLabelText('Save'));
		unmount();
		const post = fetchMock.mock.calls.find(([u]) => u === '/api/events');
		expect(post).toBeTruthy();
		const events = JSON.parse(post![1].body).events;
		expect(events.map((e: { type: string; card_id: string }) => [e.card_id, e.type])).toEqual([
			['c_7', 'like'],
			['c_7', 'save']
		]);
	});

	it('takes the saved state from the server when it knows it', async () => {
		localStorage.clear();
		fetchMock.mockImplementation(async (url: string) => ({
			ok: true,
			json: async () => (url === '/api/saved' ? { cards: [fakeCard({ id: 'c_8' })] } : fakeCard({ id: 'c_8' }))
		}));
		const data = await load({ params: { id: 'c_8' } } as never);
		render(Page, { data } as never);
		expect(screen.getByLabelText('Save').getAttribute('aria-pressed')).toBe('true');
	});

	it('does not keep the state of the previous card after navigation', async () => {
		localStorage.clear();
		setFlag('c_a', 'liked', true);
		setAnswer('c_a', { correct: true, answer_index: 1, explanation: 'because A', choice: 1 });
		const a = fakeCard({ id: 'c_a', hook: 'Hook A', interaction: { question: 'Q?', choices: ['x', 'y'] } });
		const b = fakeCard({ id: 'c_b', hook: 'Hook B', interaction: { question: 'Other?', choices: ['p', 'q'] } });
		const { rerender } = render(Page, { data: { card: a } } as never);
		expect(screen.getByLabelText('Like').getAttribute('aria-pressed')).toBe('true');
		await rerender({ data: { card: b } } as never);
		expect(screen.getByText('Hook B')).toBeInTheDocument();
		expect(screen.getByLabelText('Like').getAttribute('aria-pressed')).toBe('false');
		expect(screen.queryByText('because A')).toBeNull();
	});
});
