// Beat lists: how a template card plays piece by piece.
// After beat i, the template shows its first `shown` parts. Each beat waits long enough to
// read its part. Visuals without an entry here are static.
import type { Visual } from './types.ts';

export type Beat = { shown: number; ms: number };

const MIN_MS = 800;
const MAX_MS = 4000;
const BASE_MS = 600;
const MS_PER_CHAR = 35;

// Each part in reveal order: a `key` the component uses to know which parts are shown, and
// the `text` that sets how long its beat waits. A component given `shown` displays the first
// `shown` parts of this list (partsFor), in its own layout order.
export type Part = { key: string; text: string };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const templateParts: Record<string, (data: any) => Part[]> = {
	group_chat: (d) =>
		d.messages.map((m: { text: string }, i: number) => ({
			key: String(i),
			text: m.text
		})),
	iceberg: (d) =>
		d.layers.map((l: { label: string; items: string[] }, i: number) => ({
			key: String(i),
			text: [l.label, ...l.items].join(' ')
		})),
	thread: (d) => d.posts.map((p: string, i: number) => ({ key: String(i), text: p })),
	day_in_life: (d) =>
		d.steps.map((s: { time: string; text: string }, i: number) => ({
			key: String(i),
			text: `${s.time} ${s.text}`
		})),
	// Worst tier first, so the reveal builds up to S.
	tier_list: (d) =>
		[...d.rows].reverse().map((r: { tier: string; items: { name: string; why: string }[] }) => ({
			key: r.tier,
			text: r.items.map((it) => `${it.name} ${it.why}`).join(' ')
		})),
	// Red and green alternate.
	flags: (d) => {
		const out: Part[] = [];
		for (let i = 0; i < Math.max(d.red.length, d.green.length); i++) {
			if (i < d.red.length) out.push({ key: `red:${d.red[i]}`, text: d.red[i] });
			if (i < d.green.length) out.push({ key: `green:${d.green[i]}`, text: d.green[i] });
		}
		return out;
	}
};

export function partsFor(visual: Visual): Part[] {
	if (visual.kind === 'text_meme') return visual.lines.map((l, i) => ({ key: String(i), text: l }));
	if (visual.kind !== 'template') return [];
	return templateParts[visual.template]?.(visual.data) ?? [];
}

/** Keys of the parts in reveal order. */
export function revealOrder(visual: Visual): string[] {
	return partsFor(visual).map((p) => p.key);
}

function readMs(text: string): number {
	return Math.min(MAX_MS, Math.max(MIN_MS, BASE_MS + MS_PER_CHAR * text.length));
}

export function beatsFor(visual: Visual): Beat[] {
	return partsFor(visual).map((p, i) => ({ shown: i + 1, ms: readMs(p.text) }));
}

export function totalMs(beats: Beat[]): number {
	return beats.reduce((sum, b) => sum + b.ms, 0);
}

/** For a template component: keys of its first `shown` parts. */
export function shownKeys(template: string, data: unknown, shown: number): Set<string> {
	const parts = templateParts[template]?.(data) ?? [];
	return new Set(parts.slice(0, shown).map((p) => p.key));
}
