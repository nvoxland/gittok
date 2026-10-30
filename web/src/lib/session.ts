const KEY = 'codescroll.session';
let memory: string | undefined;

function randomId(): string {
	try {
		return crypto.randomUUID();
	} catch {
		return Math.random().toString(36).slice(2) + Date.now().toString(36);
	}
}

export function getSessionId(): string {
	if (memory) return memory;
	try {
		const stored = sessionStorage.getItem(KEY);
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
