import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import StoryViewer from './StoryViewer.svelte';
import type { Story } from '#lib/types.ts';

const NOW = 1_700_000_000;
const story: Story = {
	repo: 'storefront',
	mascot: 'otter',
	mascot_image: null,
	seen: false,
	commits: [
		{ sha: 'a'.repeat(40), short: 'aaaaaaa', ts: NOW - 7200, author: 'Ann', subject: 'First fix', files: 3 },
		{ sha: 'b'.repeat(40), short: 'bbbbbbb', ts: NOW - 60, author: 'Bob', subject: 'Second fix', files: 1 }
	]
};

function setup(over: Record<string, unknown> = {}) {
	const onClose = vi.fn();
	const onSeen = vi.fn();
	render(StoryViewer, { story, onClose, onSeen, now: NOW, ...over });
	return { onClose, onSeen };
}

describe('StoryViewer', () => {
	it('shows the first commit details', () => {
		setup();
		expect(screen.getByText('First fix')).toBeInTheDocument();
		expect(screen.getByText(/Ann/)).toBeInTheDocument();
		expect(screen.getByText(/2h ago/)).toBeInTheDocument();
		expect(screen.getByText(/3 files/)).toBeInTheDocument();
		expect(screen.getByText('aaaaaaa')).toBeInTheDocument();
	});

	it('renders one progress bar per commit with the current one active', () => {
		setup();
		const bars = screen.getAllByTestId('progress');
		expect(bars).toHaveLength(2);
		expect(bars[0]).toHaveAttribute('data-state', 'active');
		expect(bars[1]).toHaveAttribute('data-state', 'upcoming');
	});

	it('moves on right tap and back on left tap', async () => {
		setup();
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		expect(screen.getByText('Second fix')).toBeInTheDocument();
		expect(screen.getByText(/1 file(?!s)/)).toBeInTheDocument();
		expect(screen.getAllByTestId('progress')[0]).toHaveAttribute('data-state', 'done');
		await fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
		expect(screen.getByText('First fix')).toBeInTheDocument();
	});

	it('closes when tapping right on the last page', async () => {
		const { onClose } = setup();
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		expect(onClose).toHaveBeenCalled();
	});

	it('closes with the X button and Escape', async () => {
		const { onClose } = setup();
		await fireEvent.click(screen.getByRole('button', { name: 'Close' }));
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(onClose).toHaveBeenCalledTimes(2);
	});

	it('closes on swipe down', async () => {
		const { onClose } = setup();
		const dialog = screen.getByRole('dialog');
		await fireEvent.touchStart(dialog, { touches: [{ clientX: 100, clientY: 100 }] });
		await fireEvent.touchEnd(dialog, { changedTouches: [{ clientX: 102, clientY: 260 }] });
		expect(onClose).toHaveBeenCalled();
	});

	it('does not close on a short vertical move', async () => {
		const { onClose } = setup();
		const dialog = screen.getByRole('dialog');
		await fireEvent.touchStart(dialog, { touches: [{ clientX: 100, clientY: 100 }] });
		await fireEvent.touchEnd(dialog, { changedTouches: [{ clientX: 100, clientY: 120 }] });
		expect(onClose).not.toHaveBeenCalled();
	});

	it('marks each sha seen when shown', async () => {
		const { onSeen } = setup();
		expect(onSeen).toHaveBeenCalledWith('storefront', ['a'.repeat(40)]);
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		expect(onSeen).toHaveBeenCalledWith('storefront', ['b'.repeat(40)]);
		expect(onSeen).toHaveBeenCalledTimes(2);
	});

	it('links a commit page to its card, else to GitHub, else nothing', async () => {
		const linked: Story = {
			...story,
			commits: [
				{ ...story.commits[0], card_id: 'c_1', url: null },
				{ ...story.commits[1], card_id: null, url: 'https://github.com/o/r/commit/bbb' },
				{ ...story.commits[1], sha: 'c'.repeat(40), short: 'ccccccc', subject: 'Third' }
			]
		};
		setup({ story: linked });
		expect(screen.getByRole('link', { name: /read the card/i })).toHaveAttribute('href', '/card/c_1');
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		expect(screen.getByRole('link', { name: /github/i })).toHaveAttribute(
			'href',
			'https://github.com/o/r/commit/bbb'
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		expect(screen.queryByRole('link')).toBeNull();
	});

	it('puts the digest card first and does not mark it as a commit seen', async () => {
		const withDigest: Story = {
			...story,
			digest: { card_id: 'c_d', day: '2026-10-30', hook: 'Auth day', learn: 'Three commits reshaped auth.' }
		};
		const { onSeen } = setup({ story: withDigest });
		expect(screen.getByText('Auth day')).toBeInTheDocument();
		expect(screen.getByText('Three commits reshaped auth.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /read card/i })).toHaveAttribute('href', '/card/c_d');
		expect(screen.getAllByTestId('progress')).toHaveLength(3);
		expect(onSeen).not.toHaveBeenCalled();
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		expect(screen.getByText('First fix')).toBeInTheDocument();
	});
});

describe('StoryViewer autoplay', () => {
	afterEach(() => vi.useRealTimers());

	it('advances every 5 seconds and ends with onEnd', async () => {
		vi.useFakeTimers();
		const onEnd = vi.fn();
		const onClose = vi.fn();
		setup({ autoplay: true, onEnd, onClose });
		expect(screen.getByText('First fix')).toBeInTheDocument();
		await vi.advanceTimersByTimeAsync(5000);
		expect(screen.getByText('Second fix')).toBeInTheDocument();
		await vi.advanceTimersByTimeAsync(5000);
		expect(onEnd).toHaveBeenCalledTimes(1);
		expect(onClose).not.toHaveBeenCalled();
	});

	it('pauses while held', async () => {
		vi.useFakeTimers();
		setup({ autoplay: true });
		const dialog = screen.getByRole('dialog');
		await fireEvent.pointerDown(dialog);
		await vi.advanceTimersByTimeAsync(20000);
		expect(screen.getByText('First fix')).toBeInTheDocument();
		await fireEvent.pointerUp(dialog);
		await vi.advanceTimersByTimeAsync(5000);
		expect(screen.getByText('Second fix')).toBeInTheDocument();
	});

	it('does not advance by itself without autoplay', async () => {
		vi.useFakeTimers();
		setup();
		await vi.advanceTimersByTimeAsync(30000);
		expect(screen.getByText('First fix')).toBeInTheDocument();
	});
});
