<script>
	import { page } from '$app/stores';
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';

	let frn = '';
	let data = null;
	let error = '';
	let loading = true;

	$: frn = $page.params.frn;

	async function load() {
		loading = true;
		error = '';
		data = null;
		try {
			data = await get(`/identity/frn/${frn}`);
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	onMount(load);
	$: if (frn) load();
</script>

<svelte:head>
	<title>FRN {frn} — FCC ULS Explorer</title>
</svelte:head>

<h1>FRN {frn}</h1>
<p class="muted">
	Every Amateur callsign and Tower registration on file with this FCC Registration Number — the
	broadest "everything tied to this licensee" view.
</p>

{#if loading}
	<p class="muted">Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if data}
	{#if data.members.length === 0}
		<p class="muted">No records found for this FRN.</p>
	{:else}
		<div class="card">
			<table>
				<thead><tr><th>Type</th><th>Identifier</th><th>Name</th></tr></thead>
				<tbody>
					{#each data.members as m}
						<tr>
							<td>{m.source}</td>
							<td>
								{#if m.source === 'amateur'}
									<a href={`/amateur/${m.subject_key}`}>{m.subject_key}</a>
								{:else}
									<a href={`/towers/${m.subject_key}`}>{m.subject_key}</a>
								{/if}
							</td>
							<td>{m.entity_name}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}
