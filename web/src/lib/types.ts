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

export type MemeVisual = { kind: 'meme'; template: string; lines: string[] };
export type TextMemeStyle = 'pov' | 'nobody_me' | 'starter_pack' | 'expectation_reality';
export type TextMemeVisual = { kind: 'text_meme'; style: TextMemeStyle; lines: string[] };
export type IllustrationVisual = {
	kind: 'illustration';
	prompt: string;
	caption: string;
	mascots?: string[];
};
export type ComicPanelSpec = { prompt: string; caption: string };
export type ComicVisual = { kind: 'comic'; panels: ComicPanelSpec[]; mascots?: string[] };
export type ChartName =
	'top_churn_files' | 'top_churn_dirs' | 'commit_hours' | 'author_shares' | 'co_change';
export type ChartVisual = {
	kind: 'chart';
	chart: ChartName;
	repo: string;
	window?: string;
	dir?: string;
	title?: string;
};
export type DiagramVisual = { kind: 'diagram'; title?: string; mermaid: string };

export type IcebergData = { title: string; layers: { label: string; items: string[] }[] };
export type TierRow = {
	tier: 'S' | 'A' | 'B' | 'C' | 'D' | 'F';
	items: { name: string; why: string }[];
};
export type TierListData = { title: string; rows: TierRow[] };
export type GroupChatData = { title: string; messages: { from: string; text: string }[] };
export type FlagsData = { subject: string; red: string[]; green: string[] };
export type DatingProfileData = {
	name: string;
	age: string | number;
	bio: string;
	likes: string[];
	dealbreakers: string[];
};
export type GlowUpData = {
	subject: string;
	before: { label: string; text: string };
	after: { label: string; text: string };
};
export type BreakingNewsData = { headline: string; subhead?: string; ticker?: string[] };
export type HoroscopeData = { subject: string; sign: string; forecast: string; lucky?: string };
export type ThreadData = { posts: string[] };
export type DayInLifeData = { subject: string; steps: { time: string; text: string }[] };
export type HotTakeData = { take: string };

export type TemplateDataMap = {
	iceberg: IcebergData;
	tier_list: TierListData;
	group_chat: GroupChatData;
	flags: FlagsData;
	dating_profile: DatingProfileData;
	glow_up: GlowUpData;
	breaking_news: BreakingNewsData;
	horoscope: HoroscopeData;
	thread: ThreadData;
	day_in_life: DayInLifeData;
	hot_take: HotTakeData;
};
export type TemplateName = keyof TemplateDataMap;
export type TemplateVisual = {
	[K in TemplateName]: { kind: 'template'; template: K; data: TemplateDataMap[K] };
}[TemplateName];

export type Visual =
	| CodeVisual
	| TextVisual
	| MemeVisual
	| TextMemeVisual
	| IllustrationVisual
	| ComicVisual
	| ChartVisual
	| DiagramVisual
	| TemplateVisual;

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

export type ResolvedImages = { images: string[]; width: number; height: number };
export type ResolvedChart = {
	type: 'bar';
	title: string;
	x_label: string;
	y_label: string;
	bars: { label: string; value: number }[];
};
export type ResolvedAccount = {
	handle: string;
	repo: string;
	path: string;
	kind: 'file' | 'dir';
};

export type Resolved = {
	visual: ResolvedCode | ResolvedImages | ResolvedChart | null;
	account?: ResolvedAccount;
	depth: (ResolvedCode | ResolvedDiff | null)[];
};

export type Comment = { persona: string; text: string; spoiler?: boolean };
// The reader's own reply to a persona's comment; shown only to the reader.
export type Reply = {
	id: number;
	card_id: string;
	persona: string;
	comment_index: number;
	text: string;
	created_at: string;
	answered_card_id: string | null;
};
export type Series = { key: string; part: number; of: number };
export type Source = { repo: string; commit: string };

export type Interaction = {
	question: string;
	choices: string[];
	// Stripped by the feed API; revealed by POST /api/answer.
	answer_index?: number | null;
	explanation?: string;
};
export type AnswerResponse = {
	correct: boolean | null;
	answer_index: number | null;
	explanation: string;
};

export type CardLink = { label: string; url: string | null };
export type CardLinks = {
	repo_url: string;
	panels: (string | null)[];
	sources: CardLink[];
};

export type Card = {
	id: string;
	created_at: string;
	repo: string;
	story_type: string;
	format: string;
	persona: string;
	tone: string;
	hook: string;
	// "After this card you know ..."; absent on cards stored before it was required.
	learn?: string;
	visual: Visual;
	account?: string;
	series?: Series | null;
	interaction?: Interaction;
	depth: DepthPanel[];
	comments: Comment[];
	replies?: Reply[];
	sources: Source[];
	resolved: Resolved;
	// GitHub URLs; null when the repo has no GitHub URL.
	links?: CardLinks | null;
};

export type FeedResponse = {
	cards: Card[];
	next_cursor: string | null;
	// The card last seen, served first on a fresh load (null when there is none).
	resume_card_id?: string | null;
	fromCache?: boolean;
};

export type FeedEventType =
	| 'impression'
	| 'dwell'
	| 'skip'
	| 'scroll_back'
	| 'depth_open'
	| 'lightbox_open'
	| 'like'
	| 'save'
	| 'knew_it'
	| 'teach_more'
	| 'answer'
	| 'source_tap'
	| 'beats_done'
	| 'replay'
	| 'beat_tap';

export type FeedEvent = {
	card_id: string;
	type: FeedEventType;
	ts: number;
	data?: Record<string, unknown>;
};

export type RepoStats = {
	commits_365: number;
	authors_365: number;
	last_commit_ts: number | null;
	top_files: { path: string; commits: number }[];
	top_dirs: { path: string; commits: number }[];
};
export type MapDir = {
	dir: string;
	cards_seen: number;
	cards_available: number;
	quiz_right: number;
	quiz_wrong: number;
	novelty: number;
	verdicts: Record<string, number>;
};
export type RepoMap = { name: string; dirs: MapDir[] };

export type FeedFilter = { repo?: string; dir?: string };

export type RepoProfile = {
	name: string;
	mascot: string | null;
	mascot_image: string | null;
	group: string | null;
	stats: RepoStats;
	verdicts?: { dir: string; counts: Record<string, number> }[];
	cards: Card[];
};

export type StoryCommit = {
	sha: string;
	short: string;
	ts: number;
	author: string;
	subject: string;
	files: number;
	seen?: boolean;
	/** A card that cites this commit. */
	card_id?: string | null;
	/** GitHub commit URL, only when no card covers it. */
	url?: string | null;
};
export type StoryDigest = { card_id: string; day: string; hook: string; learn: string };
export type Story = {
	repo: string;
	mascot: string | null;
	mascot_image: string | null;
	commits: StoryCommit[];
	seen: boolean;
	digest?: StoryDigest | null;
};

export type AppNotification = {
	id: number;
	kind: string;
	text: string;
	card_id: string | null;
	created_at: number | string;
	read: boolean;
	repo?: string | null;
};
export type NotificationsResponse = { notifications: AppNotification[]; unread: number };

export type PersonaProfile = {
	handle: string;
	name: string;
	voice: string;
	bio: string | null;
	posts: Card[];
	comments: { card_id: string; repo: string; hook: string; text: string }[];
};
export type FileHistory = {
	commits: number;
	last_touched: string | null;
	authors: { name: string; commits: number }[];
};
export type FileProfile = {
	repo: string;
	path: string;
	history: FileHistory | null;
	cards: Card[];
	followed: boolean;
};
