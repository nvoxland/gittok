import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import TextMemeVisual from './TextMemeVisual.svelte';
import ChartVisual from './ChartVisual.svelte';
import { chartResolved, chartVisual, hoursResolved, textMemeVisual } from '../fixtures.ts';

describe('TextMemeVisual', () => {
	it('nobody_me mutes the nobody line', () => {
		const { container } = render(TextMemeVisual, {
			visual: textMemeVisual('nobody_me', ['nobody:', 'billing.py: fix rounding again']),
			resolved: null
		});
		expect(container.querySelector('.nobody_me')).not.toBeNull();
		expect(screen.getByText('nobody:')).toHaveClass('muted');
		expect(screen.getByText('billing.py: fix rounding again')).not.toHaveClass('muted');
	});
	it('pov renders a POV banner', () => {
		const { container } = render(TextMemeVisual, {
			visual: textMemeVisual('pov', ['you open the legacy module']),
			resolved: null
		});
		expect(container.querySelector('.pov')).not.toBeNull();
		expect(screen.getByText('you open the legacy module')).toBeInTheDocument();
	});
	it('starter_pack renders labeled tiles', () => {
		const { container } = render(TextMemeVisual, {
			visual: textMemeVisual('starter_pack', ['Makefile', 'TODO', 'tabs']),
			resolved: null
		});
		expect(container.querySelectorAll('.tile')).toHaveLength(3);
	});
	it('expectation_reality renders two columns', () => {
		const { container } = render(TextMemeVisual, {
			visual: textMemeVisual('expectation_reality', ['clean arch', 'god object']),
			resolved: null
		});
		expect(container.querySelectorAll('.col')).toHaveLength(2);
		expect(screen.getByText('Expectation')).toBeInTheDocument();
		expect(screen.getByText('Reality')).toBeInTheDocument();
	});
});

describe('ChartVisual', () => {
	it('renders one bar and label per entry (horizontal)', () => {
		const { container } = render(ChartVisual, { visual: chartVisual(), resolved: chartResolved() });
		expect(container.querySelectorAll('rect.bar')).toHaveLength(3);
		expect(container.querySelector('svg')).toHaveAttribute('role', 'img');
		expect(screen.getByText('shipping.clj')).toBeInTheDocument();
		expect(screen.getByText('41')).toBeInTheDocument();
		expect(screen.getByText('Where the edits go')).toBeInTheDocument();
		expect(screen.getByText('commits')).toBeInTheDocument();
	});
	it('commit_hours is a 24-bar vertical histogram', () => {
		const { container } = render(ChartVisual, {
			visual: chartVisual('commit_hours'),
			resolved: hoursResolved()
		});
		expect(container.querySelectorAll('rect.bar')).toHaveLength(24);
		expect(container.querySelector('svg.vertical')).not.toBeNull();
	});
	it('shows a message without data', () => {
		render(ChartVisual, { visual: chartVisual(), resolved: null });
		expect(screen.getByText(/no data/i)).toBeInTheDocument();
	});
});
