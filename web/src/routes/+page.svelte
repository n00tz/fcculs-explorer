<script>
	import { get } from '$lib/api.js';

	let query = '';
	let results = [];
	let loading = false;
	let error = '';
	let searched = false;
	let debounceTimer;

	function onInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(runSearch, 300);
	}

	async function runSearch() {
		if (query.trim().length < 2) {
			results = [];
			searched = false;
			return;
		}
		loading = true;
		error = '';
		try {
			const data = await get('/search', { q: query.trim(), limit: 25 });
			results = data.results;
			searched = true;
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function href(result) {
		if (result.result_type === 'amateur' || result.result_type === 'amateur_entity') {
			return `/amateur/${result.key}`;
		}
		return `/towers/${result.key}`;
	}

	function kindLabel(type) {
		return {
			amateur: 'Callsign',
			amateur_entity: 'Amateur Licensee',
			tower: 'Tower Registration',
			tower_entity: 'Tower Entity'
		}[type] ?? type;
	}
</script>

<svelte:head>
	<title>FCC ULS Explorer</title>
</svelte:head>

<h1>Find a callsign, tower, or licensee</h1>
<p class="muted">
	Search Amateur Radio Service licenses and Antenna Structure Registrations, then watch a
	callsign or ULS ID for changes via email, text, or webhook.
</p>

<div class="search-box">
	<input
		type="search"
		placeholder="Callsign, ASR registration number, or name (e.g. K0WNL)"
		bind:value={query}
		on:input={onInput}
		autofocus
	/>
	<button on:click={runSearch}>Search</button>
</div>

{#if loading}
	<p class="muted">Searching…</p>
{/if}
{#if error}
	<p class="error">{error}</p>
{/if}

{#if searched && !loading}
	{#if results.length === 0}
		<p class="muted">No matches for "{query}".</p>
	{:else}
		<div class="grid" style="margin-top: 1rem;">
			{#each results as r}
				<a class="card" href={href(r)} style="display:block;">
					<span class="pill">{kindLabel(r.result_type)}</span>
					<strong style="margin-left: 0.5rem;">{r.label}</strong>
					{#if r.label !== r.key}
						<span class="muted"> ({r.key})</span>
					{/if}
				</a>
			{/each}
		</div>
	{/if}
{/if}
