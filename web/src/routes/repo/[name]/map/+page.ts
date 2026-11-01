import { fetchRepoMap } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({ map: await fetchRepoMap(params.name) });
