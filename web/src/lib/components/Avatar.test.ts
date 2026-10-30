import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Avatar from './Avatar.svelte';
import Poster from './Poster.svelte';
import { accountHandle, isCodeAccount } from '#lib/account.ts';

describe('account helpers', () => {
	it('labels personas and code accounts', () => {
		expect(accountHandle('greybeard')).toBe('@greybeard');
		expect(accountHandle('storefront:src/storefront/shipping.clj')).toBe('@shipping.clj');
		expect(accountHandle('storefront:src/storefront/')).toBe('@storefront');
		expect(isCodeAccount('a:b')).toBe(true);
		expect(isCodeAccount('greybeard')).toBe(false);
	});
});

describe('Avatar', () => {
	it('uses the avatars api', () => {
		const { container } = render(Avatar, { handle: 'greybeard' });
		expect(container.querySelector('img')!.getAttribute('src')).toBe('/api/avatars/greybeard');
	});
	it('falls back to initials when the image errors', async () => {
		const { container } = render(Avatar, { handle: 'penny_learns' });
		await fireEvent.error(container.querySelector('img')!);
		expect(container.querySelector('img')).toBeNull();
		expect(screen.getByText('PL')).toBeInTheDocument();
	});
});

describe('Poster', () => {
	it('renders a persona with avatar', () => {
		const { container } = render(Poster, { account: 'greybeard' });
		expect(screen.getByText('@greybeard')).toBeInTheDocument();
		expect(container.querySelector('img')).not.toBeNull();
	});
	it('renders a code account with icon and no avatar request', () => {
		const { container } = render(Poster, { account: 'sf:src/shipping.clj' });
		expect(screen.getByText('@shipping.clj')).toBeInTheDocument();
		expect(container.querySelector('img')).toBeNull();
		expect(container.querySelector('[data-icon="file"]')).not.toBeNull();
	});
	it('uses a folder icon for directories', () => {
		const { container } = render(Poster, { account: 'sf:src/', kind: 'dir' });
		expect(container.querySelector('[data-icon="dir"]')).not.toBeNull();
	});
});
