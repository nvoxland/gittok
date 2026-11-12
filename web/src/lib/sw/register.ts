type SyncReg = { sync?: { register(tag: string): Promise<void> } };

export const SYNC_TAG = 'replay-events';

export async function registerServiceWorker(
	nav: Navigator,
	win: Pick<Window, 'addEventListener'>,
	enabled: boolean
): Promise<void> {
	if (!enabled || !('serviceWorker' in nav)) return;
	try {
		const reg = (await nav.serviceWorker.register('/sw.js')) as ServiceWorkerRegistration & SyncReg;
		const replay = async () => {
			const ready = await nav.serviceWorker.ready;
			(ready.active ?? reg.active)?.postMessage({ type: 'replay' });
		};
		await replay();
		win.addEventListener('online', () => void replay());
		// Background Sync where available; otherwise the replay above and the online event cover it.
		await reg.sync?.register(SYNC_TAG).catch(() => {});
	} catch {
		// the app works without a worker
		console.info('Blamescroll: offline mode is off. Service workers need HTTPS or localhost.');
	}
}
