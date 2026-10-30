// Mirrors docs/api.md.

export type CodeVisual = {
	kind: 'code';
	repo: string;
	path: string;
	commit: string;
	lines: [number, number];
	callouts?: { line: number; text: string }[];
};

export type TextVisual = {
	kind: 'text';
	title?: string;
	body?: string;
	bullets?: string[];
};

export type Visual = CodeVisual | TextVisual;

export type ExplainPanel = { kind: 'explain'; text: string };
export type CodePanel = {
	kind: 'code';
	repo: string;
	path: string;
	commit: string;
	lines: [number, number];
};
export type CodeDiffPanel = {
	kind: 'code_diff';
	repo: string;
	path: string;
	commit: string;
	[key: string]: unknown;
};

export type DepthPanel = ExplainPanel | CodePanel | CodeDiffPanel;

export type ResolvedCode = { code: string; language: string; start_line: number };
export type ResolvedDiff = { diff: string };

export type Resolved = {
	visual: ResolvedCode | null;
	depth: (ResolvedCode | ResolvedDiff | null)[];
};

export type Comment = { persona: string; text: string };
export type Source = { repo: string; commit: string };

export type Card = {
	id: string;
	created_at: string;
	repo: string;
	story_type: string;
	format: string;
	persona: string;
	tone: string;
	hook: string;
	visual: Visual;
	depth: DepthPanel[];
	comments: Comment[];
	sources: Source[];
	resolved: Resolved;
};

export type FeedResponse = { cards: Card[]; next_cursor: string | null };

export type FeedEventType =
	| 'impression'
	| 'dwell'
	| 'skip'
	| 'scroll_back'
	| 'depth_open'
	| 'like'
	| 'save'
	| 'explain_more'
	| 'answer'
	| 'source_tap';

export type FeedEvent = {
	card_id: string;
	type: FeedEventType;
	ts: number;
	data?: Record<string, unknown>;
};
