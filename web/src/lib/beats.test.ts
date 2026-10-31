import { afterEach, describe, expect, it } from 'vitest';
import { beatsFor, revealOrder, setPlaybackSpeed, shownKeys, totalMs } from './beats.ts';
import type { Visual } from './types.ts';
import { templateFixtures, textMemeVisual as textMeme } from './components/fixtures.ts';

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
	data: {
		title: 'Ice',
		layers: ['a', 'b', 'c'].map((l) => ({ label: l, items: [`${l} item`] }))
	}
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
		const take = {
			kind: 'template',
			template: 'hot_take',
			data: { take: 'x' }
		} as Visual;
		expect(beatsFor(take)).toEqual([]);
	});

	it('keeps every beat between 0.6 and 2 seconds', () => {
		const long = structuredClone(chat) as typeof chat & { data: { messages: { text: string }[] } };
		long.data.messages[0].text = 'x'.repeat(500);
		long.data.messages[1].text = 'x';
		const ms = beatsFor(long).map((b) => b.ms);
		expect(ms).toEqual([2000, 600]);
	});

	it('gives a 55-character line about 1.3 seconds', () => {
		const one = structuredClone(chat) as typeof chat & { data: { messages: { text: string }[] } };
		one.data.messages[0].text = 'x'.repeat(55);
		expect(beatsFor(one)[0].ms).toBe(1310);
	});


	it('totals the sequence length', () => {
		const beats = beatsFor(iceberg);
		expect(totalMs(beats)).toBe(beats.reduce((s, b) => s + b.ms, 0));
	});

	it('plays thread posts and day-in-life steps in order', () => {
		expect(beatsFor(templateFixtures.thread).map((b) => b.shown)).toEqual([1, 2, 3]);
		expect(beatsFor(templateFixtures.day_in_life).map((b) => b.shown)).toEqual([1, 2, 3]);
	});

	it('plays one beat per tier row and per flag, and text memes line by line', () => {
		expect(beatsFor(templateFixtures.tier_list)).toHaveLength(2);
		expect(beatsFor(templateFixtures.flags)).toHaveLength(3);
		expect(beatsFor(textMeme('pov', ['a', 'b', 'c']) as Visual)).toHaveLength(3);
	});

	it('orders tier rows worst first and alternates red and green flags', () => {
		expect(revealOrder(templateFixtures.tier_list)).toEqual(['F', 'S']);
		const flags = {
			kind: 'template',
			template: 'flags',
			data: { subject: 's', red: ['r1', 'r2'], green: ['g1'] }
		} as Visual;
		expect(revealOrder(flags)).toEqual(['red:r1', 'green:g1', 'red:r2']);
	});
});

describe('shownKeys', () => {
	it('gives a component the keys of its first parts', () => {
		const tl = templateFixtures.tier_list as { data: unknown };
		expect([...shownKeys('tier_list', tl.data, 1)]).toEqual(['F']);
		expect([...shownKeys('tier_list', tl.data, Infinity)]).toEqual(['F', 'S']);
	});
});

describe('playback speed', () => {
	afterEach(() => setPlaybackSpeed(1));

	it('divides every beat by the speed the viewer chose', () => {
		const normal = beatsFor(chat).map((b) => b.ms);
		setPlaybackSpeed(2);
		expect(beatsFor(chat).map((b) => b.ms)).toEqual(normal.map((ms) => Math.round(ms / 2)));
	});

	it('ignores nonsense speeds', () => {
		const normal = beatsFor(chat).map((b) => b.ms);
		setPlaybackSpeed(0);
		setPlaybackSpeed(Number.NaN);
		expect(beatsFor(chat).map((b) => b.ms)).toEqual(normal);
	});
});
