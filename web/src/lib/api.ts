import type { Card, FeedEvent, FeedResponse, RepoProfile } from './types';

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

export async function fetchRepo(name: string): Promise<RepoProfile> {
	const res = await fetch(`/api/repos/${encodeURIComponent(name)}`);
	if (!res.ok) throw new Error(`GET /api/repos/${name} failed: ${res.status}`);
	return (await res.json()) as RepoProfile;
}

export async function fetchCard(id: string): Promise<Card> {
	const res = await fetch(`/api/cards/${encodeURIComponent(id)}`);
	if (!res.ok) throw new Error(`GET /api/cards/${id} failed: ${res.status}`);
	return (await res.json()) as Card;
}
