import type { FeedEvent, FeedResponse } from './types';

export async function fetchFeed(cursor?: string, limit = 20): Promise<FeedResponse> {
	const params = new URLSearchParams({ limit: String(limit) });
	if (cursor) params.set('cursor', cursor);
	const res = await fetch(`/api/feed?${params}`);
	if (!res.ok) throw new Error(`GET /api/feed failed: ${res.status}`);
	return (await res.json()) as FeedResponse;
}

export async function postEvents(events: FeedEvent[]): Promise<void> {
	const res = await fetch('/api/events', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ events })
	});
	if (!res.ok) throw new Error(`POST /api/events failed: ${res.status}`);
}
