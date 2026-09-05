/**
 * Thin fetch wrapper for the FastAPI backend. Always sends credentials so
 * the magic-link session cookie round-trips correctly, and normalizes
 * non-2xx responses into thrown Errors with the server's detail message.
 */
const BASE = '/api';

async function request(path, options = {}) {
	const res = await fetch(`${BASE}${path}`, {
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		...options
	});
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const body = await res.json();
			detail = body.detail || detail;
		} catch {
			// response wasn't JSON; fall back to statusText
		}
		const error = new Error(detail);
		error.status = res.status;
		throw error;
	}
	if (res.status === 204) return null;
	return res.json();
}

export function get(path, params) {
	const query = params
		? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '')).toString()
		: '';
	return request(`${path}${query}`);
}

export function post(path, body) {
	return request(path, { method: 'POST', body: JSON.stringify(body) });
}

export function del(path) {
	return request(path, { method: 'DELETE' });
}
