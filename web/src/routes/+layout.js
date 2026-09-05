// The whole app runs as a client-rendered SPA (see svelte.config.js comment)
// because detail pages have dynamic route params that can't be prerendered
// and there is no Node server at runtime in the static-file deployment.
export const ssr = false;
export const prerender = false;
