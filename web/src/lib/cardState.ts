// Per-card like/save state and per-session quiz answers.
// Memory first; localStorage / sessionStorage are best-effort.
const KEY = 'codescroll.card-state';
const ANSWER_KEY = 'codescroll.answers';

export type CardFlags = { liked?: boolean; saved?: boolean };

let flagsCache: Record<string, CardFlags> | undefined;
let answersCache: Record<string, unknown> | undefined;

const flagsMap = () => (flagsCache ??= load<Record<string, CardFlags>>(() => localStorage, KEY));
const answersMap = () =>
	(answersCache ??= load<Record<string, unknown>>(() => sessionStorage, ANSWER_KEY));

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
	return answersMap()[id] as T | undefined;
}

export function setAnswer(id: string, value: unknown): void {
	const answers = answersMap();
	answers[id] = value;
	save(() => sessionStorage, ANSWER_KEY, answers);
}

export function resetCardStateForTest(): void {
	flagsCache = undefined;
	answersCache = undefined;
}
