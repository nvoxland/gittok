import { fetchRepo } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({ profile: await fetchRepo(params.name) });
