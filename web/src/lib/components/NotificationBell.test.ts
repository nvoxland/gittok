import { render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import NotificationBell from './NotificationBell.svelte';

const fetchMock = vi.fn();
beforeEach(() => {
	vi.useFakeTimers();
	vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
	fetchMock.mockReset();
	vi.unstubAllGlobals();
	vi.useRealTimers();
});
const unread = (n: number) => ({ ok: true, json: async () => ({ notifications: [], unread: n }) });

describe('NotificationBell', () => {
	it('links to /notifications and shows the unread badge', async () => {
		fetchMock.mockResolvedValue(unread(3));
		render(NotificationBell);
		await vi.advanceTimersByTimeAsync(0);
		expect(fetchMock.mock.calls[0][0]).toBe('/api/notifications?unread=1');
		expect(screen.getByRole('link', { name: /Notifications/ })).toHaveAttribute('href', '/notifications');
		expect(screen.getByTestId('badge')).toHaveTextContent('3');
	});

	it('hides the badge at zero', async () => {
		fetchMock.mockResolvedValue(unread(0));
		render(NotificationBell);
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.queryByTestId('badge')).toBeNull();
	});

	it('survives a failed fetch', async () => {
		fetchMock.mockRejectedValue(new Error('offline'));
		render(NotificationBell);
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.queryByTestId('badge')).toBeNull();
	});

	it('polls every 60 seconds while visible', async () => {
		fetchMock.mockResolvedValueOnce(unread(1)).mockResolvedValue(unread(2));
		render(NotificationBell);
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(60_000);
		expect(fetchMock).toHaveBeenCalledTimes(2);
		expect(screen.getByTestId('badge')).toHaveTextContent('2');
	});

	it('does not poll while the page is hidden', async () => {
		fetchMock.mockResolvedValue(unread(1));
		const spy = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
		render(NotificationBell);
		await vi.advanceTimersByTimeAsync(0);
		fetchMock.mockClear();
		await vi.advanceTimersByTimeAsync(120_000);
		expect(fetchMock).not.toHaveBeenCalled();
		spy.mockRestore();
	});
});
