import { beforeEach, describe, expect, it } from 'vitest';
import { getItemWithLegacy } from './legacyKey';

describe('getItemWithLegacy', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('reads the new key', () => {
		localStorage.setItem('gittok.x', 'new');
		localStorage.setItem('blamescroll.x', 'mid');
		localStorage.setItem('codescroll.x', 'old');
		expect(getItemWithLegacy(localStorage, 'gittok.x')).toBe('new');
	});

	it('falls back once to the blamescroll key and writes the new one', () => {
		localStorage.setItem('blamescroll.x', 'mid');
		localStorage.setItem('codescroll.x', 'old');
		expect(getItemWithLegacy(localStorage, 'gittok.x')).toBe('mid');
		expect(localStorage.getItem('gittok.x')).toBe('mid');
	});

	it('falls back to the codescroll key and writes the new one', () => {
		localStorage.setItem('codescroll.x', 'old');
		expect(getItemWithLegacy(localStorage, 'gittok.x')).toBe('old');
		expect(localStorage.getItem('gittok.x')).toBe('old');
	});

	it('returns null when no key exists', () => {
		expect(getItemWithLegacy(localStorage, 'gittok.x')).toBeNull();
	});
});
