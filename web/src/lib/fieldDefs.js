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
 *
 * The GMRS/Aircraft/Ship code tables (`type_of_carrier`,
 * `type_of_authorization`, `ship_general_class`, `ship_special_class`,
 * `ship_type`, and the ZA/AC/SA/SB/SE service codes) are sourced from FCC
 * Form 605 (Main Form + Schedules B, C and G), the FCC ULS code-definitions
 * reference, and FCC's published radio-service code list, then checked
 * against the real distinct values in the downloaded dumps (2026-09-07).
 * Where FCC publishes no decode table at all -- notably ship
 * `working_freq_s1`/`working_freq_s2` -- the field is left intentionally
 * undecoded and rendered as the raw code, because a plausible-looking wrong
 * definition is worse than none.
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
	county_code: 'FIPS county code for the structure location (not decoded per-county here; cross-reference a FIPS county table if needed).',

	// --- Aircraft (Part 87, aircr_ac) ---
	aircraft_count: 'Number of aircraft covered by this license.',
	type_of_carrier: 'Whether the aircraft is flown privately or as a commercial air carrier.',
	portable_indicator: 'Whether the radio equipment is portable (may be moved between aircraft) rather than fixed to one airframe.',
	fleet_indicator: 'Whether this license covers a fleet of aircraft under a single authorization.',
	n_number: 'FAA aircraft registration ("tail number") of the aircraft this station is installed in.',

	// --- Ship (Part 80, ship_sh) ---
	type_of_authorization: 'Whether this licence covers one vessel, a single portable transmitter used across vessels, or a whole fleet.',
	count_in_fleet: 'Number of vessels covered, when this is a fleet licence.',
	general_class: 'Broad category of vessel (FCC "General Class of Ship").',
	special_class: 'Specific vessel type within the general class (FCC "Special Class of Ship").',
	ship_name: 'Name of the vessel.',
	ship_number: 'Official number of the ship (as registered with the vessel documentation authority).',
	international_voyages: 'Whether the vessel travels on international voyages.',
	foreign_communications: 'Whether the station is authorized to communicate with foreign coast stations.',
	radiotelegraph: 'Whether a Morse radiotelegraph working series has been requested for this vessel.',
	mmsi_request: 'Whether a Maritime Mobile Service Identity (MMSI) was requested with this application.',
	gross_tonnage: 'Gross tonnage of the vessel (a measure of internal volume, not weight).',
	ship_length: 'Overall length of the vessel, in feet.',
	// Deliberately NOT decoded: FCC publishes the field name but no table of
	// what the "Wnn" values mean, and no third-party ULS parser decodes them
	// either. A wrong tooltip would be worse than none.
	working_freq_s1: 'Working frequency series 1. FCC does not publish a decode table for these codes; shown as-is.',
	working_freq_s2: 'Working frequency series 2. FCC does not publish a decode table for these codes; shown as-is.',
	self_id_number: 'Selective-calling (Sel Call) number assigned to this station.',
	comsat_id_number: 'INMARSAT selective-calling identity for this station.',
	station_number: 'Maritime Mobile Service Identity (MMSI) -- the 9-digit number that identifies this vessel in digital selective calling and AIS.',

	// --- Ship radio equipment (ship_sr) ---
	epirb_identification_code: 'Identification code of the vessel\u2019s Emergency Position-Indicating Radio Beacon (EPIRB).',
	epirb_406_mhz: 'Whether the vessel carries a 406 MHz EPIRB (satellite distress beacon).',
	epirb_121_5_mhz: 'Whether the vessel carries a 121.5 MHz EPIRB (homing distress beacon).',
	sart: 'Whether the vessel carries a Search and Rescue Transponder (SART), used to show a lifeboat\u2019s position on rescuers\u2019 radar.',
	dsc: 'Whether the vessel carries Digital Selective Calling equipment, used to send automated distress alerts.',
	raft_count: 'Number of liferafts carried.',
	lifeboat_count: 'Number of lifeboats carried.',
	vessel_capacity: 'Total number of people the vessel is certified to carry.',

	// --- Ship exemption request (ship_se) ---
	ship_type: 'Vessel type as certified by the U.S. Coast Guard.',
	radiotelephone_exempt_req: 'Whether an exemption from radiotelephone (VHF/MF) equipment requirements was requested.',
	gmdss_exemp_req: 'Whether an exemption from Global Maritime Distress and Safety System (GMDSS) requirements was requested.',
	radio_dir_exempt_req: 'Whether an exemption from radio direction-finding equipment requirements was requested.',
	vessel_size_exempt: 'Vessel size given as a ground for the exemption request.',
	equipment_exempt: 'Variety of equipment already on board, given as a ground for the exemption request.',
	ltd_routes_exempt: 'Limited routes travelled, given as a ground for the exemption request.',
	cond_voyages_exempt: 'Conditions of the voyages undertaken, given as a ground for the exemption request.',
	other_exempt: 'Some other ground was given for the exemption request.',
	voyage_description: 'Operator\u2019s free-text description of the voyages the vessel undertakes, supporting an exemption request.'
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
		HV: 'Vanity (Amateur)',
		// Personal radio services added alongside Amateur. Strings are the
		// FCC's own service descriptions from its published radio-service
		// code list.
		ZA: 'General Mobile Radio (GMRS)',
		AC: 'Aircraft',
		SA: 'Ship Recreational or Voluntarily Equipped',
		SB: 'Ship Compulsory Equipped',
		SE: 'Ship Exemption'
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
	},

	// --- Aircraft (Part 87) ---------------------------------------------
	// FCC Form 605 Schedule C, Item 5 binds these letters explicitly:
	// "If the application is for a Private Aircraft, enter 'P'. Otherwise,
	// enter 'A' for Air Carrier."
	type_of_carrier: {
		P: 'Private aircraft',
		A: 'Air carrier'
	},

	// --- Ship (Part 80) -------------------------------------------------
	// FCC Form 605 Schedule B, Item 4 (and the FCC ULS code-definitions
	// reference) define exactly these three values.
	type_of_authorization: {
		R: 'Regular (one vessel only)',
		P: 'Portable (one transmitter used aboard various U.S. vessels)',
		F: 'Fleet (several vessels under one authorization)'
	},

	// FCC "General Class of Ship". The FCC defines exactly these five codes;
	// a handful of rows in the real data carry other values (single-row
	// data-entry errors, e.g. a Special Class code typed into this field),
	// which deliberately fall through to being shown as the raw code rather
	// than guessed at.
	ship_general_class: {
		MM: 'Merchant',
		PL: 'Pleasure',
		SV: 'Rescue',
		FV: 'Fishing',
		GV: 'Official service ship'
	},

	// FCC "Special Class of Ship" -- the 30 codes FCC publishes on Form 605
	// Schedule B. As above, rare unlisted values render as the raw code.
	ship_special_class: {
		ACV: 'Air-cushion vehicle',
		AUX: 'Auxiliary ship',
		BLK: 'Bulk carrier',
		BLN: 'Whaler',
		BTA: 'Factory ship',
		CA: 'Cargo ship',
		CAB: 'Coaster',
		CBL: 'Cable ship',
		CHA: 'Barge',
		CHR: 'Trawler',
		CIT: 'Tanker',
		CON: 'Container ship',
		ECO: 'Training ship',
		EXP: 'Research or survey ship',
		FBT: 'Ferry',
		FRG: 'Reefer',
		MTB: 'Motorboat',
		OIL: 'Oil tanker',
		PA: 'Passenger ship',
		PH: 'Fishing vessel',
		PLT: 'Pilot tender',
		PMX: 'Cargo and passenger',
		RAM: 'Salvage ship',
		RAV: 'Supply vessel',
		SLO: 'Sloop',
		TPO: 'Ore carrier',
		TRA: 'Tramp',
		TUG: 'Tug',
		VDT: 'Hydrofoil',
		VLR: 'Sailing ship',
		YAT: 'Yacht'
	},

	// FCC Form 605 Schedule G, Item 4a: "Vessel is certified by the U.S.
	// Coast Guard as a: Passenger / Cargo vessel."
	ship_type: {
		C: 'Cargo vessel',
		P: 'Passenger vessel'
	},

	// Shared Y/N flag decode, used by the many indicator columns in the
	// aircraft and ship records (portable/fleet indicators, equipment
	// present, exemption grounds claimed, and so on).
	yes_no: {
		Y: 'Yes',
		N: 'No'
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
