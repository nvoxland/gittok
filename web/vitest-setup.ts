import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/svelte';
import { afterEach } from 'vitest';

// vitest globals are off, so testing-library cannot auto-register cleanup.
afterEach(() => cleanup());
