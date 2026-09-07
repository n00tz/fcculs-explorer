<script>
	/**
	 * Generic browse table for a personal radio service (GMRS / Aircraft /
	 * Ship), driven entirely by a config from lib/personalServices.js.
	 *
	 * Deliberately one component rather than three near-identical pages, so
	 * every service gets identical sorting, filtering, pagination, tooltips
	 * and code definitions by construction. See personalServices.js for the
	 * full rationale.
	 */
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';
	import { page as pageStore } from '$app/stores';
	import { fieldHelp, describeCode } from '$lib/fieldDefs.js';
	import CodeValue from '$lib/CodeValue.svelte';

	export let service;

	let filterValues = {};
	let page = 1;
	const pageSize = 25;
	let sortColumn = 'call_sign';
	let sortOrder = 'asc';

	let items = [];
	let total = 0;
	let loading = false;
	let error = '';

	// Pre-fill filters from the URL so crosslinks from detail pages (e.g.
	// clicking a state) work the same way they do for Amateur/Tower.
	function readFiltersFromUrl() {
		const params = $pageStore.url.searchParams;
		const next = {};
		for (const filter of service.filters) {
			next[filter.key] = params.get(filter.key) ?? '';
		}
		filterValues = next;
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const params = { sort: sortColumn, order: sortOrder, page, page_size: pageSize };
			for (const [key, value] of Object.entries(filterValues)) {
				if (value) params[key] = value;
			}
			const data = await get(service.apiPath, params);
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

	function setFilter(key, value) {
		filterValues = { ...filterValues, [key]: value ?? '' };
		applyFilters();
	}

	function toggleSort(column) {
		if (!column) return;
		if (sortColumn === column) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortColumn = column;
			sortOrder = 'asc';
		}
		page = 1;
		load();
	}

	function sortIndicator(column) {
		if (sortColumn !== column) return '';
		return sortOrder === 'asc' ? ' \u25b2' : ' \u25bc';
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

	// `service` changes when navigating between /gmrs and /ship without a
	// full page load, so reset paging/filters and refetch.
	let currentService = null;
	$: if (service && service.name !== currentService) {
		currentService = service.name;
		page = 1;
		sortColumn = 'call_sign';
		sortOrder = 'asc';
		readFiltersFromUrl();
		load();
	}

	onMount(() => {
		readFiltersFromUrl();
		load();
	});
</script>

<svelte:head>
	<title>Browse {service.title} — FCC ULS Explorer</title>
</svelte:head>

<h1>{service.heading}</h1>
<p class="muted">{service.blurb}</p>

<div class="filters">
	{#each service.filters as filter (filter.key)}
		{#if filter.kind === 'select'}
			<select
				value={filterValues[filter.key] ?? ''}
				on:change={(e) => setFilter(filter.key, e.currentTarget.value)}
			>
				{#each filter.options as option}
					<option value={option.value}>{option.label}</option>
				{/each}
			</select>
		{:else}
			<input
				placeholder={filter.placeholder}
				maxlength={filter.maxlength}
				value={filterValues[filter.key] ?? ''}
				on:input={(e) => (filterValues[filter.key] = e.currentTarget.value)}
				on:keydown={(e) => e.key === 'Enter' && applyFilters()}
			/>
		{/if}
	{/each}
	<button on:click={applyFilters}>Apply filters</button>
</div>

{#if error}<p class="error">{error}</p>{/if}

<table>
	<thead>
		<tr>
			{#each service.columns as col (col.key)}
				<th>
					{#if col.sort}
						<button
							class="sort-th"
							title={fieldHelp(col.help ?? col.category ?? col.key)}
							on:click={() => toggleSort(col.sort)}
						>{col.label}{sortIndicator(col.sort)}</button>
					{:else}
						<span title={fieldHelp(col.help ?? col.category ?? col.key)}>{col.label}</span>
					{/if}
				</th>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#each items as row}
			<tr>
				{#each service.columns as col (col.key)}
					<td>
						{#if col.kind === 'callsign'}
							<a href={`${service.route}/${row.call_sign}`}>{row.call_sign}</a>
						{:else if col.kind === 'status'}
							<button
								class="pill-link"
								title={describeCode('license_status', row.license_status)}
								on:click={() => setFilter('status', row.license_status)}
							>
								<span class={`pill status-${row.license_status}`}>{row.license_status}</span>
							</button>
						{:else if col.kind === 'location'}
							{#if row.city}<button class="pill-link" on:click={() => setFilter('city', row.city)}>{row.city}</button>,{/if}
							{#if row.state}<button class="pill-link" on:click={() => setFilter('state', row.state)}>{row.state}</button>{/if}
							{#if !row.city && !row.state}—{/if}
						{:else if col.kind === 'code'}
							<CodeValue category={col.category} code={row[col.key]} />
						{:else}
							{row[col.key] ?? '—'}
						{/if}
					</td>
				{/each}
			</tr>
		{/each}
	</tbody>
</table>

{#if loading}<p class="muted">Loading…</p>{/if}
{#if !loading && items.length === 0}<p class="muted">No matching licences found.</p>{/if}

<div class="pagination">
	<button class="secondary" disabled={page <= 1} on:click={prevPage}>← Previous</button>
	<span class="muted">Page {page} · {total} total</span>
	<button class="secondary" disabled={page * pageSize >= total} on:click={nextPage}>Next →</button>
</div>
