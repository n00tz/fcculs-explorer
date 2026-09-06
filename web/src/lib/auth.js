/**
 * Shared client-side auth state. A svelte store holding the current signed-in
 * user (or null), populated from GET /auth/me. The layout nav and any page
 * that cares about sign-in state read from this store instead of each
 * fetching /auth/me independently, so the nav's Sign in/Sign out link stays
 * in sync everywhere after login/logout.
 */
import { writable } from 'svelte/store';
import { get as apiGet, post as apiPost } from './api.js';

export const user = writable(null);
export const authChecked = writable(false);

export async function refreshUser() {
	try {
		const u = await apiGet('/auth/me');
		user.set(u);
	} catch (e) {
		user.set(null);
	} finally {
		authChecked.set(true);
	}
}

export async function logout() {
	try {
		await apiPost('/auth/logout');
	} finally {
		user.set(null);
	}
}
