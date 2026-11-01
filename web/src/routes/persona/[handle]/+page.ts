import { fetchPersona } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({ profile: await fetchPersona(params.handle) });
