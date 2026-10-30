import type { Component } from 'svelte';
import CodeVisual from './CodeVisual.svelte';
import TextVisual from './TextVisual.svelte';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const visuals: Record<string, Component<any>> = {
	code: CodeVisual,
	text: TextVisual
};
