import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Feed from './Feed.svelte';
import type { Card, FeedEvent } from '#lib/types.ts';

function fakeCard(n: number): Card {
	return {
		id: `c_${n}`,
		created_at: '2026-10-30T12:00:00Z',
		repo: 'gittok',
		story_type: 'hot_spot',
		format: 'code_card',
		persona: 'greybeard',
		tone: 'dry-deadpan',
		hook: `Hook number ${n}`,
		visual: { kind: 'text', title: 't' },
		depth: [],
		comments: [],
		sources: [],
		resolved: { visual: null, depth: [] }
	};
}

describe('Feed', () => {
	it('renders one Card per feed item', () => {
		const cards = [1, 2, 3].map(fakeCard);
		const { container } = render(Feed, { cards });
		expect(container.querySelector('.feed')).toBeInTheDocument();
		expect(screen.getAllByRole('article')).toHaveLength(3);
		for (const c of cards) expect(screen.getByText(c.hook)).toBeInTheDocument();
	});

	describe('events', () => {
		type Entry = Partial<IntersectionObserverEntry> & { target: Element };
		let observers: FakeIO[] = [];

		class FakeIO {
			observed = new Set<Element>();
			constructor(
				public cb: (entries: Entry[]) => void,
				public options?: IntersectionObserverInit
			) {
				observers.push(this);
			}
			observe(el: Element) {
				this.observed.add(el);
			}
			unobserve(el: Element) {
				this.observed.delete(el);
			}
			disconnect() {
				this.observed.clear();
			}
			fire(target: Element, visible: boolean) {
				this.cb([{ target, isIntersecting: visible, intersectionRatio: visible ? 0.8 : 0.1 }]);
			}
		}

		afterEach(() => {
			vi.unstubAllGlobals();
			vi.useRealTimers();
			observers = [];
		});

		function setup() {
			vi.stubGlobal('IntersectionObserver', FakeIO);
			const events: FeedEvent[] = [];
			const { container } = render(Feed, {
				cards: [1, 2].map(fakeCard),
				onEvent: (e: FeedEvent) => events.push(e)
			});
			const io = observers[0];
			const el = (id: string) => container.querySelector(`[data-card-id="${id}"]`)!;
			return { events, io, el, container };
		}

		it('emits impression when a card becomes visible', () => {
			const { events, io, el } = setup();
			expect(io.options?.threshold).toBe(0.6);
			expect(io.observed.has(el('c_1'))).toBe(true);
			io.fire(el('c_1'), true);
			expect(events).toHaveLength(1);
			expect(events[0]).toMatchObject({ card_id: 'c_1', type: 'impression' });
			expect(typeof events[0].ts).toBe('number');
		});

		it('emits dwell with ms (no skip) when a card leaves after 1s or more', () => {
			vi.useFakeTimers();
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			vi.advanceTimersByTime(4200);
			io.fire(el('c_1'), false);
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell']);
			expect(events[1].data).toEqual({ ms: 4200 });
		});

		it('emits dwell and skip when a card leaves in under 1000 ms', () => {
			vi.useFakeTimers();
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			vi.advanceTimersByTime(400);
			io.fire(el('c_1'), false);
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell', 'skip']);
			expect(events[1].data).toEqual({ ms: 400 });
		});

		it('emits depth_open with the panel index when the horizontal panel changes', async () => {
			vi.stubGlobal('IntersectionObserver', FakeIO);
			const events: FeedEvent[] = [];
			const card = { ...fakeCard(1), depth: [{ kind: 'explain' as const, text: 'x' }] };
			const { container } = render(Feed, { cards: [card], onEvent: (e: FeedEvent) => events.push(e) });
			const row = container.querySelector('.panels') as HTMLElement;
			Object.defineProperty(row, 'clientWidth', { value: 200, configurable: true });
			row.scrollLeft = 200;
			await fireEvent.scroll(row);
			expect(events).toHaveLength(1);
			expect(events[0]).toMatchObject({ card_id: 'c_1', type: 'depth_open', data: { panel: 1 } });
		});
	});
});
