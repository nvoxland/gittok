import { tick } from 'svelte';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Feed from './Feed.svelte';
import type { Card, FeedEvent } from '#lib/types.ts';
import { getSessionId } from '#lib/session.ts';
import { resetCardStateForTest } from '#lib/cardState.ts';
import { templateFixtures } from './fixtures.ts';

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
			resetCardStateForTest();
			setVisibility('visible');
			vi.unstubAllGlobals();
			vi.useRealTimers();
			observers = [];
		});

		it('watches cards against the viewport, because the page itself scrolls', () => {
			const { io } = setup();
			expect(io.options?.root ?? null).toBeNull();
		});

		it('marks only the first card as first (it shares the screen with the top bar)', () => {
			const { container } = setup();
			const articles = container.querySelectorAll('article');
			expect(articles[0]).toHaveClass('first');
			expect(articles[1]).not.toHaveClass('first');
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

		it('asks for more cards when a card near the end is on screen', () => {
			vi.stubGlobal('IntersectionObserver', FakeIO);
			const onNearEnd = vi.fn();
			const { container } = render(Feed, {
				cards: [1, 2, 3, 4, 5, 6, 7, 8].map(fakeCard),
				onNearEnd
			});
			const io = observers[0];
			const el = (id: string) => container.querySelector(`[data-card-id="${id}"]`)!;
			io.fire(el('c_2'), true);
			expect(onNearEnd).not.toHaveBeenCalled();
			io.fire(el('c_2'), false);
			io.fire(el('c_3'), true); // 5 cards left after it
			expect(onNearEnd).toHaveBeenCalledTimes(1);
		});

		it('emits impression when a card becomes visible', () => {
			const { events, io, el } = setup();
			expect(io.options?.threshold).toBe(0.6);
			expect(io.observed.has(el('c_1'))).toBe(true);
			io.fire(el('c_1'), true);
			expect(events).toHaveLength(1);
			expect(events[0]).toMatchObject({ card_id: 'c_1', type: 'impression' });
			expect(typeof events[0].ts).toBe('number');
		});

		it('adds the session id to every event', () => {
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			io.fire(el('c_1'), false);
			expect(events.length).toBeGreaterThanOrEqual(2);
			for (const e of events) expect(e.data?.session).toBe(getSessionId());
			expect(events[1].data).toMatchObject({ ms: expect.any(Number) });
		});

		it('emits scroll_back only when an already-impressed card becomes visible again', () => {
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			io.fire(el('c_1'), false);
			expect(events.map((e) => e.type)).not.toContain('scroll_back');
			io.fire(el('c_1'), true);
			expect(events.map((e) => e.type)).toEqual([
				'impression',
				'dwell',
				'skip',
				'impression',
				'scroll_back'
			]);
			io.fire(el('c_2'), true);
			expect(events.filter((e) => e.type === 'scroll_back')).toHaveLength(1);
		});

		it('emits dwell with ms (no skip) when a card leaves after 1s or more', () => {
			vi.useFakeTimers();
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			vi.advanceTimersByTime(4200);
			io.fire(el('c_1'), false);
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell']);
			expect(events[1].data).toMatchObject({ ms: 4200 });
		});

		function setupChat() {
			vi.stubGlobal('IntersectionObserver', FakeIO);
			const events: FeedEvent[] = [];
			const visual = structuredClone(templateFixtures.group_chat);
			visual.data.messages[0].text = 'a first message long enough to take over a second to read';
			const chat = { ...fakeCard(1), id: 'c_chat', visual } as Card;
			const { container } = render(Feed, {
				cards: [chat, fakeCard(2)],
				onEvent: (e: FeedEvent) => events.push(e)
			});
			const el = container.querySelector('[data-card-id="c_chat"]')!;
			return { events, io: observers[0], el, container };
		}

		it('plays a beat card only while it is the card on screen', async () => {
			vi.useFakeTimers();
			const { io, el } = setupChat();
			await tick();
			expect(el.querySelectorAll('.bubble:not(.typing)')).toHaveLength(0);
			io.fire(el, true);
			await tick();
			expect(el.querySelectorAll('.bubble:not(.typing)')).toHaveLength(1);
		});

		it('sends watch time with the dwell of a beat card', async () => {
			vi.useFakeTimers();
			const { events, io, el } = setupChat();
			io.fire(el, true);
			await tick();
			await vi.advanceTimersByTimeAsync(3000);
			io.fire(el, false);
			const dwell = events.find((e) => e.type === 'dwell')!;
			expect(dwell.data).toMatchObject({ ms: 3000, total_ms: expect.any(Number) });
			expect(dwell.data!.ms_played).toBeGreaterThan(0);
			expect(dwell.data!.ms_played).toBeLessThanOrEqual(3000);
		});

		it('leaving a beat card during its first beat is a skip, even after 1 s', async () => {
			vi.useFakeTimers();
			const { events, io, el } = setupChat();
			io.fire(el, true);
			await tick();
			await vi.advanceTimersByTimeAsync(1100); // the first message waits longer than this
			io.fire(el, false);
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell', 'skip']);
		});

		it('emits dwell and skip when a card leaves in under 1000 ms', () => {
			vi.useFakeTimers();
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			vi.advanceTimersByTime(400);
			io.fire(el('c_1'), false);
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell', 'skip']);
			expect(events[1].data).toMatchObject({ ms: 400 });
		});

		function setVisibility(state: 'visible' | 'hidden') {
			Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
			document.dispatchEvent(new Event('visibilitychange'));
		}

		it('closes the dwell of the visible card when the tab is hidden, and restarts it when shown', () => {
			vi.useFakeTimers();
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			vi.advanceTimersByTime(3000);
			setVisibility('hidden');
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell']);
			expect(events[1].data).toMatchObject({ ms: 3000 });
			vi.advanceTimersByTime(60_000);
			setVisibility('visible');
			expect(events).toHaveLength(2); // no new impression
			vi.advanceTimersByTime(2000);
			io.fire(el('c_1'), false);
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell', 'dwell']);
			expect(events[2].data).toMatchObject({ ms: 2000 });
		});

		it('emits skip when the tab is hidden within 1000 ms', () => {
			vi.useFakeTimers();
			const { events, io, el } = setup();
			io.fire(el('c_1'), true);
			vi.advanceTimersByTime(300);
			setVisibility('hidden');
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell', 'skip']);
			setVisibility('visible');
		});

		it('closes the dwell when the feed is destroyed', () => {
			vi.useFakeTimers();
			vi.stubGlobal('IntersectionObserver', FakeIO);
			const events: FeedEvent[] = [];
			const { container, unmount } = render(Feed, {
				cards: [fakeCard(1)],
				onEvent: (e: FeedEvent) => events.push(e)
			});
			observers[0].fire(container.querySelector('[data-card-id="c_1"]')!, true);
			vi.advanceTimersByTime(2500);
			unmount();
			expect(events.map((e) => e.type)).toEqual(['impression', 'dwell']);
			expect(events[1].data).toMatchObject({ ms: 2500 });
		});

		it('emits depth_open with the panel index when the horizontal panel changes', async () => {
			vi.stubGlobal('IntersectionObserver', FakeIO);
			const events: FeedEvent[] = [];
			const card = { ...fakeCard(1), depth: [{ kind: 'explain' as const, text: 'x' }] };
			const { container } = render(Feed, {
				cards: [card],
				onEvent: (e: FeedEvent) => events.push(e)
			});
			const row = container.querySelector('.panels') as HTMLElement;
			Object.defineProperty(row, 'clientWidth', { value: 200, configurable: true });
			row.scrollLeft = 200;
			await fireEvent.scroll(row);
			expect(events).toHaveLength(1);
			expect(events[0]).toMatchObject({ card_id: 'c_1', type: 'depth_open', data: { panel: 1 } });
		});

		describe('windowing', () => {
			const many = (n: number) => Array.from({ length: n }, (_, i) => fakeCard(i + 1));
			function setupMany(n = 30) {
				vi.stubGlobal('IntersectionObserver', FakeIO);
				const events: FeedEvent[] = [];
				const onNearEnd = vi.fn();
				const { container, rerender } = render(Feed, {
					cards: many(n),
					onEvent: (e: FeedEvent) => events.push(e),
					onNearEnd
				});
				const el = (n: number) => container.querySelector(`[data-card-id="c_${n}"]`) as HTMLElement;
				const full = () =>
					[...container.querySelectorAll('article:not(.placeholder)')].map((a) =>
						a.getAttribute('data-card-id')
					);
				const show = async (n: number) => {
					observers[0].fire(el(n), true);
					await tick();
				};
				const hide = async (n: number) => {
					observers[0].fire(el(n), false);
					await tick();
				};
				return { container, events, el, full, show, hide, onNearEnd, rerender };
			}

			it('renders full cards only near the start; the rest are placeholders', () => {
				const { container, full } = setupMany();
				expect(container.querySelectorAll('[data-card-id]')).toHaveLength(30);
				expect(full()).toEqual(['c_1', 'c_2', 'c_3', 'c_4']);
				expect(screen.queryByText('Hook number 20')).toBeNull();
			});

			it('a placeholder keeps the place of its card: an article with the id and a label, nothing inside', () => {
				const { el } = setupMany();
				const ph = el(20);
				expect(ph.tagName).toBe('ARTICLE');
				expect(ph).toHaveClass('placeholder');
				expect(ph).toHaveAttribute('aria-label', 'Hook number 20');
				expect(ph.childElementCount).toBe(0);
			});

			it('a placeholder has the height and the snap point of a card', async () => {
				const { readFileSync } = await import('node:fs');
				const css = readFileSync(`${process.cwd()}/src/lib/components/Feed.svelte`, 'utf8');
				const rule = css.match(/\.placeholder\s*\{([^}]*)\}/)![1];
				expect(rule).toMatch(/height:\s*100dvh/);
				expect(rule).toMatch(/scroll-snap-align:\s*start/);
			});

			it('moves the window with the card on screen and unmounts the far cards', async () => {
				const { full, show, hide } = setupMany();
				await show(1);
				await hide(1);
				await show(10);
				expect(full()).toEqual(['c_7', 'c_8', 'c_9', 'c_10', 'c_11', 'c_12', 'c_13']);
				expect(screen.queryByText('Hook number 1')).toBeNull();
				expect(screen.getByText('Hook number 10')).toBeInTheDocument();
			});

			it('keeps the window while no card is 60% on screen (between two cards)', async () => {
				const { full, show, hide } = setupMany();
				await show(10);
				await hide(10);
				expect(full()).toContain('c_10');
				expect(full()).toHaveLength(7);
			});

			it('watches every card, also placeholders and cards that mount later', async () => {
				const { container, show } = setupMany();
				const io = observers[0];
				expect(observers).toHaveLength(1);
				expect(io.observed.size).toBe(30);
				await show(10);
				expect(observers).toHaveLength(1); // one observer for the life of the feed
				expect(io.observed.size).toBe(30);
				for (const a of container.querySelectorAll('[data-card-id]')) {
					expect(io.observed.has(a)).toBe(true);
				}
			});

			it('landing on a placeholder is an impression, and the card then mounts', async () => {
				const { events, show, el } = setupMany();
				expect(el(20)).toHaveClass('placeholder');
				await show(20);
				expect(events.map((e) => [e.card_id, e.type])).toEqual([['c_20', 'impression']]);
				expect(el(20)).not.toHaveClass('placeholder');
				expect(screen.getByText('Hook number 20')).toBeInTheDocument();
			});

			it('the swap from placeholder to card is not a second impression, and the dwell goes on', async () => {
				vi.useFakeTimers();
				const { events, show, hide, el } = setupMany();
				await show(20);
				// The browser reports the new element once, as visible.
				observers[0].fire(el(20), true);
				vi.advanceTimersByTime(3000);
				await hide(20);
				expect(events.map((e) => e.type)).toEqual(['impression', 'dwell']);
				expect(events[1].data).toMatchObject({ ms: 3000 });
			});

			it('coming back to an unmounted card is a scroll_back, and it mounts again', async () => {
				const { events, show, hide, full } = setupMany();
				await show(1);
				await hide(1);
				await show(10);
				await hide(10);
				expect(full()).not.toContain('c_1');
				await show(1);
				expect(full()).toContain('c_1');
				expect(events.filter((e) => e.card_id === 'c_1').map((e) => e.type)).toEqual([
					'impression',
					'dwell',
					'skip',
					'impression',
					'scroll_back'
				]);
			});

			it('still asks for more near the end when the last cards are placeholders', async () => {
				const { show, onNearEnd } = setupMany();
				await show(10);
				expect(onNearEnd).not.toHaveBeenCalled();
				await show(25);
				expect(onNearEnd).toHaveBeenCalledTimes(1);
			});

			it('only the first card of the list is first, also as a placeholder', async () => {
				const { el, show } = setupMany();
				expect(el(1)).toHaveClass('first');
				await show(10);
				expect(el(1)).toHaveClass('placeholder');
				expect(el(1)).toHaveClass('first');
				expect(el(2)).not.toHaveClass('first');
			});

			it('watches cards added by the next page', async () => {
				const { rerender, container } = setupMany(5);
				await rerender({ cards: many(8) });
				expect(observers).toHaveLength(1);
				expect(observers[0].observed.size).toBe(8);
				expect(observers[0].observed.has(container.querySelector('[data-card-id="c_8"]')!)).toBe(true);
			});
		});

		describe('keyboard', () => {
			let into: ReturnType<typeof vi.fn>;
			beforeEach(() => {
				into = vi.fn();
				Element.prototype.scrollIntoView = into as never;
			});
			afterEach(() => {
				delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
			});
			function setup3() {
				vi.stubGlobal('IntersectionObserver', FakeIO);
				const { container } = render(Feed, { cards: [1, 2, 3].map(fakeCard) });
				const el = (n: number) => container.querySelector(`[data-card-id="c_${n}"]`) as HTMLElement;
				return { container, el, io: observers[0] };
			}
			const target = () => into.mock.instances[into.mock.instances.length - 1] as unknown as HTMLElement;

			it('j and ArrowDown go to the next card; k and ArrowUp to the previous one', async () => {
				const { el, io } = setup3();
				io.fire(el(1), true);
				await fireEvent.keyDown(document.body, { key: 'j' });
				expect(target()).toBe(el(2));
				expect(into).toHaveBeenLastCalledWith({ behavior: 'smooth', block: 'start' });
				io.fire(el(1), false);
				io.fire(el(2), true);
				await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
				expect(target()).toBe(el(3));
				await fireEvent.keyDown(document.body, { key: 'k' });
				expect(target()).toBe(el(1));
				await fireEvent.keyDown(document.body, { key: 'ArrowUp' });
				expect(target()).toBe(el(1));
				// The first card snaps by its bottom edge, under the top bar.
				expect(into).toHaveBeenLastCalledWith({ behavior: 'smooth', block: 'end' });
			});

			it('leaves the key to the browser past the last card (the end card is below)', async () => {
				const { el, io } = setup3();
				io.fire(el(3), true);
				const e = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
				document.body.dispatchEvent(e);
				expect(into).not.toHaveBeenCalled();
				expect(e.defaultPrevented).toBe(false);
			});

			it('ignores keys typed into a field, keys with a modifier, and keys a card already used', async () => {
				const { el, io } = setup3();
				io.fire(el(1), true);
				const input = document.createElement('textarea');
				document.body.appendChild(input);
				await fireEvent.keyDown(input, { key: 'j' });
				input.remove();
				await fireEvent.keyDown(document.body, { key: 'j', metaKey: true });
				const used = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
				used.preventDefault();
				document.body.dispatchEvent(used);
				expect(into).not.toHaveBeenCalled();
			});

			it('does nothing while a dialog (lightbox, story) is open', async () => {
				const { el, io } = setup3();
				io.fire(el(1), true);
				const dialog = document.createElement('div');
				dialog.setAttribute('aria-modal', 'true');
				document.body.appendChild(dialog);
				await fireEvent.keyDown(document.body, { key: 'j' });
				dialog.remove();
				expect(into).not.toHaveBeenCalled();
			});

			it('jumps without animation when the user asks for reduced motion', async () => {
				vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q }));
				const { el, io } = setup3();
				io.fire(el(1), true);
				await fireEvent.keyDown(document.body, { key: 'j' });
				expect(into).toHaveBeenLastCalledWith({ behavior: 'auto', block: 'start' });
			});
		});
	});
});
