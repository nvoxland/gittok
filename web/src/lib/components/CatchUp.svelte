<script lang="ts">
	import StoryViewer from './StoryViewer.svelte';
	import { catchUpQueue } from './catchUp.ts';
	import type { Story } from '#lib/types.ts';

	let {
		stories,
		onSeen,
		onClose
	}: {
		stories: Story[];
		onSeen: (repo: string, shas: string[]) => void;
		onClose: () => void;
	} = $props();

	// A snapshot: marking pages seen while playing must not change the queue.
	const queue = catchUpQueue(stories);
	let at = $state(0);

	function onEnd() {
		if (at >= queue.length - 1) onClose();
		else at += 1;
	}
</script>

{#if queue[at]}
	{#key queue[at].repo}
		<StoryViewer story={queue[at]} {onSeen} {onClose} {onEnd} autoplay />
	{/key}
{/if}
