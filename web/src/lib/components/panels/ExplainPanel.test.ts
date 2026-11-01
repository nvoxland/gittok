import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ExplainPanel from './ExplainPanel.svelte';

describe('ExplainPanel', () => {
	it('renders paragraphs, code spans, bold and lists', () => {
		const { container } = render(ExplainPanel, {
			text: 'Edit `store.py` and **now**.\n\n- one\n- two'
		});
		expect(container.querySelectorAll('p')).toHaveLength(1);
		expect(container.querySelector('code')?.textContent).toBe('store.py');
		expect(container.querySelector('strong')?.textContent).toBe('now');
		expect(container.querySelectorAll('li')).toHaveLength(2);
	});

	it('shows HTML as text', () => {
		const { container } = render(ExplainPanel, { text: '<script>alert(1)</script>' });
		expect(container.querySelector('script')).toBeNull();
		expect(container.textContent).toContain('<script>alert(1)</script>');
	});

	it('lists sources that have a URL as links that open in a new tab', () => {
		const { container } = render(ExplainPanel, {
			text: 'Why.',
			sources: [
				{ label: 'abc1234', url: 'https://github.com/o/r/commit/abc1234' },
				{ label: 'src/x.py', url: null }
			]
		});
		const links = container.querySelectorAll('.sources a');
		expect(links).toHaveLength(1);
		expect(links[0].getAttribute('href')).toBe('https://github.com/o/r/commit/abc1234');
		expect(links[0].getAttribute('target')).toBe('_blank');
		expect(links[0].getAttribute('rel')).toContain('noopener');
		expect(container.textContent).toContain('Sources');
	});

	it('has no Sources list without URLs', () => {
		const { container } = render(ExplainPanel, {
			text: 'Why.',
			sources: [{ label: 'x', url: null }]
		});
		expect(container.querySelector('.sources')).toBeNull();
	});

	it('shows the learn line as a lead above the text', () => {
		const { container } = render(ExplainPanel, {
			text: 'Body.',
			learn: 'How total() rounds money.'
		});
		const lead = container.querySelector('.learn');
		expect(lead?.textContent).toContain("You'll learn:");
		expect(lead?.textContent).toContain('How total() rounds money.');
		const p = container.querySelector('p:not(.learn)')!;
		expect(lead!.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('renders without a learn line (cards stored before it existed)', () => {
		const { container } = render(ExplainPanel, { text: 'Body.' });
		expect(container.querySelector('.learn')).toBeNull();
		expect(container.querySelector('p')?.textContent).toBe('Body.');
	});
});
