import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import DiffPanel from './DiffPanel.svelte';

const diff = '@@ -1,2 +1,2 @@\n context\n-old line\n+new line';

describe('DiffPanel', () => {
	it('marks + and - lines', () => {
		const { container } = render(DiffPanel, {
			repo: 'gittok',
			path: 'src/x.py',
			commit: 'abcdef1234567',
			diff
		});
		expect(container.querySelector('.del')?.textContent).toContain('old line');
		expect(container.querySelector('.add')?.textContent).toContain('new line');
		expect(container.querySelectorAll('.add')).toHaveLength(1);
		expect(container.querySelectorAll('.del')).toHaveLength(1);
		expect(container.textContent).toContain('gittok · src/x.py · abcdef1');
	});
});
