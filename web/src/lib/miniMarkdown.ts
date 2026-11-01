// A tiny, safe markdown subset for the explain panel: paragraphs, "- " lists, `code`, **bold**.
// It builds plain nodes. The caller renders them with text bindings, never as HTML.

export type Inline = { kind: 'text' | 'code' | 'bold'; text: string };
export type Block = { type: 'p'; inline: Inline[] } | { type: 'ul'; items: Inline[][] };

const LONG_PARAGRAPH = 280;

export function parseInline(src: string): Inline[] {
	const out: Inline[] = [];
	let text = '';
	const flush = () => {
		if (text) out.push({ kind: 'text', text });
		text = '';
	};
	let i = 0;
	while (i < src.length) {
		const marker = src.startsWith('**', i) ? '**' : src[i] === '`' ? '`' : null;
		const end = marker ? src.indexOf(marker, i + marker.length) : -1;
		if (marker && end > i + marker.length) {
			flush();
			out.push({
				kind: marker === '`' ? 'code' : 'bold',
				text: src.slice(i + marker.length, end)
			});
			i = end + marker.length;
		} else {
			text += src[i];
			i += 1;
		}
	}
	flush();
	return out;
}

// Sentence ends: ". " followed by a capital letter or a backtick.
export function splitSentences(text: string): string[] {
	return text.split(/(?<=\.)\s+(?=[A-Z`])/);
}

function chunkSentences(sentences: string[]): string[] {
	const out: string[] = [];
	let i = 0;
	while (i < sentences.length) {
		const left = sentences.length - i;
		const take = left === 4 ? 2 : Math.min(3, left);
		out.push(sentences.slice(i, i + take).join(' '));
		i += take;
	}
	return out;
}

export function parseMarkdown(text: string): Block[] {
	const groups = text.split(/\n\s*\n/).filter((g) => g.trim() !== '');
	if (groups.length === 1 && !/^\s*- /m.test(groups[0]) && groups[0].length > LONG_PARAGRAPH) {
		const flat = groups[0].replace(/\s*\n\s*/g, ' ').trim();
		groups.splice(0, 1, ...chunkSentences(splitSentences(flat)));
	}
	const blocks: Block[] = [];
	for (const g of groups) {
		let para: string[] = [];
		let items: string[] | null = null;
		const endPara = () => {
			if (para.length) blocks.push({ type: 'p', inline: parseInline(para.join(' ')) });
			para = [];
		};
		const endList = () => {
			if (items) blocks.push({ type: 'ul', items: items.map(parseInline) });
			items = null;
		};
		for (const raw of g.split('\n')) {
			const line = raw.trim();
			if (line === '') continue;
			if (line.startsWith('- ')) {
				endPara();
				(items ??= []).push(line.slice(2).trim());
			} else {
				endList();
				para.push(line);
			}
		}
		endPara();
		endList();
	}
	return blocks;
}
