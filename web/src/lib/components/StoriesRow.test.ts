import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import StoriesRow from './StoriesRow.svelte';
import type { Story } from '#lib/types.ts';

const story = (o: Partial<Story> = {}): Story => ({
	repo: 'storefront',
	mascot: 'otter',
	mascot_image: '/assets/mascots/otter.png',
	seen: false,
	commits: [],
	...o
});

describe('StoriesRow', () => {
	it('renders nothing when there are no stories', () => {
		const { container } = render(StoriesRow, { stories: [], onOpen: () => {} });
		expect(container.querySelector('.stories')).toBeNull();
	});

	it('shows the mascot image and an unseen ring', () => {
		render(StoriesRow, { stories: [story()], onOpen: () => {} });
		const btn = screen.getByRole('button', { name: /storefront/ });
		expect(btn).toHaveAttribute('data-seen', 'false');
		expect(btn.querySelector('img')).toHaveAttribute('src', '/assets/mascots/otter.png');
	});

	it('falls back to the repo initial and marks seen stories', () => {
		render(StoriesRow, { stories: [story({ mascot_image: null, seen: true })], onOpen: () => {} });
		const btn = screen.getByRole('button', { name: /storefront/ });
		expect(btn).toHaveAttribute('data-seen', 'true');
		expect(btn.querySelector('img')).toBeNull();
		expect(btn).toHaveTextContent('S');
	});

	it('calls onOpen with the index', async () => {
		const onOpen = vi.fn();
		render(StoriesRow, { stories: [story({ repo: 'a' }), story({ repo: 'b' })], onOpen });
		await fireEvent.click(screen.getByRole('button', { name: /^b/ }));
		expect(onOpen).toHaveBeenCalledWith(1);
	});

	it('has no Catch me up button, even with unseen stories', () => {
		render(StoriesRow, { stories: [story()], onOpen: () => {}, onCatchUp: () => {} } as never);
		expect(screen.queryByRole('button', { name: /catch me up/i })).toBeNull();
	});
});
