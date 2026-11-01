import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import MemeVisual from './MemeVisual.svelte';
import IllustrationVisual from './IllustrationVisual.svelte';
import ComicVisual from './ComicVisual.svelte';
import { comicVisual, illustrationVisual, images, memeVisual } from '../fixtures.ts';

describe('MemeVisual', () => {
	it('renders img from resolved with dims, lazy, alt from lines, no overlay', () => {
		const { container } = render(MemeVisual, { visual: memeVisual(), resolved: images() });
		const img = container.querySelector('img')!;
		expect(img.getAttribute('src')).toBe('/assets/c_1/0.png');
		expect(img.getAttribute('width')).toBe('1024');
		expect(img.getAttribute('height')).toBe('1024');
		expect(img.getAttribute('loading')).toBe('lazy');
		expect(img.getAttribute('alt')).toBe('Reading the docs / Reading git blame');
		expect(container.querySelector('.caption')).toBeNull();
	});
});

describe('IllustrationVisual', () => {
	it('renders img and overlays the caption', () => {
		const { container } = render(IllustrationVisual, {
			visual: illustrationVisual(),
			resolved: images()
		});
		expect(container.querySelector('img')!.getAttribute('src')).toBe('/assets/c_1/0.png');
		expect(container.querySelector('img')!.getAttribute('alt')).toBe('Me, deploying on a Friday');
		expect(container.querySelector('.caption')).toHaveTextContent('Me, deploying on a Friday');
		expect(screen.getByText('Me, deploying on a Friday')).toBeInTheDocument();
	});
});

describe('ComicVisual', () => {
	it('renders one panel per image with captions', () => {
		const { container } = render(ComicVisual, { visual: comicVisual(4), resolved: images(4) });
		expect(container.querySelectorAll('.panel')).toHaveLength(4);
		expect(container.querySelector('.grid')).toHaveClass('cols-2');
		expect(screen.getByText('Caption 2')).toBeInTheDocument();
	});
	it('puts 3 panels side by side in one strip, so the whole comic fits on the front', () => {
		const { container } = render(ComicVisual, { visual: comicVisual(3), resolved: images(3) });
		expect(container.querySelector('.grid')).toHaveClass('cols-3');
	});
	it('while playing, shows only the current panel, full width', () => {
		const { container } = render(ComicVisual, {
			visual: comicVisual(3),
			resolved: images(3),
			shown: 2
		});
		const panels = container.querySelectorAll('.panel');
		expect(panels).toHaveLength(1);
		expect(container.querySelector('.grid')).toHaveClass('cols-1');
		expect(panels[0]).toHaveTextContent('Caption 1');
		expect(panels[0].querySelector('img')!.getAttribute('src')).toBe(images(3).images[1]);
	});
	it('shows captions under the pictures, not over them', () => {
		const { container } = render(ComicVisual, { visual: comicVisual(3), resolved: images(3) });
		const panel = container.querySelector('.panel')!;
		expect(panel.lastElementChild!.tagName).toBe('FIGCAPTION');
		expect(panel.querySelector('figcaption')).toHaveClass('below');
	});
});
