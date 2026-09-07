<script>
	/**
	 * Generic detail page for a personal radio service (GMRS / Aircraft /
	 * Ship), driven by a config from lib/personalServices.js.
	 *
	 * Renders the same blocks Amateur does -- licence, licensee, service
	 * specifics, related identities, change history and licence history --
	 * with the same tooltips, code definitions and watch links, so no
	 * service is a second-class citizen. See personalServices.js.
	 */
	import { page } from '$app/stores';
	import { get } from '$lib/api.js';
	import { onMount } from 'svelte';
	import { user } from '$lib/auth.js';
	import CodeValue from '$lib/CodeValue.svelte';
	import CodeHint from '$lib/CodeHint.svelte';
	import { fieldHelp } from '$lib/fieldDefs.js';
	import { serviceRoute } from '$lib/personalServices.js';

	export let service;

	let detail = null;
	let error = '';
	let loading = true;
	let callSign = '';

	function watchLink(subjectType, value) {
		// Scope the watch to this service by default: someone viewing their
		// GMRS licence almost certainly wants GMRS alerts. They can widen it
		// on the watches page.
		return (
			`/watches?subject_type=${encodeURIComponent(subjectType)}` +
			`&subject_value=${encodeURIComponent(value)}&service=${encodeURIComponent(service.name)}`
		);
	}

	$: callSign = $page.params.callsign;

	async function load() {
		loading = true;
		error = '';
		detail = null;
		try {
			detail = await get(`${service.apiPath}/${callSign}`);
		} catch (e) {
			error = e.status === 404 ? `No ${service.label} record found for ${callSign}.` : e.message;
		} finally {
			loading = false;
		}
	}

	onMount(load);
	$: if (callSign && service) load();

	/** Join FCC's sequence-split voyage rows back into one readable text. */
	function joinedText(rows, field) {
		if (!rows || rows.length === 0) return '';
		return rows
			.map((row) => (row[field] ?? '').trim())
			.filter(Boolean)
			.join(' ');
	}

	function contactName(entity) {
		return (
			[entity?.first_name, entity?.mi, entity?.last_name, entity?.suffix]
				.filter(Boolean)
				.join(' ') || '—'
		);
	}
</script>

<svelte:head>
	<title>{callSign} — {service.label} — FCC ULS Explorer</title>
</svelte:head>

{#if loading}
	<p class="muted">Loading…</p>
{:else if error}
	<p class="error">{error}</p>
{:else if detail}
	<h1>
		{detail.header.call_sign}
		<span class={`pill status-${detail.header.license_status}`}>{detail.header.license_status}</span>
		<span class="muted">{service.label}</span>
		{#if $user}
			<a class="watch-link" href={watchLink('callsign', detail.header.call_sign)}>🔔 Watch this callsign</a>
		{/if}
	</h1>

	{#each service.detailSections as section (section.title)}
		{#if section.kind === 'entity'}
			<h2>{section.title}</h2>
			<div class="card detail-grid">
				<div><div class="label">Licensee / Entity</div><div class="value">{detail.entity?.entity_name ?? '—'}</div></div>
				<div><div class="label">Contact Name</div><div class="value">{contactName(detail.entity)}</div></div>
				<div>
					<div class="label">FRN</div>
					<div class="value">
						{#if detail.entity?.frn}
							<a href={`/identity/frn/${detail.entity.frn}`}>{detail.entity.frn}</a>
							{#if $user}<a class="watch-link" href={watchLink('frn', detail.entity.frn)}>🔔 Watch this FRN</a>{/if}
						{:else}—{/if}
					</div>
				</div>
				<div><div class="label">Entity Type <span class="hint" title={fieldHelp('entity_type')}>?</span></div><div class="value"><CodeValue category="entity_type" code={detail.entity?.entity_type} /></div></div>
				<div><div class="label">Applicant Type <span class="hint" title={fieldHelp('applicant_type_code')}>?</span></div><div class="value"><CodeValue category="applicant_type_code" code={detail.entity?.applicant_type_code} /></div></div>
				<div><div class="label">Street Address</div><div class="value">{[detail.entity?.street_address, detail.entity?.po_box, detail.entity?.attention_line].filter(Boolean).join(', ') || '—'}</div></div>
				<div>
					<div class="label">Location</div>
					<div class="value">
						{#if detail.entity?.city}<a href={`${service.route}?city=${encodeURIComponent(detail.entity.city)}`}>{detail.entity.city}</a>,{/if}
						{#if detail.entity?.state}<a href={`${service.route}?state=${detail.entity.state}`}>{detail.entity.state}</a>{/if}
						{#if !detail.entity?.city && !detail.entity?.state}—{/if}
						{detail.entity?.zip_code ?? ''}
					</div>
				</div>
				<div><div class="label">Phone</div><div class="value">{detail.entity?.phone ?? '—'}</div></div>
				<div><div class="label">Email</div><div class="value">{detail.entity?.email ?? '—'}</div></div>
				<div><div class="label">Status <span class="hint" title={fieldHelp('entity_status_code')}>?</span></div><div class="value">{#if detail.entity?.status_code}{detail.entity.status_code} <CodeHint category="entity_status_code" code={detail.entity.status_code} />{:else}Active{/if} {detail.entity?.status_date ? `(${detail.entity.status_date})` : ''}</div></div>
			</div>
		{:else if section.kind === 'joined_text'}
			{#if joinedText(detail[section.source], section.joinField)}
				<h2>{section.title}</h2>
				<div class="card">
					<p>{joinedText(detail[section.source], section.joinField)}</p>
				</div>
			{/if}
		{:else if detail[section.source]}
			<h2>{section.title}</h2>
			<div class="card detail-grid">
				{#each section.fields as field (field.key)}
					<div>
						<div class="label">
							{field.label}
							{#if fieldHelp(field.key)}<span class="hint" title={fieldHelp(field.key)}>?</span>{/if}
						</div>
						<div class="value">
							{#if field.category}
								<CodeValue category={field.category} code={detail[section.source][field.key]} />
							{:else}
								{detail[section.source][field.key] ?? '—'}
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/each}

	{#if detail.related_identities.length > 0}
		<h2>
			Related Identities <span class="muted">(same FRN)</span>
			{#if detail.entity?.frn}<a href={`/identity/frn/${detail.entity.frn}`} class="muted">view all →</a>{/if}
		</h2>
		<p class="muted">
			Other FCC licences and tower registrations held under this same FRN — including
			any Amateur Radio licence.
		</p>
		<div class="card">
			<table>
				<thead><tr><th>Type</th><th>Identifier</th><th>Name</th></tr></thead>
				<tbody>
					{#each detail.related_identities as rel}
						<tr>
							<td>{rel.source}</td>
							<td>
								{#if serviceRoute(rel.source, rel.subject_key)}
									<a href={serviceRoute(rel.source, rel.subject_key)}>{rel.subject_key}</a>
								{:else}
									{rel.subject_key}
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
