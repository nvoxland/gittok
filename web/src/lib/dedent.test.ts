import { describe, expect, it } from 'vitest';
import { dedent } from './dedent.ts';

describe('dedent', () => {
	it('removes the indent every non-blank line shares', () => {
		expect(dedent('\t\t\tif (x) {\n\t\t\t\ty();\n\n\t\t\t}')).toBe('if (x) {\n  y();\n\n}');
	});
	it('draws a leading tab as two spaces', () => {
		expect(dedent('a\n\tb\n\t\tc')).toBe('a\n  b\n    c');
	});
	it('handles spaces and leaves unindented code alone', () => {
		expect(dedent('    def f():\n        return 1')).toBe('def f():\n    return 1');
		expect(dedent('x = 1\ny = 2')).toBe('x = 1\ny = 2');
	});
	it('keeps the line count so line numbers stay right', () => {
		const src = '\t\ta\n\n\t\tb\n';
		expect(dedent(src).split('\n')).toHaveLength(src.replace(/\n$/, '').split('\n').length);
	});
});
