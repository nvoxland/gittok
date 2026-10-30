import { describe, expect, it } from 'vitest';
import { relativeTime } from './relativeTime.ts';

describe('relativeTime', () => {
	const now = 1_000_000;
	it('says just now under a minute', () => expect(relativeTime(now - 30, now)).toBe('just now'));
	it('uses minutes', () => expect(relativeTime(now - 5 * 60, now)).toBe('5m ago'));
	it('uses hours', () => expect(relativeTime(now - 3 * 3600 - 10, now)).toBe('3h ago'));
	it('uses days', () => expect(relativeTime(now - 2 * 86400, now)).toBe('2d ago'));
	it('clamps future times', () => expect(relativeTime(now + 99, now)).toBe('just now'));
});
