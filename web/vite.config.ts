import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [
		sveltekit({
			adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: false })
		})
	],
	server: {
		// The feed server of the clone (`server.port`); set GITTOK_PORT if you changed it.
		proxy: {
			'/api': `http://127.0.0.1:${process.env.GITTOK_PORT ?? '7313'}`,
			'/healthz': `http://127.0.0.1:${process.env.GITTOK_PORT ?? '7313'}`
		}
	},
	resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
	test: {
		environment: 'jsdom',
		include: ['src/**/*.test.ts'],
		setupFiles: ['./vitest-setup.ts'],
		globals: false
	}
});
