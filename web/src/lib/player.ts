// The beats player: a small state machine with timers.
// It plays only while active (card on screen, tab shown). Hold pauses the sequence but
// counts as watched time; tap jumps ahead without adding watched time.
import { totalMs, type Beat } from './beats.ts';

export type PlayerState = { shown: number; beat: number; done: boolean; paused: boolean };
export type PlayerStats = { msPlayed: number; totalMs: number; beat: number; done: boolean };

export type PlayerOptions = {
	onChange?: (s: PlayerState) => void;
	onDone?: () => void;
	onTap?: (beat: number) => void;
	onReplay?: () => void;
	reducedMotion?: boolean;
	alreadyPlayed?: boolean;
};

export function createPlayer(beats: Beat[], opts: PlayerOptions = {}) {
	const finished = !!(opts.reducedMotion || opts.alreadyPlayed) || beats.length === 0;
	const state: PlayerState = finished
		? { shown: Infinity, beat: beats.length, done: true, paused: false }
		: { shown: 0, beat: -1, done: false, paused: false };
	let active = false;
	let held = false;
	let remaining = 0; // ms left in the current beat
	let timer: ReturnType<typeof setTimeout> | undefined;
	let since: number | undefined; // when the current played stretch started
	let played = 0;

	const changed = () => opts.onChange?.({ ...state });
	const counting = () => active && !state.done;
	const running = () => counting() && !held;

	function stopClock() {
		if (since !== undefined) played += Date.now() - since;
		since = undefined;
	}
	function startClock() {
		if (since === undefined && counting()) since = Date.now();
	}
	function clearTimer() {
		if (timer === undefined) return;
		clearTimeout(timer);
		timer = undefined;
	}
	let timerStart = 0;
	function arm() {
		clearTimer();
		if (!running()) return;
		timerStart = Date.now();
		timer = setTimeout(() => {
			timer = undefined;
			advance();
		}, remaining);
	}
	function pauseTimer() {
		if (timer === undefined) return;
		remaining -= Date.now() - timerStart;
		clearTimer();
	}
	function goTo(i: number) {
		if (i >= beats.length) {
			stopClock();
			clearTimer();
			Object.assign(state, { shown: Infinity, beat: beats.length, done: true, paused: false });
			changed();
			opts.onDone?.();
			return;
		}
		state.beat = i;
		state.shown = beats[i].shown;
		remaining = beats[i].ms;
		changed();
		arm();
	}
	function advance() {
		goTo(state.beat + 1);
	}

	return {
		state,
		setActive(on: boolean) {
			if (on === active) return;
			if (!on) {
				pauseTimer();
				stopClock();
				active = false;
				return;
			}
			active = true;
			if (state.done) return;
			startClock();
			if (state.beat < 0) goTo(0);
			else arm();
		},
		hold(on: boolean) {
			if (on === held || state.done) return;
			held = on;
			state.paused = on;
			if (on) pauseTimer();
			else arm();
			changed();
		},
		tap() {
			if (state.done || state.beat < 0) return;
			opts.onTap?.(state.beat);
			advance();
		},
		replay() {
			if (beats.length === 0) return;
			opts.onReplay?.();
			Object.assign(state, { done: false, paused: false });
			held = false;
			startClock();
			goTo(0);
		},
		stats(): PlayerStats {
			const live = since !== undefined ? Date.now() - since : 0;
			return { msPlayed: played + live, totalMs: totalMs(beats), beat: state.beat, done: state.done };
		},
		destroy() {
			clearTimer();
			stopClock();
		}
	};
}
