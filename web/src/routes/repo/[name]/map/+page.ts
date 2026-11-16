import { fetchRepoMap } from '#lib/api.ts';
import { orHttpError } from '#lib/loadError.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({ map: await orHttpError(fetchRepoMap(params.name)) });
