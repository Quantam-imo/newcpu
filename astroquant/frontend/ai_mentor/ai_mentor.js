async function loadMentorV3() {
	const symbol = ((document.getElementById("chartSymbol") || {}).value) || "GC.FUT";
	const r = await fetch(`/mentor?symbol=${encodeURIComponent(symbol)}`);
	const d = await r.json();
	const c = d.context || {};
	const l = d.liquidity || {};
	const i = d.institution || {};
	const ict = d.ict || {};
	const g = d.gann || {};
	const gs = (g.signals && typeof g.signals === "object") ? g.signals : {};
	const angle = g.angle || gs.angle || {};
	const square9 = g.square_of_9 || gs.square_of_9 || {};
	const priceTime = g.price_time || gs.price_time || {};
	const octave = g.octave || gs.octave || {};
	const planet = g.planet_alignment || gs.planet_alignment || {};
	const a = d.astro || {};
	const n = d.news || {};
	const s = d.session || {};
	const p = d.probability || {};

	const gStatus = g.enabled === false
		? "OFF"
		: (g.detected ? `${g.direction || "--"} ${g.confidence != null ? `${Number(g.confidence).toFixed(1)}%` : ""}`.trim() : "NO SIGNAL");
	const gConcepts = [
		`Score ${g.score ?? "--"}`,
		`Cross ${g.cross ?? "--"}`,
		`Deg ${g.degree ?? "--"}`,
		`Vib ${g.vibration ?? "--"}`,
		`C144 ${g.cycle_144 ? "Y" : "N"}`,
		`A9 ${square9.level ?? "--"}`,
		`PT ${priceTime.aligned ? "Y" : "N"}`,
		`Ang ${angle.angle ?? "--"}`,
		`Oct ${octave.zone ?? "--"}`,
		`Plan ${planet.score ?? "--"}`,
	].join(" | ");
	const gClass = g.enabled === false
		? "gann-off"
		: (!g.detected ? "gann-none" : (String(g.direction || "").toUpperCase() === "SELL" ? "gann-sell" : "gann-buy"));

	document.getElementById("mentorContext").innerHTML = `Price: <span class="live">${c.price ?? "--"}</span>`;
	document.getElementById("mentorLiquidity").innerHTML = `Liquidity Target: ${l.external_high ?? "--"}`;
	document.getElementById("mentorInstitution").innerHTML = `Delta: ${i.delta ?? "--"}`;
	document.getElementById("mentorICT").innerHTML = `ICT Event: ${ict.turtle_soup ?? "--"}`;
	const mentorGannEl = document.getElementById("mentorGann");
	if (mentorGannEl) {
		mentorGannEl.classList.remove("gann-off", "gann-none", "gann-buy", "gann-sell");
		mentorGannEl.classList.add(gClass);
		mentorGannEl.innerHTML = `Gann: ${gStatus} | T1 ${g.target_100 ?? "--"} | T2 ${g.target_200 ?? "--"}<br/>${gConcepts}`;
	}
	document.getElementById("mentorAstro").innerHTML = `Astro Event: ${a.planet_event ?? "--"}`;
	document.getElementById("mentorNews").innerHTML = `News: ${n.next_event ?? "--"}`;
	document.getElementById("mentorSession").innerHTML = `Session Phase: ${s.phase ?? "--"}`;
	document.getElementById("mentorProbability").innerHTML = `Probability: ${p.score ?? 0}%`;
	document.getElementById("mentorStory").textContent = d.story || "--";
}
