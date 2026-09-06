<script>
	import { page } from '$app/stores';
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';

	let detail = null;
	let error = '';
	let loading = true;
	let callSign = '';

	$: callSign = $page.params.callsign;

	async function load() {
		loading = true;
		error = '';
		detail = null;
		try {
			detail = await get(`/amateur/${callSign}`);
		} catch (e) {
			error = e.status === 404 ? `No record found for ${callSign}.` : e.message;
		} finally {
			loading = false;
		}
	}

	onMount(load);
	$: if (callSign) load();
</script>

<svelte:head>
	<title>{callSign} — FCC ULS Explorer</title>
</svelte:head>

{#if loading}
	<p class="muted">Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if detail}
	<h1>
		{detail.header.call_sign}
		<span class={`pill status-${detail.header.license_status}`}>{detail.header.license_status}</span>
	</h1>

	<div class="card detail-grid">
		<div><div class="label">Licensee</div><div class="value">{detail.entity?.entity_name ?? '—'}</div></div>
		<div><div class="label">Location</div><div class="value">{detail.entity ? `${detail.entity.city ?? ''}, ${detail.entity.state ?? ''}` : '—'}</div></div>
		<div><div class="label">FRN</div><div class="value">{detail.entity?.frn ?? '—'}</div></div>
		<div><div class="label">Operator Class</div><div class="value">{detail.amateur_specific?.operator_class ?? '—'}</div></div>
		<div><div class="label">Group Code</div><div class="value">{detail.amateur_specific?.group_code ?? '—'}</div></div>
		<div><div class="label">Trustee</div><div class="value">{detail.amateur_specific?.trustee_callsign ?? '—'}</div></div>
		<div><div class="label">Grant Date</div><div class="value">{detail.header.grant_date ?? '—'}</div></div>
		<div><div class="label">Expires</div><div class="value">{detail.header.expired_date ?? '—'}</div></div>
		<div><div class="label">ULS System ID</div><div class="value">{detail.header.unique_system_identifier}</div></div>
	</div>

	{#if detail.related_identities.length > 0}
		<h2>Related Identities <span class="muted">(same FRN)</span></h2>
		<div class="card">
			<table>
				<thead><tr><th>Type</th><th>Identifier</th><th>Name</th></tr></thead>
				<tbody>
					{#each detail.related_identities as rel}
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
		<p class="muted">No changes recorded yet. Watch this callsign to be alerted on future changes.</p>
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

	{#if detail.history.length > 0}
		<h2>License History</h2>
		<div class="card">
			<table>
				<thead><tr><th>Date</th><th>Code</th><th>Meaning</th></tr></thead>
				<tbody>
					{#each detail.history as h}
						<tr>
							<td>{h.log_date}</td>
							<td><code>{h.code}</code></td>
							<td>{h.code_description ?? ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}
