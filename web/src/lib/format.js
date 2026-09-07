// Locale is pinned rather than left to the environment. The web app builds
// with adapter-static, so markup is prerendered under Node and hydrated in
// the browser; an unpinned toLocaleString() can format differently in those
// two places and produce a hydration mismatch.
export function formatCount(n) {
	return Number(n).toLocaleString('en-US');
}
