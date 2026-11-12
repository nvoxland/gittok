import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Card from './Card.svelte';
import {
	chartResolved,
	chartVisual,
	comicVisual,
	fakeCard,
	images,
	memeVisual,
	templateFixtures,
	textMemeVisual
} from './fixtures.ts';

describe('Card header', () => {
	it('shows the persona with avatar when there is no account', () => {
		const { container } = render(Card, { card: fakeCard() });
		expect(screen.getByText('@greybeard')).toBeInTheDocument();
		expect(container.querySelector('header img')!.getAttribute('src')).toBe('/api/avatars/greybeard');
	});
	it('shows the code account with a file icon instead of the persona', () => {
		const card = fakeCard({
			account: 'gittok:src/shipping.clj',
			resolved: {
				visual: null,
				depth: [],
				account: {
					handle: '@shipping.clj',
					repo: 'gittok',
					path: 'src/shipping.clj',
					kind: 'file'
				}
			}
		});
		const { container } = render(Card, { card });
		expect(screen.getByText('@shipping.clj')).toBeInTheDocument();
		expect(screen.queryByText('@greybeard')).toBeNull();
		expect(container.querySelector('header [data-icon="file"]')).not.toBeNull();
	});
	it('uses the folder icon for a dir account', () => {
		const card = fakeCard({
			account: 'gittok:src',
			resolved: {
				visual: null,
				depth: [],
				account: { handle: '@src', repo: 'gittok', path: 'src', kind: 'dir' }
			}
		});
		const { container } = render(Card, { card });
		expect(container.querySelector('header [data-icon="dir"]')).not.toBeNull();
	});
	it('links the repo name to its profile', () => {
		render(Card, { card: fakeCard({ repo: 'storefront master' }) });
		expect(screen.getByRole('link', { name: 'storefront master' })).toHaveAttribute(
			'href',
			'/repo/storefront%20master'
		);
	});
	it('falls back to initials when the header avatar fails', async () => {
		const { container } = render(Card, { card: fakeCard({ persona: 'penny_learns' }) });
		await fireEvent.error(container.querySelector('header img')!);
		expect(container.querySelector('header .fallback')).toHaveTextContent('PL');
	});
	it('shows avatars in comments', () => {
		const { container } = render(Card, {
			card: fakeCard({ comments: [{ persona: 'archivist', text: 'Since 2019.' }] })
		});
		expect(container.querySelector('.comments img')!.getAttribute('src')).toBe(
			'/api/avatars/archivist'
		);
	});
});

describe('Card visual dispatch', () => {
	it('renders each image and chart kind', () => {
		const cases = [
			{ visual: memeVisual(), resolved: images(), sel: 'img.media' },
			{ visual: comicVisual(2), resolved: images(2), sel: '.panel' },
			{ visual: textMemeVisual('pov', ['x']), resolved: null, sel: '.pov' },
			{ visual: chartVisual(), resolved: chartResolved(), sel: 'rect.bar' },
			{ visual: templateFixtures.thread, resolved: null, sel: '.post' },
			{ visual: templateFixtures.hot_take, resolved: null, sel: 'blockquote' }
		];
		for (const c of cases) {
			const { container, unmount } = render(Card, {
				card: fakeCard({ visual: c.visual, resolved: { visual: c.resolved, depth: [] } })
			});
			expect(container.querySelector(c.sel), c.sel).not.toBeNull();
			unmount();
		}
	});
});

describe('Card header links and series', () => {
	it('links the persona handle to its profile', () => {
		render(Card, { card: fakeCard() });
		expect(screen.getByRole('link', { name: /@greybeard/ })).toHaveAttribute(
			'href',
			'/persona/greybeard'
		);
	});
	it('links a code account to its file page', () => {
		const card = fakeCard({
			account: 'gittok:src/sub scriptions.clj',
			resolved: {
				visual: null,
				depth: [],
				account: {
					handle: '@sub scriptions.clj',
					repo: 'gittok',
					path: 'src/sub scriptions.clj',
					kind: 'file'
				}
			}
		});
		render(Card, { card });
		expect(screen.getByRole('link', { name: /@sub scriptions.clj/ })).toHaveAttribute(
			'href',
			'/file/gittok/src/sub%20scriptions.clj'
		);
	});
	it('shows a Part n/of chip for a series card and none otherwise', () => {
		const { unmount } = render(Card, {
			card: fakeCard({ series: { key: 'saga', part: 2, of: 3 } })
		});
		expect(screen.getByText('Part 2/3')).toBeInTheDocument();
		unmount();
		render(Card, { card: fakeCard({ series: null }) });
		expect(screen.queryByText(/^Part /)).toBeNull();
	});
});
