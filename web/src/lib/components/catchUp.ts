import type { Story } from '#lib/types.ts';

/** The stories to play for "Catch me up": repos with unseen commits, unseen commits only. */
export function catchUpQueue(stories: Story[]): Story[] {
	return stories
		.map((s) => ({ ...s, commits: s.commits.filter((c) => !c.seen) }))
		.filter((s) => s.commits.length > 0);
}
