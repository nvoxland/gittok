import { describe, expect, it } from 'vitest';
import { fitFontPx, isClipped, isDismissSwipe, isShrunk } from './lightbox.ts';

describe('isClipped', () => {
	it('is true when the content is taller than the box', () => {
		expect(isClipped(400, 300)).toBe(true);
		expect(isClipped(300, 300)).toBe(false);
		expect(isClipped(301, 300)).toBe(false); // sub-pixel rounding
		expect(isClipped(0, 0)).toBe(false);
	});
});

describe('isShrunk', () => {
	it('computes the fit font from columns and box width', () => {
		expect(fitFontPx(310, 50)).toBeCloseTo(10, 0);
	});
	it('is true below 0.7rem (11.2px), false above, false for an unmeasured box', () => {
		expect(isShrunk(310, 50)).toBe(true);
		expect(isShrunk(310, 30)).toBe(false);
		expect(isShrunk(0, 50)).toBe(false);
	});
});

describe('isDismissSwipe', () => {
	it('needs a long mostly-vertical downward move from the top of the scroll', () => {
		expect(isDismissSwipe(0, 120, 0)).toBe(true);
		expect(isDismissSwipe(0, 120, 50)).toBe(false); // scrolled down: it is a scroll
		expect(isDismissSwipe(0, 40, 0)).toBe(false);
		expect(isDismissSwipe(0, -120, 0)).toBe(false);
		expect(isDismissSwipe(100, 120, 0)).toBe(false); // sideways
	});
});
