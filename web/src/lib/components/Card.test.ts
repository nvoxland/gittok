import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCardStateForTest } from '#lib/cardState.ts';
import Card from './Card.svelte';
import type { Card as CardT } from '#lib/types.ts';
import { fakeCard } from './fixtures.ts';

describe('Card', () => {
	it('renders a card that has no comments field', () => {
		const card = fakeCard({}) as Partial<CardT>;
		delete card.comments;
		render(Card, { card: card as CardT });
		expect(screen.getByText(card.hook!)).toBeInTheDocument();
	});

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

	it('keeps the front panel from scrolling so a vertical swipe moves the feed', () => {
		const card = fakeCard({
			visual: {
				kind: 'code',
				repo: 'gittok',
				path: 'src/x.py',
				commit: 'abcdef1234567890',
				lines: [10, 10]
			} as unknown as CardT['visual'],
			resolved: {
				visual: { code: 'x = 1', language: 'python', start_line: 10 },
				depth: [null, { code: 'y = 2', language: 'python', start_line: 1 }]
			},
			depth: [
				{ kind: 'explain', text: 'Why.' },
				{ kind: 'code', repo: 'gittok', path: 'src/x.py', commit: 'abcdef1234567890', lines: [1, 1] }
			] as CardT['depth']
		});
		const { container } = render(Card, { card });
		const front = container.querySelector('section[data-panel="0"]')!;
		expect(front).toHaveClass('front');
		expect(container.querySelector('section[data-panel="1"]')).not.toHaveClass('front');
		// Front code wraps (no sideways scroller fighting the panel swipe); depth code does not.
		expect(front.querySelector('.codeblock')).toHaveClass('fit'); // shrinks to fit; never scrolls or overflows
		expect(container.querySelector('section[data-panel="2"] .codeblock')).not.toHaveClass('wrap');
	});

	it('shows two comments with avatars on the front and all of them on a last panel', () => {
		const card = fakeCard({
			depth: [{ kind: 'explain', text: 'Why.' }],
			comments: [
				{ persona: 'penny_learns', text: 'Wait, why?' },
				{ persona: 'archivist', text: 'Since 2019.' },
				{ persona: 'greybeard', text: 'Told you.' }
			]
		});
		const { container } = render(Card, { card });
		const front = container.querySelector('section.front')!;
		const faces = [...front.querySelectorAll('.face-comments li')];
		expect(faces.map((li) => li.querySelector('.comment-body > span')?.textContent?.trim())).toEqual([
			'@penny_learns: Wait, why?',
			'@archivist: Since 2019.'
		]);
		expect(front.querySelectorAll('.face-comments img')).toHaveLength(2);
		expect(front.querySelector('.face-comments img')!.getAttribute('src')).toBe(
			'/api/avatars/penny_learns'
		);
		expect(within(front as HTMLElement).getByRole('button', { name: 'All 3 comments' })).toBeTruthy();
		const panel = container.querySelector('section.comments-panel')!;
		expect(panel.getAttribute('data-panel')).toBe('2');
		const items = [...panel.querySelectorAll('.comments li')].map((li) =>
			li.querySelector('.comment-body > span')?.textContent?.trim()
		);
		expect(items).toEqual(['@penny_learns: Wait, why?', '@archivist: Since 2019.', '@greybeard: Told you.']);
		expect(container.querySelectorAll('.dot')).toHaveLength(3);
	});

	it('comment author names link to the persona page', () => {
		const card = fakeCard({ comments: [{ persona: 'penny_learns', text: 'Wait, why?' }] });
		const { container } = render(Card, { card });
		const link = container.querySelector('section.front .face-comments a')!;
		expect(link).toHaveAttribute('href', '/persona/penny_learns');
		expect(link.textContent).toBe('@penny_learns');
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
		expect(JSON.parse(localStorage.getItem('blamescroll.card-state')!).c_save.saved).toBe(true);
	});

	it('keeps the side column short: Knew it and More sit in the bottom row with the dots', () => {
		const { container } = render(Card, { card: fakeCard({ id: 'c_rows' }) });
		const side = container.querySelector('.actions') as HTMLElement;
		const bottom = container.querySelector('.bottom-row') as HTMLElement;
		expect(side.querySelectorAll('button').length).toBeLessThanOrEqual(3);
		expect(bottom).toContainElement(screen.getByRole('button', { name: 'Knew it' }));
		expect(bottom).toContainElement(screen.getByRole('button', { name: 'Teach me more' }));
		expect(bottom).toContainElement(container.querySelector('.dots') as HTMLElement);
	});

	it('shows visible labels under the action icons', () => {
		render(Card, { card: fakeCard({ id: 'c_labels' }) });
		for (const name of ['Like', 'Save', 'Knew it', 'More']) {
			expect(screen.getByText(name, { selector: '.label' })).toBeInTheDocument();
		}
	});

	it('knew it and teach more each emit once, fill, and persist', async () => {
		const calls: [string, Record<string, unknown> | undefined][] = [];
		const card = fakeCard({ id: 'c_know' });
		const { unmount } = render(Card, { card, onAction: (t: string, d?: Record<string, unknown>) => calls.push([t, d]) });
		const knew = screen.getByRole('button', { name: /knew it/i });
		const more = screen.getByRole('button', { name: /teach me more/i });
		expect(knew).toHaveAttribute('aria-pressed', 'false');
		await fireEvent.click(knew);
		await fireEvent.click(knew);
		await fireEvent.click(more);
		await fireEvent.click(more);
		expect(knew).toHaveAttribute('aria-pressed', 'true');
		expect(more).toHaveAttribute('aria-pressed', 'true');
		expect(calls).toEqual([
			['knew_it', { on: true }],
			['teach_more', { on: true }]
		]);
		unmount();
		resetCardStateForTest();
		render(Card, { card });
		expect(screen.getByRole('button', { name: /knew it/i })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: /teach me more/i })).toHaveAttribute('aria-pressed', 'true');
	});

	it('a comments button with the count jumps to the comments panel', async () => {
		const card = fakeCard({
			depth: [{ kind: 'explain', text: 'Plain words.' }],
			comments: [
				{ persona: 'greybeard', text: 'Told you.' },
				{ persona: 'archivist', text: 'Since 2019.' }
			]
		});
		const { container } = render(Card, { card });
		const row = container.querySelector('.panels') as HTMLElement;
		Object.defineProperty(row, 'clientWidth', { value: 300, configurable: true });
		row.scrollTo = vi.fn() as never;
		const btn = screen.getByRole('button', { name: 'Comments (2)' });
		expect(btn).toHaveTextContent('2');
		await fireEvent.click(btn);
		expect(row.scrollTo).toHaveBeenCalledWith({ left: 600, behavior: 'smooth' });
	});

	it('has no explain-more button, and no comments button without comments', () => {
		render(Card, { card: fakeCard({ comments: [] }) });
		expect(screen.queryByRole('button', { name: /explain more/i })).toBeNull();
		expect(screen.queryByRole('button', { name: /comments/i })).toBeNull();
		expect(screen.getByRole('button', { name: 'Like' })).toBeInTheDocument();
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

	it('a quiz comment with spoiler false shows before the answer', () => {
		const card = quiz({
			comments: [
				{ persona: 'greybeard', text: 'Hidden until answered.' },
				{ persona: 'archivist', text: 'Safe to read.', spoiler: false }
			]
		});
		render(Card, { card });
		expect(screen.getAllByText(/Safe to read/).length).toBeGreaterThan(0);
		expect(screen.queryByText(/Hidden until answered/)).toBeNull();
	});

	it('a non-quiz comment with spoiler true stays hidden only on quizzes', () => {
		render(Card, { card: fakeCard({ comments: [{ persona: 'greybeard', text: 'Plain.' }] }) });
		expect(screen.getAllByText(/Plain\./).length).toBeGreaterThan(0);
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
		expect(screen.getAllByText(/Told you so/).length).toBeGreaterThan(0);
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
		expect(screen.getAllByText(/Told you so/).length).toBeGreaterThan(0);
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

describe('Card replies', () => {
	const fetchMock = vi.fn();
	beforeEach(() => vi.stubGlobal('fetch', fetchMock));
	afterEach(() => {
		fetchMock.mockReset();
		vi.unstubAllGlobals();
		resetCardStateForTest();
	});
	const withComment = (over: Partial<CardT> = {}) =>
		fakeCard({
			id: 'c_9',
			comments: [{ persona: 'greybeard', text: 'Floats and money.' }],
			...over
		});

	it('the reply box posts and the reply shows as You', async () => {
		const stored = {
			id: 4,
			card_id: 'c_9',
			persona: 'greybeard',
			comment_index: 0,
			text: 'Why floats?',
			created_at: 'x',
			answered_card_id: null
		};
		fetchMock.mockResolvedValue({ ok: true, json: async () => stored });
		render(Card, { card: withComment() });
		await fireEvent.click(screen.getAllByRole('button', { name: 'Reply' })[0]);
		const box = screen.getByRole('textbox', { name: 'Your reply' });
		expect(box).toHaveAttribute('maxlength', '280');
		await fireEvent.input(box, { target: { value: 'Why floats?' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Send' }));
		expect((await screen.findAllByText('Why floats?')).length).toBeGreaterThan(0);
		expect(screen.getAllByText('You').length).toBeGreaterThan(0);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/replies');
		expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
			card_id: 'c_9',
			comment_index: 0,
			text: 'Why floats?'
		});
	});

	it('does not send an empty reply', async () => {
		render(Card, { card: withComment() });
		await fireEvent.click(screen.getAllByRole('button', { name: 'Reply' })[0]);
		expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
	});

	it('an answered reply links to the answer card', () => {
		const card = withComment({
			replies: [
				{
					id: 4,
					card_id: 'c_9',
					persona: 'greybeard',
					comment_index: 0,
					text: 'Why floats?',
					created_at: 'x',
					answered_card_id: 'c_77'
				}
			]
		});
		render(Card, { card });
		expect(screen.getAllByText('Why floats?').length).toBeGreaterThan(0);
		expect(screen.getAllByRole('link', { name: /@greybeard answered/ })[0]).toHaveAttribute(
			'href',
			'/card/c_77'
		);
	});
});
