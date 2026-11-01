import { fetchSaved } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => ({ cards: await fetchSaved() });
