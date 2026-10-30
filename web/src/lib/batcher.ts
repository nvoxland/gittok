import type { FeedEvent } from './types.ts';

export function createBatcher(post: (events: FeedEvent[]) => Promise<void>, intervalMs = 5000) {
	let queue: FeedEvent[] = [];
	let timer: ReturnType<typeof setInterval> | undefined;

	async function flush(): Promise<void> {
		if (queue.length === 0) return;
		const batch = queue;
		queue = [];
		try {
			await post(batch);
		} catch {
			queue = [...batch, ...queue];
		}
	}

	return {
		push(e: FeedEvent) {
			queue.push(e);
		},
		flush,
		start() {
			timer ??= setInterval(() => void flush(), intervalMs);
		},
		stop() {
			if (timer !== undefined) clearInterval(timer);
			timer = undefined;
		}
	};
}
