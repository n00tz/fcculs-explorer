<script>
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';
	import { page as pageStore } from '$app/stores';

	let registrationNumber = '';
	let structureType = '';
	let city = '';
	let state = '';
	let statusCode = '';
	let heightMin = '';
	let heightMax = '';
	let constructedAfter = '';
	let constructedBefore = '';
	let page = 1;
	const pageSize = 25;

	let items = [];
	let total = 0;
	let loading = false;
	let error = '';

	function readFiltersFromUrl() {
		const params = $pageStore.url.searchParams;
		registrationNumber = params.get('registrationNumber') ?? '';
		structureType = params.get('structureType') ?? '';
		city = params.get('city') ?? '';
		state = params.get('state') ?? '';
		statusCode = params.get('status') ?? '';
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const data = await get('/towers', {
				registrationNumber: registrationNumber || undefined,
				structureType: structureType || undefined,
				city: city || undefined,
				state: state || undefined,
				status: statusCode || undefined,
				heightMin: heightMin || undefined,
				heightMax: heightMax || undefined,
				constructedAfter: constructedAfter || undefined,
				constructedBefore: constructedBefore || undefined,
				page,
				page_size: pageSize
			});
			items = data.items;
			total = data.total;
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function applyFilters() {
		page = 1;
		load();
	}

	function setFilter(field, value) {
		if (field === 'structureType') structureType = value ?? '';
		else if (field === 'status') statusCode = value ?? '';
		else if (field === 'city') city = value ?? '';
		else if (field === 'state') state = value ?? '';
		applyFilters();
	}

	function nextPage() {
		if (page * pageSize < total) {
			page += 1;
			load();
		}
	}
	function prevPage() {
		if (page > 1) {
			page -= 1;
			load();
		}
	}

	onMount(() => {
		readFiltersFromUrl();
		load();
	});
</script>

<svelte:head>
	<title>Browse Towers — FCC ULS Explorer</title>
</svelte:head>

<h1>Antenna Structure Registrations (Towers)</h1>

<div class="filters">
	<input placeholder="Registration # (partial)" bind:value={registrationNumber} />
	<input placeholder="Structure type (partial)" bind:value={structureType} />
	<input placeholder="City (partial)" bind:value={city} />
	<input placeholder="State" maxlength="2" bind:value={state} />
	<select bind:value={statusCode}>
		<option value="">Any status</option>
		<option value="C">Constructed</option>
		<option value="G">Granted</option>
		<option value="D">Dismantled</option>
	</select>
	<input placeholder="Min height (AGL, ft)" type="number" bind:value={heightMin} />
	<input placeholder="Max height (AGL, ft)" type="number" bind:value={heightMax} />
	<label class="filter-label">Constructed after <input type="date" bind:value={constructedAfter} /></label>
	<label class="filter-label">Constructed before <input type="date" bind:value={constructedBefore} /></label>
	<button on:click={applyFilters}>Apply filters</button>
</div>

{#if error}<p class="error">{error}</p>{/if}

<table>
	<thead>
		<tr>
			<th>Registration #</th>
			<th>Type</th>
			<th>Status</th>
			<th>Location</th>
			<th>Height (AGL)</th>
			<th>Constructed</th>
		</tr>
	</thead>
	<tbody>
		{#each items as row}
			<tr>
				<td><a href={`/towers/${row.registration_number}`}>{row.registration_number}</a></td>
				<td>
					{#if row.structure_type}
						<button class="pill-link" on:click={() => setFilter('structureType', row.structure_type)}>{row.structure_type}</button>
					{:else}—{/if}
				</td>
				<td>
					<button class="pill-link" on:click={() => setFilter('status', row.status_code)}>
						<span class="pill">{row.status_code ?? '—'}</span>
					</button>
				</td>
				<td>
					{#if row.structure_city}<button class="pill-link" on:click={() => setFilter('city', row.structure_city)}>{row.structure_city}</button>,{/if}
					{#if row.structure_state_code}<button class="pill-link" on:click={() => setFilter('state', row.structure_state_code)}>{row.structure_state_code}</button>{/if}
					{#if !row.structure_city && !row.structure_state_code}—{/if}
				</td>
				<td>{row.overall_height_above_ground ?? '—'}</td>
				<td>{row.date_constructed ?? '—'}</td>
			</tr>
		{/each}
	</tbody>
</table>

{#if loading}<p class="muted">Loading…</p>{/if}

<div class="pagination">
	<button class="secondary" disabled={page <= 1} on:click={prevPage}>← Previous</button>
	<span class="muted">Page {page} · {total} total</span>
	<button class="secondary" disabled={page * pageSize >= total} on:click={nextPage}>Next →</button>
</div>
