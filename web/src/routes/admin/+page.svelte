<script>
	import { get, post, patch, del } from '$lib/api.js';
	import { onMount } from 'svelte';

	// This route is intentionally not linked from the nav. Auth is a single
	// process-wide superuser password printed to the API container's logs
	// at startup (see api/app/admin_auth.py) -- there is no separate admin
	// account/email, just this one shared password.
	let authed = false;
	let checkingAuth = true;
	let password = '';
	let loginError = '';

	let tab = 'users';

	let users = [];
	let usersTotal = 0;
	let usersPage = 1;
	const pageSize = 25;

	let watches = [];
	let watchesTotal = 0;
	let watchesPage = 1;

	let error = '';
	let editingUserId = null;
	let editingUserEmail = '';
	let editingWatchId = null;
	let editingWatchValue = '';

	async function checkAuth() {
		checkingAuth = true;
		try {
			await get('/admin/me');
			authed = true;
			await loadUsers();
			await loadWatches();
		} catch (e) {
			authed = false;
		} finally {
			checkingAuth = false;
		}
	}

	async function login() {
		loginError = '';
		try {
			await post('/admin/login', { password });
			password = '';
			authed = true;
			await loadUsers();
			await loadWatches();
		} catch (e) {
			loginError = e.message;
		}
	}

	async function logoutAdmin() {
		await post('/admin/logout');
		authed = false;
	}

	async function loadUsers() {
		error = '';
		try {
			const data = await get('/admin/users', { page: usersPage, page_size: pageSize });
			users = data.items;
			usersTotal = data.total;
		} catch (e) {
			error = e.message;
		}
	}

	async function loadWatches() {
		error = '';
		try {
			const data = await get('/admin/watches', { page: watchesPage, page_size: pageSize });
			watches = data.items;
			watchesTotal = data.total;
		} catch (e) {
			error = e.message;
		}
	}

	function usersNextPage() {
		if (usersPage * pageSize < usersTotal) {
			usersPage += 1;
			loadUsers();
		}
	}
	function usersPrevPage() {
		if (usersPage > 1) {
			usersPage -= 1;
			loadUsers();
		}
	}
	function watchesNextPage() {
		if (watchesPage * pageSize < watchesTotal) {
			watchesPage += 1;
			loadWatches();
		}
	}
	function watchesPrevPage() {
		if (watchesPage > 1) {
			watchesPage -= 1;
			loadWatches();
		}
	}

	function startEditUser(u) {
		editingUserId = u.id;
		editingUserEmail = u.email;
	}
	async function saveUser(id) {
		try {
			await patch(`/admin/users/${id}`, { email: editingUserEmail });
			editingUserId = null;
			await loadUsers();
		} catch (e) {
			error = e.message;
		}
	}
	async function deleteUser(id, emailAddr) {
		if (!confirm(`Delete user ${emailAddr}? This also deletes their channels and watches.`)) return;
		try {
			await del(`/admin/users/${id}`);
			await loadUsers();
			await loadWatches();
		} catch (e) {
			error = e.message;
		}
	}

	function startEditWatch(w) {
		editingWatchId = w.id;
		editingWatchValue = w.subject_value;
	}
	async function saveWatch(id) {
		try {
			await patch(`/admin/watches/${id}`, { subject_value: editingWatchValue });
			editingWatchId = null;
			await loadWatches();
		} catch (e) {
			error = e.message;
		}
	}
	async function toggleWatchActive(w) {
		try {
			await patch(`/admin/watches/${w.id}`, { is_active: !w.is_active });
			await loadWatches();
		} catch (e) {
			error = e.message;
		}
	}
	async function deleteWatch(id) {
		if (!confirm('Delete this watch?')) return;
		try {
			await del(`/admin/watches/${id}`);
			await loadWatches();
			await loadUsers();
		} catch (e) {
			error = e.message;
		}
	}

	onMount(checkAuth);
</script>

<svelte:head>
	<title>Admin — FCC ULS Explorer</title>
	<meta name="robots" content="noindex, nofollow" />
</svelte:head>

{#if checkingAuth}
	<p class="muted">Checking admin session…</p>
{:else if !authed}
	<h1>Admin sign-in</h1>
	<p class="muted">
		The superuser password is generated fresh each time the API container starts and printed to
		its logs (<code>journalctl --user -u fcculs-api</code> / <code>podman logs api</code>). It is
		never stored anywhere else.
	</p>
	<div class="card" style="max-width: 420px;">
		<form on:submit|preventDefault={login}>
			<label for="admin-password">Password</label><br />
			<input id="admin-password" type="password" required bind:value={password} style="width: 100%; margin: 0.5rem 0;" />
			<br />
			<button type="submit">Sign in</button>
		</form>
		{#if loginError}<p class="error">{loginError}</p>{/if}
	</div>
{:else}
	<h1>
		Admin
		<button class="secondary" on:click={logoutAdmin} style="float: right;">Sign out</button>
	</h1>

	{#if error}<p class="error">{error}</p>{/if}

	<div class="filters">
		<button class:secondary={tab !== 'users'} on:click={() => (tab = 'users')}>Users</button>
		<button class:secondary={tab !== 'watches'} on:click={() => (tab = 'watches')}>Watches</button>
	</div>

	{#if tab === 'users'}
		<h2>Users</h2>
		<div class="card">
			<table>
				<thead>
					<tr><th>ID</th><th>Email</th><th>Channels</th><th>Watches</th><th>Created</th><th></th></tr>
				</thead>
				<tbody>
					{#each users as u}
						<tr>
							<td>{u.id}</td>
							<td>
								{#if editingUserId === u.id}
									<input bind:value={editingUserEmail} />
								{:else}
									{u.email}
								{/if}
							</td>
							<td>{u.channel_count}</td>
							<td>{u.watch_count}</td>
							<td>{u.created_at}</td>
							<td>
								{#if editingUserId === u.id}
									<button on:click={() => saveUser(u.id)}>Save</button>
									<button class="secondary" on:click={() => (editingUserId = null)}>Cancel</button>
								{:else}
									<button class="secondary" on:click={() => startEditUser(u)}>Edit</button>
									<button class="danger" on:click={() => deleteUser(u.id, u.email)}>Delete</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div class="pagination">
			<button class="secondary" disabled={usersPage <= 1} on:click={usersPrevPage}>← Previous</button>
			<span class="muted">Page {usersPage} · {usersTotal} total</span>
			<button class="secondary" disabled={usersPage * pageSize >= usersTotal} on:click={usersNextPage}>Next →</button>
		</div>
	{:else}
		<h2>Watches</h2>
		<div class="card">
			<table>
				<thead>
					<tr><th>ID</th><th>User</th><th>Type</th><th>Subject</th><th>Channel</th><th>Active</th><th>Created</th><th></th></tr>
				</thead>
				<tbody>
					{#each watches as w}
						<tr>
							<td>{w.id}</td>
							<td>{w.user_email}</td>
							<td>{w.subject_type}</td>
							<td>
								{#if editingWatchId === w.id}
									<input bind:value={editingWatchValue} />
								{:else}
									{w.subject_value}
								{/if}
							</td>
							<td>{w.label ?? w.channel_type}</td>
							<td>
								<button class="secondary" on:click={() => toggleWatchActive(w)}>
									{w.is_active ? 'Active' : 'Inactive'}
								</button>
							</td>
							<td>{w.created_at}</td>
							<td>
								{#if editingWatchId === w.id}
									<button on:click={() => saveWatch(w.id)}>Save</button>
									<button class="secondary" on:click={() => (editingWatchId = null)}>Cancel</button>
								{:else}
									<button class="secondary" on:click={() => startEditWatch(w)}>Edit</button>
									<button class="danger" on:click={() => deleteWatch(w.id)}>Delete</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<div class="pagination">
			<button class="secondary" disabled={watchesPage <= 1} on:click={watchesPrevPage}>← Previous</button>
			<span class="muted">Page {watchesPage} · {watchesTotal} total</span>
			<button class="secondary" disabled={watchesPage * pageSize >= watchesTotal} on:click={watchesNextPage}>Next →</button>
		</div>
	{/if}
{/if}
