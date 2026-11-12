import { afterEach, describe, expect, it, vi } from 'vitest';
import { getSessionId, resetSessionForTest } from './session.ts';

afterEach(() => {
	vi.unstubAllGlobals();
	sessionStorage.clear();
	resetSessionForTest();
});

describe('session id', () => {
	it('is stable and kept in sessionStorage', () => {
		const a = getSessionId();
		expect(a.length).toBeGreaterThan(8);
		expect(getSessionId()).toBe(a);
		expect(sessionStorage.getItem('gittok.session')).toBe(a);
		resetSessionForTest();
		expect(getSessionId()).toBe(a);
	});
	it('falls back to memory when sessionStorage throws', () => {
		vi.stubGlobal('sessionStorage', {
			getItem() {
				throw new Error('blocked');
			},
			setItem() {
				throw new Error('blocked');
			}
		});
		const a = getSessionId();
		expect(getSessionId()).toBe(a);
	});
});
