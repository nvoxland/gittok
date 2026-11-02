// Pure helpers for the full-screen visual viewer.

const CLIP_SLACK_PX = 2;
// Smaller than this and fitted code is hard to read on a phone.
const MIN_READABLE_PX = 0.7 * 16;
// CodeBlock sizes its font to 100cqw / (cols * 0.62); keep in step with its CSS.
const CHAR_WIDTH_EM = 0.62;
const SWIPE_MIN_PX = 80;

/** The visual box is shorter than its content (the rest is cut off). */
export function isClipped(scrollHeight: number, clientHeight: number): boolean {
	return scrollHeight > clientHeight + CLIP_SLACK_PX;
}

/** The font size (px) CodeBlock `fit` computes, before its 0.55rem to 0.8rem clamp. */
export function fitFontPx(boxWidth: number, cols: number): number {
	return boxWidth / (cols * CHAR_WIDTH_EM);
}

/** Fitted code that is too small to read. An unmeasured box (width 0) is not shrunk. */
export function isShrunk(boxWidth: number, cols: number): boolean {
	return boxWidth > 0 && fitFontPx(boxWidth, cols) < MIN_READABLE_PX;
}

/** A downward swipe that should close the viewer: long, mostly vertical, from the scroll top. */
export function isDismissSwipe(dx: number, dy: number, scrollTop: number): boolean {
	return scrollTop <= 0 && dy >= SWIPE_MIN_PX && Math.abs(dx) < dy / 2;
}
