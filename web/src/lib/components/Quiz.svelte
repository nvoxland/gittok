<script lang="ts">
	import { postAnswer } from '#lib/api.ts';
	import { getAnswer, setAnswer } from '#lib/cardState.ts';
	import type { AnswerResponse, Interaction } from '#lib/types.ts';

	type Result = AnswerResponse & { choice: number };

	let {
		cardId,
		interaction,
		onAnswer
	}: {
		cardId: string;
		interaction: Interaction;
		onAnswer?: (choice: number, correct: boolean | null) => void;
	} = $props();

	let result = $state<Result | undefined>(getAnswer<Result>(cardId));
	let pending = $state(false);
	let failed = $state(false);

	async function pick(choice: number) {
		if (result || pending) return;
		pending = true;
		failed = false;
		try {
			const res = await postAnswer(cardId, choice);
			result = { ...res, choice };
			setAnswer(cardId, result);
			onAnswer?.(choice, res.correct);
		} catch {
			failed = true;
		} finally {
			pending = false;
		}
	}

	function choiceClass(i: number): string {
		if (!result) return '';
		if (result.answer_index === i) return 'correct';
		if (result.choice === i && result.correct === false) return 'wrong';
		return '';
	}
</script>

<div class="quiz">
	<p class="question">{interaction.question}</p>
	<div class="choices">
		{#each interaction.choices as choice, i (i)}
			<button
				type="button"
				class="choice {choiceClass(i)}"
				class:picked={result?.choice === i}
				disabled={result !== undefined || pending}
				onclick={() => pick(i)}>{choice}</button
			>
		{/each}
	</div>
	{#if failed}
		<p class="status" role="alert">Could not send the answer. Try again.</p>
	{/if}
	{#if result}
		<div class="reveal" role="status">
			{#if result.correct === null}
				<p class="verdict">No right answer. See what the personas think.</p>
			{:else}
				<p class="verdict {result.correct ? 'ok' : 'bad'}">
					{result.correct ? 'Correct' : 'Incorrect'}
				</p>
				{#if result.explanation}<p class="explanation">{result.explanation}</p>{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.quiz {
		margin-top: 0.75rem;
	}
	.question {
		margin: 0 0 0.5rem;
		font-weight: 600;
	}
	.choices {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding-right: 56px;
	}
	.choice {
		min-height: 44px;
		padding: 0.5rem 0.75rem;
		text-align: left;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--surface);
		color: inherit;
		font: inherit;
		cursor: pointer;
		overflow-wrap: anywhere;
	}
	.choice:disabled {
		cursor: default;
		opacity: 0.85;
	}
	.choice.picked {
		border-color: var(--accent);
	}
	.choice.correct {
		background: rgba(46, 160, 67, 0.25);
		border-color: rgb(46, 160, 67);
	}
	.choice.wrong {
		background: rgba(248, 81, 73, 0.25);
		border-color: rgb(248, 81, 73);
	}
	.verdict {
		margin: 0.5rem 0 0;
		font-weight: 600;
	}
	.verdict.ok {
		color: rgb(46, 160, 67);
	}
	.verdict.bad {
		color: rgb(248, 81, 73);
	}
	.explanation {
		margin: 0.25rem 0 0;
		font-size: 0.9rem;
	}
	.status {
		color: #e5484d;
		font-size: 0.85rem;
	}
</style>
