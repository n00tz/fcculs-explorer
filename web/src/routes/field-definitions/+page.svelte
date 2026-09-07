<script>
	import { FIELD_HELP, CODE_MAPS } from '$lib/fieldDefs.js';

	// A human label for each field key, purely for organizing this
	// reference page -- not used elsewhere.
	const SECTIONS = [
		{
			title: 'Amateur Radio Licenses',
			fields: [
				['license_status', 'Status'],
				['radio_service_code', 'Radio Service Code'],
				['eligibility_rule_num', 'Eligibility Rule'],
				['entity_type', 'Entity Type'],
				['applicant_type_code', 'Applicant Type'],
				['entity_status_code', 'Licensee Status'],
				['operator_class', 'Operator Class'],
				['group_code', 'Group Code'],
				['region_code', 'Region Code'],
				['trustee_indicator', 'Trustee Indicator'],
				['vanity_relationship', 'Vanity Relationship'],
				['systematic_callsign_change', 'Systematic Callsign Change'],
				['vanity_callsign_change', 'Vanity Callsign Change']
			]
		},
		{
			title: 'Tower Structure Registrations',
			fields: [
				['structure_type', 'Structure Type'],
				['status_code', 'Status'],
				['nepa_flag', 'NEPA Flag'],
				['application_purpose', 'Application Purpose'],
				['previous_purpose', 'Previous Purpose'],
				['painting_and_lighting', 'Painting/Lighting'],
				['proposed_marking_and_lighting', 'Proposed Marking/Lighting'],
				['county_code', 'County Code']
			]
		},
		{
			// GMRS uses only the generic ULS HD/EN records, so every field
			// it shows is already covered by the shared section below.
			title: 'GMRS Licenses',
			fields: [
				['license_status', 'Status'],
				['radio_service_code', 'Radio Service Code'],
				['entity_type', 'Entity Type'],
				['applicant_type_code', 'Applicant Type']
			]
		},
		{
			title: 'Aircraft Radio Stations (Part 87)',
			fields: [
				['n_number', 'N-Number (tail number)'],
				['type_of_carrier', 'Type of Carrier'],
				['portable_indicator', 'Portable Indicator'],
				['fleet_indicator', 'Fleet Indicator'],
				['aircraft_count', 'Aircraft Count']
			]
		},
		{
			title: 'Ship Radio Stations (Part 80)',
			fields: [
				['type_of_authorization', 'Type of Authorization'],
				['general_class', 'General Class'],
				['special_class', 'Special Class'],
				['station_number', 'MMSI Number'],
				['ship_number', 'Official Number of Ship'],
				['ship_name', 'Ship Name'],
				['gross_tonnage', 'Gross Tonnage'],
				['ship_length', 'Ship Length'],
				['international_voyages', 'International Voyages'],
				['foreign_communications', 'Foreign Communications'],
				['radiotelegraph', 'Radiotelegraph Working Series'],
				['self_id_number', 'Sel Call Number'],
				['comsat_id_number', 'Sel Call — INMARSAT'],
				['working_freq_s1', 'Working Frequency'],
				['ship_type', 'Ship Type (exemption request)'],
				['voyage_description', 'Voyage Description']
			]
		}
	];

	// Map a FIELD_HELP key to the CODE_MAPS category actually used to
	// decode its values, where the names differ (see CodeValue usage on
	// the detail pages for the authoritative pairing).
	const CATEGORY_OVERRIDES = {
		status_code: 'status_code_tower',
		previous_purpose: 'application_purpose',
		// Ship class codes live under ship_-prefixed categories to avoid
		// colliding with other services' generic "class" fields.
		general_class: 'ship_general_class',
		special_class: 'ship_special_class',
		// Simple Y/N indicator fields all share one decode table.
		portable_indicator: 'yes_no',
		fleet_indicator: 'yes_no',
		international_voyages: 'yes_no',
		foreign_communications: 'yes_no'
	};

	function categoryFor(key) {
		return CATEGORY_OVERRIDES[key] ?? key;
	}
</script>

<svelte:head>
	<title>Field Definitions — FCC ULS Explorer</title>
</svelte:head>

<h1>Field Definitions</h1>
<p class="muted">
	Reference for abbreviated or coded fields shown across the site. Codes verified against FCC's
	own published ULS code definitions are noted as such in <code>web/src/lib/fieldDefs.js</code>;
	some fields (particularly Tower/ASR-specific codes) have no located official FCC decode table
	and are marked best-effort or not officially documented accordingly -- unmapped or unverified
	codes are always shown as-is rather than guessed.
</p>

{#each SECTIONS as section}
	<h2>{section.title}</h2>
	<div class="card">
		<table>
			<thead>
				<tr><th>Field</th><th>Meaning</th><th>Codes</th></tr>
			</thead>
			<tbody>
				{#each section.fields as [key, label]}
					{@const map = CODE_MAPS[categoryFor(key)]}
					<tr>
						<td>{label}</td>
						<td>{FIELD_HELP[key] ?? '—'}</td>
						<td>
							{#if map}
								<ul class="code-list">
									{#each Object.entries(map) as [code, desc]}
										<li><code>{code}</code> — {desc}</li>
									{/each}
								</ul>
							{:else}
								<span class="muted">No decode table available; shown as-is.</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/each}

<style>
	.code-list {
		margin: 0;
		padding-left: 1.1rem;
		font-size: 0.85rem;
	}
	.code-list li {
		margin-bottom: 0.15rem;
	}
	table td {
		vertical-align: top;
	}
</style>
