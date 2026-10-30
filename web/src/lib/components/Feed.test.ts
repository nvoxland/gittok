import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Feed from './Feed.svelte';
import type { Card } from '$lib/types';

function fakeCard(n: number): Card {
	return {
		id: `c_${n}`,
		created_at: '2026-10-30T12:00:00Z',
		repo: 'gittok',
		story_type: 'hot_spot',
		format: 'code_card',
		persona: 'greybeard',
		tone: 'dry-deadpan',
		hook: `Hook number ${n}`,
		visual: { kind: 'text', title: 't' },
		depth: [],
		comments: [],
		sources: [],
		resolved: { visual: null, depth: [] }
	};
}

describe('Feed', () => {
	it('renders one Card per feed item', () => {
		const cards = [1, 2, 3].map(fakeCard);
		const { container } = render(Feed, { cards });
		expect(container.querySelector('.feed')).toBeInTheDocument();
		expect(screen.getAllByRole('article')).toHaveLength(3);
		for (const c of cards) expect(screen.getByText(c.hook)).toBeInTheDocument();
	});
});
