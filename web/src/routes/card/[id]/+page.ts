import { fetchCard, fetchSaved } from '#lib/api.ts';
import { setFlag } from '#lib/cardState.ts';
import { orHttpError } from '#lib/loadError.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	const [card, saved] = await Promise.all([
		orHttpError(fetchCard(params.id)),
		// The server knows what was saved on other devices; localStorage only this one.
		fetchSaved().then(
			(cards) => (Array.isArray(cards) ? cards.some((c) => c.id === params.id) : null),
			() => null
		)
	]);
	if (saved !== null) setFlag(card.id, 'saved', saved);
	return { card };
};
