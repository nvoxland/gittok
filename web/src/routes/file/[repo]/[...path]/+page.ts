import { fetchFile } from '#lib/api.ts';
import { orHttpError } from '#lib/loadError.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({
	profile: await orHttpError(fetchFile(params.repo, params.path))
});
