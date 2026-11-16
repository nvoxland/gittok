<script lang="ts">
	import { page } from '$app/state';

	const status = $derived(page.status);
	const text = $derived(
		status === 404
			? 'This page no longer exists. The card may have been removed.'
			: status === 401
				? 'This device needs pairing. Open the feed and pair with a code.'
				: (page.error?.message ?? 'Something went wrong.')
	);
</script>

<main class="error-page" role="alert">
	<h1>{status}</h1>
	<p>{text}</p>
	<div class="actions">
		<button type="button" onclick={() => window.location.reload()}>Try again</button>
		<a href="/">&larr; Back to the feed</a>
	</div>
</main>

<style>
	.error-page {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		min-height: 100dvh;
		padding: 0 max(16px, env(safe-area-inset-right)) 0 max(16px, env(safe-area-inset-left));
		text-align: center;
		color: var(--muted);
	}
	h1,
	p {
		margin: 0;
	}
	h1 {
		color: var(--text);
	}
	.actions {
		display: flex;
		align-items: center;
		gap: 1rem;
	}
	button {
		padding: 0.6rem 1.2rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	a {
		color: var(--muted);
		text-decoration: none;
	}
</style>
