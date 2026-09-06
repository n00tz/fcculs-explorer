<script>
	import { page } from '$app/stores';
	import { get } from '$lib/api.js';
	import { refreshUser } from '$lib/auth.js';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	let status = 'verifying';
	let error = '';

	onMount(async () => {
		const token = $page.url.searchParams.get('token');
		if (!token) {
			status = 'error';
			error = 'Missing sign-in token.';
			return;
		}
		try {
			// GET with credentials so the Set-Cookie from a successful
			// verification is stored for this origin.
			await get('/auth/verify', { token });
			await refreshUser();
			status = 'done';
			setTimeout(() => goto('/watches'), 800);
		} catch (e) {
			status = 'error';
			error = e.message;
		}
	});
</script>

<svelte:head>
	<title>Signing in… — FCC ULS Explorer</title>
</svelte:head>

<h1>Signing in…</h1>

{#if status === 'verifying'}
	<p class="muted">Verifying your sign-in link…</p>
{:else if status === 'done'}
	<p>Signed in! Redirecting to your watches…</p>
{:else}
	<p class="error">{error}</p>
	<p><a href="/login">Request a new sign-in link</a></p>
{/if}
