import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = resolve(__dirname, '../../..');
const read = (p: string) => readFileSync(resolve(root, p), 'utf8');

describe('PWA static files', () => {
	const manifest = () => JSON.parse(read('static/manifest.webmanifest'));
	it('has a standalone manifest named GitTok', () => {
		const m = manifest();
		expect(m.name).toBe('GitTok');
		expect(m.short_name).toBeTruthy();
		expect(m.display).toBe('standalone');
		expect(m.start_url).toBe('/');
		expect(m.theme_color).toBe('#f6f6f4');
		expect(m.background_color).toBe('#f6f6f4');
	});
	it('lists 192 and 512 icons that exist', () => {
		const sizes = manifest().icons.map((i: { sizes: string }) => i.sizes);
		expect(sizes).toEqual(expect.arrayContaining(['192x192', '512x512']));
		for (const i of manifest().icons) expect(existsSync(resolve(root, 'static', i.src.slice(1)))).toBe(true);
	});
	it('links the manifest, apple icon and theme colors from app.html', () => {
		const html = read('src/app.html');
		expect(html).toContain('rel="manifest" href="/manifest.webmanifest"');
		expect(html).toContain('rel="apple-touch-icon" href="/apple-touch-icon.png"');
		expect(html).toContain('name="theme-color" content="#f6f6f4" media="(prefers-color-scheme: light)"');
		expect(html).toContain('name="theme-color" content="#0e0e10" media="(prefers-color-scheme: dark)"');
	});
});
