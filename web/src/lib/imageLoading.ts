// Images load lazily, except where the image is on screen as soon as it mounts:
// the first card of the feed and the lightbox. Those set the context; images read it.
import { getContext, setContext } from 'svelte';

const KEY = Symbol('eager-images');

export function setEagerImages(eager: () => boolean): void {
	setContext(KEY, eager);
}

/** Call during component init. */
export function imageLoading(): 'eager' | 'lazy' {
	return getContext<(() => boolean) | undefined>(KEY)?.() ? 'eager' : 'lazy';
}
