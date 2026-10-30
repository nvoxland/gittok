import type { Component } from 'svelte';
import CodeVisual from './CodeVisual.svelte';
import TextVisual from './TextVisual.svelte';
import MemeVisual from './MemeVisual.svelte';
import IllustrationVisual from './IllustrationVisual.svelte';
import ComicVisual from './ComicVisual.svelte';
import TextMemeVisual from './TextMemeVisual.svelte';
import ChartVisual from './ChartVisual.svelte';
import DiagramVisual from './DiagramVisual.svelte';
import TemplateVisual from './TemplateVisual.svelte';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const visuals: Record<string, Component<any>> = {
	code: CodeVisual,
	text: TextVisual,
	meme: MemeVisual,
	illustration: IllustrationVisual,
	comic: ComicVisual,
	text_meme: TextMemeVisual,
	chart: ChartVisual,
	diagram: DiagramVisual,
	template: TemplateVisual
};
