<script>
	import { get } from '$lib/api.js';
	import HeroGraphic from '$lib/HeroGraphic.svelte';

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

<div class="hero">
	<div class="hero-text">
		<h1>A fast, modern way to browse the FCC ULS — and know the moment it changes</h1>
		<p class="muted">
			Search and cross-link Amateur Radio Service licenses and Antenna Structure Registrations,
			traverse the relationships behind a callsign or FRN (previous callsigns, club trustees,
			shared tower sites), and watch anything that matters to you — no password required. Sign
			in with just an email and get alerts by email, SMS, or webhook the moment a daily FCC
			update touches your callsign, FRN, or tower.
		</p>
	</div>
	<HeroGraphic />
</div>

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

<div class="feature-grid">
	<div class="card feature-card">
		<h3>🔎 Browse &amp; search</h3>
		<p>
			Paginated Amateur Radio and Tower Structure tables with click-to-sort columns and
			partial-match filters on every displayed field — city, state, name, callsign, and more.
		</p>
	</div>
	<div class="card feature-card">
		<h3>🕸️ Discover related identities</h3>
		<p>
			Detail pages cross-link by FRN, licensee, and site so you can traverse the full history
			behind a callsign — previous callsigns tied to the same FRN, club trustees, and towers
			sharing a location — without falling back to a search box every time.
		</p>
	</div>
	<div class="card feature-card">
		<h3>🔔 Get notified — no password required</h3>
		<p>
			Sign in with a one-time magic link emailed to you, then watch a callsign, ULS/ASR
			registration number, or FRN (even before you've been assigned a callsign) for changes.
			Choose email, SMS via your carrier's gateway, or a webhook (ntfy, Discord, Telegram,
			Matrix, or generic) — and send yourself a test alert first to confirm it arrives.
		</p>
	</div>
</div>
