<script lang="ts">
	import SourceLine from './SourceLine.svelte';

	let {
		repo,
		path,
		commit,
		url,
		diff,
		onSourceTap
	}: {
		repo: string;
		path: string;
		commit: string;
		url?: string | null;
		diff: string;
		onSourceTap?: () => void;
	} = $props();

	function cls(line: string): string {
		if (line.startsWith('+++') || line.startsWith('---')) return 'meta';
		if (line.startsWith('+')) return 'add';
		if (line.startsWith('-')) return 'del';
		if (line.startsWith('@@')) return 'hunk';
		return '';
	}

	const lines = $derived(diff.replace(/\n$/, '').split('\n'));
</script>

<div class="diff-panel">
	<SourceLine {repo} {path} {commit} {url} onTap={onSourceTap} />
	<pre class="diff"><code
			>{#each lines as line, i (i)}<span class="dl {cls(line)}">{line}</span>{/each}</code
		></pre>
</div>

<style>
	.diff {
		margin: 0;
		overflow-x: auto;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.5rem 0;
		font: 0.8rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
	}
	code {
		display: block;
		width: max-content;
		min-width: 100%;
	}
	.dl {
		display: block;
		padding: 0 0.75rem;
		white-space: pre;
	}
	.add {
		background: rgba(46, 160, 67, 0.2);
	}
	.del {
		background: rgba(248, 81, 73, 0.2);
	}
	.hunk,
	.meta {
		color: var(--muted);
	}
</style>
