import { beforeEach, describe, expect, it } from 'vitest';
import { getItemWithLegacy } from './legacyKey';

describe('getItemWithLegacy', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('reads the new key', () => {
		localStorage.setItem('blamescroll.x', 'new');
		localStorage.setItem('codescroll.x', 'old');
		expect(getItemWithLegacy(localStorage, 'blamescroll.x')).toBe('new');
	});

	it('falls back once to the old key and writes the new one', () => {
		localStorage.setItem('codescroll.x', 'old');
		expect(getItemWithLegacy(localStorage, 'blamescroll.x')).toBe('old');
		expect(localStorage.getItem('blamescroll.x')).toBe('old');
	});

	it('returns null when neither key exists', () => {
		expect(getItemWithLegacy(localStorage, 'blamescroll.x')).toBeNull();
	});
});
