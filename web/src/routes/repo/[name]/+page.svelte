<script lang="ts">
	import RepoProfile from '#lib/components/RepoProfile.svelte';
	let { data } = $props();
</script>

<RepoProfile profile={data.profile} />
