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

	<h2>Registration</h2>
	<div class="card detail-grid">
		<div><div class="label">Structure Type</div><div class="value">{#if detail.registration.structure_type}<a href={`/towers?structureType=${encodeURIComponent(detail.registration.structure_type)}`}>{detail.registration.structure_type}</a>{:else}—{/if}</div></div>
		<div><div class="label">Status</div><div class="value">{#if detail.registration.status_code}<a href={`/towers?status=${detail.registration.status_code}`}>{detail.registration.status_code}</a>{:else}—{/if}</div></div>
		<div>
			<div class="label">Location</div>
			<div class="value">
				{#if detail.registration.structure_city}<a href={`/towers?city=${encodeURIComponent(detail.registration.structure_city)}`}>{detail.registration.structure_city}</a>,{/if}
				{#if detail.registration.structure_state_code}<a href={`/towers?state=${detail.registration.structure_state_code}`}>{detail.registration.structure_state_code}</a>{/if}
				{#if !detail.registration.structure_city && !detail.registration.structure_state_code}—{/if}
			</div>
		</div>
		<div><div class="label">Street Address</div><div class="value">{detail.registration.structure_street_address ?? '—'}</div></div>
		<div><div class="label">County</div><div class="value">{detail.registration.county_code ?? '—'}</div></div>
		<div><div class="label">ZIP</div><div class="value">{detail.registration.zip_code ?? '—'}</div></div>
		<div><div class="label">Height AGL (ft)</div><div class="value">{detail.registration.overall_height_above_ground ?? '—'}</div></div>
		<div><div class="label">Height AMSL (ft)</div><div class="value">{detail.registration.overall_height_amsl ?? '—'}</div></div>
		<div><div class="label">Ground Elevation</div><div class="value">{detail.registration.ground_elevation ?? '—'}</div></div>
		<div><div class="label">Application Purpose</div><div class="value">{detail.registration.application_purpose ?? '—'}</div></div>
		<div><div class="label">Previous Purpose</div><div class="value">{detail.registration.previous_purpose ?? '—'}</div></div>
		<div><div class="label">Date Entered</div><div class="value">{detail.registration.date_entered ?? '—'}</div></div>
		<div><div class="label">Date Received</div><div class="value">{detail.registration.date_received ?? '—'}</div></div>
		<div><div class="label">Date Issued</div><div class="value">{detail.registration.date_issued ?? '—'}</div></div>
		<div><div class="label">Date Constructed</div><div class="value">{detail.registration.date_constructed ?? '—'}</div></div>
		<div><div class="label">Date Dismantled</div><div class="value">{detail.registration.date_dismantled ?? '—'}</div></div>
		<div><div class="label">FAA Study #</div><div class="value">{detail.registration.faa_study_number ?? '—'}</div></div>
		<div><div class="label">FAA Determination Date</div><div class="value">{detail.registration.date_faa_determination_issued ?? '—'}</div></div>
		<div><div class="label">FAA Circular #</div><div class="value">{detail.registration.faa_circular_number ?? '—'}</div></div>
		<div><div class="label">Painting/Lighting</div><div class="value">{detail.registration.painting_and_lighting ?? '—'}</div></div>
		<div><div class="label">Proposed Marking/Lighting</div><div class="value">{detail.registration.proposed_marking_and_lighting ?? '—'}</div></div>
		<div><div class="label">NEPA Flag</div><div class="value">{detail.registration.nepa_flag ?? '—'}</div></div>
	</div>

	{#if detail.entities.length > 0}
		<h2>Owners / Contacts</h2>
		<div class="card">
			<table>
				<thead><tr><th>Entity</th><th>Type</th><th>FRN</th><th>Location</th><th>Phone</th><th>Contact</th></tr></thead>
				<tbody>
					{#each detail.entities as e}
						<tr>
							<td>{e.entity_name}</td>
							<td>{e.entity_type ?? '—'}</td>
							<td>{#if e.frn}<a href={`/identity/frn/${e.frn}`}>{e.frn}</a>{:else}—{/if}</td>
							<td>
								{#if e.city}<a href={`/towers?city=${encodeURIComponent(e.city)}`}>{e.city}</a>,{/if}
								{#if e.state}<a href={`/towers?state=${e.state}`}>{e.state}</a>{/if}
							</td>
							<td>{e.phone ?? '—'}</td>
							<td>{[e.first_name, e.mi, e.last_name, e.suffix].filter(Boolean).join(' ') || '—'}</td>
						</tr>
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
