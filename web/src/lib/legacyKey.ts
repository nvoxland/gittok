// Product rename: keys used to start with "codescroll.". Read the new key; if it is absent,
// read the old key once and copy the value to the new key.
export function getItemWithLegacy(store: Storage, key: string): string | null {
	const current = store.getItem(key);
	if (current !== null) return current;
	const old = store.getItem(key.replace(/^blamescroll\./, 'codescroll.'));
	if (old !== null) {
		try {
			store.setItem(key, old);
		} catch {
			// ignore: the value is still returned
		}
	}
	return old;
}
