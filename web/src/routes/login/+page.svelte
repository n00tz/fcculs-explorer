<script>
	import { post } from '$lib/api.js';

	let email = '';
	let submitted = false;
	let error = '';
	let loading = false;

	async function requestLink() {
		loading = true;
		error = '';
		try {
			await post('/auth/request-link', { email });
			submitted = true;
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Sign in — FCC ULS Explorer</title>
</svelte:head>

<h1>Sign in</h1>
<p class="muted">
	No password needed. Enter your email and we'll send you a one-time sign-in link, valid for 15
	minutes.
</p>

{#if submitted}
	<div class="card">
		<p>If that email is registered, a sign-in link is on its way. Check your inbox and click the link to continue.</p>
	</div>
{:else}
	<div class="card" style="max-width: 420px;">
		<form on:submit|preventDefault={requestLink}>
			<label for="email">Email address</label><br />
			<input id="email" type="email" required bind:value={email} style="width: 100%; margin: 0.5rem 0;" />
			<br />
			<button type="submit" disabled={loading}>{loading ? 'Sending…' : 'Send sign-in link'}</button>
		</form>
		{#if error}<p class="error">{error}</p>{/if}
	</div>
{/if}
