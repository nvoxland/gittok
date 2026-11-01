import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown, splitSentences } from './miniMarkdown';

describe('parseInline', () => {
	it('finds code spans and bold', () => {
		expect(parseInline('Edit `a.py` and **this** now')).toEqual([
			{ kind: 'text', text: 'Edit ' },
			{ kind: 'code', text: 'a.py' },
			{ kind: 'text', text: ' and ' },
			{ kind: 'bold', text: 'this' },
			{ kind: 'text', text: ' now' }
		]);
	});

	it('keeps an unclosed marker as text', () => {
		expect(parseInline('a `b and **c')).toEqual([{ kind: 'text', text: 'a `b and **c' }]);
	});

	it('does not parse bold inside code', () => {
		expect(parseInline('`**x**`')).toEqual([{ kind: 'code', text: '**x**' }]);
	});

	it('keeps HTML as plain text', () => {
		expect(parseInline('<script>alert(1)</script>')).toEqual([
			{ kind: 'text', text: '<script>alert(1)</script>' }
		]);
	});
});

describe('parseMarkdown', () => {
	it('splits paragraphs on blank lines', () => {
		const blocks = parseMarkdown('One.\n\nTwo.');
		expect(blocks.map((b) => b.type)).toEqual(['p', 'p']);
	});

	it('reads "- " lines as a list', () => {
		const blocks = parseMarkdown('Intro\n\n- one `x`\n- two\n- three');
		expect(blocks[1]).toEqual({
			type: 'ul',
			items: [
				[
					{ kind: 'text', text: 'one ' },
					{ kind: 'code', text: 'x' }
				],
				[{ kind: 'text', text: 'two' }],
				[{ kind: 'text', text: 'three' }]
			]
		});
	});

	it('ends a list when plain text follows', () => {
		const blocks = parseMarkdown('- a\n- b\nafter');
		expect(blocks.map((b) => b.type)).toEqual(['ul', 'p']);
	});

	it('returns nothing for blank text', () => {
		expect(parseMarkdown('  \n ')).toEqual([]);
	});

	it('splits one long paragraph into 2-3 sentence paragraphs', () => {
		const s = 'The sync engine batches writes into one transaction per tick';
		const text = Array.from({ length: 8 }, (_, i) => `${s} number ${i}.`).join(' ');
		const blocks = parseMarkdown(text);
		expect(blocks.length).toBeGreaterThan(2);
		for (const b of blocks) expect(b.type).toBe('p');
	});

	it('leaves a short single paragraph alone', () => {
		expect(parseMarkdown('Short one. Another one.')).toHaveLength(1);
	});

	it('does not split a paragraph that already has blank lines', () => {
		const long = 'Word. '.repeat(100).trim();
		expect(parseMarkdown(`${long}\n\nShort.`)).toHaveLength(2);
	});

	it('keeps script tags as text', () => {
		const [b] = parseMarkdown('<script>x</script> `y`');
		expect(b.type).toBe('p');
		if (b.type === 'p') expect(b.inline[0]).toEqual({ kind: 'text', text: '<script>x</script> ' });
	});
});

describe('splitSentences', () => {
	it('splits at a period before a capital letter or a backtick', () => {
		expect(splitSentences('It ran. Then `x` broke. ok. fine.')).toEqual([
			'It ran.',
			'Then `x` broke. ok. fine.'
		]);
	});

	it('does not split on file names', () => {
		expect(splitSentences('See store.py for it. Done.')).toEqual(['See store.py for it.', 'Done.']);
	});
});
