import { render, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { diagramVisual } from '../fixtures.ts';

const { initialize, renderFn } = vi.hoisted(() => ({ initialize: vi.fn(), renderFn: vi.fn() }));
vi.mock('mermaid', () => ({ default: { initialize, render: renderFn } }));

import DiagramVisual from './DiagramVisual.svelte';

beforeEach(() => {
	initialize.mockReset();
	renderFn.mockReset();
});

describe('DiagramVisual', () => {
	it('renders the svg that mermaid returns', async () => {
		renderFn.mockResolvedValue({ svg: '<svg data-testid="m"><g></g></svg>' });
		const { container } = render(DiagramVisual, { visual: diagramVisual(), resolved: null });
		await waitFor(() => expect(container.querySelector('.diagram svg')).not.toBeNull());
		expect(renderFn.mock.calls[0][1]).toBe('flowchart LR\n  A[api] --> B[store]');
		expect(initialize.mock.calls[0][0]).toMatchObject({ startOnLoad: false, securityLevel: 'strict' });
	});
	it('passes a theme', async () => {
		renderFn.mockResolvedValue({ svg: '<svg></svg>' });
		render(DiagramVisual, { visual: diagramVisual(), resolved: null });
		await waitFor(() => expect(initialize).toHaveBeenCalled());
		expect(['default', 'dark']).toContain(initialize.mock.calls[0][0].theme);
	});
	it('falls back to source in a pre on failure', async () => {
		renderFn.mockRejectedValue(new Error('parse error'));
		const { container } = render(DiagramVisual, { visual: diagramVisual(), resolved: null });
		await waitFor(() => expect(container.querySelector('pre')).not.toBeNull());
		expect(container.querySelector('pre')!.textContent).toContain('A[api] --> B[store]');
	});
});
