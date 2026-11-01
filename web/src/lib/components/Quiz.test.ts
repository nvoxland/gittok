import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Quiz from './Quiz.svelte';
import { ApiError } from '#lib/api.ts';

const postAnswer = vi.hoisted(() => vi.fn());
vi.mock('#lib/api.ts', async (orig) => ({
	...(await orig<typeof import('#lib/api.ts')>()),
	postAnswer
}));

const interaction = { question: 'Which?', choices: ['A', 'B'] } as never;

beforeEach(() => {
	postAnswer.mockReset();
});

describe('Quiz', () => {
	it('shows a quiet message and does not retry when the card is gone', async () => {
		postAnswer.mockImplementation(() =>
			Promise.reject(new ApiError('POST /api/answer failed: 404', 404))
		);
		render(Quiz, { cardId: 'c_gone', interaction });
		await fireEvent.click(screen.getByRole('button', { name: 'A' }));
		expect(await screen.findByText('This card is gone.')).toBeInTheDocument();
		expect(screen.queryByText(/Try again/)).toBeNull();
		for (const b of screen.getAllByRole('button')) expect(b).toBeDisabled();
		await fireEvent.click(screen.getByRole('button', { name: 'B' }));
		expect(postAnswer).toHaveBeenCalledTimes(1);
	});

	it('still offers a retry on other errors', async () => {
		postAnswer.mockImplementation(() =>
			Promise.reject(new ApiError('POST /api/answer failed: 500', 500))
		);
		render(Quiz, { cardId: 'c_err', interaction });
		await fireEvent.click(screen.getByRole('button', { name: 'A' }));
		expect(await screen.findByText(/Try again/)).toBeInTheDocument();
		expect(screen.queryByText('This card is gone.')).toBeNull();
	});
});
