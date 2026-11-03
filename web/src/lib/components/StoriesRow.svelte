<script lang="ts">
	import type { Story } from '#lib/types.ts';
	let {
		stories,
		onOpen
	}: { stories: Story[]; onOpen: (index: number) => void } = $props();
	let failed = $state<Record<string, boolean>>({});
</script>

{#if stories.length > 0}
	<div class="stories" role="list" aria-label="Stories">
		{#each stories as story, i (story.repo)}
			<div role="listitem">
				<button
					type="button"
					class="story"
					data-seen={story.seen}
					aria-label="{story.repo} story"
					onclick={() => onOpen(i)}
				>
					<span class="ring">
						{#if story.mascot_image && !failed[story.repo]}
							<img
								src={story.mascot_image}
								alt=""
								onerror={() => (failed[story.repo] = true)}
							/>
						{:else}
							<span class="initial" aria-hidden="true">{story.repo.charAt(0).toUpperCase()}</span>
						{/if}
					</span>
					<span class="name">{story.repo}</span>
				</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	.stories {
		display: flex;
		gap: 10px;
		overflow-x: auto;
		padding: 6px 16px;
		scrollbar-width: none;
	}
	.story {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		width: 52px;
		min-height: 44px;
		padding: 0;
		border: 0;
		background: none;
		color: var(--text);
		cursor: pointer;
	}
	.ring {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 50%;
		padding: 3px;
		background: var(--border);
	}
	.story[data-seen='false'] .ring {
		background: linear-gradient(135deg, var(--accent), #e5484d);
	}
	.ring img,
	.initial {
		width: 100%;
		height: 100%;
		border-radius: 50%;
		object-fit: cover;
		background: var(--surface);
		border: 2px solid var(--bg);
		box-sizing: border-box;
	}
	.initial {
		display: grid;
		place-items: center;
		font-weight: 700;
	}
	.name {
		max-width: 52px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.65rem;
		color: var(--muted);
	}
</style>
