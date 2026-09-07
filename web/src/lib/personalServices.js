/**
 * Display configuration for the personal radio services that share the
 * generic ULS record layout: GMRS, Aircraft (Part 87) and Ship (Part 80).
 *
 * This mirrors the API's own config-driven router factory
 * (api/app/routers/personal_services.py). The reason is the same on both
 * sides: the explicit goal of adding these services was that their users
 * should not be second-class citizens next to Amateur, and the surest way
 * to guarantee that is to make parity structural. There is ONE browse
 * component and ONE detail component; every service automatically gets the
 * same sorting, filtering, tooltips, code definitions, watch links and
 * cross-service identity grouping, because there is only one implementation
 * of each. Adding a fourth service is an entry in this file, not a new set
 * of pages to keep in sync.
 *
 * Every coded/abbreviated column below names a `category` from
 * fieldDefs.js, so it renders with a definition (inline parenthetical when
 * short, tooltip when long) exactly as Amateur and Tower fields do. That is
 * a project-wide standard, not a per-page choice.
 */

// Status options shared by every ULS service (the HD record's
// license_status is a generic ULS field, not an Amateur-specific one).
const STATUS_OPTIONS = [
	{ value: '', label: 'Any status' },
	{ value: 'A', label: 'Active' },
	{ value: 'E', label: 'Expired' },
	{ value: 'C', label: 'Cancelled' },
	{ value: 'T', label: 'Terminated' }
];

// Filters every service supports, because they come from the shared
// HD/EN records.
const COMMON_FILTERS = [
	{ key: 'callsign', placeholder: 'Callsign (partial)' },
	{ key: 'name', placeholder: 'Licensee name (partial)' },
	{ key: 'city', placeholder: 'City (partial)' },
	{ key: 'state', placeholder: 'State', maxlength: 2 },
	{ key: 'status', kind: 'select', options: STATUS_OPTIONS }
];

// Columns every service shows. Service-specific columns are spliced in
// after the callsign/status pair.
const COMMON_TAIL_COLUMNS = [
	{ key: 'entity_name', label: 'Licensee', sort: 'entity_name' },
	{ key: 'location', label: 'Location', sort: 'city', kind: 'location' },
	{ key: 'grant_date', label: 'Grant', sort: 'grant_date' },
	{ key: 'expired_date', label: 'Expires', sort: 'expired_date' }
];

const COMMON_HEAD_COLUMNS = [
	{ key: 'call_sign', label: 'Callsign', sort: 'call_sign', kind: 'callsign' },
	{ key: 'license_status', label: 'Status', sort: 'license_status', kind: 'status' }
];

// The License and Licensee blocks are identical across services because
// the underlying HD and EN records are byte-identical FCC record types.
const LICENSE_SECTION = {
	source: 'header',
	title: 'License',
	fields: [
		{ key: 'license_status', label: 'Status', category: 'license_status' },
		{ key: 'radio_service_code', label: 'Radio Service Code', category: 'radio_service_code' },
		{ key: 'uls_file_number', label: 'ULS File Number' },
		{ key: 'unique_system_identifier', label: 'ULS System ID' },
		{ key: 'grant_date', label: 'Grant Date' },
		{ key: 'expired_date', label: 'Expires' },
		{ key: 'effective_date', label: 'Effective Date' },
		{ key: 'last_action_date', label: 'Last Action Date' },
		{ key: 'cancellation_date', label: 'Cancellation Date' }
	]
};

const LICENSEE_SECTION = {
	source: 'entity',
	title: 'Licensee',
	kind: 'entity'
};

export const PERSONAL_SERVICES = {
	gmrs: {
		name: 'gmrs',
		label: 'GMRS',
		title: 'GMRS Licenses',
		heading: 'General Mobile Radio Service (GMRS)',
		blurb:
			'GMRS is a licensed two-way radio service for short-distance personal and family ' +
			'communication. One licence covers the licensee and their immediate family.',
		apiPath: '/gmrs',
		route: '/gmrs',
		filters: COMMON_FILTERS,
		columns: [...COMMON_HEAD_COLUMNS, ...COMMON_TAIL_COLUMNS],
		// GMRS has no service-specific FCC record -- HD/EN/HS is the whole
		// dataset -- so its detail page is the shared sections only.
		detailSections: [LICENSE_SECTION, LICENSEE_SECTION]
	},

	aircraft: {
		name: 'aircraft',
		label: 'Aircraft',
		title: 'Aircraft Licenses',
		heading: 'Aircraft Radio Stations (Part 87)',
		blurb:
			'Radio station licences for aircraft. Most flying in the US does not require one, ' +
			'but international flights and some commercial operations do.',
		apiPath: '/aircraft',
		route: '/aircraft',
		filters: [...COMMON_FILTERS, { key: 'n_number', placeholder: 'N-number / tail number' }],
		columns: [
			...COMMON_HEAD_COLUMNS,
			{ key: 'n_number', label: 'N-Number', sort: 'n_number', help: 'n_number' },
			{
				key: 'type_of_carrier',
				label: 'Carrier',
				sort: 'type_of_carrier',
				kind: 'code',
				category: 'type_of_carrier'
			},
			...COMMON_TAIL_COLUMNS
		],
		detailSections: [
			LICENSE_SECTION,
			LICENSEE_SECTION,
			{
				source: 'aircraft_specific',
				title: 'Aircraft Details',
				fields: [
					{ key: 'n_number', label: 'N-Number (tail number)' },
					{ key: 'aircraft_count', label: 'Aircraft Count' },
					{ key: 'type_of_carrier', label: 'Type of Carrier', category: 'type_of_carrier' },
					{ key: 'portable_indicator', label: 'Portable', category: 'yes_no' },
					{ key: 'fleet_indicator', label: 'Fleet', category: 'yes_no' }
				]
			}
		]
	},

	ship: {
		name: 'ship',
		label: 'Ship',
		title: 'Ship Licenses',
		heading: 'Ship Radio Stations (Part 80)',
		blurb:
			'Radio station licences for vessels. Recreational boats in US waters usually do not ' +
			'need one, but international voyages and compulsorily-equipped ships do.',
		apiPath: '/ship',
		route: '/ship',
		filters: [
			...COMMON_FILTERS,
			{ key: 'ship_name', placeholder: 'Ship name (partial)' },
			{ key: 'mmsi', placeholder: 'MMSI number' }
		],
		columns: [
			...COMMON_HEAD_COLUMNS,
			{ key: 'ship_name', label: 'Ship Name', sort: 'ship_name' },
			{
				key: 'general_class',
				label: 'Class',
				sort: 'general_class',
				kind: 'code',
				category: 'ship_general_class'
			},
			{ key: 'station_number', label: 'MMSI', help: 'station_number' },
			...COMMON_TAIL_COLUMNS
		],
		detailSections: [
			LICENSE_SECTION,
			LICENSEE_SECTION,
			{
				source: 'ship_specific',
				title: 'Ship Details',
				fields: [
					{ key: 'ship_name', label: 'Ship Name' },
					{ key: 'station_number', label: 'MMSI Number' },
					{
						key: 'type_of_authorization',
						label: 'Type of Authorization',
						category: 'type_of_authorization'
					},
					{ key: 'general_class', label: 'General Class', category: 'ship_general_class' },
					{ key: 'special_class', label: 'Special Class', category: 'ship_special_class' },
					{ key: 'ship_number', label: 'Official Number of Ship' },
					{ key: 'gross_tonnage', label: 'Gross Tonnage' },
					{ key: 'ship_length', label: 'Ship Length' },
					{ key: 'count_in_fleet', label: 'Count in Fleet' },
					{ key: 'international_voyages', label: 'International Voyages', category: 'yes_no' },
					{ key: 'foreign_communications', label: 'Foreign Communications', category: 'yes_no' },
					{ key: 'radiotelegraph', label: 'Radiotelegraph Working Series' },
					{ key: 'mmsi_request', label: 'MMSI Requested', category: 'yes_no' },
					{ key: 'self_id_number', label: 'Sel Call Number' },
					{ key: 'comsat_id_number', label: 'Sel Call — INMARSAT' },
					{ key: 'working_freq_s1', label: 'Working Frequency 1' },
					{ key: 'working_freq_s2', label: 'Working Frequency 2' }
				]
			},
			{
				source: 'radio_equipment',
				title: 'Radio Equipment',
				fields: [
					{ key: 'vhf', label: 'VHF', category: 'yes_no' },
					{ key: 'mf', label: 'MF', category: 'yes_no' },
					{ key: 'hf', label: 'HF', category: 'yes_no' },
					{ key: 'dsc', label: 'DSC', category: 'yes_no' },
					{ key: 'inmarsat_a', label: 'INMARSAT A', category: 'yes_no' },
					{ key: 'inmarsat_b', label: 'INMARSAT B', category: 'yes_no' },
					{ key: 'inmarsat_c', label: 'INMARSAT C', category: 'yes_no' },
					{ key: 'inmarsat_m', label: 'INMARSAT M', category: 'yes_no' },
					{ key: 'inmarsat_mini', label: 'INMARSAT Mini-M', category: 'yes_no' },
					{ key: 'epirb_406_mhz', label: 'EPIRB 406 MHz', category: 'yes_no' },
					{ key: 'epirb_121_5_mhz', label: 'EPIRB 121.5 MHz', category: 'yes_no' },
					{ key: 'epirb_identification_code', label: 'EPIRB ID Code' },
					{ key: 'sart', label: 'SART', category: 'yes_no' },
					{ key: 'raft_count', label: 'Life Raft Count' },
					{ key: 'lifeboat_count', label: 'Lifeboat Count' },
					{ key: 'vessel_capacity', label: 'Vessel Capacity' }
				]
			},
			{
				source: 'exemption_request',
				title: 'Exemption Request',
				fields: [
					{ key: 'ship_type', label: 'Ship Type', category: 'ship_type' },
					{ key: 'port_registry', label: 'Port of Registry' },
					{ key: 'owner', label: 'Owner' },
					{ key: 'operater', label: 'Operator' },
					{ key: 'charter', label: 'Charterer' },
					{ key: 'agent', label: 'Agent' },
					{ key: 'foreign_port', label: 'Foreign Port' },
					{
						key: 'radiotelephone_exempt_req',
						label: 'Radiotelephone Exemption',
						category: 'yes_no'
					},
					{ key: 'gmdss_exemp_req', label: 'GMDSS Exemption', category: 'yes_no' },
					{ key: 'radio_dir_exempt_req', label: 'Radio Direction Exemption', category: 'yes_no' },
					{ key: 'vessel_size_exempt', label: 'Vessel Size Exemption', category: 'yes_no' },
					{ key: 'equipment_exempt', label: 'Equipment Exemption', category: 'yes_no' },
					{ key: 'ltd_routes_exempt', label: 'Limited Routes Exemption', category: 'yes_no' },
					{ key: 'cond_voyages_exempt', label: 'Conditional Voyages Exemption', category: 'yes_no' },
					{ key: 'other_exempt', label: 'Other Exemption', category: 'yes_no' },
					{ key: 'other_exempt_desc', label: 'Other Exemption Description' },
					{ key: 'prev_exempt_file_number', label: 'Previous Exemption File Number' },
					{ key: 'number_of_crew', label: 'Number of Crew' },
					{ key: 'number_passengers', label: 'Number of Passengers' },
					{ key: 'number_others', label: 'Number of Others' }
				]
			},
			{
				// FCC splits one long voyage description across several
				// sequence-numbered rows; the API returns them in order and
				// this renders them re-joined as the single sentence they
				// were always meant to be.
				source: 'voyages',
				title: 'Voyage Description',
				kind: 'joined_text',
				joinField: 'voyage_description'
			}
		]
	}
};

export const PERSONAL_SERVICE_LIST = Object.values(PERSONAL_SERVICES);

/** Route for a search result / related-identity row, by its `source`. */
export function serviceRoute(source, key) {
	if (source === 'amateur') return `/amateur/${key}`;
	if (source === 'tower') return `/towers/${key}`;
	if (PERSONAL_SERVICES[source]) return `${PERSONAL_SERVICES[source].route}/${key}`;
	return null;
}
