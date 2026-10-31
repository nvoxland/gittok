// Live watch stats per card, so the feed can send them with the dwell event.
import type { PlayerStats } from './player.ts';

const getters = new Map<string, () => PlayerStats>();

export function registerPlayStats(cardId: string, get: () => PlayerStats): () => void {
	getters.set(cardId, get);
	return () => {
		if (getters.get(cardId) === get) getters.delete(cardId);
	};
}

export function playStats(cardId: string): PlayerStats | undefined {
	return getters.get(cardId)?.();
}
