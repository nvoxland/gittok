import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import TemplateVisual from '../TemplateVisual.svelte';
import TextMemeVisual from '../TextMemeVisual.svelte';
import { textMemeVisual } from '../../fixtures.ts';

const flagsVisual = {
	kind: 'template',
	template: 'flags',
	data: { subject: 's', red: ['r1', 'r2'], green: ['g1'] }
};

describe('beats: flags', () => {
	const rf = (extra: object) =>
		render(TemplateVisual, {
			visual: flagsVisual,
			resolved: null,
			...extra
		} as never).container;
	it('shown=2 shows the first red and the first green', () => {
		const c = rf({ shown: 2 });
		expect([...c.querySelectorAll('li')].map((l) => l.textContent)).toEqual(['r1', 'g1']);
	});
	it('shows all by default', () => {
		expect(rf({}).querySelectorAll('li')).toHaveLength(3);
	});
});

describe('beats: text memes', () => {
	const lines = ['one', 'two', 'three'];
	for (const style of ['pov', 'nobody_me', 'starter_pack', 'expectation_reality']) {
		it(`${style}: shown=1 shows only the first line`, () => {
			const { container } = render(TextMemeVisual, {
				visual: textMemeVisual(style, lines),
				shown: 1
			} as never);
			expect(container.textContent).toContain('one');
			expect(container.textContent).not.toContain('two');
		});
		it(`${style}: default shows all`, () => {
			const { container } = render(TextMemeVisual, {
				visual: textMemeVisual(style, lines)
			} as never);
			expect(container.textContent).toContain('three');
		});
	}
});
