import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
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
