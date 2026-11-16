import { fetchSaved } from '#lib/api.ts';
import { orHttpError } from '#lib/loadError.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => ({ cards: await orHttpError(fetchSaved()) });
