// Regenerate committed PWA icons from the selected commit-comet artwork.
// Run on macOS: node web/scripts/gen-icons.mjs (uses the built-in sips tool).
import { execFileSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = join(root, 'icon-source.png');
const out = join(root, 'static');
for (const [name, size] of [
    ['icon-192.png', 192],
    ['icon-512.png', 512],
    ['apple-touch-icon.png', 180]
]) {
    execFileSync('sips', ['-z', String(size), String(size), source, '--out', join(out, name)]);
}
// Keep all artwork inside the maskable icon's central safe circle.
const maskable = join(out, 'icon-maskable-512.png');
execFileSync('sips', ['-z', '288', '288', source, '--out', maskable]);
execFileSync('sips', ['-p', '512', '512', '--padColor', '300025', maskable, '--out', maskable]);
