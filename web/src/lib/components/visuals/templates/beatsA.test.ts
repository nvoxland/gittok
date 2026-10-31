import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import TemplateVisual from '../TemplateVisual.svelte';
import { templateFixtures } from '../../fixtures.ts';

const rs = (name: string, shown?: number) =>
	render(TemplateVisual, {
		visual: templateFixtures[name],
		resolved: null,
		...(shown === undefined ? {} : { shown })
	}).container;

describe('beats A: thread, day_in_life, tier_list', () => {
	it('thread shows the first posts', () => {
		expect(rs('thread', 2).querySelectorAll('.post')).toHaveLength(2);
		expect(rs('thread').querySelectorAll('.post')).toHaveLength(3);
	});
	it('day_in_life shows the first steps', () => {
		const c = rs('day_in_life', 1);
		expect(c.querySelectorAll('.step')).toHaveLength(1);
		expect(c.querySelector('.time')).toHaveTextContent('09:00');
		expect(rs('day_in_life').querySelectorAll('.step')).toHaveLength(3);
	});
	it('tier_list reveals the worst tier first', () => {
		const c = rs('tier_list', 1);
		const rows = c.querySelectorAll('.row');
		expect(rows).toHaveLength(1);
		expect(rows[0].querySelector('.tier')).toHaveAttribute('data-tier', 'F');
		expect(rs('tier_list', 2).querySelectorAll('.row')).toHaveLength(2);
		expect(rs('tier_list').querySelectorAll('.row')).toHaveLength(2);
	});
});
