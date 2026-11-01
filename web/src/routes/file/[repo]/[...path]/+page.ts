import { fetchFile } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({
	profile: await fetchFile(params.repo, params.path)
});
