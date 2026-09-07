<script>
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import { gfmHeadingId } from 'marked-gfm-heading-id';

	// The site's Help page renders the exact same docs/user-guide.md that
	// ships in the repo -- web/Dockerfile copies it in as a static asset
	// at build time (see compose.yaml/deploy/update.sh's --build-context
	// wiring) so there is one source of truth, not a duplicated copy
	// hand-maintained inside the web app. The gfmHeadingId extension gives
	// headings real "id" attributes so the guide's own "Contents" list of
	// #anchor links still works once rendered here.
	marked.use(gfmHeadingId());

	let html = '';
	let loadError = false;

	onMount(async () => {
		try {
			const res = await fetch('/user-guide.md');
			if (!res.ok) throw new Error(`status ${res.status}`);
			const markdown = await res.text();
			html = marked.parse(markdown, { gfm: true });
		} catch (err) {
			loadError = true;
		}
	});
</script>

<svelte:head>
	<title>Help &amp; User Guide — FCC ULS Explorer</title>
</svelte:head>

{#if loadError}
	<div class="card">
		<h1>Help</h1>
		<p>
			Sorry, the user guide couldn't be loaded right now. Try reloading the page, or see
			<code>docs/user-guide.md</code> in the project repository.
		</p>
	</div>
{:else if html}
	<div class="markdown-body">
		{@html html}
	</div>
{:else}
	<p class="muted">Loading help…</p>
{/if}
