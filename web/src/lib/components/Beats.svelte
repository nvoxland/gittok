<script lang="ts">
	// Plays a card front piece by piece, like a short video.
	// Tap skips ahead, a long press pauses, and the finished card offers a replay.
	import { onDestroy, type Snippet } from 'svelte';
	import type { Beat } from '#lib/beats.ts';
	import { prefersReducedMotion } from '#lib/motion.ts';
	import { createPlayer, type PlayerState } from '#lib/player.ts';
	import { hasPlayed, setPlayed } from '#lib/cardState.ts';
	import { registerPlayStats } from '#lib/playStats.ts';
	import type { FeedEventType } from '#lib/types.ts';

	let {
		cardId,
		beats,
		active = false,
		onAction,
		children
	}: {
		cardId: string;
		beats: Beat[];
		active?: boolean;
		onAction?: (type: FeedEventType, data?: Record<string, unknown>) => void;
		children: Snippet<[number]>;
	} = $props();

	const HOLD_MS = 250;
	const reducedMotion = prefersReducedMotion();

	let view = $state<PlayerState>({ shown: Infinity, beat: 0, done: true, paused: false });
	// svelte-ignore state_referenced_locally
	const player = createPlayer(beats, {
		reducedMotion,
		alreadyPlayed: hasPlayed(cardId),
		onChange: (s) => (view = s),
		onDone: () => {
			setPlayed(cardId);
			onAction?.('beats_done', { beats: beats.length, ms_played: player.stats().msPlayed });
		},
		onTap: (beat) => onAction?.('beat_tap', { beat }),
		onReplay: () => onAction?.('replay')
	});
	view = { ...player.state };
	// svelte-ignore state_referenced_locally
	const unregister = beats.length ? registerPlayStats(cardId, () => player.stats()) : () => {};

	$effect(() => {
		player.setActive(active);
	});
	onDestroy(() => {
		unregister();
		player.destroy();
	});

	let holdTimer: ReturnType<typeof setTimeout> | undefined;
	let holding = false;
	function interactive(e: Event) {
		return (e.target as Element | null)?.closest?.('a, button, input, label') != null;
	}
	function down(e: PointerEvent) {
		if (view.done || interactive(e)) return;
		holdTimer = setTimeout(() => {
			holding = true;
			player.hold(true);
		}, HOLD_MS);
	}
	function release(tap: boolean) {
		if (holdTimer === undefined && !holding) return;
		clearTimeout(holdTimer);
		holdTimer = undefined;
		if (holding) {
			holding = false;
			player.hold(false);
		} else if (tap) {
			player.tap();
		}
	}
</script>

{#if beats.length === 0}
	{@render children(Infinity)}
{:else}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="beats"
		onpointerdown={down}
		onpointerup={() => release(true)}
		onpointercancel={() => release(false)}
		onpointerleave={() => release(false)}
	>
		<!-- One fixed-height row: the progress bar while playing, the replay button after. It sits
		     above the content, so nothing covers the button and nothing jumps when it swaps. -->
		<div class="controls">
			{#if view.done}
				<button type="button" class="replay" aria-label="Replay" onclick={() => player.replay()}
					>↻ Replay</button
				>
			{:else}
				<div class="progress" class:paused={view.paused} aria-hidden="true">
					{#each beats as b, i (i)}
						<span
							class="seg"
							class:full={i < view.beat}
							class:now={i === view.beat}
							style="--ms:{b.ms}ms"
						></span>
					{/each}
				</div>
			{/if}
		</div>
		{@render children(view.shown)}
	</div>
{/if}

<style>
	.beats {
		position: relative;
		touch-action: manipulation;
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}
	.controls {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		height: 28px;
		margin-bottom: 0.25rem;
	}
	.progress {
		flex: 1;
		display: flex;
		gap: 3px;
	}
	.seg {
		flex: 1;
		height: 3px;
		border-radius: 2px;
		background: var(--border);
		background-image: linear-gradient(var(--accent), var(--accent));
		background-repeat: no-repeat;
		background-size: 0% 100%;
	}
	.seg.full {
		background-size: 100% 100%;
	}
	.seg.now {
		animation: fill var(--ms) linear forwards;
	}
	.progress.paused .seg.now {
		animation-play-state: paused;
	}
	@keyframes fill {
		to {
			background-size: 100% 100%;
		}
	}
	.replay {
		height: 28px;
		padding: 0 0.75rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--muted);
		font: inherit;
		font-size: 0.8rem;
		cursor: pointer;
	}
	@media (prefers-reduced-motion: reduce) {
		.seg.now {
			animation: none;
		}
	}
</style>
