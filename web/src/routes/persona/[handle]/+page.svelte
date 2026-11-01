<script lang="ts">
	import Avatar from '#lib/components/Avatar.svelte';
	let { data } = $props();
	const p = $derived(data.profile);
</script>

<main class="profile">
	<a class="back" href="/">&larr; Feed</a>
	<header>
		<Avatar handle={p.handle} size={72} />
		<div>
			<h1>{p.name}</h1>
			<span class="handle">@{p.handle}</span>
		</div>
	</header>
	<p class="bio">{p.bio ?? p.voice}</p>

	<h2>Posts</h2>
	{#if p.posts.length === 0}
		<p class="empty">No posts yet</p>
	{:else}
		<ul class="grid">
			{#each p.posts as c (c.id)}
				<li>
					<a href="/card/{encodeURIComponent(c.id)}">
						<span class="fmt">{c.format.replace(/_/g, ' ')}</span>
						<span class="hook">{c.hook}</span>
						<span class="by">{c.repo}</span>
					</a>
				</li>
			{/each}
		</ul>
	{/if}

	<h2>Comments</h2>
	{#if p.comments.length === 0}
		<p class="empty">No comments yet</p>
	{:else}
		<ul class="comments">
			{#each p.comments as c (c.card_id + c.text)}
				<li>
					<a href="/card/{encodeURIComponent(c.card_id)}">{c.text}</a>
					<span class="on">on "{c.hook}" · {c.repo}</span>
				</li>
			{/each}
		</ul>
	{/if}
</main>

<style>
	.profile {
		padding: 0.75rem 16px 2rem;
		max-width: 48rem;
		margin: 0 auto;
	}
	.back {
		color: var(--muted);
		text-decoration: none;
		font-size: 0.85rem;
	}
	header {
		display: flex;
		gap: 1rem;
		align-items: center;
		margin: 0.75rem 0;
	}
	h1 {
		margin: 0;
		font-size: 1.6rem;
	}
	.handle,
	.empty,
	.on {
		color: var(--muted);
	}
	.bio {
		margin: 0 0 0.5rem;
		overflow-wrap: anywhere;
	}
	h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--muted);
		margin: 1.25rem 0 0.4rem;
	}
	.grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
		gap: 8px;
	}
	.grid a {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		height: 100%;
		padding: 0.6rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 10px;
		color: inherit;
		text-decoration: none;
	}
	.fmt {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--accent);
	}
	.hook {
		font-size: 0.9rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.by {
		margin-top: auto;
		font-size: 0.75rem;
		color: var(--muted);
	}
	.comments {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.comments li {
		display: flex;
		flex-direction: column;
		padding: 0.4rem 0;
		border-bottom: 1px solid var(--border);
		overflow-wrap: anywhere;
	}
	.comments a {
		color: inherit;
		text-decoration: none;
	}
	.on {
		font-size: 0.75rem;
	}
</style>
