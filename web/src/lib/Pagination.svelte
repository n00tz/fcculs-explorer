<script>
	import { formatCount as fmt } from '$lib/format.js';

	// Shared pager for every paginated view. Replaces what used to be
	// seven copies of `Page {page} · {total} total`, which read as though
	// the record count were the page count -- and never showed the number
	// a reader actually looks for, since total pages was computed nowhere.
	//
	// Owning the Previous/Next disable conditions here too means the
	// `page * pageSize >= total` boundary is expressed once rather than
	// being re-derived correctly at seven call sites.
	export let page;
	export let pageSize;
	export let total;
	// `total` is 0 until the first fetch resolves, so without this the
	// pager flashes "No results" on every single page load.
	export let loading = false;
	// Compact drops the word "showing" for space-constrained placements
	// (the homepage widget must not push content below the fold).
	export let compact = false;
	export let onPrev;
	export let onNext;

	$: totalPages = Math.max(1, Math.ceil(total / pageSize));
	$: first = total === 0 ? 0 : (page - 1) * pageSize + 1;
	$: last = Math.min(page * pageSize, total);
	$: onFirstPage = page <= 1;
	$: onLastPage = page * pageSize >= total;
</script>

<div class="pagination">
	<button class="secondary" disabled={onFirstPage} on:click={onPrev}>← Previous</button>
	<span class="status muted">
		{#if loading && total === 0}
			&nbsp;
		{:else if total === 0}
			No results
		{:else if compact}
			Page {fmt(page)} of {fmt(totalPages)} · {fmt(first)}–{fmt(last)} of {fmt(total)}
		{:else}
			Page {fmt(page)} of {fmt(totalPages)} · showing {fmt(first)}–{fmt(last)} of {fmt(total)}
		{/if}
	</span>
	<button class="secondary" disabled={onLastPage} on:click={onNext}>Next →</button>
</div>
