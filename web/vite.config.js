import { sveltekit } from '@sveltejs/kit/vite';

/** @type {import('vite').UserConfig} */
export default {
	plugins: [sveltekit()],
	server: {
		// In dev, proxy API calls to a locally-running FastAPI instance so the
		// SvelteKit dev server and API can run on separate ports without CORS
		// headaches; production uses Caddy for the same same-origin effect.
		proxy: {
			'/api': {
				target: process.env.FCCULS_API_PROXY_TARGET || 'http://localhost:8000',
				changeOrigin: true
			}
		}
	}
};
