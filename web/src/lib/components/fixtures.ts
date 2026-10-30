import type { Card } from '#lib/types.ts';

export function fakeCard(over: Partial<Card> = {}): Card {
	return {
		id: 'c_1',
		created_at: '2026-10-30T12:00:00Z',
		repo: 'gittok',
		story_type: 'hot_spot',
		format: 'code_card',
		persona: 'greybeard',
		tone: 'dry-deadpan',
		hook: 'This file has been edited 41 times.',
		visual: { kind: 'text', title: 'Title', body: 'Body' },
		depth: [],
		comments: [],
		sources: [],
		resolved: { visual: null, depth: [] },
		...over
	};
}
