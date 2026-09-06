<script>
	import { page } from '$app/stores';
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';
	import { user } from '$lib/auth.js';

	let detail = null;
	let error = '';
	let loading = true;
	let callSign = '';

	function watchLink(subjectType, value) {
		return `/watches?subject_type=${encodeURIComponent(subjectType)}&subject_value=${encodeURIComponent(value)}`;
	}

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
		{#if $user}
			<a class="watch-link" href={watchLink('callsign', detail.header.call_sign)}>🔔 Watch this callsign</a>
		{/if}
	</h1>

	<h2>License</h2>
	<div class="card detail-grid">
		<div><div class="label">Status</div><div class="value">{#if detail.header.license_status}<a href={`/amateur?status=${detail.header.license_status}`}>{detail.header.license_status}</a>{:else}—{/if}</div></div>
		<div><div class="label">Radio Service Code</div><div class="value">{detail.header.radio_service_code ?? '—'}</div></div>
		<div><div class="label">ULS File Number</div><div class="value">{detail.header.uls_file_number ?? '—'}</div></div>
		<div><div class="label">ULS System ID</div><div class="value">{detail.header.unique_system_identifier}</div></div>
		<div><div class="label">Grant Date</div><div class="value">{detail.header.grant_date ?? '—'}</div></div>
		<div><div class="label">Expires</div><div class="value">{detail.header.expired_date ?? '—'}</div></div>
		<div><div class="label">Effective Date</div><div class="value">{detail.header.effective_date ?? '—'}</div></div>
		<div><div class="label">Last Action Date</div><div class="value">{detail.header.last_action_date ?? '—'}</div></div>
		<div><div class="label">Cancellation Date</div><div class="value">{detail.header.cancellation_date ?? '—'}</div></div>
		<div><div class="label">Eligibility Rule</div><div class="value">{detail.header.eligibility_rule_num ?? '—'}</div></div>
	</div>

	<h2>Licensee</h2>
	<div class="card detail-grid">
		<div><div class="label">Licensee / Entity</div><div class="value">{detail.entity?.entity_name ?? '—'}</div></div>
		<div><div class="label">Contact Name</div><div class="value">{[detail.entity?.first_name, detail.entity?.mi, detail.entity?.last_name, detail.entity?.suffix].filter(Boolean).join(' ') || '—'}</div></div>
		<div><div class="label">FRN</div><div class="value">{#if detail.entity?.frn}<a href={`/identity/frn/${detail.entity.frn}`}>{detail.entity.frn}</a>{#if $user}<a class="watch-link" href={watchLink('frn', detail.entity.frn)}>🔔 Watch this FRN</a>{/if}{:else}—{/if}</div></div>
		<div><div class="label">Entity Type</div><div class="value">{detail.entity?.entity_type ?? '—'}</div></div>
		<div><div class="label">Applicant Type</div><div class="value">{detail.entity?.applicant_type_code ?? '—'}</div></div>
		<div><div class="label">Street Address</div><div class="value">{[detail.entity?.street_address, detail.entity?.po_box, detail.entity?.attention_line].filter(Boolean).join(', ') || '—'}</div></div>
		<div>
			<div class="label">Location</div>
			<div class="value">
				{#if detail.entity?.city}<a href={`/amateur?city=${encodeURIComponent(detail.entity.city)}`}>{detail.entity.city}</a>,{/if}
				{#if detail.entity?.state}<a href={`/amateur?state=${detail.entity.state}`}>{detail.entity.state}</a>{/if}
				{#if !detail.entity?.city && !detail.entity?.state}—{/if}
				{detail.entity?.zip_code ?? ''}
			</div>
		</div>
		<div><div class="label">Phone</div><div class="value">{detail.entity?.phone ?? '—'}</div></div>
		<div><div class="label">Fax</div><div class="value">{detail.entity?.fax ?? '—'}</div></div>
		<div><div class="label">Email</div><div class="value">{detail.entity?.email ?? '—'}</div></div>
		<div><div class="label">Status</div><div class="value">{detail.entity?.status_code ?? '—'} {detail.entity?.status_date ? `(${detail.entity.status_date})` : ''}</div></div>
	</div>

	<h2>Amateur Details</h2>
	<div class="card detail-grid">
		<div><div class="label">Operator Class</div><div class="value">{#if detail.amateur_specific?.operator_class}<a href={`/amateur?class=${detail.amateur_specific.operator_class}`}>{detail.amateur_specific.operator_class}</a>{:else}—{/if}</div></div>
		<div><div class="label">Group Code</div><div class="value">{detail.amateur_specific?.group_code ?? '—'}</div></div>
		<div><div class="label">Region Code</div><div class="value">{detail.amateur_specific?.region_code ?? '—'}</div></div>
		<div>
			<div class="label">Trustee</div>
			<div class="value">
				{#if detail.amateur_specific?.trustee_callsign}
					<a href={`/amateur/${detail.amateur_specific.trustee_callsign}`}>{detail.amateur_specific.trustee_callsign}</a>
					{detail.amateur_specific.trustee_name ? `(${detail.amateur_specific.trustee_name})` : ''}
				{:else}
					—
				{/if}
			</div>
		</div>
		<div><div class="label">Trustee Indicator</div><div class="value">{detail.amateur_specific?.trustee_indicator ?? '—'}</div></div>
		<div>
			<div class="label">Previous Callsign</div>
			<div class="value">
				{#if detail.amateur_specific?.previous_callsign}
					<a href={`/amateur/${detail.amateur_specific.previous_callsign}`}>{detail.amateur_specific.previous_callsign}</a>
				{:else}
					—
				{/if}
				{detail.amateur_specific?.previous_operator_class ? `(class ${detail.amateur_specific.previous_operator_class})` : ''}
			</div>
		</div>
		<div><div class="label">Vanity Relationship</div><div class="value">{detail.amateur_specific?.vanity_relationship ?? '—'}</div></div>
		<div><div class="label">Systematic Callsign Change</div><div class="value">{detail.amateur_specific?.systematic_callsign_change ?? '—'}</div></div>
		<div><div class="label">Vanity Callsign Change</div><div class="value">{detail.amateur_specific?.vanity_callsign_change ?? '—'}</div></div>
	</div>

	{#if detail.related_identities.length > 0}
		<h2>
			Related Identities <span class="muted">(same FRN)</span>
			{#if detail.entity?.frn}<a href={`/identity/frn/${detail.entity.frn}`} class="muted">view all →</a>{/if}
		</h2>
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
