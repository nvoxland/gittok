<script lang="ts">
	import RepoMap from '#lib/components/RepoMap.svelte';
	let { data } = $props();
</script>

<RepoMap map={data.map} />
