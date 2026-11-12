// Product renames: keys used to start with "blamescroll." and, before that, "codescroll.".
// Read the new key; if it is absent, read the newest old key once and copy the value to the new key.
const LEGACY_PREFIXES = ['blamescroll.', 'codescroll.'];

export function getItemWithLegacy(store: Storage, key: string): string | null {
	const current = store.getItem(key);
	if (current !== null) return current;
	for (const prefix of LEGACY_PREFIXES) {
		const old = store.getItem(key.replace(/^gittok\./, prefix));
		if (old === null) continue;
		try {
			store.setItem(key, old);
		} catch {
			// ignore: the value is still returned
		}
		return old;
	}
	return null;
}
