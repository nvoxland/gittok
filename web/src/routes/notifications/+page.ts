import { fetchNotifications } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => ({ ...(await fetchNotifications()) });
