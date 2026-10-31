import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Beats from './test/BeatsHarness.svelte';
import { playStats } from '#lib/playStats.ts';
import { resetCardStateForTest } from '#lib/cardState.ts';

const beats = [
	{ shown: 1, ms: 1000 },
	{ shown: 2, ms: 1000 }
];


describe('Beats', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		resetCardStateForTest();
	});
	afterEach(() => vi.useRealTimers());

	function setup(over = {}) {
		const onAction = vi.fn();
		const r = render(Beats, { cardId: 'c_1', beats, active: true, onAction, ...over });
		return { ...r, onAction };
	}

	it('plays, shows a progress segment per beat, then offers replay', async () => {
		const { container, onAction } = setup();
		expect(container.querySelectorAll('.seg')).toHaveLength(2);
		expect(screen.getByTestId('shown')).toHaveTextContent('1');
		await vi.advanceTimersByTimeAsync(1000);
		expect(screen.getByTestId('shown')).toHaveTextContent('2');
		await vi.advanceTimersByTimeAsync(1000);
		expect(screen.getByTestId('shown')).toHaveTextContent('Infinity');
		expect(onAction).toHaveBeenCalledWith('beats_done', { beats: 2, ms_played: 2000 });
		await fireEvent.click(screen.getByRole('button', { name: 'Replay' }));
		expect(onAction).toHaveBeenCalledWith('replay');
		expect(screen.getByTestId('shown')).toHaveTextContent('1');
	});

	it('puts replay in the progress row, not over the content, and keeps the row height', async () => {
		const { container } = setup();
		const row = container.querySelector('.controls')!;
		expect(row.querySelector('.progress')).not.toBeNull();
		await vi.advanceTimersByTimeAsync(2000);
		expect(container.querySelector('.controls')).toBe(row);
		expect(row.querySelector('.replay')).not.toBeNull();
		expect(row.querySelector('.progress')).toBeNull();
	});

	it('a card that already played can be replayed from the start', async () => {
		setup();
		await vi.advanceTimersByTimeAsync(2000);
		document.body.innerHTML = '';
		const { onAction } = setup();
		await fireEvent.click(screen.getByRole('button', { name: 'Replay' }));
		expect(onAction).toHaveBeenCalledWith('replay');
		expect(screen.getByTestId('shown')).toHaveTextContent('1');
		await vi.advanceTimersByTimeAsync(1000);
		expect(screen.getByTestId('shown')).toHaveTextContent('2');
	});

	it('a quick tap skips ahead and is recorded', async () => {
		const { container, onAction } = setup();
		const stage = container.querySelector('.beats')!;
		await fireEvent.pointerDown(stage);
		await fireEvent.pointerUp(stage);
		expect(screen.getByTestId('shown')).toHaveTextContent('2');
		expect(onAction).toHaveBeenCalledWith('beat_tap', { beat: 0 });
	});

	it('a long press pauses until released', async () => {
		const { container } = setup();
		const stage = container.querySelector('.beats')!;
		await fireEvent.pointerDown(stage);
		await vi.advanceTimersByTimeAsync(3000);
		expect(screen.getByTestId('shown')).toHaveTextContent('1');
		await fireEvent.pointerUp(stage);
		await vi.advanceTimersByTimeAsync(1000);
		expect(screen.getByTestId('shown')).toHaveTextContent('2');
	});

	it('does not play while inactive and publishes its stats', async () => {
		setup({ active: false });
		await vi.advanceTimersByTimeAsync(5000);
		expect(screen.getByTestId('shown')).toHaveTextContent('0');
		expect(playStats('c_1')).toMatchObject({ totalMs: 2000, msPlayed: 0, done: false });
	});

	it('a card that already played shows the full view at once', async () => {
		setup();
		await vi.advanceTimersByTimeAsync(2000);
		document.body.innerHTML = '';
		setup();
		expect(screen.getByTestId('shown')).toHaveTextContent('Infinity');
	});

	it('without beats it just renders the full view', () => {
		const { container } = setup({ beats: [] });
		expect(screen.getByTestId('shown')).toHaveTextContent('Infinity');
		expect(container.querySelector('.seg')).toBeNull();
	});
});
