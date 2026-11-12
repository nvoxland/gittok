<script lang="ts">
	// A one-time hint for the two gestures of the feed. Dismissed once, it stays away on this device.
	const KEY = 'gittok.hints';

	function seenBefore(): boolean {
		try {
			return localStorage.getItem(KEY) === '1';
		} catch {
			return false; // storage unavailable: show it; it can still be dismissed for this visit
		}
	}

	let open = $state(!seenBefore());

	function dismiss() {
		open = false;
		try {
			localStorage.setItem(KEY, '1');
		} catch {
			// storage unavailable: dismissed for this visit only
		}
	}
</script>

{#if open}
	<aside class="hints" role="note" aria-label="How to use the feed">
		<ul>
			<li><span aria-hidden="true">↑</span> Swipe up for the next card</li>
			<li><span aria-hidden="true">←</span> Swipe left for more depth</li>
		</ul>
		<button type="button" onclick={dismiss}>Got it</button>
	</aside>
{/if}

<style>
	.hints {
		position: fixed;
		left: 50%;
		bottom: calc(4.5rem + env(safe-area-inset-bottom)); /* above a card's bottom row */
		z-index: 15;
		transform: translateX(-50%);
		display: flex;
		align-items: center;
		gap: 0.75rem;
		width: max-content;
		max-width: calc(100vw - 32px - env(safe-area-inset-left) - env(safe-area-inset-right));
		padding: 0.5rem 0.5rem 0.5rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 12px;
		background: var(--surface);
		color: var(--text);
		font-size: 0.85rem;
		animation: hint-in 0.3s ease-out;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.15rem;
	}
	li span {
		display: inline-block;
		width: 1.1em;
		color: var(--accent);
		font-weight: 700;
	}
	button {
		flex: none;
		min-height: 44px;
		padding: 0 0.9rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	@keyframes hint-in {
		from {
			opacity: 0;
			transform: translate(-50%, 8px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.hints {
			animation: none;
		}
	}
</style>
