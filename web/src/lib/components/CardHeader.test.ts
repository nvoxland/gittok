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
		render(Card, { card: fakeCard({ repo: 'harbor master' }) });
		expect(screen.getByRole('link', { name: 'harbor master' })).toHaveAttribute(
			'href',
			'/repo/harbor%20master'
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
	it('renders each M2 kind', () => {
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
