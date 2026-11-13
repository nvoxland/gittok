// Per-card like/save state and per-session quiz answers.
// Memory first; localStorage / sessionStorage are best-effort.

import type { Reply } from './types.ts';

const KEY = 'gittok.card-state';
const ANSWER_KEY = 'gittok.answers';

export type CardFlags = { liked?: boolean; saved?: boolean; disliked?: boolean };

let flagsCache: Record<string, CardFlags> | undefined;
let answersCache: Record<string, StoredAnswer> | undefined;

// Answers are kept per tab so a quiz you answered stays answered. A card that the server shows
// again is due for spaced repetition, so it must be answerable again. Rule: a stored answer
// expires after 12 hours, and the page calls clearAnswers() for every card in a freshly
// fetched feed batch (a card in a new batch has not been seen in this batch, so it is new or due).
const ANSWER_TTL_MS = 12 * 3600_000;
type StoredAnswer = { value: unknown; at: number };

const flagsMap = () => (flagsCache ??= load<Record<string, CardFlags>>(() => localStorage, KEY));
const answersMap = () =>
	(answersCache ??= load<Record<string, StoredAnswer>>(() => sessionStorage, ANSWER_KEY));

function load<T>(store: () => Storage, key: string): T {
	try {
		return JSON.parse(store().getItem(key) ?? '{}') as T;
	} catch {
		return {} as T;
	}
}
function save(store: () => Storage, key: string, value: unknown): void {
	try {
		store().setItem(key, JSON.stringify(value));
	} catch {
		// storage unavailable: memory only
	}
}

export function getFlags(id: string): CardFlags {
	return flagsMap()[id] ?? {};
}

export function setFlag(id: string, flag: keyof CardFlags, on: boolean): void {
	const flags = flagsMap();
	flags[id] = { ...flags[id], [flag]: on };
	save(() => localStorage, KEY, flags);
}

export function getAnswer<T>(id: string): T | undefined {
	const stored = answersMap()[id];
	if (!stored || Date.now() - stored.at > ANSWER_TTL_MS) {
		return undefined;
	}
	return stored.value as T;
}

export function setAnswer(id: string, value: unknown): void {
	const answers = answersMap();
	answers[id] = { value, at: Date.now() };
	save(() => sessionStorage, ANSWER_KEY, answers);
}

export function clearAnswers(ids: string[]): void {
	const answers = answersMap();
	let changed = false;
	for (const id of ids) {
		if (id in answers) {
			delete answers[id];
			changed = true;
		}
	}
	if (changed) save(() => sessionStorage, ANSWER_KEY, answers);
}

// Beat cards play once; afterwards they open on the full view.
const PLAYED_KEY = 'gittok.played';
let playedCache: Record<string, number> | undefined;
const playedMap = () => (playedCache ??= load<Record<string, number>>(() => localStorage, PLAYED_KEY));

export function hasPlayed(id: string): boolean {
	return id in playedMap();
}

export function setPlayed(id: string): void {
	const played = playedMap();
	played[id] = Date.now();
	save(() => localStorage, PLAYED_KEY, played);
}

// Replies sent in this page load. The feed unmounts cards far from the screen; a card that
// mounts again reads its replies from here, because its `card.replies` is from the first fetch.
const sentReplies = new Map<string, Reply[]>();

export function addSentReply(cardId: string, reply: Reply): void {
	sentReplies.set(cardId, [...(sentReplies.get(cardId) ?? []), reply]);
}

/** The server's replies plus the ones sent since, each once. */
export function withSentReplies(cardId: string, fromServer: Reply[]): Reply[] {
	const have = new Set(fromServer.map((r) => r.id));
	return [...fromServer, ...(sentReplies.get(cardId) ?? []).filter((r) => !have.has(r.id))];
}

export function resetCardStateForTest(): void {
	sentReplies.clear();
	flagsCache = undefined;
	answersCache = undefined;
	playedCache = undefined;
	try {
		localStorage.removeItem(PLAYED_KEY);
	} catch {
		// no storage
	}
}
