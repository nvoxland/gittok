import { afterEach, describe, expect, it, vi } from 'vitest';
import { prefersReducedMotion, scrollBehavior } from './motion.ts';

function stubMotion(reduce: boolean) {
	vi.stubGlobal('matchMedia', (q: string) => ({ matches: reduce && q.includes('reduce'), media: q }));
}

describe('motion', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('is false when matchMedia does not exist', () => {
		vi.stubGlobal('matchMedia', undefined);
		expect(prefersReducedMotion()).toBe(false);
		expect(scrollBehavior()).toBe('smooth');
	});

	it('scrolls without animation when the user asks for reduced motion', () => {
		stubMotion(true);
		expect(prefersReducedMotion()).toBe(true);
		expect(scrollBehavior()).toBe('auto');
	});

	it('scrolls smoothly otherwise', () => {
		stubMotion(false);
		expect(scrollBehavior()).toBe('smooth');
	});
});
