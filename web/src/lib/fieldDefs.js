/**
 * Central registry of field-level help text ("what does this field mean")
 * and value-level code definitions ("what does this specific code value
 * mean") for FCC ULS data fields, so every browse/detail page across the
 * app -- and any future ULS dataset added later -- can look up a
 * definition by a stable field/category key instead of duplicating
 * hardcoded strings per page.
 *
 * Sourcing note: `license_status`, `application_purpose`,
 * `application_status`, `operator_class`, `entity_type`, and
 * `radio_service_code` are cross-checked against real distinct values
 * observed in this project's own ingested production data (query run
 * 2026-09-06) and a well-structured, independently-maintained third-party
 * ULS parser (github.com/tgies/uls). The remaining tables (group_code,
 * region_code, applicant_type_code, structure_type, tower status_code,
 * vanity_relationship, trustee_indicator, and the *_flag fields) are
 * best-effort, based on publicly documented/community-understood FCC
 * ULS & amateur radio licensing conventions -- same "best effort, unknown
 * falls back to the raw code" spirit already used by
 * api/app/history_codes.py and notifier/app/senders/email_to_sms.py.
 * See docs/fcc-data-reference.md §7 for the full sourcing notes.
 */

// Field-level help: attached next to a <label> (e.g. via the existing
// `.hint` tooltip span pattern already used on the Watches page) to
// explain what the FIELD itself represents, independent of its value.
export const FIELD_HELP = {
	// Amateur -- License header (amat_hd)
	license_status: 'Current status of this license.',
	radio_service_code: 'FCC radio service this license belongs to.',
	eligibility_rule_num: 'FCC rule part under which this license was granted eligibility.',
	// Amateur -- Licensee/entity (amat_en)
	entity_type: 'Role this entity record plays relative to the license.',
	applicant_type_code: 'Category of applicant that holds this license.',
	entity_status_code: 'Status of this entity/licensee record. Blank normally means Active.',
	// Amateur -- Amateur-specific (amat_am)
	operator_class: 'Amateur operator license class, which determines the frequency privileges the licensee may use.',
	group_code: "Callsign format group the FCC assigned this callsign from, historically tied to operator class at time of issuance.",
	region_code: 'US amateur radio call-district number historically associated with this license.',
	trustee_indicator: 'Whether a trustee is on file for this callsign (common for club station licenses).',
	vanity_relationship: "How this vanity (specially-requested) callsign relates to the licensee, e.g. a former callsign of the same person or a deceased relative's callsign.",
	systematic_callsign_change: 'Code related to a systematic (FCC-sequential) callsign reassignment on this record. FCC does not publish a decode table for this code; shown as-is.',
	vanity_callsign_change: 'Code related to a vanity (specially-requested) callsign change on this record. FCC does not publish a decode table for this code; shown as-is.',
	// Tower / ASR (tower_ra)
	structure_type: 'FCC structure-type code describing the kind of antenna structure.',
	status_code: 'Current status of this antenna structure registration.',
	nepa_flag: 'Whether this structure was subject to National Environmental Policy Act (NEPA) environmental review.',
	application_purpose: 'FCC ULS purpose code describing what this filing requested.',
	previous_purpose: 'Purpose code of the prior filing for this structure, if any.',
	painting_and_lighting: 'FAA-specified paint/lighting scheme required for aviation-obstruction marking.',
	proposed_marking_and_lighting: 'Paint/lighting scheme proposed in the current filing, pending FAA review.',
	county_code: 'FIPS county code for the structure location (not decoded per-county here; cross-reference a FIPS county table if needed).'
};

// Code -> human description maps, keyed by a category name shared across
// pages (not always the same as the raw DB column name, since e.g. amateur
// license_status and tower status_code use different code sets but the
// same category key would be confusing -- kept distinct below).
export const CODE_MAPS = {
	license_status: {
		A: 'Active',
		C: 'Cancelled',
		E: 'Expired',
		L: 'Pending Legal Status',
		P: 'Parent Station Cancelled',
		T: 'Terminated',
		X: 'Term Pending'
	},
	radio_service_code: {
		HA: 'Amateur',
		HV: 'Vanity (Amateur)'
	},
	// FCC ULS entity-record status code (amat_en.status_code) -- per the
	// FCC's own generic ULS code-definitions reference: blank normally
	// means Active, so this map only needs to cover the non-blank cases.
	entity_status_code: {
		T: 'Terminated',
		X: 'Termination Pending'
	},
	entity_type: {
		CE: 'Transferee Contact',
		CL: 'Licensee Contact',
		CR: 'Assignor Contact',
		CS: 'Lessee Contact',
		E: 'Transferee',
		L: 'Licensee',
		O: 'Owner',
		R: 'Assignor or Transferor',
		S: 'Lessee'
	},
	// FCC Form 605/601 applicant type codes (standard across many ULS
	// services); only a subset (B, G, I, M, R) has been observed in this
	// project's ingested Amateur data, full list kept for completeness.
	applicant_type_code: {
		B: 'Amateur Club',
		C: 'Corporation',
		D: 'General Partnership',
		E: 'Limited Partnership',
		F: 'Limited Liability Partnership',
		G: 'Governmental Entity',
		H: 'Other',
		I: 'Individual',
		J: 'Joint Venture',
		L: 'Limited Liability Company',
		M: 'Military Recreation',
		O: 'Consortium',
		P: 'Partnership',
		R: 'RACES (Radio Amateur Civil Emergency Service)',
		T: 'Trust',
		U: 'Unincorporated Association'
	},
	operator_class: {
		A: 'Advanced',
		E: 'Amateur Extra',
		G: 'General',
		N: 'Novice',
		P: 'Technician Plus',
		T: 'Technician'
	},
	// Historical callsign-format sequential issuance group.
	group_code: {
		A: 'Group A (historically Extra/Advanced class, shorter 2x1 format)',
		B: 'Group B (historically Advanced/General class, 2x2 format)',
		C: 'Group C (historically Technician/General/Novice class, 1x3 format)',
		D: 'Group D (default group for all newly issued licenses, 2x3 format)'
	},
	// US amateur call-district numbers (0-9 continental, 10+ territories).
	region_code: {
		'0': 'CO, IA, KS, MN, MO, NE, ND, SD',
		'1': 'CT, ME, MA, NH, RI, VT',
		'2': 'NJ, NY',
		'3': 'DE, DC, MD, PA',
		'4': 'AL, FL, GA, KY, NC, SC, TN, VA',
		'5': 'AR, LA, MS, NM, OK, TX',
		'6': 'CA',
		'7': 'AZ, ID, MT, NV, OR, UT, WA, WY',
		'8': 'MI, OH, WV',
		'9': 'IL, IN, WI',
		'10': 'Alaska',
		'11': 'Hawaii',
		'12': 'Caribbean insular areas (Puerto Rico, US Virgin Islands)',
		'13': 'Pacific insular areas (Guam, American Samoa, etc.)'
	},
	trustee_indicator: {
		Y: 'Yes',
		N: 'No'
	},
	nepa_flag: {
		Y: 'Yes',
		N: 'No'
	},
	// FCC ULS application purpose codes -- verified against the FCC's own
	// generic ULS code-definitions reference ("AD Application Purpose"
	// list, corroborated via github.com/tgies/uls's mirrored copy of the
	// FCC's public_access_database_definitions materials). Note: ASR/Tower
	// filings also use a few purpose codes (OC, DI, SU) observed in this
	// project's own ingested production data that do NOT appear in that
	// generic list and have no located authoritative decode -- they are
	// deliberately left undecoded (fall back to raw code) rather than
	// guessing.
	application_purpose: {
		AA: 'Assignment of Authorization',
		AM: 'Amendment',
		AR: 'DE Annual Report',
		AU: 'Administrative Update',
		CA: 'Cancellation of License',
		CB: 'C Block Election',
		DC: 'Data Correction',
		DU: 'Duplicate License',
		EX: 'Request for Extension of Time',
		HA: 'HAC Report',
		LC: 'Cancel a Lease',
		LE: 'Extend Term of a Lease',
		LM: 'Modification of a Lease',
		LN: 'New Lease',
		LT: 'Transfer of Control of a Lessee',
		LU: 'Administrative Update of a Lease',
		MD: 'Modification',
		NE: 'New',
		NT: 'Required Notification',
		RE: 'DE Reportable Event',
		RL: 'Register Link/Location',
		RM: 'Renewal/Modification',
		RO: 'Renewal Only',
		TC: 'Transfer of Control',
		WD: 'Withdrawal of Application'
	},
	// ASR/Tower registration status codes -- sourced from a third-party
	// ASR ingestion tool (github.com/lf-connectivity/ISPToolbox) that
	// cites the FCC's own "pubacc_asr_codes_data_elem.pdf" as its source;
	// cross-checked against the actual distinct values observed in this
	// project's ingested production data (A, C, G, I, T dominate; D, N,
	// O, P, R, W are rarer/unobserved here but included for completeness).
	status_code_tower: {
		A: 'Cancelled',
		C: 'Constructed',
		D: 'Dismissed',
		G: 'Granted',
		I: 'Dismantled',
		N: 'Inactive',
		O: 'Owner removed',
		P: 'Pending',
		R: 'Returned',
		T: 'Terminated',
		W: 'Withdrawn'
	},
	// Antenna structure type -- sourced from the FCC's own generic ULS
	// code-definitions reference ("LO Structure Type" list, which also
	// documents the ASR-specific structure types even though ASR has no
	// separate published record dictionary of its own), cross-checked
	// against a third-party ASR ingestion tool's independent mapping.
	// Multi-tower-array shorthand codes (e.g. "3TA1") and any other
	// unmapped code fall back to the raw value rather than guessing.
	structure_type: {
		B: 'Building',
		BANT: 'Building with antenna on top',
		BMAST: 'Building with mast',
		BPIPE: 'Building with pipe',
		BPOLE: 'Building with pole',
		BRIDG: 'Bridge',
		BTWR: 'Building with tower',
		GTOWER: 'Guyed structure used for communication purposes',
		LTOWER: 'Lattice tower',
		MAST: 'Mast',
		MTOWER: 'Monopole',
		NNGTANN: 'Guyed tower array',
		NNLTANN: 'Lattice tower array',
		NNMTANN: 'Monopole array',
		PIPE: 'Pipe',
		POLE: 'Pole',
		RIG: 'Oil or other type of rig',
		SIGN: 'Sign or billboard',
		SILO: 'Silo',
		STACK: 'Smoke stack',
		TANK: 'Tank (water, gas, etc.)',
		TOWER: 'Free-standing or guyed structure used for communication',
		TREE: 'Tree used as an antenna support',
		UPOLE: 'Utility pole/tower used to provide service',
		UTOWER: 'Unguyed, free-standing tower'
	}
};

/** Returns the field-level help text for a field key, or '' if none defined. */
export function fieldHelp(key) {
	return FIELD_HELP[key] ?? '';
}

/** Returns the code -> description map for a category, or {} if none defined. */
export function codeMap(category) {
	return CODE_MAPS[category] ?? {};
}

/**
 * Returns a description for `code` within `category`, or undefined if the
 * code/category is unmapped (callers should fall back to showing the raw
 * code unchanged).
 */
export function describeCode(category, code) {
	if (!code) return undefined;
	const map = CODE_MAPS[category];
	if (!map) return undefined;
	return map[code] ?? map[String(code).toUpperCase()];
}

/**
 * True if a description is short enough (a single word) to render inline
 * as "CODE (Description)" without risking layout breakage in a narrow
 * table column or pill on mobile. Longer descriptions should be rendered
 * as a mouseover tooltip instead (see the `.hint`/title= pattern).
 */
export function isShortDescription(desc) {
	return typeof desc === 'string' && desc.trim().length > 0 && !desc.includes(' ');
}
