<script lang="ts">
	import { markNotificationsRead } from '#lib/api.ts';
	import type { AppNotification } from '#lib/types.ts';

	let { data } = $props();
	let items = $state<AppNotification[]>([]);
	$effect.pre(() => {
		items = data.notifications.map((n: AppNotification) => ({ ...n }));
	});

	function markRead(n: AppNotification) {
		if (n.read) return;
		n.read = true;
		void markNotificationsRead([n.id]).catch(() => {
			n.read = false;
		});
	}
	async function markAll() {
		const prev = items.map((n) => n.read);
		items.forEach((n) => (n.read = true));
		try {
			await markNotificationsRead('all');
		} catch {
			items.forEach((n, i) => (n.read = prev[i]));
		}
	}
</script>

<a class="back" href="/">&larr; Feed</a>
<div class="head">
	<h1>Notifications</h1>
	<button type="button" class="all" onclick={markAll}>Mark all read</button>
</div>
{#if items.length === 0}
	<p class="empty">No notifications</p>
{:else}
	<ul>
		{#each items as n (n.id)}
			<li data-unread={!n.read}>
				{#if n.card_id}
					<a href="/card/{encodeURIComponent(n.card_id)}" onclick={() => markRead(n)}>{n.text}</a>
				{:else}
					<button type="button" onclick={() => markRead(n)}>{n.text}</button>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	.back {
		display: block;
		padding: 0.5rem 16px 0;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-right: 16px;
	}
	h1 {
		margin: 0.5rem 16px;
		font-size: 1.25rem;
	}
	.all {
		min-height: 44px;
		border: 0;
		background: none;
		color: var(--accent);
		cursor: pointer;
	}
	.empty {
		margin: 1rem 16px;
		color: var(--muted);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0 16px 16px;
	}
	li {
		border-bottom: 1px solid var(--border);
		font-weight: 400;
	}
	li[data-unread='true'] {
		font-weight: 700;
	}
	li a,
	li button {
		display: block;
		width: 100%;
		min-height: 44px;
		padding: 0.75rem 0;
		border: 0;
		background: none;
		color: inherit;
		font: inherit;
		text-align: left;
		text-decoration: none;
		cursor: pointer;
	}
</style>
