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

	it('fit sizes the font to the longest line instead of wrapping', () => {
		const code = 'short\n' + 'x'.repeat(50) + '\n\tindented';
		const { container } = render(CodeBlock, { code, startLine: 87, fit: true });
		const block = container.querySelector('.codeblock') as HTMLElement;
		expect(block).toHaveClass('fit');
		expect(block).not.toHaveClass('wrap');
		// 50 chars + a 2-digit line number gutter (2 + 2 spaces of margin)
		expect(block.style.getPropertyValue('--cols')).toBe('54');
		expect(block.parentElement).toHaveClass('fit-box');
	});

	it('fit falls back to wrapping when lines are too long to shrink into view', () => {
		const { container } = render(CodeBlock, { code: 'y'.repeat(120), fit: true });
		expect(container.querySelector('.codeblock')).toHaveClass('wrap');
	});

	it('fit reports when the fitted font is too small to read', () => {
		const sizes: Array<() => void> = [];
		vi.stubGlobal(
			'ResizeObserver',
			class {
				constructor(cb: () => void) {
					sizes.push(cb);
				}
				observe() {}
				disconnect() {}
			}
		);
		const onShrunk = vi.fn();
		// 56 chars + gutter = 59 cols; in a 300px box the font is about 8px
		render(CodeBlock, { code: 'x'.repeat(56), fit: true, onShrunk });
		vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
		sizes.forEach((cb) => cb());
		expect(onShrunk).toHaveBeenLastCalledWith(true);
		vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(900);
		sizes.forEach((cb) => cb());
		expect(onShrunk).toHaveBeenLastCalledWith(false);
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	it('large drops fit and uses the big font class', () => {
		const { container } = render(CodeBlock, { code: 'a', large: true });
		expect(container.querySelector('.codeblock')).toHaveClass('large');
		expect(container.querySelector('.codeblock')).not.toHaveClass('fit');
	});

	it('wraps long lines only when asked', () => {
		const { container } = render(CodeBlock, { code: 'a', wrap: true });
		expect(container.querySelector('.codeblock')).toHaveClass('wrap');
		const plain = render(CodeBlock, { code: 'b' });
		expect(plain.container.querySelector('.codeblock')).not.toHaveClass('wrap');
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

describe('CodeBlock indentation', () => {
	it('shows deeply nested code without the indent its lines share', () => {
		const { container } = render(CodeBlock, {
			props: { code: '\t\t\t\thold(on) {\n\t\t\t\t\treturn;\n\t\t\t\t}', startLine: 96 }
		});
		const src = [...container.querySelectorAll('.src')].map((e) => e.textContent);
		expect(src).toEqual(['hold(on) {', '  return;', '}']);
		expect(container.querySelector('.ln')?.textContent).toBe('96');
	});
});
