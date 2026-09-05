import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		// Fully static build: Caddy serves these files directly and reverse
		// proxies /api to the FastAPI service. Dynamic routes (callsign/tower
		// detail pages) can't be enumerated at build time, so we run as a
		// client-rendered SPA (ssr disabled in the root layout) with a
		// fallback shell for any path not statically prerendered.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: false
		})
	}
};

export default config;
