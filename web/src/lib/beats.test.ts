import { describe, expect, it } from 'vitest';
import { beatsFor, totalMs } from './beats.ts';
import type { Visual } from './types.ts';

const chat = {
	kind: 'template',
	template: 'group_chat',
	data: {
		title: 't',
		messages: [
			{ from: 'greybeard', text: 'hi' },
			{ from: 'archivist', text: 'a much longer message than the first one' }
		]
	}
} as Visual;

const iceberg = {
	kind: 'template',
	template: 'iceberg',
	data: { title: 'Ice', layers: ['a', 'b', 'c'].map((l) => ({ label: l, items: [`${l} item`] })) }
} as Visual;

describe('beatsFor', () => {
	it('gives a group chat one beat per message, longer messages wait longer', () => {
		const beats = beatsFor(chat);
		expect(beats.map((b) => b.shown)).toEqual([1, 2]);
		expect(beats[1].ms).toBeGreaterThan(beats[0].ms);
	});

	it('gives an iceberg one beat per layer, surface first', () => {
		expect(beatsFor(iceberg).map((b) => b.shown)).toEqual([1, 2, 3]);
	});

	it('gives static visuals no beats', () => {
		expect(beatsFor({ kind: 'text', body: 'x' } as Visual)).toEqual([]);
		const take = { kind: 'template', template: 'hot_take', data: { take: 'x' } } as Visual;
		expect(beatsFor(take)).toEqual([]);
	});

	it('keeps every beat between 0.8 and 4 seconds', () => {
		const long = structuredClone(chat) as typeof chat & { data: { messages: { text: string }[] } };
		long.data.messages[0].text = 'x'.repeat(500);
		for (const b of beatsFor(long)) {
			expect(b.ms).toBeGreaterThanOrEqual(800);
			expect(b.ms).toBeLessThanOrEqual(4000);
		}
	});

	it('totals the sequence length', () => {
		const beats = beatsFor(iceberg);
		expect(totalMs(beats)).toBe(beats.reduce((s, b) => s + b.ms, 0));
	});
});
