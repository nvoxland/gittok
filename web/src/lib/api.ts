import { getSessionId } from './session.ts';
import type {
	AnswerResponse,
	Card,
	FeedEvent,
	FeedResponse,
	NotificationsResponse,
	RepoProfile,
	Story
} from './types';

export async function fetchFeed(cursor?: string, limit = 20): Promise<FeedResponse> {
	const params = new URLSearchParams({ limit: String(limit) });
	if (cursor) params.set('cursor', cursor);
	const res = await fetch(`/api/feed?${params}`);
	if (!res.ok) throw new Error(`GET /api/feed failed: ${res.status}`);
	const feed = (await res.json()) as FeedResponse;
	// The service worker marks responses it served from cache.
	if (res.headers?.get('X-From-Cache') === '1') feed.fromCache = true;
	return feed;
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

export async function postAnswer(card_id: string, choice: number): Promise<AnswerResponse> {
	const res = await fetch('/api/answer', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ card_id, choice, session: getSessionId() })
	});
	if (!res.ok) throw new Error(`POST /api/answer failed: ${res.status}`);
	return (await res.json()) as AnswerResponse;
}

export async function fetchSaved(): Promise<Card[]> {
	const res = await fetch('/api/saved');
	if (!res.ok) throw new Error(`GET /api/saved failed: ${res.status}`);
	return ((await res.json()) as { cards: Card[] }).cards;
}

export async function fetchStories(): Promise<Story[]> {
	const res = await fetch('/api/stories');
	if (!res.ok) throw new Error(`GET /api/stories failed: ${res.status}`);
	return ((await res.json()) as { stories?: Story[] }).stories ?? [];
}

export type Prefs = { playback_speed: number };

export async function fetchPrefs(): Promise<Prefs> {
	const res = await fetch('/api/prefs');
	if (!res.ok) throw new Error(`GET /api/prefs failed: ${res.status}`);
	return (await res.json()) as Prefs;
}

async function postJson(url: string, body: unknown): Promise<void> {
	const res = await fetch(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`POST ${url} failed: ${res.status}`);
}

export function markStoriesSeen(repo: string, shas: string[]): Promise<void> {
	return postJson('/api/stories/seen', { repo, shas });
}

export async function fetchNotifications(unreadOnly = false): Promise<NotificationsResponse> {
	const res = await fetch(unreadOnly ? '/api/notifications?unread=1' : '/api/notifications');
	if (!res.ok) throw new Error(`GET /api/notifications failed: ${res.status}`);
	const body = (await res.json()) as Partial<NotificationsResponse>;
	return { notifications: body.notifications ?? [], unread: body.unread ?? 0 };
}

export function markNotificationsRead(ids: number[] | 'all'): Promise<void> {
	return postJson('/api/notifications/read', ids === 'all' ? { all: true } : { ids });
}
