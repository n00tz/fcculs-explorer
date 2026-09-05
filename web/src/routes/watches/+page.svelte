<script>
	import { get, post, del } from '$lib/api.js';
	import { onMount } from 'svelte';

	let user = null;
	let channels = [];
	let watches = [];
	let loading = true;
	let error = '';

	// New channel form
	let channelType = 'webhook';
	let channelLabel = '';
	let channelConfigText = '{"url": "https://example.com/hook"}';
	let channelError = '';

	// New watch form
	let watchSubjectType = 'callsign';
	let watchSubjectValue = '';
	let watchChannelId = '';
	let watchError = '';

	const CHANNEL_CONFIG_HINTS = {
		smtp: '{"email": "you@example.com"}',
		email_to_sms: '{"phone": "5551234567", "carrier": "verizon"}',
		webhook: '{"url": "https://example.com/hook"}',
		ntfy: '{"url": "https://ntfy.sh/your-topic"}',
		discord: '{"url": "https://discord.com/api/webhooks/..."}',
		telegram: '{"bot_token": "123:abc", "chat_id": "123456"}',
		matrix: '{"homeserver": "https://matrix.org", "room_id": "!abc:matrix.org", "access_token": "..."}'
	};
	$: channelConfigText = CHANNEL_CONFIG_HINTS[channelType] ?? '{}';

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

	async function createChannel() {
		channelError = '';
		let config;
		try {
			config = JSON.parse(channelConfigText);
		} catch {
			channelError = 'Config must be valid JSON.';
			return;
		}
		try {
			await post('/channels', { channel_type: channelType, label: channelLabel || null, config });
			channelLabel = '';
			await loadAll();
		} catch (e) {
			channelError = e.message;
		}
	}

	async function deleteChannel(id) {
		await del(`/channels/${id}`);
		await loadAll();
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

	onMount(loadAll);
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
				<thead><tr><th>Type</th><th>Label</th><th>Config</th><th></th></tr></thead>
				<tbody>
					{#each channels as c}
						<tr>
							<td>{c.channel_type}</td>
							<td>{c.label ?? '—'}</td>
							<td><code>{JSON.stringify(c.config)}</code></td>
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
			<label>
				Config (JSON)
				<textarea bind:value={channelConfigText} rows="3" style="width:100%; font-family: monospace;" />
			</label>
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

		<h2>Add a watch</h2>
		<form on:submit|preventDefault={createWatch} class="grid" style="max-width: 480px;">
			<label>
				Watch type
				<select bind:value={watchSubjectType}>
					<option value="callsign">Callsign</option>
					<option value="uls_id">ULS System ID</option>
					<option value="asr_registration_number">ASR Registration Number</option>
				</select>
			</label>
			<label>
				Value
				<input bind:value={watchSubjectValue} placeholder="e.g. K0WNL" required />
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
