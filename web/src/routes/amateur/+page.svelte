<script>
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';
	import { page as pageStore } from '$app/stores';

	let callsign = '';
	let name = '';
	let city = '';
	let state = '';
	let statusCode = '';
	let operatorClass = '';
	let page = 1;
	const pageSize = 25;

	let items = [];
	let total = 0;
	let loading = false;
	let error = '';

	// Support crosslinks from detail pages (e.g. clicking a state/class on a
	// callsign's detail page) by pre-filling filters from the URL's query
	// params on first load.
	function readFiltersFromUrl() {
		const params = $pageStore.url.searchParams;
		callsign = params.get('callsign') ?? '';
		name = params.get('name') ?? '';
		city = params.get('city') ?? '';
		state = params.get('state') ?? '';
		statusCode = params.get('status') ?? '';
		operatorClass = params.get('class') ?? '';
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const data = await get('/amateur', {
				callsign: callsign || undefined,
				name: name || undefined,
				city: city || undefined,
				state: state || undefined,
				status: statusCode || undefined,
				class: operatorClass || undefined,
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
		if (field === 'status') statusCode = value ?? '';
		else if (field === 'class') operatorClass = value ?? '';
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
	<title>Browse Amateur Licenses — FCC ULS Explorer</title>
</svelte:head>

<h1>Amateur Radio Licenses</h1>

<div class="filters">
	<input placeholder="Callsign (partial)" bind:value={callsign} />
	<input placeholder="Licensee name (partial)" bind:value={name} />
	<input placeholder="City (partial)" bind:value={city} />
	<input placeholder="State" maxlength="2" bind:value={state} />
	<select bind:value={statusCode}>
		<option value="">Any status</option>
		<option value="A">Active</option>
		<option value="E">Expired</option>
		<option value="C">Cancelled</option>
		<option value="T">Terminated</option>
	</select>
	<input placeholder="Operator class (e.g. G)" maxlength="2" bind:value={operatorClass} />
	<button on:click={applyFilters}>Apply filters</button>
</div>

{#if error}<p class="error">{error}</p>{/if}

<table>
	<thead>
		<tr>
			<th>Callsign</th>
			<th>Status</th>
			<th>Class</th>
			<th>Licensee</th>
			<th>Location</th>
			<th>Grant</th>
			<th>Expires</th>
		</tr>
	</thead>
	<tbody>
		{#each items as row}
			<tr>
				<td><a href={`/amateur/${row.call_sign}`}>{row.call_sign}</a></td>
				<td>
					<button class="pill-link" on:click={() => setFilter('status', row.license_status)}>
						<span class={`pill status-${row.license_status}`}>{row.license_status}</span>
					</button>
				</td>
				<td>
					{#if row.operator_class}
						<button class="pill-link" on:click={() => setFilter('class', row.operator_class)}>{row.operator_class}</button>
					{:else}—{/if}
				</td>
				<td>{row.entity_name ?? '—'}</td>
				<td>
					{#if row.city}<button class="pill-link" on:click={() => setFilter('city', row.city)}>{row.city}</button>,{/if}
					{#if row.state}<button class="pill-link" on:click={() => setFilter('state', row.state)}>{row.state}</button>{/if}
					{#if !row.city && !row.state}—{/if}
				</td>
				<td>{row.grant_date ?? '—'}</td>
				<td>{row.expired_date ?? '—'}</td>
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
