import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CatchUp from './CatchUp.svelte';
import { catchUpQueue } from './catchUp.ts';
import type { Story } from '#lib/types.ts';

const commit = (c: string, seen: boolean, subject: string) => ({
	sha: c.repeat(40),
	short: c.repeat(7),
	ts: 1,
	author: 'Ann',
	subject,
	files: 1,
	seen
});
const mk = (repo: string, commits: Story['commits'], over: Partial<Story> = {}): Story => ({
	repo,
	mascot: null,
	mascot_image: null,
	seen: false,
	commits,
	...over
});
const digest = { card_id: 'c_d', day: '2026-10-30', hook: 'Alpha digest', learn: 'Learn text here.' };

describe('catchUpQueue', () => {
	it('keeps only unseen commits and skips repos with none', () => {
		const q = catchUpQueue([
			mk('a', [commit('1', true, 'old'), commit('2', false, 'new')]),
			mk('b', [commit('3', true, 'seen')], { seen: true })
		]);
		expect(q.map((s) => s.repo)).toEqual(['a']);
		expect(q[0].commits.map((c) => c.subject)).toEqual(['new']);
	});
});

describe('CatchUp', () => {
	afterEach(() => vi.useRealTimers());

	it('plays each repo digest first, then its unseen commits, then the next repo', async () => {
		vi.useFakeTimers();
		const onClose = vi.fn();
		render(CatchUp, {
			stories: [
				mk('alpha', [commit('1', false, 'A one')], { digest }),
				mk('beta', [commit('2', false, 'B one')])
			],
			onSeen: () => {},
			onClose
		});
		expect(screen.getByText('Alpha digest')).toBeInTheDocument();
		await vi.advanceTimersByTimeAsync(5000);
		expect(screen.getByText('A one')).toBeInTheDocument();
		await vi.advanceTimersByTimeAsync(5000);
		expect(screen.getByText('B one')).toBeInTheDocument();
		expect(onClose).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(5000);
		expect(onClose).toHaveBeenCalledTimes(1);
	});
});
