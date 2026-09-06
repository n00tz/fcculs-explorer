<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, refreshUser, logout } from '$lib/auth.js';

	onMount(refreshUser);

	async function handleLogout() {
		await logout();
		goto('/');
	}
</script>

<div class="app-shell">
	<header class="topbar">
		<a class="brand" href="/">FCC ULS Explorer</a>
		<nav>
			<a href="/amateur">Amateur</a>
			<a href="/towers">Towers</a>
			<a href="/watches">My Watches</a>
			{#if $user}
				<span class="muted">{$user.email}</span>
				<button class="secondary" on:click={handleLogout}>Sign out</button>
			{:else}
				<a href="/login">Sign in</a>
			{/if}
		</nav>
	</header>
	<main>
		<slot />
	</main>
	<footer>
		<p>
			Data sourced from the FCC Universal Licensing System (ULS) public files. Not affiliated
			with the FCC.
		</p>
	</footer>
</div>
