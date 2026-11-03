/** Code as it should be shown in a narrow box: leading tabs as two spaces, then the indent
 * that every non-blank line shares removed. The line count never changes, so line numbers
 * stay right. Display only: cards still cite the real lines. */
export function dedent(code: string): string {
	const lines = code
		.replace(/\n$/, '')
		.split('\n')
		.map((l) => l.replace(/^\t+/, (tabs) => '  '.repeat(tabs.length)));
	const indents = lines.filter((l) => l.trim()).map((l) => l.match(/^ */)![0].length);
	const cut = indents.length ? Math.min(...indents) : 0;
	return lines.map((l) => l.slice(Math.min(cut, l.match(/^ */)![0].length))).join('\n');
}
