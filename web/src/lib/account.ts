/** Accounts are a persona handle ("greybeard") or a code account ("repo:path"). */
export function isCodeAccount(account: string): boolean {
	return account.includes(':');
}

export function accountHandle(account: string): string {
	if (!isCodeAccount(account)) return `@${account}`;
	const path = account.slice(account.indexOf(':') + 1).replace(/\/+$/, '');
	return `@${path.split('/').pop() || path}`;
}

export function initials(handle: string): string {
	const parts = handle.replace(/^@/, '').split(/[^A-Za-z0-9]+/).filter(Boolean);
	if (parts.length === 0) return '?';
	if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
	return (parts[0][0] + parts[1][0]).toUpperCase();
}
