// Beat lists: how a template card plays piece by piece.
// After beat i, the template shows its first `shown` parts. Each beat waits long enough to
// read its part. Visuals without an entry here are static.
import type { Visual } from './types.ts';

export type Beat = { shown: number; ms: number };

const MIN_MS = 800;
const MAX_MS = 4000;
const BASE_MS = 600;
const MS_PER_CHAR = 35;

// The text of each part, in reveal order. A template's component must show its parts in the
// same order when given `shown`.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const parts: Record<string, (data: any) => string[]> = {
	group_chat: (d) => d.messages.map((m: { text: string }) => m.text),
	iceberg: (d) =>
		d.layers.map((l: { label: string; items: string[] }) => [l.label, ...l.items].join(' '))
};

function readMs(text: string): number {
	return Math.min(MAX_MS, Math.max(MIN_MS, BASE_MS + MS_PER_CHAR * text.length));
}

export function beatsFor(visual: Visual): Beat[] {
	if (visual.kind !== 'template') return [];
	const fn = parts[visual.template];
	if (!fn) return [];
	return fn(visual.data).map((text, i) => ({ shown: i + 1, ms: readMs(text) }));
}

export function totalMs(beats: Beat[]): number {
	return beats.reduce((sum, b) => sum + b.ms, 0);
}
