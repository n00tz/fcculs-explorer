<script>
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';

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

	onMount(load);
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
				<td>{row.structure_type ?? '—'}</td>
				<td><span class="pill">{row.status_code ?? '—'}</span></td>
				<td>{row.structure_city ? `${row.structure_city}, ${row.structure_state_code}` : row.structure_state_code ?? '—'}</td>
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
