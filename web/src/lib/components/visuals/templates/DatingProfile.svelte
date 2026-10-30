<script lang="ts">
	import Poster from '#lib/components/Poster.svelte';
	import type { DatingProfileData } from '#lib/types.ts';
	let { data }: { data: DatingProfileData } = $props();
</script>

<div class="profile">
	<div class="head">
		<Poster account={data.name} size={56} />
		<span class="age">{data.age}</span>
	</div>
	<p class="bio">{data.bio}</p>
	<h4>Likes</h4>
	<ul class="chips">{#each data.likes as l, i (i)}<li class="like">{l}</li>{/each}</ul>
	<h4>Dealbreakers</h4>
	<ul class="chips">{#each data.dealbreakers as l, i (i)}<li class="deal">{l}</li>{/each}</ul>
</div>

<style>
	.profile {
		border: 1px solid var(--border);
		border-radius: 16px;
		background: var(--surface);
		padding: 1rem;
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-weight: 700;
		font-size: 1.1rem;
	}
	.age {
		color: var(--muted);
	}
	.bio {
		font-style: italic;
	}
	h4 {
		margin: 0.5rem 0 0.25rem;
		font-size: 0.75rem;
		text-transform: uppercase;
		color: var(--muted);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.chips li {
		border-radius: 999px;
		padding: 0.2rem 0.7rem;
		font-size: 0.85rem;
	}
	.like { background: var(--good-bg); color: var(--good); }
	.deal { background: var(--bad-bg); color: var(--bad); }
</style>
