import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearAnswers, getAnswer, resetCardStateForTest, setAnswer } from './cardState.ts';

describe('answers', () => {
	beforeEach(() => {
		sessionStorage.clear();
		resetCardStateForTest();
		vi.useFakeTimers();
		vi.setSystemTime(new Date('2026-10-30T10:00:00Z'));
	});
	afterEach(() => vi.useRealTimers());

	it('remembers an answer, also after a reload of the in-memory cache', () => {
		setAnswer('c_1', { choice: 1 });
		expect(getAnswer('c_1')).toEqual({ choice: 1 });
		resetCardStateForTest();
		expect(getAnswer('c_1')).toEqual({ choice: 1 });
	});

	it('forgets an answer after 12 hours', () => {
		setAnswer('c_1', { choice: 1 });
		vi.advanceTimersByTime(11 * 3600_000);
		expect(getAnswer('c_1')).toEqual({ choice: 1 });
		vi.advanceTimersByTime(2 * 3600_000);
		expect(getAnswer('c_1')).toBeUndefined();
	});

	it('clearAnswers forgets only the listed cards', () => {
		setAnswer('c_1', 'a');
		setAnswer('c_2', 'b');
		clearAnswers(['c_1', 'c_9']);
		expect(getAnswer('c_1')).toBeUndefined();
		expect(getAnswer('c_2')).toBe('b');
		resetCardStateForTest();
		expect(getAnswer('c_1')).toBeUndefined();
	});
});
