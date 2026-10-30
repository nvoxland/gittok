import { fetchCard } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => ({ card: await fetchCard(params.id) });
