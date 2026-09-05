<script>
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';

	let state = '';
	let statusCode = '';
	let operatorClass = '';
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
			const data = await get('/amateur', {
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
	<title>Browse Amateur Licenses — FCC ULS Explorer</title>
</svelte:head>

<h1>Amateur Radio Licenses</h1>

<div class="filters">
	<input placeholder="State (e.g. KS)" maxlength="2" bind:value={state} />
	<select bind:value={statusCode}>
		<option value="">Any status</option>
		<option value="A">Active</option>
		<option value="E">Expired</option>
		<option value="C">Cancelled</option>
	</select>
	<input placeholder="Operator class (e.g. E)" maxlength="2" bind:value={operatorClass} />
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
				<td><span class={`pill status-${row.license_status}`}>{row.license_status}</span></td>
				<td>{row.operator_class ?? '—'}</td>
				<td>{row.entity_name ?? '—'}</td>
				<td>{row.city ? `${row.city}, ${row.state}` : row.state ?? '—'}</td>
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
