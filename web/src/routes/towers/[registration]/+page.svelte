<script>
	import { page } from '$app/stores';
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';

	let detail = null;
	let error = '';
	let loading = true;
	let registration = '';

	$: registration = $page.params.registration;

	async function load() {
		loading = true;
		error = '';
		detail = null;
		try {
			detail = await get(`/towers/${registration}`);
		} catch (e) {
			error = e.status === 404 ? `No record found for registration ${registration}.` : e.message;
		} finally {
			loading = false;
		}
	}

	onMount(load);
	$: if (registration) load();
</script>

<svelte:head>
	<title>Tower {registration} — FCC ULS Explorer</title>
</svelte:head>

{#if loading}
	<p class="muted">Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if detail}
	<h1>
		Tower {detail.registration.registration_number}
		<span class="pill">{detail.registration.status_code}</span>
	</h1>

	<div class="card detail-grid">
		<div><div class="label">Structure Type</div><div class="value">{detail.registration.structure_type ?? '—'}</div></div>
		<div><div class="label">Location</div><div class="value">{detail.registration.structure_city ?? ''}, {detail.registration.structure_state_code ?? ''}</div></div>
		<div><div class="label">Height AGL</div><div class="value">{detail.registration.overall_height_above_ground ?? '—'}</div></div>
		<div><div class="label">Height AMSL</div><div class="value">{detail.registration.overall_height_amsl ?? '—'}</div></div>
		<div><div class="label">Constructed</div><div class="value">{detail.registration.date_constructed ?? '—'}</div></div>
		<div><div class="label">FAA Study #</div><div class="value">{detail.registration.faa_study_number ?? '—'}</div></div>
	</div>

	{#if detail.entities.length > 0}
		<h2>Owners / Contacts</h2>
		<div class="card">
			<table>
				<thead><tr><th>Entity</th><th>FRN</th><th>Location</th></tr></thead>
				<tbody>
					{#each detail.entities as e}
						<tr><td>{e.entity_name}</td><td>{e.frn ?? '—'}</td><td>{e.city ?? ''}, {e.state ?? ''}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if detail.coordinates.length > 0}
		<h2>Coordinates</h2>
		<div class="card">
			<table>
				<thead><tr><th>Type</th><th>Latitude</th><th>Longitude</th></tr></thead>
				<tbody>
					{#each detail.coordinates as c}
						<tr>
							<td>{c.coordinate_type}</td>
							<td>{c.latitude_direction} {c.latitude_total_seconds}"</td>
							<td>{c.longitude_direction} {c.longitude_total_seconds}"</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if detail.related_by_site.length > 0}
		<h2>Other Towers at This Site</h2>
		<div class="card">
			<table>
				<thead><tr><th>Registration #</th><th>Location</th></tr></thead>
				<tbody>
					{#each detail.related_by_site as t}
						<tr><td><a href={`/towers/${t.registration_number}`}>{t.registration_number}</a></td><td>{t.structure_city ?? ''}, {t.structure_state_code ?? ''}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if detail.related_by_frn.length > 0}
		<h2>Related Identities <span class="muted">(same FRN)</span></h2>
		<div class="card">
			<table>
				<thead><tr><th>Type</th><th>Identifier</th><th>Name</th></tr></thead>
				<tbody>
					{#each detail.related_by_frn as rel}
						<tr>
							<td>{rel.source}</td>
							<td>
								{#if rel.source === 'amateur'}
									<a href={`/amateur/${rel.subject_key}`}>{rel.subject_key}</a>
								{:else}
									<a href={`/towers/${rel.subject_key}`}>{rel.subject_key}</a>
								{/if}
							</td>
							<td>{rel.entity_name}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<h2>Change History</h2>
	{#if detail.change_log.length === 0}
		<p class="muted">No changes recorded yet. Watch this registration number to be alerted on future changes.</p>
	{:else}
		<div class="card">
			<table>
				<thead><tr><th>Field</th><th>Old</th><th>New</th><th>Effective</th><th>Detected</th></tr></thead>
				<tbody>
					{#each detail.change_log as ev}
						<tr>
							<td>{ev.field_name}</td>
							<td>{ev.old_value ?? '(blank)'}</td>
							<td>{ev.new_value ?? '(blank)'}</td>
							<td>{ev.effective_date}</td>
							<td>{ev.detected_at}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}
