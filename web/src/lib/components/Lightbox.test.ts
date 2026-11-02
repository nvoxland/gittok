import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCardStateForTest } from '#lib/cardState.ts';
import Card from './Card.svelte';
import type { Card as CardT } from '#lib/types.ts';
import { fakeCard, images, memeVisual, templateFixtures } from './fixtures.ts';

const codeCard = (over: Partial<CardT> = {}) =>
	fakeCard({
		hook: 'Read this code.',
		visual: {
			kind: 'code',
			repo: 'gittok',
			path: 'src/x.py',
			commit: 'abcdef1234567890',
			lines: [10, 12]
		} as unknown as CardT['visual'],
		resolved: {
			visual: { code: 'line_a()\nline_b()\nline_c()', language: 'python', start_line: 10 },
			depth: []
		},
		...over
	});

describe('Card lightbox', () => {
	let observers: Array<() => void> = [];
	beforeEach(() => {
		observers = [];
		vi.stubGlobal(
			'ResizeObserver',
			class {
				constructor(cb: () => void) {
					observers.push(cb);
				}
				observe() {}
				disconnect() {}
			}
		);
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		resetCardStateForTest();
	});

	function size(el: Element, scrollHeight: number, clientHeight: number) {
		Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scrollHeight });
		Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight });
		observers.forEach((cb) => cb());
	}

	it('a tap on a code visual opens the lightbox with every line and no fit class', async () => {
		const onAction = vi.fn();
		const { container } = render(Card, { card: codeCard(), onAction });
		expect(screen.queryByRole('dialog')).toBeNull();
		await fireEvent.click(container.querySelector('.visual')!);
		const dialog = screen.getByRole('dialog');
		expect(dialog).toHaveAttribute('aria-modal', 'true');
		expect(within(dialog).getByText('line_a()')).toBeInTheDocument();
		expect(within(dialog).getByText('line_c()')).toBeInTheDocument();
		expect(within(dialog).getByText('Read this code.')).toBeInTheDocument();
		expect(dialog.querySelector('.codeblock')).not.toHaveClass('fit');
		expect(onAction).toHaveBeenCalledWith('lightbox_open', { kind: 'code' });
	});

	it('Escape and the close button close it', async () => {
		const { container } = render(Card, { card: codeCard() });
		await fireEvent.click(container.querySelector('.visual')!);
		expect(document.body.style.overflow).toBe('hidden');
		await fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
		expect(screen.queryByRole('dialog')).toBeNull();
		await fireEvent.click(container.querySelector('.visual')!);
		await fireEvent.click(screen.getByRole('button', { name: 'Close' }));
		expect(screen.queryByRole('dialog')).toBeNull();
		expect(document.body.style.overflow).not.toBe('hidden');
	});

	it('every visual has a corner Expand button that opens it', async () => {
		render(Card, { card: codeCard() });
		await fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
		expect(screen.getByRole('dialog')).toBeInTheDocument();
	});

	it('a clipped visual shows the fade and Tap to expand; a fitting one only the corner icon', async () => {
		const { container } = render(Card, { card: codeCard() });
		const visual = container.querySelector('.visual')!;
		size(visual, 300, 300);
		await Promise.resolve();
		expect(screen.queryByText('Tap to expand')).toBeNull();
		expect(screen.getByRole('button', { name: 'Expand' })).toBeInTheDocument();
		size(visual, 600, 300);
		await vi.waitFor(() => expect(screen.getByText('Tap to expand')).toBeInTheDocument());
	});

	it('on a beat card a tap skips a beat and only the corner button opens the lightbox', async () => {
		const onAction = vi.fn();
		const card = fakeCard({ visual: templateFixtures.thread });
		const { container } = render(Card, { card, active: true, onAction });
		const visual = container.querySelector('.visual')!;
		await fireEvent.pointerDown(visual.querySelector('.beats')!);
		await fireEvent.pointerUp(visual.querySelector('.beats')!);
		expect(onAction).toHaveBeenCalledWith('beat_tap', expect.anything());
		await fireEvent.click(visual);
		expect(screen.queryByRole('dialog')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
		const dialog = screen.getByRole('dialog');
		expect(dialog.querySelectorAll('.post')).toHaveLength(3);
		expect(onAction).toHaveBeenCalledWith('lightbox_open', { kind: 'template' });
	});

	it('an image visual opens full width', async () => {
		const card = fakeCard({ visual: memeVisual(), resolved: { visual: images(), depth: [] } });
		const { container } = render(Card, { card });
		await fireEvent.click(container.querySelector('.visual')!);
		const dialog = screen.getByRole('dialog');
		expect(dialog.querySelector('img.media')).toHaveAttribute('src', '/assets/c_1/0.png');
		expect(dialog.querySelector('.lb-body')).toHaveClass('media-kind');
	});
});
