import { getItemWithLegacy } from './legacyKey';

const KEY = 'blamescroll.session';
let memory: string | undefined;

// crypto.randomUUID exists only in secure contexts (HTTPS, localhost), not on a LAN http:// page.
export function randomId(): string {
	try {
		return crypto.randomUUID();
	} catch {
		return Math.random().toString(36).slice(2) + Date.now().toString(36);
	}
}

export function getSessionId(): string {
	if (memory) return memory;
	try {
		const stored = getItemWithLegacy(sessionStorage, KEY);
		if (stored) {
			memory = stored;
			return stored;
		}
	} catch {
		// sessionStorage unavailable: keep the id in memory only.
	}
	memory = randomId();
	try {
		sessionStorage.setItem(KEY, memory);
	} catch {
		// ignore
	}
	return memory;
}

export function resetSessionForTest(): void {
	memory = undefined;
}
