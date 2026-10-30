// Both arguments are unix seconds.
export function relativeTime(ts: number, now = Date.now() / 1000): string {
	const s = Math.max(0, now - ts);
	if (s < 60) return 'just now';
	if (s < 3600) return `${Math.floor(s / 60)}m ago`;
	if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
	return `${Math.floor(s / 86400)}d ago`;
}
