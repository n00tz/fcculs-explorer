<!--
	Original inline artwork (no external assets, no license/attribution
	concerns): a broadcast tower emitting concentric "on the air" signal
	arcs, paired with a small connected cluster of nodes representing a
	group of related identities (the FRN/callsign/tower "identity
	grouping" feature). Colored entirely from the site's existing dark
	theme CSS variables (--text, --text-dim, --accent, --surface-alt,
	--bg) so it stays consistent if the palette is ever retuned, with a
	subtle pulse animation that respects prefers-reduced-motion.
-->
<div class="hero-graphic" aria-hidden="true">
	<svg viewBox="0 0 480 320" preserveAspectRatio="xMidYMid meet" role="img">
		<title>Broadcast tower emitting signal arcs, linked to a cluster of related identity nodes</title>

		<!-- signal arcs, radiating up-right from the tower's beacon -->
		<path
			class="signal-arc"
			style="--arc-op: 0.9; animation-delay: 0s;"
			d="M 174.66 52.61 A 18 18 0 0 1 187.39 65.34"
		/>
		<path
			class="signal-arc"
			style="--arc-op: 0.7; animation-delay: 0.3s;"
			d="M 179.3 35.2 A 36 36 0 0 1 204.8 60.7"
		/>
		<path
			class="signal-arc"
			style="--arc-op: 0.5; animation-delay: 0.6s;"
			d="M 183.98 17.84 A 54 54 0 0 1 222.2 56.03"
		/>
		<path
			class="signal-arc"
			style="--arc-op: 0.32; animation-delay: 0.9s;"
			d="M 188.1 2.4 A 70 70 0 0 1 237.6 51.9"
		/>

		<!-- tower lattice -->
		<g class="tower-lines">
			<line x1="170" y1="100" x2="125" y2="280" />
			<line x1="170" y1="100" x2="215" y2="280" />
			<line x1="157.5" y1="150" x2="182.5" y2="150" />
			<line x1="147.5" y1="190" x2="192.5" y2="190" />
			<line x1="137.5" y1="230" x2="202.5" y2="230" />
			<line x1="125" y1="280" x2="215" y2="280" />
			<line x1="157.5" y1="150" x2="192.5" y2="190" />
			<line x1="182.5" y1="150" x2="147.5" y2="190" />
			<line x1="147.5" y1="190" x2="202.5" y2="230" />
			<line x1="192.5" y1="190" x2="137.5" y2="230" />
			<line x1="137.5" y1="230" x2="215" y2="280" />
			<line x1="202.5" y1="230" x2="125" y2="280" />
			<line x1="170" y1="100" x2="170" y2="70" />
		</g>

		<!-- beacon at the mast tip -->
		<circle class="beacon-dot" cx="170" cy="68" r="4" />

		<!-- cluster of related identities, one highlighted (the record you're watching) -->
		<g class="identity-cluster">
			<line x1="300" y1="200" x2="340" y2="170" />
			<line x1="300" y1="200" x2="350" y2="230" />
			<line x1="300" y1="200" x2="305" y2="250" />
			<circle class="node-peer" cx="340" cy="170" r="6" />
			<circle class="node-peer" cx="350" cy="230" r="6" />
			<circle class="node-peer" cx="305" cy="250" r="6" />
			<circle class="node-watched" cx="300" cy="200" r="9" />
		</g>
	</svg>
</div>
