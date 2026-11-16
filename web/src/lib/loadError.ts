import { error } from '@sveltejs/kit';
import { ApiError } from './api.ts';

/** For load functions: a failed API call becomes a SvelteKit error that keeps its HTTP status. */
export async function orHttpError<T>(call: Promise<T>): Promise<T> {
	try {
		return await call;
	} catch (e) {
		if (e instanceof ApiError) error(e.status, e.message);
		throw e;
	}
}
