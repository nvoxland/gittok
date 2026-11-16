import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ page: { status: 500, error: { message: 'boom' } } }));
vi.mock('$app/state', () => state);
import ErrorPage from './+error.svelte';

describe('+error.svelte', () => {
	it('says the card no longer exists on 404, with a way back to the feed', () => {
		state.page.status = 404;
		render(ErrorPage);
		expect(screen.getByText(/no longer exists/i)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /feed/i }).getAttribute('href')).toBe('/');
		expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
	});
	it('says the device needs pairing on 401', () => {
		state.page.status = 401;
		render(ErrorPage);
		expect(screen.getByText(/needs pairing/i)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /feed/i }).getAttribute('href')).toBe('/');
	});
	it('shows the status and message for other errors', () => {
		state.page.status = 500;
		render(ErrorPage);
		expect(screen.getByText('500')).toBeInTheDocument();
		expect(screen.getByText(/boom/)).toBeInTheDocument();
	});
});
