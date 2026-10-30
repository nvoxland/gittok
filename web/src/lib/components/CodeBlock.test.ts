import { render, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const codeToHtml = vi.hoisted(() => vi.fn());
vi.mock('shiki', () => ({ codeToHtml }));
import CodeBlock from './CodeBlock.svelte';

describe('CodeBlock', () => {
	beforeEach(() => {
		codeToHtml.mockReset();
		codeToHtml.mockRejectedValue(new Error('shiki disabled in test'));
	});

	it('shows starting line number', () => {
		const { container } = render(CodeBlock, { code: 'a\nb\nc', startLine: 10 });
		const nums = [...container.querySelectorAll('.ln')].map((n) => n.textContent);
		expect(nums).toEqual(['10', '11', '12']);
	});

	it('escapes HTML in code', () => {
		const { container } = render(CodeBlock, { code: '<script>alert(1)</script> & <b>x</b>' });
		expect(container.querySelector('script')).toBeNull();
		expect(container.querySelector('b')).toBeNull();
		expect(container.querySelector('.src')?.textContent).toBe('<script>alert(1)</script> & <b>x</b>');
		expect(container.querySelector('.src')?.innerHTML).toContain('&lt;b&gt;');
	});

	it('swaps in Shiki html with dual themes once loaded', async () => {
		codeToHtml.mockResolvedValueOnce('<pre class="shiki"><code><span class="line">HL</span></code></pre>');
		const { container } = render(CodeBlock, { code: 'x = 1', language: 'python' });
		expect(container.querySelector('.codeblock')).toBeInTheDocument();
		await waitFor(() => expect(container.querySelector('.shiki')).toBeInTheDocument());
		expect(codeToHtml).toHaveBeenCalledWith(
			'x = 1',
			expect.objectContaining({
				lang: 'python',
				themes: { light: 'github-light', dark: 'github-dark' }
			})
		);
	});

	it('keeps plain text when Shiki fails (unknown language)', async () => {
		codeToHtml.mockRejectedValueOnce(new Error('unknown language'));
		const { container } = render(CodeBlock, { code: 'abc', language: 'nope' });
		await waitFor(() => expect(codeToHtml).toHaveBeenCalledTimes(1));
		expect(container.querySelector('.shiki')).toBeNull();
		expect(container.querySelector('.src')?.textContent).toBe('abc');
	});
});
