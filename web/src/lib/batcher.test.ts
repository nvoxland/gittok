import { afterEach, describe, expect, it, vi } from 'vitest';
import { createBatcher } from './batcher.ts';
import type { FeedEvent } from './types.ts';

const ev = (n: number): FeedEvent => ({ card_id: `c_${n}`, type: 'impression', ts: n });

describe('createBatcher', () => {
	afterEach(() => vi.useRealTimers());

	it('posts queued events every interval and not when empty', async () => {
		vi.useFakeTimers();
		const post = vi.fn().mockResolvedValue(undefined);
		const b = createBatcher(post, 5000);
		b.start();
		vi.advanceTimersByTime(5000);
		expect(post).not.toHaveBeenCalled();
		b.push(ev(1));
		b.push(ev(2));
		vi.advanceTimersByTime(5000);
		expect(post).toHaveBeenCalledWith([ev(1), ev(2)]);
		vi.advanceTimersByTime(5000);
		expect(post).toHaveBeenCalledTimes(1);
		b.stop();
	});

	it('flush posts immediately and requeues events when the post fails', async () => {
		const post = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValue(undefined);
		const b = createBatcher(post, 5000);
		b.push(ev(1));
		await b.flush();
		b.push(ev(2));
		await b.flush();
		expect(post).toHaveBeenLastCalledWith([ev(1), ev(2)]);
	});
});
