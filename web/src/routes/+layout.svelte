<script>
	import '../app.css';
</script>

<div class="app-shell">
	<header class="topbar">
		<a class="brand" href="/">FCC ULS Explorer</a>
		<nav>
			<a href="/amateur">Amateur</a>
			<a href="/towers">Towers</a>
			<a href="/watches">My Watches</a>
			<a href="/login">Sign in</a>
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
