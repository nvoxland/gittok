import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import RepoProfile from './RepoProfile.svelte';
import { fakeCard, memeVisual, images } from './fixtures.ts';
import type { RepoProfile as Profile } from '#lib/types.ts';

const profile = (over: Partial<Profile> = {}): Profile => ({
	name: 'storefront',
	mascot: 'otter',
	mascot_image: '/assets/mascots/otter.png',
	group: 'work',
	stats: {
		commits_365: 321,
		authors_365: 4,
		last_commit_ts: 1761826800,
		top_files: [{ path: 'src/a.clj', commits: 40 }],
		top_dirs: [{ path: 'src', commits: 90 }]
	},
	cards: [
		fakeCard({ id: 'c_1', hook: 'First hook' }),
		fakeCard({
			id: 'c_2',
			hook: 'Second hook',
			format: 'meme',
			visual: memeVisual(),
			resolved: { visual: images(), depth: [] }
		})
	],
	...over
});

describe('RepoProfile', () => {
	it('links to the map and top dirs to the filtered feed', () => {
		render(RepoProfile, { profile: profile() });
		expect(screen.getByRole('link', { name: 'Map' })).toHaveAttribute(
			'href',
			'/repo/storefront/map'
		);
		expect(screen.getByRole('link', { name: 'src' })).toHaveAttribute(
			'href',
			'/?repo=storefront&dir=src'
		);
	});

	it('shows verdict counts per top dir', () => {
		render(RepoProfile, {
			profile: profile({
				verdicts: [
					{ dir: 'billing', counts: { cursed: 2, core: 1 } },
					{ dir: 'api', counts: { clever: 3 } }
				]
			})
		});
		const row = screen.getByTestId('verdicts-billing');
		expect(row).toHaveTextContent('billing');
		expect(row).toHaveTextContent('cursed 2');
		expect(row).toHaveTextContent('core 1');
		expect(screen.getByTestId('verdicts-api')).toHaveTextContent('clever 3');
	});
	it('hides the verdict section when there are none', () => {
		render(RepoProfile, { profile: profile({ verdicts: [] }) });
		expect(screen.queryByRole('heading', { name: 'Verdicts' })).toBeNull();
	});
	it('renders name, group, mascot and stats', () => {
		const { container } = render(RepoProfile, { profile: profile() });
		expect(screen.getByRole('heading', { name: 'storefront' })).toBeInTheDocument();
		expect(screen.getByText('work')).toBeInTheDocument();
		expect(container.querySelector('img.mascot')!.getAttribute('src')).toBe(
			'/assets/mascots/otter.png'
		);
		expect(screen.getByText('321')).toBeInTheDocument();
		expect(screen.getByText('4')).toBeInTheDocument();
		expect(screen.getByText('2025-10-30')).toBeInTheDocument();
		expect(screen.getByText('src/a.clj')).toBeInTheDocument();
		expect(screen.getByText('src')).toBeInTheDocument();
	});
	it('shows a placeholder without a mascot image', () => {
		const { container } = render(RepoProfile, {
			profile: profile({ mascot_image: null, mascot: null })
		});
		expect(container.querySelector('img.mascot')).toBeNull();
		expect(container.querySelector('.mascot.placeholder')).not.toBeNull();
	});
	it('lists cards linking to /card/{id}', () => {
		render(RepoProfile, { profile: profile() });
		expect(screen.getByRole('link', { name: /First hook/ })).toHaveAttribute('href', '/card/c_1');
		expect(screen.getByRole('link', { name: /Second hook/ })).toHaveAttribute('href', '/card/c_2');
	});
	it('handles no cards and no last commit', () => {
		render(RepoProfile, {
			profile: profile({ cards: [], stats: { ...profile().stats, last_commit_ts: null } })
		});
		expect(screen.getByText(/no cards yet/i)).toBeInTheDocument();
	});
});
