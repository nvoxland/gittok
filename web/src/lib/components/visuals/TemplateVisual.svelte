<script lang="ts">
	import type { Component } from 'svelte';
	import Iceberg from './templates/Iceberg.svelte';
	import TierList from './templates/TierList.svelte';
	import GroupChat from './templates/GroupChat.svelte';
	import Flags from './templates/Flags.svelte';
	import DatingProfile from './templates/DatingProfile.svelte';
	import GlowUp from './templates/GlowUp.svelte';
	import BreakingNews from './templates/BreakingNews.svelte';
	import Horoscope from './templates/Horoscope.svelte';
	import Thread from './templates/Thread.svelte';
	import DayInLife from './templates/DayInLife.svelte';
	import HotTake from './templates/HotTake.svelte';
	import type { TemplateVisual } from '#lib/types.ts';

	let {
		visual,
		persona,
		shown = Infinity
	}: { visual: TemplateVisual; resolved?: unknown; persona?: string; shown?: number } = $props();

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const templates: Record<string, Component<any>> = {
		iceberg: Iceberg,
		tier_list: TierList,
		group_chat: GroupChat,
		flags: Flags,
		dating_profile: DatingProfile,
		glow_up: GlowUp,
		breaking_news: BreakingNews,
		horoscope: Horoscope,
		thread: Thread,
		day_in_life: DayInLife,
		hot_take: HotTake
	};
	const Template = $derived(templates[visual.template]);
</script>

{#if Template}
	<Template data={visual.data} {persona} {shown} />
{:else}
	<p class="unsupported">Unsupported template: {visual.template}</p>
{/if}

<style>
	.unsupported {
		color: var(--muted);
		border: 1px dashed var(--border);
		border-radius: 8px;
		padding: 0.5rem;
	}
</style>
