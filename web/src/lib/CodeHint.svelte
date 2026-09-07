<script>
	// Renders just the definition suffix for a coded value that's already
	// being displayed elsewhere (e.g. inside a link) -- a short (single
	// word) description in parentheses, or a mouseover `.hint` tooltip for
	// longer descriptions, matching the same "never break layout" rule as
	// CodeValue.svelte. Renders nothing if the code is blank or unmapped.
	import { describeCode, isShortDescription } from './fieldDefs.js';

	export let category;
	export let code;
</script>

{#if code}
	{@const description = describeCode(category, code)}
	{#if description}
		{#if isShortDescription(description)}
			<span class="muted">({description})</span>
		{:else}
			<span class="hint" title={description}>?</span>
		{/if}
	{/if}
{/if}
