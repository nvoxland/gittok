import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCardStateForTest } from '#lib/cardState.ts';
import Card from './Card.svelte';
import type { Card as CardT } from '#lib/types.ts';
import { fakeCard } from './fixtures.ts';

describe('Card', () => {
	it('renders hook and one panel per depth entry', () => {
		const card = fakeCard({
			depth: [
				{ kind: 'explain', text: 'Plain words.' },
				{ kind: 'explain', text: 'More words.' }
			],
			resolved: { visual: null, depth: [null, null] }
		});
		const { container } = render(Card, { card });
		expect(screen.getByText(card.hook)).toBeInTheDocument();
		expect(container.querySelectorAll('[data-panel]')).toHaveLength(3);
		expect(container.querySelectorAll('.dot')).toHaveLength(3);
		expect(screen.getByText('@greybeard')).toBeInTheDocument();
		expect(screen.getByText('dry-deadpan')).toBeInTheDocument();
		expect(screen.getByText('gittok')).toBeInTheDocument();
	});

	it('renders text visual title, body and bullets', () => {
		const card = fakeCard({
			visual: { kind: 'text', title: 'Big Title', body: 'Some body', bullets: ['one', 'two'] }
		});
		render(Card, { card });
		expect(screen.getByText('Big Title')).toBeInTheDocument();
		expect(screen.getByText('Some body')).toBeInTheDocument();
		expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['one', 'two']);
	});

	it('renders code visual from resolved, not visual.excerpt', () => {
		const card = fakeCard({
			visual: {
				kind: 'code',
				repo: 'gittok',
				path: 'src/x.py',
				commit: 'abcdef1234567890',
				lines: [10, 11],
				excerpt: 'FAKE MODEL CODE',
				callouts: [{ line: 11, text: 'Look here' }]
			} as unknown as CardT['visual'],
			resolved: {
				visual: { code: 'real_line_a()\nreal_line_b()', language: 'python', start_line: 10 },
				depth: []
			}
		});
		const { container } = render(Card, { card });
		expect(container.textContent).toContain('real_line_a()');
		expect(container.textContent).not.toContain('FAKE MODEL CODE');
		expect(screen.getByText(/src\/x\.py/)).toBeInTheDocument();
		expect(screen.getByText(/abcdef1/)).toBeInTheDocument();
		expect(screen.getByText('Look here')).toBeInTheDocument();
		expect(screen.getByText(/L11/)).toBeInTheDocument();
		expect(container.querySelector('.line.hl .ln')?.textContent).toBe('11');
	});

	it('renders comments with @handles', () => {
		const card = fakeCard({
			comments: [
				{ persona: 'penny_learns', text: 'Wait, why?' },
				{ persona: 'archivist', text: 'Since 2019.' }
			]
		});
		const { container } = render(Card, { card });
		const items = [...container.querySelectorAll('.comments li')].map((li) => li.textContent?.trim());
		expect(items).toEqual(['@penny_learns: Wait, why?', '@archivist: Since 2019.']);
	});

	it('renders fallback for unknown visual kind', () => {
		const card = fakeCard({ visual: { kind: 'hologram' } as unknown as CardT['visual'] });
		render(Card, { card });
		expect(screen.getByText(/unsupported card type/i)).toBeInTheDocument();
		expect(screen.getByText(card.hook)).toBeInTheDocument();
	});

	it('renders code and diff depth panels from resolved', () => {
		const card = fakeCard({
			depth: [
				{ kind: 'code', repo: 'gittok', path: 'a.py', commit: 'aaaaaaa1111', lines: [5, 6] },
				{ kind: 'code_diff', repo: 'gittok', path: 'b.py', commit: 'bbbbbbb2222' }
			],
			resolved: {
				visual: null,
				depth: [
					{ code: 'depth_code()', language: 'python', start_line: 5 },
					{ diff: '-gone\n+here' }
				]
			}
		});
		const { container } = render(Card, { card });
		const panels = container.querySelectorAll('[data-panel]');
		expect(panels[1].textContent).toContain('depth_code()');
		expect(panels[1].querySelector('.ln')?.textContent).toBe('5');
		expect(panels[1].textContent).toContain('gittok · a.py · aaaaaaa');
		expect(panels[2].querySelector('.add')?.textContent).toBe('+here');
		expect(panels[2].querySelector('.del')?.textContent).toBe('-gone');
	});

	it('reports panel changes on horizontal scroll and marks the active dot', async () => {
		const card = fakeCard({
			depth: [{ kind: 'explain', text: 'x' }],
			resolved: { visual: null, depth: [null] }
		});
		const calls: number[] = [];
		const { container } = render(Card, { card, onPanelChange: (i: number) => calls.push(i) });
		const row = container.querySelector('.panels') as HTMLElement;
		Object.defineProperty(row, 'clientWidth', { value: 300, configurable: true });
		row.scrollLeft = 300;
		await fireEvent.scroll(row);
		expect(calls).toEqual([1]);
		expect(container.querySelectorAll('.dot')[1]).toHaveClass('active');
	});
});

describe('Card actions', () => {
	afterEach(() => {
		localStorage.clear();
		resetCardStateForTest();
	});

	it('like toggles with aria-pressed, emits {on} and persists', async () => {
		const calls: [string, Record<string, unknown> | undefined][] = [];
		const card = fakeCard({ id: 'c_like' });
		const { unmount } = render(Card, { card, onAction: (t: string, d?: Record<string, unknown>) => calls.push([t, d]) });
		const btn = screen.getByRole('button', { name: /like/i });
		expect(btn).toHaveAttribute('aria-pressed', 'false');
		await fireEvent.click(btn);
		expect(btn).toHaveAttribute('aria-pressed', 'true');
		await fireEvent.click(btn);
		expect(btn).toHaveAttribute('aria-pressed', 'false');
		expect(calls).toEqual([
			['like', { on: true }],
			['like', { on: false }]
		]);
		await fireEvent.click(btn);
		unmount();
		resetCardStateForTest();
		render(Card, { card });
		expect(screen.getByRole('button', { name: /like/i })).toHaveAttribute('aria-pressed', 'true');
	});

	it('save toggles and emits {on}', async () => {
		const calls: [string, Record<string, unknown> | undefined][] = [];
		render(Card, { card: fakeCard({ id: 'c_save' }), onAction: (t: string, d?: Record<string, unknown>) => calls.push([t, d]) });
		const btn = screen.getByRole('button', { name: /save/i });
		await fireEvent.click(btn);
		expect(btn).toHaveAttribute('aria-pressed', 'true');
		expect(calls).toEqual([['save', { on: true }]]);
		expect(JSON.parse(localStorage.getItem('codescroll.card-state')!).c_save.saved).toBe(true);
	});

	it('explain more scrolls the depth row to the first explain panel and emits', async () => {
		const calls: [string, unknown][] = [];
		const card = fakeCard({
			depth: [
				{ kind: 'code', repo: 'gittok', path: 'a.py', commit: 'abcdef1234', lines: [1, 2] },
				{ kind: 'explain', text: 'Plain words.' }
			],
			resolved: { visual: null, depth: [null, null] }
		});
		const { container } = render(Card, { card, onAction: (t: string, d?: unknown) => calls.push([t, d]) });
		const row = container.querySelector('.panels') as HTMLElement;
		Object.defineProperty(row, 'clientWidth', { value: 300, configurable: true });
		row.scrollTo = vi.fn() as never;
		await fireEvent.click(screen.getByRole('button', { name: /explain more/i }));
		expect(row.scrollTo).toHaveBeenCalledWith({ left: 600, behavior: 'smooth' });
		expect(calls).toEqual([['explain_more', {}]]);
	});

	it('emits source_tap with the panel index from a code panel link', async () => {
		const calls: [string, unknown][] = [];
		const card = fakeCard({
			depth: [{ kind: 'code', repo: 'gittok', path: 'a.py', commit: 'abcdef1234', lines: [1, 2] }],
			resolved: { visual: null, depth: [{ code: 'x = 1', language: 'python', start_line: 1 }] }
		});
		render(Card, { card, onAction: (t: string, d?: unknown) => calls.push([t, d]) });
		await fireEvent.click(screen.getByRole('link', { name: /a\.py/ }));
		expect(calls).toEqual([['source_tap', { panel: 1 }]]);
	});

	it('emits source_tap from a diff panel link', async () => {
		const calls: [string, unknown][] = [];
		const card = fakeCard({
			depth: [{ kind: 'code_diff', repo: 'gittok', path: 'b.py', commit: 'abcdef1234' }],
			resolved: { visual: null, depth: [{ diff: '+x' }] }
		});
		render(Card, { card, onAction: (t: string, d?: unknown) => calls.push([t, d]) });
		await fireEvent.click(screen.getByRole('link', { name: /b\.py/ }));
		expect(calls).toEqual([['source_tap', { panel: 1 }]]);
	});
});

describe('Card quiz', () => {
	const fetchMock = vi.fn();
	beforeEach(() => vi.stubGlobal('fetch', fetchMock));
	afterEach(() => {
		fetchMock.mockReset();
		vi.unstubAllGlobals();
		sessionStorage.clear();
		resetCardStateForTest();
	});

	const quiz = (over: Partial<CardT> = {}) =>
		fakeCard({
			id: 'q_1',
			format: 'quiz',
			story_type: 'quiz',
			interaction: { question: 'What is wrong here?', choices: ['Alpha', 'Beta', 'Gamma'] },
			comments: [{ persona: 'greybeard', text: 'Told you so.' }],
			...over
		});
	const reply = (body: unknown) => fetchMock.mockResolvedValue({ ok: true, json: async () => body });

	it('shows the question and choices, no comments before answering', () => {
		render(Card, { card: quiz() });
		expect(screen.getByText('What is wrong here?')).toBeInTheDocument();
		expect(screen.getAllByRole('button', { name: /^(Alpha|Beta|Gamma)$/ })).toHaveLength(3);
		expect(screen.queryByText(/Told you so/)).toBeNull();
	});

	it('correct answer: posts, emits answer, reveals explanation, disables choices', async () => {
		reply({ correct: true, answer_index: 1, explanation: 'Beta wins.' });
		const calls: [string, unknown][] = [];
		render(Card, { card: quiz(), onAction: (t: string, d?: unknown) => calls.push([t, d]) });
		await fireEvent.click(screen.getByRole('button', { name: 'Beta' }));
		expect(await screen.findByText('Beta wins.')).toBeInTheDocument();
		expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ card_id: 'q_1', choice: 1 });
		// The server records the answer event (POST /api/answer); the card must not emit a second one.
		expect(calls.filter(([t]) => t === 'answer')).toEqual([]);
		expect(screen.getByRole('button', { name: 'Beta' })).toHaveClass('correct');
		for (const n of ['Alpha', 'Beta', 'Gamma'])
			expect(screen.getByRole('button', { name: n })).toBeDisabled();
		expect(screen.getByText(/Told you so/)).toBeInTheDocument();
		expect(screen.getByText('Correct')).toBeInTheDocument();
	});

	it('wrong answer: marks the pick wrong and the right choice correct', async () => {
		reply({ correct: false, answer_index: 2, explanation: 'It was Gamma.' });
		const calls: [string, unknown][] = [];
		render(Card, { card: quiz(), onAction: (t: string, d?: unknown) => calls.push([t, d]) });
		await fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
		expect(await screen.findByText('It was Gamma.')).toBeInTheDocument();
		// The server records the answer event (POST /api/answer); the card must not emit a second one.
		expect(calls.filter(([t]) => t === 'answer')).toEqual([]);
		expect(screen.getByRole('button', { name: 'Alpha' })).toHaveClass('wrong');
		expect(screen.getByRole('button', { name: 'Gamma' })).toHaveClass('correct');
		expect(screen.getByText('Incorrect')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Beta' }));
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('this_or_that: says there is no right answer and shows the comments', async () => {
		reply({ correct: null, answer_index: null, explanation: '' });
		const calls: [string, unknown][] = [];
		render(Card, {
			card: quiz({
				story_type: 'this_or_that',
				interaction: { question: 'Tabs or spaces?', choices: ['Tabs', 'Spaces'] }
			}),
			onAction: (t: string, d?: unknown) => calls.push([t, d])
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Spaces' }));
		expect(
			await screen.findByText('No right answer. See what the personas think.')
		).toBeInTheDocument();
		// The server records the answer event (POST /api/answer); the card must not emit a second one.
		expect(calls.filter(([t]) => t === 'answer')).toEqual([]);
		expect(screen.getByText(/Told you so/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Tabs' })).toBeDisabled();
	});

	it('remembers the answer for the session', async () => {
		reply({ correct: true, answer_index: 0, explanation: 'Alpha.' });
		const card = quiz();
		const { unmount } = render(Card, { card });
		await fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
		await screen.findByText('Alpha.');
		unmount();
		resetCardStateForTest();
		render(Card, { card });
		expect(screen.getByText('Alpha.')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Beta' })).toBeDisabled();
	});
});
