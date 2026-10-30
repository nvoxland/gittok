import { afterEach, describe, expect, it, vi } from 'vitest';
import { createBatcher } from './batcher.ts';
import type { FeedEvent } from './types.ts';

const ev = (n: number): FeedEvent => ({ card_id: `c_${n}`, type: 'impression', ts: n });

const withId = (e: FeedEvent) => ({ ...e, data: { ...e.data, event_id: expect.stringMatching(/^[0-9a-f-]{36}$/) } });

describe('createBatcher', () => {
	it('stamps a unique event_id, keeps existing data, and keeps it across requeue', async () => {
		const post = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValue(undefined);
		const b = createBatcher(post, 5000);
		b.push({ ...ev(1), data: { k: 1 } });
		b.push(ev(2));
		await b.flush();
		await b.flush();
		const [first, second] = post.mock.calls[1][0] as FeedEvent[];
		expect(first.data?.k).toBe(1);
		expect(first.data?.event_id).not.toBe(second.data?.event_id);
		expect(first.data?.event_id).toBe((post.mock.calls[0][0] as FeedEvent[])[0].data?.event_id);
	});

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
		expect(post).toHaveBeenCalledWith([withId(ev(1)), withId(ev(2))]);
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
		expect(post).toHaveBeenLastCalledWith([withId(ev(1)), withId(ev(2))]);
	});

	describe('leaving the page', () => {
		afterEach(() => vi.unstubAllGlobals());

		it('stop() sends pending events with sendBeacon as a JSON blob', async () => {
			const beacon = vi.fn().mockReturnValue(true);
			vi.stubGlobal('navigator', { sendBeacon: beacon });
			const b = createBatcher(vi.fn().mockResolvedValue(undefined), 5000);
			b.start();
			b.push(ev(1));
			b.stop();
			expect(beacon).toHaveBeenCalledTimes(1);
			const [url, blob] = beacon.mock.calls[0] as [string, Blob];
			expect(url).toBe('/api/events');
			expect(blob.type).toBe('application/json');
			expect(JSON.parse(await blob.text())).toEqual({ events: [withId(ev(1))] });
			b.stop();
			expect(beacon).toHaveBeenCalledTimes(1);
		});

		it('stop() falls back to fetch with keepalive when sendBeacon is missing', () => {
			vi.stubGlobal('navigator', {});
			const f = vi.fn().mockResolvedValue({ ok: true });
			vi.stubGlobal('fetch', f);
			const b = createBatcher(vi.fn(), 5000);
			b.push(ev(1));
			b.stop();
			expect(f).toHaveBeenCalledTimes(1);
			const init = f.mock.calls[0][1] as RequestInit;
			expect(init.keepalive).toBe(true);
			expect(JSON.parse(init.body as string)).toEqual({ events: [withId(ev(1))] });
		});

		it('stop() with nothing queued sends nothing', () => {
			const beacon = vi.fn().mockReturnValue(true);
			vi.stubGlobal('navigator', { sendBeacon: beacon });
			createBatcher(vi.fn(), 5000).stop();
			expect(beacon).not.toHaveBeenCalled();
		});

		it('flushes on pagehide', () => {
			const beacon = vi.fn().mockReturnValue(true);
			vi.stubGlobal('navigator', { sendBeacon: beacon });
			const b = createBatcher(vi.fn(), 5000);
			b.start();
			b.push(ev(1));
			window.dispatchEvent(new Event('pagehide'));
			expect(beacon).toHaveBeenCalledTimes(1);
			b.stop();
		});
	});
});
