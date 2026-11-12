// Checks on the CSS source: jsdom does not lay out pages, so these rules cannot be seen at run time.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const read = (rel: string) => readFileSync(`${process.cwd()}/src/${rel}`, 'utf8');
const style = (rel: string) => read(rel).split('<style>')[1] ?? '';
/** The body of the first rule whose selector is `sel` (at the start of a line). */
function rule(css: string, sel: string): string {
	const esc = sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const m = css.match(new RegExp(`(?:^|\\n)\\s*${esc}\\s*\\{([^}]*)\\}`));
	if (!m) throw new Error(`no rule ${sel}`);
	return m[1];
}

function luminance(hex: string): number {
	const [r, g, b] = [1, 3, 5].map((i) => {
		const c = parseInt(hex.slice(i, i + 2), 16) / 255;
		return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}
function tokens(block: string): Record<string, string> {
	return Object.fromEntries([...block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
}

describe('safe-area insets', () => {
	it('the top bar stays clear of the notch', () => {
		const css = style('routes/+page.svelte');
		expect(rule(css, '.chrome')).toContain('env(safe-area-inset-top)');
		expect(rule(css, '.chrome')).toContain('env(safe-area-inset-left)');
		expect(rule(css, '.links')).toContain('env(safe-area-inset-right)');
	});
	it('the offline banner and the end card stay clear of the home indicator', () => {
		const css = style('routes/+page.svelte');
		expect(rule(css, '.offline')).toContain('env(safe-area-inset-bottom)');
		expect(rule(css, '.end')).toContain('env(safe-area-inset-bottom)');
	});
	it('a card keeps its content and buttons inside the safe area', () => {
		const css = style('lib/components/Card.svelte');
		const article = rule(css, 'article');
		for (const side of ['top', 'right', 'bottom', 'left']) {
			expect(article).toContain(`env(safe-area-inset-${side})`);
		}
		const actions = rule(css, '.actions');
		expect(actions).toContain('env(safe-area-inset-right)');
		expect(actions).toContain('env(safe-area-inset-bottom)');
	});
	it('the first card leaves the top inset to the top bar', () => {
		expect(rule(style('lib/components/Card.svelte'), 'article.first')).toMatch(/padding-top:\s*0\.75rem/);
	});
	it('the lightbox keeps its close button and content inside the safe area', () => {
		const css = style('lib/components/Lightbox.svelte');
		expect(rule(css, 'header')).toContain('env(safe-area-inset-top)');
		expect(rule(css, 'header')).toContain('env(safe-area-inset-right)');
		expect(rule(css, '.lb-body')).toContain('env(safe-area-inset-bottom)');
	});
	it('the gesture hint sits above the home indicator', () => {
		expect(rule(style('lib/components/GestureHints.svelte'), '.hints')).toContain(
			'env(safe-area-inset-bottom)'
		);
	});
	it('the other pages pad their sides and bottom by the insets', () => {
		const css = read('app.css');
		expect(css).toMatch(/--safe-left:\s*env\(safe-area-inset-left/);
		for (const file of [
			'routes/saved/+page.svelte',
			'routes/notifications/+page.svelte',
			'routes/card/[id]/+page.svelte',
			'routes/persona/[handle]/+page.svelte',
			'routes/file/[repo]/[...path]/+page.svelte',
			'lib/components/RepoProfile.svelte'
		]) {
			expect(style(file), file).toContain('var(--safe-');
		}
	});
});

describe('colour contrast', () => {
	const css = read('app.css');
	const light = tokens(css.split('@media (prefers-color-scheme: dark)')[0]);
	const dark = tokens(css.split('@media (prefers-color-scheme: dark)')[1]);

	it('error text is at least 4.5:1 on the page and on a surface, light and dark', () => {
		for (const t of [light, dark]) {
			expect(contrast(t.bad, t.bg)).toBeGreaterThanOrEqual(4.5);
			expect(contrast(t.bad, t.surface)).toBeGreaterThanOrEqual(4.5);
		}
	});
	it('error text uses the --bad token, not the old low-contrast red', () => {
		for (const file of ['routes/+page.svelte', 'lib/components/Quiz.svelte']) {
			expect(style(file), file).not.toMatch(/(?<!-)color:\s*#e5484d/i);
		}
		expect(rule(style('routes/+page.svelte'), '.error')).toContain('var(--bad)');
		expect(rule(style('lib/components/Quiz.svelte'), '.status')).toContain('var(--bad)');
	});
	it('the unread badge text is at least 4.5:1 on its background', () => {
		const badge = rule(style('lib/components/NotificationBell.svelte'), '.badge');
		expect(badge).toContain('background: var(--news)');
		for (const t of [light, dark]) expect(contrast('#ffffff', t.news)).toBeGreaterThanOrEqual(4.5);
	});
});

describe('reduced motion', () => {
	it('a global rule stops animations, transitions and smooth scrolling', () => {
		const css = read('app.css');
		const block = css.split('@media (prefers-reduced-motion: reduce)')[1] ?? '';
		expect(block).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
		expect(block).toMatch(/animation-iteration-count:\s*1\s*!important/);
		expect(block).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
		expect(block).toMatch(/scroll-behavior:\s*auto\s*!important/);
	});
});

describe('pull-to-refresh', () => {
	it('is off on html and on body: browsers differ in which one they read for the page scroller', () => {
		expect(read('app.css')).toMatch(/html,\s*body\s*\{[^}]*overscroll-behavior-y:\s*none/);
	});
});
