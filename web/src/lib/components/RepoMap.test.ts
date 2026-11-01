import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import RepoMap from './RepoMap.svelte';
import type { RepoMap as Map } from '#lib/types.ts';

const map = (): Map => ({
	name: 'storefront',
	dirs: [
		{
			dir: 'billing',
			cards_seen: 3,
			cards_available: 2,
			quiz_right: 2,
			quiz_wrong: 1,
			novelty: 0.25,
			verdicts: { cursed: 2, core: 1 }
		},
		{
			dir: 'billing/sub',
			cards_seen: 0,
			cards_available: 0,
			quiz_right: 0,
			quiz_wrong: 0,
			novelty: 1,
			verdicts: {}
		}
	]
});

describe('RepoMap', () => {
	it('shows known-ness and verdict chips per dir', () => {
		render(RepoMap, { map: map() });
		const row = screen.getByTestId('map-billing');
		expect(row).toHaveTextContent('75% known');
		expect(row).toHaveTextContent('cursed 2');
		expect(row).toHaveTextContent('core 1');
		expect(row).toHaveTextContent('3 seen');
		expect(row).toHaveTextContent('2 new');
		expect(screen.getByTestId('map-billing/sub')).toHaveTextContent('0% known');
	});

	it('links each dir to the feed filtered to that dir', () => {
		render(RepoMap, { map: map() });
		expect(screen.getByRole('link', { name: /^billing\/sub/ })).toHaveAttribute(
			'href',
			'/?repo=storefront&dir=billing%2Fsub'
		);
	});

	it('says so when there are no dirs', () => {
		render(RepoMap, { map: { name: 'x', dirs: [] } });
		expect(screen.getByText(/No dirs yet/)).toBeInTheDocument();
	});
});
