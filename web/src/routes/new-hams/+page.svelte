<script>
	import { get } from '$lib/api.js';
	import { describeCode, fieldHelp } from '$lib/fieldDefs.js';
	import Pagination from '$lib/Pagination.svelte';
	import { formatCount } from '$lib/format.js';
	import { onMount } from 'svelte';

	let type = '';
	let page = 1;
	const pageSize = 25;

	let items = [];
	let total = 0;
	let totalIndividuals = 0;
	let totalClubs = 0;
	let loading = true;
	let error = '';

	async function load() {
		loading = true;
		error = '';
		try {
			const data = await get('/new-hams', {
				type: type || undefined,
				page,
				page_size: pageSize
			});
			items = data.items;
			total = data.total;
			totalIndividuals = data.total_individuals;
			totalClubs = data.total_clubs;
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function applyFilter() {
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
	<title>New Hams — FCC ULS Explorer</title>
</svelte:head>

<h1>🎉 New Hams</h1>
<p class="muted">
	Every amateur radio operator and club station granted their very first callsign in the last
	10 days, as reported in the FCC's daily ULS updates. This list only shows first-ever grants —
	not renewals, vanity changes, or additional callsigns for an already-licensed operator.
</p>

<div class="filters">
	<select bind:value={type} on:change={applyFilter}>
		<option value="">All</option>
		<option value="individual">Individual</option>
		<option value="club">Club</option>
	</select>
</div>

{#if error}<p class="error">{error}</p>{/if}

<p class="muted">
	<strong>{formatCount(totalIndividuals)}</strong> new amateur radio operators licensed ·
	<strong>{formatCount(totalClubs)}</strong> new club stations
	<span class="muted">(last 10 days)</span>
</p>

<table>
	<thead>
		<tr>
			<th>Callsign</th>
			<th>Name</th>
			<th>Type</th>
			<th title={fieldHelp('operator_class')}>Class</th>
			<th>City/State</th>
			<th>Grant Date</th>
		</tr>
	</thead>
	<tbody>
		{#each items as row}
			<tr>
				<td><a href={`/amateur/${row.call_sign}`}>{row.call_sign}</a></td>
				<td>{row.name ?? '—'}</td>
				<td><span class={`pill type-${row.applicant_type}`}>{row.applicant_type === 'club' ? 'Club' : 'Individual'}</span></td>
				<td>
					{#if row.operator_class}
						<span class={`pill opclass-${row.operator_class}`} title={`Operator class ${row.operator_class} — ${describeCode('operator_class', row.operator_class) ?? 'not documented'}`}>
							{describeCode('operator_class', row.operator_class) ?? row.operator_class}
						</span>
					{:else}—{/if}
				</td>
				<td>{[row.city, row.state].filter(Boolean).join(', ') || '—'}</td>
				<td>{row.grant_date ?? '—'}</td>
			</tr>
		{/each}
	</tbody>
</table>

{#if loading}<p class="muted">Loading…</p>{/if}

<Pagination {page} {pageSize} {total} {loading} onPrev={prevPage} onNext={nextPage} />
