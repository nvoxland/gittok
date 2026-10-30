// Builds build/sw.js from src/sw.ts. Runs after `vite build` (see package.json "build").
// A separate Vite lib build bundles src/sw.ts and src/lib/sw/logic.ts into one classic script,
// with the precache list (from the files in build/) and a content version baked in via `define`.
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { selectPrecache } from '../src/lib/sw/logic.ts';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'build');
const MAX_PRECACHE_BYTES = 200_000; // big chunks (mermaid, shiki) are cached at runtime instead

function walk(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
		const p = join(dir, e.name);
		if (e.name === 'node_modules') return [];
		return e.isDirectory() ? walk(p) : [p];
	});
}

const files = walk(out)
	.map((p) => ({ path: relative(out, p).split('\\').join('/'), size: statSync(p).size, abs: p }))
	.sort((a, b) => a.path.localeCompare(b.path));
const precache = selectPrecache(files, MAX_PRECACHE_BYTES);
const hash = createHash('sha256');
for (const f of files) if (f.path !== 'sw.js') hash.update(f.path).update(readFileSync(f.abs));
const version = hash.digest('hex').slice(0, 12);

await build({
	configFile: false,
	root,
	logLevel: 'warn',
	define: { __PRECACHE__: JSON.stringify(precache), __VERSION__: JSON.stringify(version) },
	build: {
		outDir: out,
		emptyOutDir: false,
		copyPublicDir: false,
		minify: true,
		lib: { entry: join(root, 'src/sw.ts'), formats: ['iife'], name: 'sw', fileName: () => 'sw.js' }
	}
});
console.log(`sw.js: ${precache.length} precached urls, version ${version}`);
