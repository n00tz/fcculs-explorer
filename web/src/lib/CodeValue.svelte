<script>
	// Renders a coded field value with its definition attached: short
	// (single-word) definitions are shown inline in parentheses so they
	// stay readable in a narrow table column or pill on mobile; longer
	// definitions are shown only as a mouseover tooltip (`.hint`) so they
	// never break layout. Unmapped codes render unchanged with no
	// decoration -- this is deliberately "best effort, never blocking".
	import { describeCode, isShortDescription } from './fieldDefs.js';

	export let code;
	export let category;
	export let placeholder = '—';

	$: description = describeCode(category, code);
	$: short = isShortDescription(description);
</script>

{#if !code}
	{placeholder}
{:else if !description}
	{code}
{:else if short}
	{code} <span class="muted">({description})</span>
{:else}
	{code}<span class="hint" title={description}>?</span>
{/if}
