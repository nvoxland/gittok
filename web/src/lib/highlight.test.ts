import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { bundledLanguages } from 'shiki';
import { describe, expect, it } from 'vitest';

// config/file_types.yaml maps a file extension to the language name a code view highlights
// with. CodeBlock gives that name to Shiki, so each name must be a language Shiki bundles.
function highlightNames(): Record<string, string> {
	const text = readFileSync(resolve(process.cwd(), '../config/file_types.yaml'), 'utf8');
	const start = text.indexOf('\nhighlight:\n');
	const out: Record<string, string> = {};
	for (const line of text.slice(start + '\nhighlight:\n'.length).split('\n')) {
		const m = /^ {2}(\.[\w+-]+):\s*([\w+-]+)\s*$/.exec(line);
		if (m) out[m[1]] = m[2];
		else if (line.trim() !== '' && !line.startsWith(' ')) break;
	}
	return out;
}

describe('the highlight table of config/file_types.yaml', () => {
	it('names only languages that the highlighter can render', () => {
		const names = highlightNames();
		expect(Object.keys(names).length).toBeGreaterThan(30);
		const unknown = Object.entries(names).filter(([, name]) => !(name in bundledLanguages));
		expect(unknown).toEqual([]);
	});
});
