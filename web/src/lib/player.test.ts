import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPlayer } from './player.ts';

const beats = [
	{ shown: 1, ms: 1000 },
	{ shown: 2, ms: 1000 },
	{ shown: 3, ms: 2000 }
];

describe('player', () => {
	beforeEach(() => vi.useFakeTimers());
	afterEach(() => vi.useRealTimers());

	function make(opts = {}) {
		const done = vi.fn();
		const p = createPlayer(beats, { onDone: done, ...opts });
		return { p, done };
	}

	it('waits until active, then shows one beat at a time and finishes', () => {
		const { p, done } = make();
		expect(p.state.shown).toBe(0);
		p.setActive(true);
		expect(p.state.shown).toBe(1);
		vi.advanceTimersByTime(1000);
		expect(p.state.shown).toBe(2);
		vi.advanceTimersByTime(1000);
		expect(p.state.shown).toBe(3);
		expect(p.state.done).toBe(false);
		vi.advanceTimersByTime(2000);
		expect(p.state.done).toBe(true);
		expect(p.state.shown).toBe(Infinity);
		expect(done).toHaveBeenCalledOnce();
		expect(p.stats()).toMatchObject({ msPlayed: 4000, totalMs: 4000, beat: 3, done: true });
	});

	it('pauses and stops counting while inactive', () => {
		const { p } = make();
		p.setActive(true);
		vi.advanceTimersByTime(500);
		p.setActive(false);
		vi.advanceTimersByTime(10_000);
		expect(p.state.shown).toBe(1);
		expect(p.stats().msPlayed).toBe(500);
		p.setActive(true);
		vi.advanceTimersByTime(500);
		expect(p.state.shown).toBe(2); // the rest of beat 1, not a fresh 1000 ms
	});

	it('hold pauses the sequence but still counts as played time', () => {
		const { p } = make();
		p.setActive(true);
		p.hold(true);
		vi.advanceTimersByTime(3000);
		expect(p.state.shown).toBe(1);
		expect(p.state.paused).toBe(true);
		expect(p.stats().msPlayed).toBe(3000);
		p.hold(false);
		vi.advanceTimersByTime(1000);
		expect(p.state.shown).toBe(2);
	});

	it('tap jumps to the next beat without adding played time', () => {
		const onTap = vi.fn();
		const { p, done } = make({ onTap });
		p.setActive(true);
		p.tap();
		p.tap();
		expect(p.state.shown).toBe(3);
		expect(onTap).toHaveBeenCalledTimes(2);
		p.tap();
		expect(p.state.done).toBe(true);
		expect(done).toHaveBeenCalledOnce();
		expect(p.stats().msPlayed).toBe(0);
	});

	it('replay starts again from the first beat', () => {
		const onReplay = vi.fn();
		const { p } = make({ onReplay });
		p.setActive(true);
		vi.advanceTimersByTime(4000);
		p.replay();
		expect(onReplay).toHaveBeenCalledOnce();
		expect(p.state).toMatchObject({ shown: 1, done: false });
		vi.advanceTimersByTime(1000);
		expect(p.state.shown).toBe(2);
		expect(p.stats().msPlayed).toBe(5000);
	});

	it('starts finished with reduced motion or when already played', () => {
		for (const opts of [{ reducedMotion: true }, { alreadyPlayed: true }]) {
			const { p, done } = make(opts);
			p.setActive(true);
			expect(p.state).toMatchObject({ shown: Infinity, done: true });
			expect(done).not.toHaveBeenCalled();
		}
	});

	it('notifies on every change', () => {
		const onChange = vi.fn();
		const { p } = make({ onChange });
		p.setActive(true);
		vi.advanceTimersByTime(1000);
		expect(onChange.mock.calls.map((c) => c[0].shown)).toEqual([1, 2]);
	});
});
