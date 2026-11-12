import type { Card } from '#lib/types.ts';

export function fakeCard(over: Partial<Card> = {}): Card {
	return {
		id: 'c_1',
		created_at: '2026-10-30T12:00:00Z',
		repo: 'gittok',
		story_type: 'hot_spot',
		format: 'code_card',
		persona: 'greybeard',
		tone: 'dry-deadpan',
		hook: 'This file has been edited 41 times.',
		visual: { kind: 'text', title: 'Title', body: 'Body' },
		depth: [],
		comments: [],
		sources: [],
		resolved: { visual: null, depth: [] },
		...over
	};
}

// Loose on purpose: component props are typed per visual, fixtures serve all of them.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyJson = any;

export const images = (n = 1) => ({
	images: Array.from({ length: n }, (_, i) => `/assets/c_1/${i}.png`),
	width: 1024,
	height: 1024
});

export const memeVisual = (): AnyJson => ({
	kind: 'meme',
	template: 'drake',
	lines: ['Reading the docs', 'Reading git blame']
});
export const illustrationVisual = (): AnyJson => ({
	kind: 'illustration',
	prompt: 'otter stacking crates',
	caption: 'Me, deploying on a Friday',
	mascots: ['otter']
});
export const comicVisual = (n = 4): AnyJson => ({
	kind: 'comic',
	panels: Array.from({ length: n }, (_, i) => ({ prompt: `p${i}`, caption: `Caption ${i}` }))
});
export const textMemeVisual = (style: string, lines: string[]): AnyJson =>
	({ kind: 'text_meme', style, lines });

export const chartResolved = (): AnyJson => ({
	type: 'bar',
	title: 'Where the edits go',
	x_label: 'commits',
	y_label: 'file',
	bars: [
		{ label: 'src/storefront/shipping.clj', value: 41 },
		{ label: 'src/b.py', value: 20 },
		{ label: 'README.md', value: 3 }
	]
});
export const hoursResolved = (): AnyJson => ({
	type: 'bar',
	title: 'Commit hours',
	x_label: 'hour',
	y_label: 'commits',
	bars: Array.from({ length: 24 }, (_, i) => ({ label: String(i).padStart(2, '0'), value: i % 7 }))
});
export const chartVisual = (chart = 'top_churn_files'): AnyJson =>
	({ kind: 'chart', chart, repo: 'gittok', title: 'Where the edits go' });

export const diagramVisual = (): AnyJson => ({
	kind: 'diagram',
	title: 'Request flow',
	mermaid: 'flowchart LR\n  A[api] --> B[store]'
});

export const templateFixtures: Record<string, AnyJson> = {
	iceberg: {
		kind: 'template',
		template: 'iceberg',
		data: {
			title: 'The iceberg of billing',
			layers: [
				{ label: 'Surface', items: ['invoice.py'] },
				{ label: 'Below', items: ['rounding hacks', 'retry loop'] },
				{ label: 'Abyss', items: ['the cron'] }
			]
		}
	},
	tier_list: {
		kind: 'template',
		template: 'tier_list',
		data: {
			title: 'Modules ranked',
			rows: [
				{ tier: 'S', items: [{ name: 'gitq', why: 'only git spawner' }] },
				{ tier: 'F', items: [{ name: 'misc', why: 'junk drawer' }] }
			]
		}
	},
	group_chat: {
		kind: 'template',
		template: 'group_chat',
		data: {
			title: 'the squad',
			messages: [
				{ from: 'greybeard', text: 'who touched billing' },
				{ from: 'gittok:src/blamescroll/gitq.py', text: 'not me' }
			]
		}
	},
	flags: {
		kind: 'template',
		template: 'flags',
		data: { subject: 'gitq.py', red: ['spawns git'], green: ['well tested', 'small'] }
	},
	dating_profile: {
		kind: 'template',
		template: 'dating_profile',
		data: {
			name: 'gittok:src/blamescroll/gitq.py',
			age: '3 years',
			bio: 'I only talk to git.',
			likes: ['subprocess'],
			dealbreakers: ['shell=True']
		}
	},
	glow_up: {
		kind: 'template',
		template: 'glow_up',
		data: {
			subject: 'parser',
			before: { label: 'Before', text: 'regex soup' },
			after: { label: 'After', text: 'a real grammar' }
		}
	},
	breaking_news: {
		kind: 'template',
		template: 'breaking_news',
		data: { headline: 'Tests pass on first try', subhead: 'Experts baffled', ticker: ['CI green', 'Lint quiet'] }
	},
	horoscope: {
		kind: 'template',
		template: 'horoscope',
		data: { subject: 'greybeard', sign: 'Capricorn', forecast: 'A merge conflict approaches.', lucky: 'Lucky file: Makefile' }
	},
	thread: {
		kind: 'template',
		template: 'thread',
		data: { posts: ['Let me explain billing.', 'It starts in 2019.', 'It never ended.'] }
	},
	day_in_life: {
		kind: 'template',
		template: 'day_in_life',
		data: {
			subject: 'greybeard',
			steps: [
				{ time: '09:00', text: 'wakes up' },
				{ time: '12:00', text: 'rebases' },
				{ time: '17:00', text: 'reverts' }
			]
		}
	},
	hot_take: {
		kind: 'template',
		template: 'hot_take',
		data: { take: 'Tabs are fine.' }
	}
};
