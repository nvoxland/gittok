import { describe, expect, it } from 'vitest';
import { ApiError } from './api.ts';
import { orHttpError } from './loadError.ts';

describe('orHttpError', () => {
	it('turns an ApiError into a SvelteKit error with the same status', async () => {
		await expect(orHttpError(Promise.reject(new ApiError('gone', 404)))).rejects.toMatchObject({ status: 404 });
	});
	it('passes values and other errors through', async () => {
		expect(await orHttpError(Promise.resolve(3))).toBe(3);
		await expect(orHttpError(Promise.reject(new TypeError('net')))).rejects.toBeInstanceOf(TypeError);
	});
});
