import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import TemplateVisual from './TemplateVisual.svelte';
import { templateFixtures } from '../fixtures.ts';

const r = (name: string) =>
	render(TemplateVisual, { visual: templateFixtures[name], resolved: null, persona: 'greybeard' }).container;

describe('TemplateVisual', () => {
	it('iceberg stacks layers with increasing depth', () => {
		const c = r('iceberg');
		const layers = c.querySelectorAll('.layer');
		expect(layers).toHaveLength(3);
		expect(layers[2]).toHaveAttribute('data-depth', '2');
		expect(screen.getByText('The iceberg of billing')).toBeInTheDocument();
		expect(screen.getByText('the cron')).toBeInTheDocument();
	});
	it('tier_list renders tier rows', () => {
		const c = r('tier_list');
		const rows = c.querySelectorAll('.row');
		expect(rows).toHaveLength(2);
		expect(rows[0].querySelector('.tier')).toHaveTextContent('S');
		expect(rows[1].querySelector('.tier')).toHaveAttribute('data-tier', 'F');
		expect(screen.getByText('gitq')).toBeInTheDocument();
	});
	it('group_chat labels senders with handles', () => {
		const c = r('group_chat');
		expect(c.querySelectorAll('.bubble')).toHaveLength(2);
		expect(screen.getByText('@greybeard')).toBeInTheDocument();
		expect(screen.getByText('@gitq.py')).toBeInTheDocument();
		expect(screen.getByText('not me')).toBeInTheDocument();
	});
	it('flags has red and green columns', () => {
		const c = r('flags');
		expect(c.querySelectorAll('.red li')).toHaveLength(1);
		expect(c.querySelectorAll('.green li')).toHaveLength(2);
	});
	it('dating_profile shows the profile card', () => {
		r('dating_profile');
		expect(screen.getByText('@gitq.py')).toBeInTheDocument();
		expect(screen.getByText(/3 years/)).toBeInTheDocument();
		expect(screen.getByText('I only talk to git.')).toBeInTheDocument();
		expect(screen.getByText('subprocess')).toBeInTheDocument();
		expect(screen.getByText('shell=True')).toBeInTheDocument();
	});
	it('glow_up shows before and after', () => {
		const c = r('glow_up');
		expect(c.querySelector('.before')).toHaveTextContent('regex soup');
		expect(c.querySelector('.after')).toHaveTextContent('a real grammar');
	});
	it('breaking_news shows banner, headline and ticker', () => {
		const c = r('breaking_news');
		expect(screen.getByText('BREAKING')).toBeInTheDocument();
		expect(screen.getByText('Tests pass on first try')).toBeInTheDocument();
		expect(c.querySelector('.ticker')).toHaveTextContent('CI green');
	});
	it('horoscope shows sign, forecast and lucky', () => {
		r('horoscope');
		expect(screen.getByText('Capricorn')).toBeInTheDocument();
		expect(screen.getByText('A merge conflict approaches.')).toBeInTheDocument();
		expect(screen.getByText('Lucky file: Makefile')).toBeInTheDocument();
	});
	it('thread numbers posts', () => {
		const c = r('thread');
		expect(c.querySelectorAll('.post')).toHaveLength(3);
		expect(screen.getByText('1/3')).toBeInTheDocument();
		expect(screen.getByText('3/3')).toBeInTheDocument();
	});
	it('day_in_life lists times', () => {
		const c = r('day_in_life');
		expect(c.querySelectorAll('.step')).toHaveLength(3);
		expect(screen.getByText('09:00')).toBeInTheDocument();
		expect(screen.getByText('reverts')).toBeInTheDocument();
	});
	it('hot_take shows the quote and avatar', () => {
		const c = r('hot_take');
		expect(screen.getByText(/Tabs are fine\./)).toBeInTheDocument();
		expect(c.querySelector('blockquote')).not.toBeNull();
		expect(c.querySelector('img')!.getAttribute('src')).toBe('/api/avatars/greybeard');
	});
	it('unknown template shows a fallback', () => {
		render(TemplateVisual, {
			visual: { kind: 'template', template: 'nope', data: {} } as never,
			resolved: null
		});
		expect(screen.getByText(/unsupported template/i)).toBeInTheDocument();
	});
});

describe('TemplateVisual with only required fields', () => {
	const minimal: Record<string, unknown> = {
		iceberg: {
			title: 't',
			layers: [
				{ label: 'a', items: ['x'] },
				{ label: 'b', items: ['y'] },
				{ label: 'c', items: ['z'] }
			]
		},
		tier_list: {
			title: 't',
			rows: [
				{ tier: 'S', items: [{ name: 'n', why: 'w' }] },
				{ tier: 'F', items: [{ name: 'm', why: 'v' }] }
			]
		},
		group_chat: {
			title: 't',
			messages: [
				{ from: 'greybeard', text: 'hi' },
				{ from: 'greybeard', text: 'yo' }
			]
		},
		flags: { subject: 's', red: ['r'], green: [] },
		dating_profile: { name: 'greybeard', age: '3', bio: 'b', likes: ['l'], dealbreakers: ['d'] },
		glow_up: { subject: 's', before: { label: 'b', text: 't' }, after: { label: 'a', text: 't' } },
		breaking_news: { headline: 'Big news' },
		horoscope: { subject: 'greybeard', sign: 'Leo', forecast: 'f' },
		thread: { posts: ['a', 'b'] },
		day_in_life: {
			subject: 'greybeard',
			steps: [
				{ time: '1', text: 'a' },
				{ time: '2', text: 'b' },
				{ time: '3', text: 'c' }
			]
		},
		hot_take: { take: 'spicy' }
	};
	for (const [name, data] of Object.entries(minimal)) {
		it(`${name} renders`, () => {
			const { container } = render(TemplateVisual, {
				visual: { kind: 'template', template: name, data },
				resolved: null
			} as never);
			expect(container.textContent?.length).toBeGreaterThan(0);
			expect(container.querySelector('.unsupported')).toBeNull();
		});
	}
});
