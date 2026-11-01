import { fireEvent, render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SourceLine from './SourceLine.svelte';
import CodePanel from './CodePanel.svelte';

const base = { repo: 'gittok', path: 'src/x.py', commit: 'abcdef1234567' };

describe('SourceLine', () => {
	it('links to GitHub in a new tab when a URL is given, and still reports the tap', async () => {
		const onTap = vi.fn();
		const url = 'https://github.com/o/r/blob/abcdef1/src/x.py#L1-L5';
		const { container } = render(SourceLine, { ...base, url, onTap });
		const a = container.querySelector('a')!;
		expect(a.getAttribute('href')).toBe(url);
		expect(a.getAttribute('target')).toBe('_blank');
		expect(a.getAttribute('rel')).toContain('noopener');
		expect(a.textContent).toContain('gittok · src/x.py · abcdef1');
		await fireEvent.click(a);
		expect(onTap).toHaveBeenCalled();
	});

	it('keeps the in-app repo link without a URL', () => {
		const { container } = render(SourceLine, base);
		const a = container.querySelector('a')!;
		expect(a.getAttribute('href')).toBe('/repo/gittok');
		expect(a.getAttribute('target')).toBeNull();
	});
});

describe('CodePanel', () => {
	it('passes the GitHub URL to its source line', () => {
		const { container } = render(CodePanel, {
			...base,
			url: 'https://github.com/o/r/blob/abcdef1/src/x.py',
			resolved: { code: 'x = 1', language: 'python', start_line: 1 }
		});
		expect(container.querySelector('a')?.getAttribute('target')).toBe('_blank');
	});

	it('has a plain link without a URL', () => {
		const { container } = render(CodePanel, {
			...base,
			resolved: { code: 'x = 1', language: 'python', start_line: 1 }
		});
		expect(container.querySelector('a')?.getAttribute('target')).toBeNull();
	});
});
