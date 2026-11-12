import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GestureHints from './GestureHints.svelte';

describe('GestureHints', () => {
	beforeEach(() => localStorage.clear());
	afterEach(() => vi.restoreAllMocks());

	it('shows the swipe hints on the first visit', () => {
		render(GestureHints);
		const hint = screen.getByRole('note', { name: 'How to use the feed' });
		expect(hint).toHaveTextContent(/swipe up/i);
		expect(hint).toHaveTextContent(/swipe left/i);
	});

	it('goes away for good when dismissed', async () => {
		const first = render(GestureHints);
		await fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
		expect(screen.queryByRole('note')).toBeNull();
		expect(localStorage.getItem('gittok.hints')).toBe('1');
		first.unmount();
		render(GestureHints);
		expect(screen.queryByRole('note')).toBeNull();
	});

	it('still works when storage throws: shown, and dismissed for this visit', async () => {
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('denied');
		});
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('denied');
		});
		render(GestureHints);
		expect(screen.getByRole('note')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
		expect(screen.queryByRole('note')).toBeNull();
	});
});
