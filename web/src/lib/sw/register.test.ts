import { describe, expect, it, vi } from 'vitest';
import { registerServiceWorker } from './register.ts';

function fakeEnv() {
	const active = { postMessage: vi.fn() };
	const reg = { active, sync: { register: vi.fn(async () => {}) } };
	const sw = { register: vi.fn(async () => reg), ready: Promise.resolve(reg) };
	const listeners: Record<string, () => void> = {};
	const win = { addEventListener: (n: string, f: () => void) => (listeners[n] = f) };
	return { sw, reg, active, win, listeners };
}

describe('registerServiceWorker', () => {
	it('does nothing in dev', async () => {
		const e = fakeEnv();
		await registerServiceWorker({ serviceWorker: e.sw } as never, e.win as never, false);
		expect(e.sw.register).not.toHaveBeenCalled();
	});
	it('does nothing without service worker support', async () => {
		const e = fakeEnv();
		await expect(registerServiceWorker({} as never, e.win as never, true)).resolves.toBeUndefined();
	});
	it('registers /sw.js, asks for a queue replay and a background sync', async () => {
		const e = fakeEnv();
		await registerServiceWorker({ serviceWorker: e.sw } as never, e.win as never, true);
		expect(e.sw.register).toHaveBeenCalledWith('/sw.js');
		expect(e.active.postMessage).toHaveBeenCalledWith({ type: 'replay' });
		expect(e.reg.sync.register).toHaveBeenCalledWith('replay-events');
	});
	it('replays again when the browser goes online', async () => {
		const e = fakeEnv();
		await registerServiceWorker({ serviceWorker: e.sw } as never, e.win as never, true);
		e.active.postMessage.mockClear();
		e.listeners.online();
		await Promise.resolve();
		expect(e.active.postMessage).toHaveBeenCalledWith({ type: 'replay' });
	});
});
