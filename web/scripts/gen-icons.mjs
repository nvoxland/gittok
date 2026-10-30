// Generates the PWA icons with node built-ins only (no image libraries).
// Run: node scripts/gen-icons.mjs   (outputs are committed in static/)
// The icon is a neutral code prompt glyph (> _) on the accent color.
import { deflateSync } from 'node:zlib';
import { writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const out = join(resolve(dirname(fileURLToPath(import.meta.url)), '..'), 'static');
const BG = [0x3b, 0x6e, 0xf5];
const FG = [255, 255, 255];
const W = 0.07; // stroke width in unit-square units
const SEGMENTS = [
	[0.34, 0.32, 0.54, 0.5],
	[0.54, 0.5, 0.34, 0.68],
	[0.58, 0.7, 0.72, 0.7]
];
const RADIUS = 0.22;

function distToSegment(px, py, [x1, y1, x2, y2]) {
	const dx = x2 - x1;
	const dy = y2 - y1;
	const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
	return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function insideRounded(x, y, r) {
	const cx = Math.min(Math.max(x, r), 1 - r);
	const cy = Math.min(Math.max(y, r), 1 - r);
	return Math.hypot(x - cx, y - cy) <= r;
}

// Returns RGBA bytes. `full` fills the whole square (maskable and apple-touch icons).
function render(size, full) {
	const SS = 4;
	const px = Buffer.alloc(size * size * 4);
	for (let y = 0; y < size; y++) {
		for (let x = 0; x < size; x++) {
			let r = 0, g = 0, b = 0, a = 0;
			for (let sy = 0; sy < SS; sy++) {
				for (let sx = 0; sx < SS; sx++) {
					const u = (x + (sx + 0.5) / SS) / size;
					const v = (y + (sy + 0.5) / SS) / size;
					if (!full && !insideRounded(u, v, RADIUS)) continue;
					const glyph = SEGMENTS.some((s) => distToSegment(u, v, s) <= W / 2);
					const c = glyph ? FG : BG;
					r += c[0]; g += c[1]; b += c[2]; a += 255;
				}
			}
			const n = SS * SS;
			const i = (y * size + x) * 4;
			const cov = a / 255;
			px[i] = cov ? Math.round(r / cov) : 0;
			px[i + 1] = cov ? Math.round(g / cov) : 0;
			px[i + 2] = cov ? Math.round(b / cov) : 0;
			px[i + 3] = Math.round(a / n);
		}
	}
	return px;
}

const crcTable = Array.from({ length: 256 }, (_, n) => {
	let c = n;
	for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
	return c >>> 0;
});
function crc32(buf) {
	let c = 0xffffffff;
	for (const byte of buf) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
	return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
	const len = Buffer.alloc(4);
	len.writeUInt32BE(data.length);
	const body = Buffer.concat([Buffer.from(type), data]);
	const crc = Buffer.alloc(4);
	crc.writeUInt32BE(crc32(body));
	return Buffer.concat([len, body, crc]);
}
function png(size, rgba) {
	const ihdr = Buffer.alloc(13);
	ihdr.writeUInt32BE(size, 0);
	ihdr.writeUInt32BE(size, 4);
	ihdr[8] = 8; // bit depth
	ihdr[9] = 6; // RGBA
	const raw = Buffer.alloc(size * (size * 4 + 1));
	for (let y = 0; y < size; y++) {
		raw[y * (size * 4 + 1)] = 0;
		rgba.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
	}
	return Buffer.concat([
		Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
		chunk('IHDR', ihdr),
		chunk('IDAT', deflateSync(raw)),
		chunk('IEND', Buffer.alloc(0))
	]);
}

const files = [
	['icon-192.png', 192, false],
	['icon-512.png', 512, false],
	['icon-maskable-512.png', 512, true],
	['apple-touch-icon.png', 180, true]
];
for (const [name, size, full] of files) writeFileSync(join(out, name), png(size, render(size, full)));

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="${RADIUS * 512}" fill="#3b6ef5"/>
<g fill="none" stroke="#fff" stroke-width="${W * 512}" stroke-linecap="round" stroke-linejoin="round">
<polyline points="${SEGMENTS[0][0] * 512},${SEGMENTS[0][1] * 512} ${SEGMENTS[0][2] * 512},${SEGMENTS[0][3] * 512} ${SEGMENTS[1][2] * 512},${SEGMENTS[1][3] * 512}"/>
<line x1="${SEGMENTS[2][0] * 512}" y1="${SEGMENTS[2][1] * 512}" x2="${SEGMENTS[2][2] * 512}" y2="${SEGMENTS[2][3] * 512}"/>
</g>
</svg>
`;
writeFileSync(join(out, 'icon.svg'), svg);
