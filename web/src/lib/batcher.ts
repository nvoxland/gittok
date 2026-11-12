import { randomId } from './session.ts';
import type { FeedEvent } from './types.ts';

export function createBatcher(
	post: (events: FeedEvent[]) => Promise<void>,
	intervalMs = 5000,
	url = '/api/events'
) {
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

	// For when the page is going away: a normal request may be cancelled, so use sendBeacon
	// (or fetch with keepalive). Fire and forget; the queue is cleared either way.
	function flushOnExit(): void {
		if (queue.length === 0) return;
		const body = JSON.stringify({ events: queue });
		queue = [];
		try {
			const blob = new Blob([body], { type: 'application/json' });
			if (typeof navigator !== 'undefined' && navigator.sendBeacon?.(url, blob)) return;
		} catch {
			// fall through to fetch
		}
		try {
			void fetch(url, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body,
				keepalive: true
			}).catch(() => {});
		} catch {
			// nothing more to try
		}
	}

	const onPageHide = () => flushOnExit();

	return {
		push(e: FeedEvent) {
			queue.push({ ...e, data: { ...e.data, event_id: randomId() } });
		},
		flush,
		flushOnExit,
		start() {
			timer ??= setInterval(() => void flush(), intervalMs);
			window.addEventListener('pagehide', onPageHide);
		},
		stop() {
			if (timer !== undefined) clearInterval(timer);
			timer = undefined;
			window.removeEventListener('pagehide', onPageHide);
			flushOnExit();
		}
	};
}
