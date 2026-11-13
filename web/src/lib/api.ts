import { encodePath } from './account.ts';
import { getSessionId } from './session.ts';
import type {
	AnswerResponse,
	Card,
	FeedEvent,
	FeedFilter,
	FeedResponse,
	FileProfile,
	RepoMap,
	NotificationsResponse,
	PersonaProfile,
	Reply,
	RepoProfile,
	Story
} from './types';

export class ApiError extends Error {
	constructor(
		message: string,
		readonly status: number
	) {
		super(message);
	}
}

export async function fetchFeed(
	cursor?: string,
	limit = 20,
	filter: FeedFilter = {},
	// Cards the page holds but the reader has not seen: the server ranks them again.
	drop: string[] = []
): Promise<FeedResponse> {
	const params = new URLSearchParams({ limit: String(limit) });
	if (cursor) params.set('cursor', cursor);
	if (filter.repo) params.set('repo', filter.repo);
	if (filter.dir) params.set('dir', filter.dir);
	if (drop.length) params.set('drop', drop.join(','));
	const res = await fetch(`/api/feed?${params}`);
	// The status lets the page tell "this device is not paired" (401) from other failures.
	if (!res.ok) throw new ApiError(`GET /api/feed failed: ${res.status}`, res.status);
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

export type RepoSummary = { name: string; ref: string; head_sha: string | null; group: string | null };

/** The configured repos. An empty list means GitTok has nothing to make cards from. */
export async function fetchRepos(): Promise<RepoSummary[]> {
	const res = await fetch('/api/repos');
	if (!res.ok) throw new ApiError(`GET /api/repos failed: ${res.status}`, res.status);
	const body = (await res.json()) as { repos?: RepoSummary[] };
	if (!Array.isArray(body.repos)) throw new Error('GET /api/repos: no repos list');
	return body.repos;
}

export async function fetchRepo(name: string): Promise<RepoProfile> {
	const res = await fetch(`/api/repos/${encodeURIComponent(name)}`);
	if (!res.ok) throw new Error(`GET /api/repos/${name} failed: ${res.status}`);
	return (await res.json()) as RepoProfile;
}

export async function fetchPersona(handle: string): Promise<PersonaProfile> {
	const res = await fetch(`/api/personas/${encodeURIComponent(handle)}`);
	if (!res.ok) throw new Error(`GET /api/personas/${handle} failed: ${res.status}`);
	return (await res.json()) as PersonaProfile;
}

export async function fetchFile(repo: string, path: string): Promise<FileProfile> {
	const res = await fetch(`/api/files/${encodeURIComponent(repo)}/${encodePath(path)}`);
	if (!res.ok) throw new Error(`GET /api/files/${repo}/${path} failed: ${res.status}`);
	return (await res.json()) as FileProfile;
}

export async function postFollow(repo: string, path: string, on: boolean): Promise<boolean> {
	const res = await fetch('/api/follows', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ repo, path, on })
	});
	if (!res.ok) throw new Error(`POST /api/follows failed: ${res.status}`);
	return ((await res.json()) as { followed: boolean }).followed;
}

export async function fetchRepoMap(name: string): Promise<RepoMap> {
	const res = await fetch(`/api/repos/${encodeURIComponent(name)}/map`);
	if (!res.ok) throw new Error(`GET /api/repos/${name}/map failed: ${res.status}`);
	return (await res.json()) as RepoMap;
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
	if (!res.ok) throw new ApiError(`POST /api/answer failed: ${res.status}`, res.status);
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

export async function postReply(
	card_id: string,
	comment_index: number,
	text: string
): Promise<Reply> {
	const res = await fetch('/api/replies', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ card_id, comment_index, text })
	});
	if (!res.ok) throw new ApiError(`POST /api/replies failed: ${res.status}`, res.status);
	return (await res.json()) as Reply;
}
