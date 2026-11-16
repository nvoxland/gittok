import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const script = readFileSync(`${process.cwd()}/../src/gittok/static/pair.js`, 'utf8');
const replace = vi.fn();
const reload = vi.fn();
const fetchMock = vi.fn();
let page: Document;
let events: EventTarget;

beforeEach(() => {
	vi.useFakeTimers();
	page = document.implementation.createHTMLDocument('Pair');
	events = new EventTarget();
	replace.mockReset();
	reload.mockReset();
	fetchMock.mockReset().mockResolvedValue({ ok: true });
});
afterEach(() => vi.useRealTimers());

function load(body: string) {
	page.body.innerHTML = body;
	new Function('document', 'window', 'navigator', 'fetch', 'setTimeout', script)(
		page,
		{ location: { replace, reload }, addEventListener: events.addEventListener.bind(events), isSecureContext: false },
		navigator, fetchMock, setTimeout
	);
}

it('requests a code without adding a form POST or wait page to Back history', async () => {
	load('<form method="post" action="/pair/code"><button>Pair with a code</button></form>');
	const submit = new Event('submit', { bubbles: true, cancelable: true });
	page.querySelector('form')!.dispatchEvent(submit);
	expect(submit.defaultPrevented).toBe(true);
	await vi.waitFor(() => expect(replace).toHaveBeenCalledWith('/pair/wait'));
	expect(fetchMock).toHaveBeenCalledWith('/pair/code', expect.objectContaining({ method: 'POST', credentials: 'same-origin' }));
});

it('replaces the wait page while checking approval instead of pushing navigation', async () => {
	load('<span data-pair-wait>Waiting</span>');
	expect(replace).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(3000);
	expect(replace).toHaveBeenCalledExactlyOnceWith('/pair/wait');
});

it('rechecks pairing by reloading the same page when it is restored from the Back cache', () => {
	load('<h1>Pair this device</h1>');
	const event = new Event('pageshow');
	Object.defineProperty(event, 'persisted', { value: true });
	events.dispatchEvent(event);
	expect(reload).toHaveBeenCalledOnce();
	expect(replace).not.toHaveBeenCalled();
});

it('shows the reason the server gives when it refuses a code', async () => {
	fetchMock.mockResolvedValue({
		ok: false,
		json: async () => ({ code: 'too_many_pair_requests', detail: 'too many devices wait for a pairing code; try again later' })
	});
	load('<form method="post" action="/pair/code"><button>Pair with a code</button></form>');
	page.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
	await vi.waitFor(() =>
		expect(page.querySelector('[role=alert]')?.textContent).toBe('Too many devices wait for a pairing code; try again later.')
	);
});

it('leaves the form usable after a failed request without navigating', async () => {
	fetchMock.mockResolvedValue({ ok: false });
	load('<form method="post" action="/pair/code"><button>Pair with a code</button></form>');
	page.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
	await vi.waitFor(() => expect(page.querySelector('[role=alert]')).not.toBeNull());
	expect(replace).not.toHaveBeenCalled();
	expect(page.querySelector('button')!.disabled).toBe(false);
});
