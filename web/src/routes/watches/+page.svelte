<script>
	import { get, post, del } from '$lib/api.js';
	import { onMount } from 'svelte';
	import { page as pageStore } from '$app/stores';

	let user = null;
	let channels = [];
	let watches = [];
	let loading = true;
	let error = '';

	// New channel form
	let channelType = 'webhook';
	let channelLabel = '';
	let channelError = '';
	let testResults = {}; // channel_id -> {status, detail}
	let testing = {}; // channel_id -> bool

	// Per-field guided config values, reset whenever channelType changes.
	let fieldValues = {};

	// Carrier options for the email-to-sms gateway dropdown -- mirrors
	// notifier/app/senders/email_to_sms.py's CARRIER_GATEWAYS keys exactly
	// so the value picked here is understood by the sender unmodified.
	const CARRIER_OPTIONS = [
		{ value: 'verizon', label: 'Verizon' },
		{ value: 'att', label: 'AT&T' },
		{ value: 'tmobile', label: 'T-Mobile' },
		{ value: 'sprint', label: 'Sprint (legacy)' },
		{ value: 'boost', label: 'Boost Mobile' },
		{ value: 'cricket', label: 'Cricket Wireless' },
		{ value: 'uscellular', label: 'US Cellular' },
		{ value: 'metro', label: 'Metro by T-Mobile' },
		{ value: 'googlefi', label: 'Google Fi' },
		{ value: 'straighttalk', label: 'Straight Talk' },
		{ value: 'consumercellular', label: 'Consumer Cellular' },
		{ value: 'xfinitymobile', label: 'Xfinity Mobile' },
		{ value: 'republicwireless', label: 'Republic Wireless' },
		{ value: 'ting', label: 'Ting' },
		{ value: 'virginmobile', label: 'Virgin Mobile' },
		{ value: 'pageplus', label: 'Page Plus' },
		{ value: 'simplemobile', label: 'Simple Mobile' },
		{ value: 'tracfone', label: 'Tracfone' },
		{ value: 'mintmobile', label: 'Mint Mobile' },
		{ value: 'visible', label: 'Visible' },
		{ value: '__other__', label: 'Other / not listed (enter gateway domain)' }
	];

	// A small per-channel-type schema drives the guided form below --
	// replaces the old raw-JSON textarea with labeled inputs/selects/
	// checkboxes, each with a tooltip, while still assembling the exact
	// same `config` dict shape the API has always accepted.
	const CHANNEL_FIELD_SCHEMAS = {
		smtp: [
			{
				key: 'email',
				label: 'Email address',
				kind: 'email',
				required: true,
				placeholder: 'you@example.com',
				tooltip: 'Where alert emails for this channel will be delivered.'
			}
		],
		email_to_sms: [
			{
				key: 'phone',
				label: 'Phone number',
				kind: 'tel',
				required: true,
				placeholder: '5551234567',
				tooltip: 'Digits only, no dashes or spaces -- used to build the carrier gateway address.'
			},
			{
				key: 'carrier',
				label: 'Carrier',
				kind: 'select',
				required: true,
				options: CARRIER_OPTIONS,
				tooltip:
					'Your phone plan carrier. Email-to-SMS gateways are unofficial and carriers can change or ' +
					'discontinue them without notice -- pick "Other" if yours is missing or has stopped working.'
			},
			{
				key: 'carrier_gateway',
				label: 'Custom gateway domain',
				kind: 'text',
				showIf: (v) => v.carrier === '__other__',
				placeholder: 'e.g. messaging.example.net',
				tooltip: 'The email domain your carrier uses for SMS gateway delivery (the part after the @ sign).'
			}
		],
		webhook: [
			{
				key: 'url',
				label: 'Webhook URL',
				kind: 'url',
				required: true,
				placeholder: 'https://example.com/hook',
				tooltip: 'Must be a public http(s) URL reachable from the server; internal/private addresses are rejected.'
			},
			{
				key: 'method',
				label: 'HTTP method',
				kind: 'select',
				options: [
					{ value: 'POST', label: 'POST (recommended)' },
					{ value: 'GET', label: 'GET' },
					{ value: 'PUT', label: 'PUT' }
				],
				default: 'POST',
				tooltip: 'Most webhook receivers expect POST; only change this if your receiver requires otherwise.'
			},
			{
				key: 'header_name',
				label: 'Extra header name (optional)',
				kind: 'text',
				placeholder: 'Authorization',
				tooltip: 'For receivers that need a single auth header, e.g. a bearer token.'
			},
			{
				key: 'header_value',
				label: 'Extra header value (optional)',
				kind: 'text',
				placeholder: 'Bearer abc123',
				showIf: (v) => !!v.header_name,
				tooltip: 'The value to send for the header name above.'
			}
		],
		ntfy: [
			{
				key: 'url',
				label: 'Topic URL',
				kind: 'url',
				required: true,
				placeholder: 'https://ntfy.sh/your-topic',
				tooltip: 'Your ntfy topic URL -- use a self-hosted ntfy server URL if you run one, or ntfy.sh with a hard-to-guess topic name.'
			}
		],
		discord: [
			{
				key: 'url',
				label: 'Discord webhook URL',
				kind: 'url',
				required: true,
				placeholder: 'https://discord.com/api/webhooks/...',
				tooltip: 'Create this in your Discord server: Channel Settings → Integrations → Webhooks.'
			}
		],
		telegram: [
			{
				key: 'bot_token',
				label: 'Bot token',
				kind: 'text',
				required: true,
				placeholder: '123456789:abc...',
				tooltip: 'Create a bot and get its token from @BotFather on Telegram.'
			},
			{
				key: 'chat_id',
				label: 'Chat ID',
				kind: 'text',
				required: true,
				placeholder: '123456789',
				tooltip: 'Message your bot once, then visit https://api.telegram.org/bot<token>/getUpdates to find your chat id.'
			}
		],
		matrix: [
			{
				key: 'homeserver',
				label: 'Homeserver URL',
				kind: 'url',
				required: true,
				placeholder: 'https://matrix.org',
				tooltip: 'The base URL of the Matrix homeserver your account lives on.'
			},
			{
				key: 'room_id',
				label: 'Room ID',
				kind: 'text',
				required: true,
				placeholder: '!abc123:matrix.org',
				tooltip: 'Internal room ID (not the room alias), found in your Matrix client\u2019s room settings.'
			},
			{
				key: 'access_token',
				label: 'Access token',
				kind: 'text',
				required: true,
				placeholder: '...',
				tooltip: 'A Matrix access token for an account with permission to post in the room above.'
			}
		]
	};

	function resetFieldValues() {
		const defaults = {};
		for (const f of CHANNEL_FIELD_SCHEMAS[channelType] ?? []) {
			defaults[f.key] = f.default ?? (f.kind === 'checkbox' ? false : '');
		}
		fieldValues = defaults;
	}
	$: channelType, resetFieldValues();

	// New watch form
	let watchSubjectType = 'callsign';
	let watchSubjectValue = '';
	let watchChannelId = '';
	let watchError = '';

	function prefillWatchFromUrl() {
		const params = $pageStore.url.searchParams;
		const type = params.get('subject_type');
		const value = params.get('subject_value');
		if (type) watchSubjectType = type;
		if (value) watchSubjectValue = value;
	}

	async function loadAll() {
		loading = true;
		error = '';
		try {
			user = await get('/auth/me');
			[channels, watches] = await Promise.all([
				get('/channels').then((d) => d.channels),
				get('/watches').then((d) => d.watches)
			]);
		} catch (e) {
			if (e.status === 401) {
				user = null;
			} else {
				error = e.message;
			}
		} finally {
			loading = false;
		}
	}

	function buildConfig() {
		const schema = CHANNEL_FIELD_SCHEMAS[channelType] ?? [];
		const config = {};
		for (const f of schema) {
			if (f.showIf && !f.showIf(fieldValues)) continue;
			const raw = fieldValues[f.key];
			if (raw === '' || raw === undefined || raw === null) continue;
			if (f.key === 'carrier' && raw === '__other__') continue; // handled by carrier_gateway instead
			config[f.key] = raw;
		}
		return config;
	}

	function validateRequired() {
		const schema = CHANNEL_FIELD_SCHEMAS[channelType] ?? [];
		for (const f of schema) {
			if (f.showIf && !f.showIf(fieldValues)) continue;
			if (f.required && !fieldValues[f.key]) {
				return `${f.label} is required.`;
			}
			if (f.key === 'carrier' && fieldValues[f.key] === '__other__' && !fieldValues.carrier_gateway) {
				return 'Enter a custom gateway domain, or pick a listed carrier.';
			}
		}
		return null;
	}

	async function createChannel() {
		channelError = '';
		const missing = validateRequired();
		if (missing) {
			channelError = missing;
			return;
		}
		try {
			await post('/channels', { channel_type: channelType, label: channelLabel || null, config: buildConfig() });
			channelLabel = '';
			resetFieldValues();
			await loadAll();
		} catch (e) {
			channelError = e.message;
		}
	}

	async function deleteChannel(id) {
		await del(`/channels/${id}`);
		await loadAll();
	}

	async function sendTest(id) {
		testing = { ...testing, [id]: true };
		testResults = { ...testResults, [id]: null };
		try {
			const result = await post(`/channels/${id}/test`, {});
			testResults = { ...testResults, [id]: result };
			if (result.status === 'sent') await loadAll();
		} catch (e) {
			testResults = { ...testResults, [id]: { status: 'failed', detail: e.message } };
		} finally {
			testing = { ...testing, [id]: false };
		}
	}

	async function createWatch() {
		watchError = '';
		if (!watchChannelId) {
			watchError = 'Choose a notification channel first.';
			return;
		}
		try {
			await post('/watches', {
				subject_type: watchSubjectType,
				subject_value: watchSubjectValue,
				channel_id: Number(watchChannelId)
			});
			watchSubjectValue = '';
			await loadAll();
		} catch (e) {
			watchError = e.message;
		}
	}

	async function deleteWatch(id) {
		await del(`/watches/${id}`);
		await loadAll();
	}

	onMount(() => {
		prefillWatchFromUrl();
		resetFieldValues();
		loadAll();
	});
</script>

<svelte:head>
	<title>My Watches — FCC ULS Explorer</title>
</svelte:head>

<h1>My Watches</h1>

{#if loading}
	<p class="muted">Loading…</p>
{:else if !user}
	<div class="card">
		<p>You need to sign in to manage watches and notification channels.</p>
		<a href="/login"><button>Sign in</button></a>
	</div>
{:else}
	<p class="muted">Signed in as {user.email}</p>
	{#if error}<p class="error">{error}</p>{/if}

	<h2>Notification Channels</h2>
	<div class="card">
		{#if channels.length === 0}
			<p class="muted">No channels yet — add one below before creating a watch.</p>
		{:else}
			<table>
				<thead><tr><th>Type</th><th>Label</th><th>Verified</th><th>Test</th><th></th></tr></thead>
				<tbody>
					{#each channels as c}
						<tr>
							<td>{c.channel_type}</td>
							<td>{c.label ?? '—'}</td>
							<td>{c.is_verified ? '✅' : '—'}</td>
							<td>
								<button class="secondary" disabled={testing[c.id]} on:click={() => sendTest(c.id)}>
									{testing[c.id] ? 'Sending…' : 'Send test'}
								</button>
								{#if testResults[c.id]}
									<div class={`test-result test-${testResults[c.id].status}`}>
										{testResults[c.id].status}{#if testResults[c.id].detail}: {testResults[c.id].detail}{/if}
									</div>
								{/if}
							</td>
							<td><button class="danger" on:click={() => deleteChannel(c.id)}>Delete</button></td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}

		<h2>Add a channel</h2>
		<form on:submit|preventDefault={createChannel} class="grid" style="max-width: 480px;">
			<label>
				Type
				<select bind:value={channelType}>
					<option value="smtp">Email (SMTP)</option>
					<option value="email_to_sms">Email-to-SMS (carrier gateway)</option>
					<option value="webhook">Generic Webhook</option>
					<option value="ntfy">ntfy</option>
					<option value="discord">Discord</option>
					<option value="telegram">Telegram</option>
					<option value="matrix">Matrix</option>
				</select>
			</label>
			<label>
				Label (optional)
				<input bind:value={channelLabel} placeholder="e.g. My phone" />
			</label>

			{#each CHANNEL_FIELD_SCHEMAS[channelType] ?? [] as f (f.key)}
				{#if !f.showIf || f.showIf(fieldValues)}
					<label>
						{f.label} <span class="hint" title={f.tooltip}>?</span>
						{#if f.kind === 'select'}
							<select bind:value={fieldValues[f.key]}>
								{#if !f.required}<option value="">— none —</option>{/if}
								{#each f.options as opt}
									<option value={opt.value}>{opt.label}</option>
								{/each}
							</select>
						{:else if f.kind === 'checkbox'}
							<input type="checkbox" bind:checked={fieldValues[f.key]} />
						{:else if f.kind === 'email'}
							<input type="email" bind:value={fieldValues[f.key]} placeholder={f.placeholder} />
						{:else if f.kind === 'tel'}
							<input type="tel" bind:value={fieldValues[f.key]} placeholder={f.placeholder} />
						{:else if f.kind === 'url'}
							<input type="url" bind:value={fieldValues[f.key]} placeholder={f.placeholder} />
						{:else}
							<input type="text" bind:value={fieldValues[f.key]} placeholder={f.placeholder} />
						{/if}
					</label>
				{/if}
			{/each}

			<button type="submit">Add channel</button>
			{#if channelError}<p class="error">{channelError}</p>{/if}
		</form>
	</div>

	<h2>Watches</h2>
	<div class="card">
		{#if watches.length === 0}
			<p class="muted">No watches yet.</p>
		{:else}
			<table>
				<thead><tr><th>Subject</th><th>Type</th><th>Channel</th><th></th></tr></thead>
				<tbody>
					{#each watches as w}
						<tr>
							<td>{w.subject_value}</td>
							<td>{w.subject_type}</td>
							<td>{w.label ?? w.channel_type}</td>
							<td><button class="danger" on:click={() => deleteWatch(w.id)}>Delete</button></td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}

		<div class="callout">
			<strong>New to ham radio and don't have a callsign yet?</strong>
			Watch your <strong>FRN</strong> instead of a callsign or ULS ID. Your FRN
			(FCC Registration Number) is assigned as soon as you register in CORES,
			well before the FCC grants your first callsign. Choose "FRN" as the watch
			type below and enter it — you'll get notified the moment any new callsign
			or tower is granted under that FRN, including your very first license.
		</div>

		<h2>Add a watch</h2>
		<form on:submit|preventDefault={createWatch} class="grid" style="max-width: 480px;">
			<label>
				Watch type
				<select bind:value={watchSubjectType}>
					<option value="callsign">Callsign</option>
					<option value="frn">FRN (for new hams without a callsign yet)</option>
					<option value="uls_id">ULS System ID</option>
					<option value="asr_registration_number">ASR Registration Number</option>
				</select>
			</label>
			<label>
				Value
				<input
					bind:value={watchSubjectValue}
					placeholder={watchSubjectType === 'frn' ? 'e.g. 0012345678' : 'e.g. K0WNL'}
					required
				/>
			</label>
			<label>
				Notify via
				<select bind:value={watchChannelId}>
					<option value="">Choose a channel…</option>
					{#each channels as c}
						<option value={c.id}>{c.label ?? c.channel_type}</option>
					{/each}
				</select>
			</label>
			<button type="submit" disabled={channels.length === 0}>Add watch</button>
			{#if watchError}<p class="error">{watchError}</p>{/if}
		</form>
	</div>
{/if}
