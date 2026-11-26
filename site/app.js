(() => {
  const STEPS_PER_ROW = 3;
  const STORAGE_KEY = "synthesis_finder_progress_v1";
  const THEME_KEY = "synthesis_finder_theme_v1";

  const state = {
    catalog: [],
    updatedAt: null,
    currentProblem: null,
    currentEntry: null,
    progress: loadProgress(),
    hideReagents: false,
    hideProducts: false,
    activeGalaxy: null,
  };

  const els = {
    catalogView: document.getElementById("catalogView"),
    problemView: document.getElementById("problemView"),
    updatedLabel: document.getElementById("updatedLabel"),
    heroReactionCount: document.getElementById("heroReactionCount"),
    heroProblemCount: document.getElementById("heroProblemCount"),
    heroProgressLabel: document.getElementById("heroProgressLabel"),
    heroProgressFill: document.getElementById("heroProgressFill"),
    galaxyStage: document.getElementById("galaxyStage"),
    galaxyCanvas: document.getElementById("galaxyCanvas"),
    galaxyTooltip: document.getElementById("galaxyTooltip"),
    ttFam: document.getElementById("ttFam"),
    ttName: document.getElementById("ttName"),
    ttMeta: document.getElementById("ttMeta"),
    searchInput: document.getElementById("searchInput"),
    difficultyFilter: document.getElementById("difficultyFilter"),
    journalFilter: document.getElementById("journalFilter"),
    progressFilter: document.getElementById("progressFilter"),
    clearGalaxyFilter: document.getElementById("clearGalaxyFilter"),
    statsRow: document.getElementById("statsRow"),
    catalogGrid: document.getElementById("catalogGrid"),
    emptyState: document.getElementById("emptyState"),
    backToCatalog: document.getElementById("backToCatalog"),
    problemLinks: document.getElementById("problemLinks"),
    problemHeader: document.getElementById("problemHeader"),
    snakeBoard: document.getElementById("snakeBoard"),
    btnHideReagents: document.getElementById("btnHideReagents"),
    btnHideProducts: document.getElementById("btnHideProducts"),
    btnStepByStep: document.getElementById("btnStepByStep"),
    btnRevealAll: document.getElementById("btnRevealAll"),
    btnBookmark: document.getElementById("btnBookmark"),
    btnMarkSolved: document.getElementById("btnMarkSolved"),
    btnSnakeHtml: document.getElementById("btnSnakeHtml"),
    themeToggle: document.getElementById("themeToggle"),
  };

  function loadProgress() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    } catch {
      return {};
    }
  }

  function saveProgress() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.progress));
  }

  function getStatus(id) {
    return state.progress[id] || { solved: false, bookmarked: false };
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY) || "light";
    document.documentElement.setAttribute("data-theme", saved);
    els.themeToggle.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", cur);
      localStorage.setItem(THEME_KEY, cur);
    });
  }

  async function loadCatalog() {
    try {
      const resp = await fetch("data/catalog.json?v=" + Date.now());
      const data = await resp.json();
      state.catalog = data.problems || [];
      state.updatedAt = data.updated_at || data.generated_at || null;
      els.updatedLabel.textContent = state.updatedAt
        ? "Updated " + new Date(state.updatedAt).toLocaleDateString()
        : `${state.catalog.length} problems`;
      if (els.heroProblemCount) {
        els.heroProblemCount.textContent = String(state.catalog.length);
      }
      populateJournalFilter();
      handleRoute();
    } catch (err) {
      els.updatedLabel.textContent = "Catalog unavailable";
      els.emptyState.textContent = "Failed to load data/catalog.json.";
      els.emptyState.classList.remove("hidden");
    }
  }

  function populateJournalFilter() {
    const journals = [...new Set(state.catalog.map(p => p.journal).filter(Boolean))].sort();
    journals.forEach(j => {
      const opt = document.createElement("option");
      opt.value = j;
      opt.textContent = j;
      els.journalFilter.appendChild(opt);
    });
  }

  const GALAXIES = [
    {
      id: "aldol",
      label: "Aldol & Enolate",
      type: "spiral",
      typeLabel: "Spiral Galaxy",
      rx: 0.20,
      ry: 0.30,
      rz: 24,
      tiltX: 0.58,
      tiltY: -0.22,
      spinSpeed: 0.0020,
      color: "#a3e635",
      lightColor: "#15803d",
      stars: [
        "Mukaiyama Aldol", "Evans Aldol", "Mannich Reaction", "Claisen Condensation",
        "Dieckmann Condensation", "Robinson Annulation", "Michael Addition", "Henry Nitroaldol",
        "Knoevenagel Condensation", "Darzens Glycidic Ester", "Reformatsky Reaction", "Stobbe Condensation",
        "Baylis-Morita-Hillman", "Stork Enamine Alkylation", "Ireland-Claisen", "Johnson-Claisen",
        "Eschenmoser-Claisen", "Carroll Rearrangement", "Overman-Claisen", "Paterson Boron Aldol",
        "Crimmins Thiazolidinethione", "Hajime-Parrish-Sauer", "List-MacMillan Organoaldol", "Tishchenko Reaction",
        "Evans-Tishchenko", "Katsuki-Sharpless Aldol", "Masamune Aldol", "Noyori Mukaiyama",
        "Kobayashi Lanthanide Aldol", "Silyl Enol Ether Allylation", "Hosomi-Sakurai", "Conia-Ene",
        "Vinylogous Mukaiyama", "Keck Asymmetric Allylation", "Brown Allylboration", "Roush Allylation",
        "Corey-Chaykovsky", "Wittig Olefination", "Horner-Wadsworth-Emmons", "Julia-Kocienski",
        "Peterson Olefination", "Tebbe Olefination", "Petasis Olefination", "Takai-Utimoto"
      ],
      keywords: ["aldol", "enolate", "mannich", "claisen", "ketone", "ester"],
    },
    {
      id: "photo",
      label: "[2+2] & Photochem",
      type: "ring",
      typeLabel: "Ring Galaxy",
      rx: 0.50,
      ry: 0.25,
      rz: -32,
      tiltX: 0.72,
      tiltY: 0.24,
      spinSpeed: -0.0016,
      color: "#38bdf8",
      lightColor: "#1d4ed8",
      stars: [
        "Paterno-Buchi", "[2+2] Enone-Alkene", "Norrish Type I", "Norrish Type II",
        "Barton Nitrite Photolysis", "de Mayo Reaction", "Di-pi-Methane", "Oxa-Di-pi-Methane",
        "Schenck Ene Reaction", "Singlet Oxygen [4+2]", "Photo-Fries", "Photochemical Beckmann",
        "Yang Cyclization", "Aza-Paterno-Buchi", "Nicewicz Photoredox", "MacMillan Photoredox",
        "Stephenson Photoredox", "Yoon [2+2] Photoredox", "Aza-Photocycloaddition", "Meta-Arene-Alkene",
        "Ortho-Arene-Alkene", "Photo-Nazarov", "Photo-Favorskii", "Barton-McCombie Photo",
        "Wender [5+2] Photo", "Crimmins [2+2]", "Carreira Photo-Ring", "Bach Enantio [2+2]",
        "Griesbeck Decarboxylation", "Saito-Matsuura", "ciamician-Silber", "Mallory Photocyclization",
        "Katz Stilbene Photo", "Wolff Photo-Arndt-Eistert", "Photo-Cope", "Photo-Claisen"
      ],
      keywords: ["photo", "2+2", "paterno", "artemisinin", "endoperoxide", "singlet oxygen", "light"],
    },
    {
      id: "coupling",
      label: "Cross-Coupling",
      type: "barred",
      typeLabel: "Barred Spiral",
      rx: 0.80,
      ry: 0.31,
      rz: 18,
      tiltX: 0.48,
      tiltY: -0.28,
      spinSpeed: 0.0018,
      color: "#f472b6",
      lightColor: "#be185d",
      stars: [
        "Suzuki-Miyaura", "Buchwald-Hartwig", "Stille Coupling", "Mizoroki-Heck",
        "Sonogashira Coupling", "Negishi Coupling", "Kumada-Corriu", "Hiyama-Denmark",
        "Tsuji-Trost Allylation", "Ullmann Biaryl", "Chan-Lam-Evans", "Castro-Stephens",
        "Glaser-Hay Coupling", "Cadiot-Chodkiewicz", "Liebeskind-Srogl", "Fukuyama Coupling",
        "Fu Alkyl Suzuki", "Hartwig C-H Borylation", "Miyaura Borylation", "Larock Indole",
        "Catellani Reaction", "Fagnou Direct Arylation", "Tamao-Kumada", "McMurry Coupling",
        "Nozaki-Hiyama-Kishi", "Pauson-Khand", "Nicholas Reaction", "Kulinkovich Cyclopropanation",
        "Fujiwara-Moritani", "Wacker Oxidation", "Grubbs Ring-Closing", "Schrock Metathesis",
        "Hoveyda-Grubbs", "Alkyne Metathesis", "Enyne Metathesis", "Baran Cross-Electrophile",
        "Weix Cross-Electrophile", "MacMillan Metallaphotoredox", "Garg Nickel Coupling", "Molander Trifluoroborate"
      ],
      keywords: ["coupling", "suzuki", "heck", "stille", "buchwald", "sonogashira", "palladium"],
    },
    {
      id: "pericyclic",
      label: "Pericyclic",
      type: "elliptical",
      typeLabel: "Elliptical Galaxy",
      rx: 0.27,
      ry: 0.72,
      rz: -14,
      tiltX: 0.38,
      tiltY: 0.35,
      spinSpeed: 0.0010,
      color: "#fbbf24",
      lightColor: "#b45309",
      stars: [
        "Diels-Alder [4+2]", "Aza-Diels-Alder", "Oxo-Diels-Alder", "Inverse-Demand Diels-Alder",
        "Cope Rearrangement", "Oxy-Cope", "Anionic Oxy-Cope", "Aza-Cope",
        "Zincke Ring-Opening", "Nazarov Cyclization", "Imino-Nazarov", "Huisgen 1,3-Dipolar",
        "Sharpless Click CuAAC", "Boger [4+2]", "Danishefsky Diene [4+2]", "Rawal Diene [4+2]",
        "Prins Cyclization", "Alder-Ene Reaction", "Carbonyl-Ene", "Conia-Ene",
        "Wender [5+2]", "Wender [4+4]", "Trost [3+2] TMM", "Gassman [2+2+1]",
        "Vollhardt [2+2+2]", "Danheiser Annulation", "Myers Allenyl-Propargyl", "Bergman Cyclization",
        "Myers-Saito Cyclization", "Schmittel Cyclization", "Ramberg-Backlund", "Sommelet-Hauser",
        "Stevens [1,2]-Shift", "Wittig [2,3]-Shift", "Mislow-Evans [2,3]", "Meisenheimer [2,3]"
      ],
      keywords: ["diels", "cope", "zincke", "nazarov", "pericyclic", "cascade", "electrocyclic", "cycloaddition", "strychnine"],
    },
    {
      id: "radical",
      label: "Radical & Electro",
      type: "multiarm",
      typeLabel: "Multi-Arm Spiral",
      rx: 0.56,
      ry: 0.74,
      rz: 30,
      tiltX: 0.52,
      tiltY: 0.16,
      spinSpeed: -0.0021,
      color: "#c084fc",
      lightColor: "#7e22ce",
      stars: [
        "Minisci Reaction", "Kolbe Electrolysis", "Giese Radical Addition", "Barton-McCombie",
        "Barton Decarboxylation", "Hunsdiecker Reaction", "Kharasch Addition", "Keck Radical Allylation",
        "Ueno-Stork Cyclization", "Snider Mn(III) Oxidative", "Baran Radical Cross-Coupling", "Mukaiyama Hydration",
        "Shono Oxidation", "Non-Kolbe Hofer-Moest", "Crum-Brown-Walker", "Hofmann-Loffler-Freytag",
        "Suarez Alkoxy Radical", "Zard Xanthate Transfer", "Curran Radical Cascade", "Renaud Azidation",
        "Studer Silyl Radical", "MacMillan Somo", "Nicewicz Hydroamination", "Rovis Co-H HAT",
        "Shenvi MHAT", "Herzon Radical Reduction", "Lin Electrocatalytic", "Baran Electro-Birch",
        "Birch Reduction", "Bouveault-Blanc", "Pinacol Coupling", "McMurry Radical",
        "Wurtz Coupling", "Sandmeyer Reaction", "Gomberg-Bachmann", "Pschorr Cyclization"
      ],
      keywords: ["radical", "minisci", "kolbe", "giese", "c-h activation", "electro"],
    },
    {
      id: "redox",
      label: "Oxidation / Red",
      type: "lenticular",
      typeLabel: "Lenticular Galaxy",
      rx: 0.82,
      ry: 0.70,
      rz: -22,
      tiltX: 1.12,
      tiltY: -0.32,
      spinSpeed: 0.0015,
      color: "#2dd4bf",
      lightColor: "#0f766e",
      stars: [
        "Sharpless Epoxidation", "Sharpless Dihydroxylation", "Sharpless Aminohydroxylation", "Jacobsen-Katsuki",
        "Shi Epoxidation", "Prilezhaev mCPBA", "Swern Oxidation", "Dess-Martin Periodinane",
        "IBX Oxidation", "Ley-Griffith TPAP", "Corey-Kim Oxidation", "Pfitzner-Moffatt",
        "Parikh-Doering", "Oppenauer Oxidation", "Jones Oxidation", "Collins Oxidation",
        "Baeyer-Villiger", "Dakin Oxidation", "Rubottom Oxidation", "Davis Oxaziridine",
        "Riley SeO2 Allylic", "Upjohn Dihydroxylation", "Lemieux-Johnson", "Malaprade Cleavage",
        "Criegee Cleavage", "Mitsunobu Inversion", "Luche Reduction", "Corey-Bakshi-Shibata",
        "Noyori Asymmetric Hydrogenation", "Lindlar Hydrogenation", "Wilkinson Hydrogenation", "Crabtree Hydrogenation",
        "Wolff-Kishner", "Clemmensen Reduction", "Mozingo Desulfurization", "DIBAL-H Reduction",
        "Midland Alpine-Borane", "Brown Hydroboration", "Tamao-Fleming", "Kornblum Oxidation"
      ],
      keywords: ["oxidation", "reduction", "epoxidation", "sharpless", "swern", "dess-martin", "mitsunobu", "peroxide"],
    },
  ];

  function problemMatchesGalaxy(item, galaxyId) {
    if (!galaxyId) return true;
    const galaxy = GALAXIES.find(g => g.id === galaxyId);
    if (!galaxy) return true;
    const hay = [
      item.id,
      item.target_molecule,
      item.title,
      ...(item.tags || []),
    ].join(" ").toLowerCase();
    return galaxy.keywords.some(kw => hay.includes(kw));
  }

  function renderCatalog() {
    const q = els.searchInput.value.trim().toLowerCase();
    const diff = els.difficultyFilter.value.toLowerCase();
    const journal = els.journalFilter.value;
    const prog = els.progressFilter.value;

    const filtered = state.catalog.filter(item => {
      if (!problemMatchesGalaxy(item, state.activeGalaxy)) return false;
      if (diff && (item.difficulty || "").toLowerCase() !== diff) return false;
      if (journal && item.journal !== journal) return false;
      const st = getStatus(item.id);
      if (prog === "solved" && !st.solved) return false;
      if (prog === "unsolved" && st.solved) return false;
      if (prog === "bookmarked" && !st.bookmarked) return false;
      if (q) {
        const hay = [
          item.target_molecule,
          item.title,
          item.journal,
          ...(item.tags || []),
          ...(item.authors || []),
        ].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const activeGalaxyObj = GALAXIES.find(g => g.id === state.activeGalaxy);
    if (els.clearGalaxyFilter) {
      els.clearGalaxyFilter.classList.toggle("hidden", !activeGalaxyObj);
      els.clearGalaxyFilter.textContent = activeGalaxyObj ? `Clear: ${activeGalaxyObj.label} ×` : "Clear Galaxy";
    }

    const solvedCount = state.catalog.filter(i => getStatus(i.id).solved).length;
    if (els.heroProgressLabel && els.heroProgressFill) {
      const pct = state.catalog.length ? Math.round((solvedCount / state.catalog.length) * 100) : 0;
      els.heroProgressLabel.textContent = `${solvedCount} / ${state.catalog.length} solved`;
      els.heroProgressFill.style.width = `${pct}%`;
    }
    const galaxySuffix = activeGalaxyObj ? ` · Galaxy: ${activeGalaxyObj.label}` : "";
    els.statsRow.textContent = `Showing ${filtered.length} of ${state.catalog.length} total syntheses · ${solvedCount} solved${galaxySuffix}`;

    els.catalogGrid.innerHTML = "";
    els.emptyState.classList.toggle("hidden", filtered.length > 0);

    filtered.forEach(item => {
      const st = getStatus(item.id);
      const card = document.createElement("article");
      card.className = "problem-card";
      card.onclick = () => {
        window.location.hash = `#/problem/${encodeURIComponent(item.id)}`;
      };

      const tagsHtml = (item.tags || []).slice(0, 3).map(t => `<span class="pill">${escapeHtml(t)}</span>`).join("");
      const solvedBadge = st.solved ? `<span class="pill pill-solved">Solved</span>` : "";
      const bookmarkBadge = st.bookmarked ? `<span class="pill pill-accent">Saved</span>` : "";

      card.innerHTML = `
        <div>
          <div class="card-top">
            <div class="card-target">${escapeHtml(item.target_molecule || item.title)}</div>
            <span class="pill pill-accent">${item.num_steps || 0} steps</span>
          </div>
          <div class="card-title">${escapeHtml(item.title)}</div>
        </div>
        <div class="card-meta">
          <span class="pill">${escapeHtml((item.difficulty || "intermediate").toLowerCase())}</span>
          ${solvedBadge}
          ${bookmarkBadge}
          ${tagsHtml}
        </div>
        <div class="card-footer">
          <span>${escapeHtml(item.journal || "Open Access")}</span>
          <span>${escapeHtml(item.year || "")}</span>
        </div>
      `;
      els.catalogGrid.appendChild(card);
    });
  }

  async function openProblem(id) {
    const entry = state.catalog.find(p => p.id === id);
    if (!entry) {
      showCatalogView();
      return;
    }
    state.currentEntry = entry;
    els.catalogView.classList.add("hidden");
    els.problemView.classList.remove("hidden");
    els.snakeBoard.innerHTML = `<div class="empty-state">Loading synthesis…</div>`;

    try {
      const resp = await fetch("data/" + entry.problem_file + "?v=" + Date.now());
      const problem = await resp.json();
      state.currentProblem = problem;
      state.hideReagents = false;
      state.hideProducts = false;
      renderProblemView(problem, entry);
    } catch {
      els.snakeBoard.innerHTML = `<div class="empty-state">Failed to load problem JSON.</div>`;
    }
  }

  function renderVisualHtml(imageUri, svgStr, label) {
    if (imageUri && imageUri.startsWith("data:image/")) {
      return `<img src="${escapeHtml(imageUri)}" alt="${escapeHtml(label)}">`;
    }
    if (svgStr && svgStr.includes("<svg")) {
      return svgStr;
    }
    return `<span style="color:#64748b;font-size:0.85rem;">${escapeHtml(label)}</span>`;
  }

  function renderProblemView(problem, entry) {
    const authors = (problem.authors || []).slice(0, 5).join(", ") + ((problem.authors || []).length > 5 ? " et al." : "");
    const meta = [authors, problem.journal, problem.year].filter(Boolean).map(escapeHtml).join(" · ");

    els.problemHeader.innerHTML = `
      <h1>${escapeHtml(problem.title || problem.target_molecule)}</h1>
      <div class="problem-header-meta">${meta}</div>
    `;

    const links = [];
    if (problem.doi) {
      links.push(`<a class="btn btn-ghost" href="https://doi.org/${encodeURIComponent(problem.doi)}" target="_blank" rel="noopener">DOI</a>`);
    }
    if (problem.pdf_url) {
      links.push(`<a class="btn btn-ghost" href="${escapeHtml(problem.pdf_url)}" target="_blank" rel="noopener">PDF</a>`);
    }
    els.problemLinks.innerHTML = links.join("");

    if (entry.html_file) {
      els.btnSnakeHtml.href = "data/" + entry.html_file;
      els.btnSnakeHtml.classList.remove("hidden");
    } else {
      els.btnSnakeHtml.classList.add("hidden");
    }

    updateActionButtons();
    renderSnakeBoard(problem);
  }

  function renderSnakeBoard(problem) {
    const steps = problem.steps || [];
    const rows = [];

    const makeMolCard = (visualHtml, isStart, stepIndex) => {
      const cls = isStart ? "mol-card start-card" : "mol-card product-card";
      const badge = isStart ? "Starting Material" : `Intermediate ${stepIndex}`;
      return `
        <div class="${cls}" ${isStart ? "" : 'data-toggle="1"'}>
          <div class="mol-badge">${badge}</div>
          <div class="mol-visual">${visualHtml}</div>
        </div>
      `;
    };

    const makeArrow = (step, dir) => {
      const conds = [step.conditions, step.yield].filter(Boolean).map(escapeHtml).join(" · ");
      const arrow = dir === "ltr" ? "&#8594;" : "&#8592;";
      return `
        <div class="step-arrow" title="${escapeHtml(step.notes || "")}">
          <div class="reagent-box" data-toggle="1">
            <span class="step-badge">Step ${step.step_index}</span>
            ${step.named_reaction ? `<div class="named-rxn">${escapeHtml(step.named_reaction)}</div>` : ""}
            <div class="reagents-text">${escapeHtml(step.reagents || "—")}</div>
            ${conds ? `<div class="cond-text">${conds}</div>` : ""}
          </div>
          <div class="arrow-line">${arrow}</div>
        </div>
      `;
    };

    const startVis = renderVisualHtml(problem.start_image, problem.start_svg, "Starting Material");
    if (steps.length === 0) {
      rows.push(`<div class="snake-row-wrap"><div class="snake-row ltr">${makeMolCard(startVis, true, 0)}</div></div>`);
    } else {
      const numRows = Math.ceil(steps.length / STEPS_PER_ROW);
      for (let r = 0; r < numRows; r++) {
        const chunk = steps.slice(r * STEPS_PER_ROW, (r + 1) * STEPS_PER_ROW);
        const dir = r % 2 === 0 ? "ltr" : "rtl";
        const items = [];
        if (r === 0) items.push(makeMolCard(startVis, true, 0));
        chunk.forEach(st => {
          const pVis = renderVisualHtml(st.product_image, st.product_svg, `Step ${st.step_index}`);
          items.push(makeArrow(st, dir));
          items.push(makeMolCard(pVis, false, st.step_index));
        });
        if (dir === "rtl") items.reverse();
        rows.push(`<div class="snake-row-wrap"><div class="snake-row ${dir}">${items.join("")}</div></div>`);
        if (r < numRows - 1) {
          const turnCls = dir === "ltr" ? "turn-right" : "turn-left";
          rows.push(`<div class="snake-turn ${turnCls}">&#8595;</div>`);
        }
      }
    }

    els.snakeBoard.innerHTML = rows.join("");
    els.snakeBoard.querySelectorAll('[data-toggle="1"]').forEach(el => {
      el.addEventListener("click", () => el.classList.toggle("is-hidden"));
    });
  }

  function updateActionButtons() {
    if (!state.currentEntry) return;
    const st = getStatus(state.currentEntry.id);
    els.btnMarkSolved.textContent = st.solved ? "Solved ✓" : "Mark Solved";
    els.btnBookmark.textContent = st.bookmarked ? "Bookmarked ★" : "Bookmark";
    els.btnHideReagents.classList.toggle("active", state.hideReagents);
    els.btnHideProducts.classList.toggle("active", state.hideProducts);
  }

  function showCatalogView() {
    els.problemView.classList.add("hidden");
    els.catalogView.classList.remove("hidden");
    renderCatalog();
  }

  function handleRoute() {
    const hash = window.location.hash || "#/";
    const match = hash.match(/^#\/problem\/(.+)$/);
    if (match) {
      openProblem(decodeURIComponent(match[1]));
    } else {
      showCatalogView();
    }
  }

  function bindEvents() {
    [els.searchInput, els.difficultyFilter, els.journalFilter, els.progressFilter].forEach(el => {
      el.addEventListener("input", renderCatalog);
      el.addEventListener("change", renderCatalog);
    });

    els.backToCatalog.addEventListener("click", () => {
      window.location.hash = "#/";
    });

    els.btnHideReagents.addEventListener("click", () => {
      state.hideReagents = !state.hideReagents;
      els.snakeBoard.querySelectorAll(".reagent-box").forEach(el => el.classList.toggle("is-hidden", state.hideReagents));
      updateActionButtons();
    });

    els.btnHideProducts.addEventListener("click", () => {
      state.hideProducts = !state.hideProducts;
      els.snakeBoard.querySelectorAll(".product-card").forEach(el => el.classList.toggle("is-hidden", state.hideProducts));
      updateActionButtons();
    });

    els.btnStepByStep.addEventListener("click", () => {
      state.hideReagents = true;
      state.hideProducts = true;
      els.snakeBoard.querySelectorAll(".reagent-box, .product-card").forEach(el => el.classList.add("is-hidden"));
      updateActionButtons();
    });

    els.btnRevealAll.addEventListener("click", () => {
      state.hideReagents = false;
      state.hideProducts = false;
      els.snakeBoard.querySelectorAll(".is-hidden").forEach(el => el.classList.remove("is-hidden"));
      updateActionButtons();
    });

    els.btnMarkSolved.addEventListener("click", () => {
      if (!state.currentEntry) return;
      const id = state.currentEntry.id;
      const cur = getStatus(id);
      state.progress[id] = { ...cur, solved: !cur.solved };
      saveProgress();
      updateActionButtons();
    });

    els.btnBookmark.addEventListener("click", () => {
      if (!state.currentEntry) return;
      const id = state.currentEntry.id;
      const cur = getStatus(id);
      state.progress[id] = { ...cur, bookmarked: !cur.bookmarked };
      saveProgress();
      updateActionButtons();
    });

    if (els.clearGalaxyFilter) {
      els.clearGalaxyFilter.addEventListener("click", () => {
        state.activeGalaxy = null;
        renderCatalog();
      });
    }

    window.addEventListener("hashchange", handleRoute);
  }

  function initGalaxyObservatory() {
    const canvas = els.galaxyCanvas;
    const tooltip = els.galaxyTooltip;
    if (!canvas || !tooltip) return;
    const ctx = canvas.getContext("2d");

    function createRng(seed) {
      let s = seed >>> 0;
      return () => {
        s = (s + 0x6d2b79f5) | 0;
        let t = Math.imul(s ^ (s >>> 15), 1 | s);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }

    function gaussian(rng) {
      const u1 = Math.max(1e-6, rng());
      const u2 = rng();
      return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    }

    function rotate3D(x, y, z, rx, ry) {
      // Rotate around X then Y
      const cy = Math.cos(rx), sy = Math.sin(rx);
      const y1 = y * cy - z * sy;
      const z1 = y * sy + z * cy;
      const cx = Math.cos(ry), sx = Math.sin(ry);
      const x2 = x * cx + z1 * sx;
      const z2 = -x * sx + z1 * cx;
      return { x: x2, y: y1, z: z2 };
    }

    if (els.heroReactionCount) {
      const uniqueReactions = new Set(GALAXIES.flatMap(g => g.stars));
      els.heroReactionCount.textContent = String(uniqueReactions.size);
    }

    function buildGalaxyStars(g, gi) {
      const rng = createRng(104729 + gi * 7919);
      const stars = [];
      const rxNames = g.stars;
      const totalStars = 92;
      const coreCount = 32;
      const glyphs = ["pin", "diamond", "pin", "sparkle"];

      for (let idx = 0; idx < totalStars; idx++) {
        const reactionName = rxNames[idx % rxNames.length];
        const isCore = idx < coreCount;
        let lx = 0, ly = 0, lz = 0;
        let size = 1.7;
        let alpha = 0.64;
        let glyph = glyphs[idx % glyphs.length];

        if (isCore) {
          // Dense roughly spherical central cluster (bulge)
          const u = rng();
          const v = rng();
          const theta = 2 * Math.PI * u;
          const cosPhi = 2 * v - 1;
          const sinPhi = Math.sqrt(Math.max(0, 1 - cosPhi * cosPhi));
          const r = 11.5 * Math.pow(rng(), 0.72);
          lx = r * sinPhi * Math.cos(theta);
          ly = r * sinPhi * Math.sin(theta);
          lz = r * cosPhi;
          size = r < 4.5 ? 2.3 : 1.7;
          alpha = r < 4.5 ? 0.78 : 0.62;
          glyph = idx % 4 === 0 ? "sparkle" : (idx % 2 === 0 ? "diamond" : "pin");
        } else {
          // Tightened morphology-specific outer stars
          const oi = idx - coreCount;
          const outerTotal = totalStars - coreCount;
          const frac = oi / outerTotal;
          size = 1.65 + rng() * 1.15;
          alpha = 0.56 + rng() * 0.22;

          if (g.type === "spiral") {
            const arm = oi % 2;
            const t = 0.10 + Math.pow(frac, 0.9) * 0.90;
            const angle = arm * Math.PI + t * 2.95 * Math.PI + gaussian(rng) * 0.12;
            const rad = 11 + t * 40 + gaussian(rng) * 1.8;
            lx = Math.cos(angle) * rad;
            ly = Math.sin(angle) * rad;
            lz = gaussian(rng) * 1.8;
          } else if (g.type === "ring") {
            const angle = frac * Math.PI * 2 + gaussian(rng) * 0.08;
            const isBridge = oi < 4;
            const rad = isBridge ? (16 + rng() * 14) : (39 + gaussian(rng) * 2.6);
            lx = Math.cos(angle) * rad;
            ly = Math.sin(angle) * rad;
            lz = gaussian(rng) * 1.6;
            if (!isBridge) size = 1.85 + rng() * 1.1;
          } else if (g.type === "barred") {
            if (oi < 16) {
              const barPos = ((oi / 15) * 2 - 1) * 22;
              lx = barPos;
              ly = gaussian(rng) * 2.0;
              lz = gaussian(rng) * 1.9;
            } else {
              const arm = oi % 2;
              const sign = arm === 0 ? 1 : -1;
              const t = (oi - 16) / Math.max(1, outerTotal - 16);
              const ang = t * 1.85 * Math.PI + gaussian(rng) * 0.11;
              const rad = 22 + t * 28 + gaussian(rng) * 1.6;
              const baseAng = sign === 1 ? 0 : Math.PI;
              lx = Math.cos(baseAng + ang) * rad;
              ly = Math.sin(baseAng + ang) * rad;
              lz = gaussian(rng) * 1.7;
            }
          } else if (g.type === "elliptical") {
            const u = rng();
            const v = rng();
            const theta = 2 * Math.PI * u;
            const cosPhi = 2 * v - 1;
            const sinPhi = Math.sqrt(Math.max(0, 1 - cosPhi * cosPhi));
            const rad = 12 + 36 * Math.pow(frac, 0.78);
            lx = rad * sinPhi * Math.cos(theta);
            ly = rad * sinPhi * Math.sin(theta) * 0.64;
            lz = rad * cosPhi * 0.52;
          } else if (g.type === "multiarm") {
            const arm = oi % 5;
            const t = 0.12 + Math.pow(frac, 0.9) * 0.88;
            const angle = arm * ((Math.PI * 2) / 5) + t * 1.7 * Math.PI + gaussian(rng) * 0.13;
            const rad = 12 + t * 38 + gaussian(rng) * 1.8;
            lx = Math.cos(angle) * rad;
            ly = Math.sin(angle) * rad;
            lz = gaussian(rng) * 2.0;
          } else if (g.type === "lenticular") {
            const angle = frac * Math.PI * 2 + rng() * 0.25;
            const rad = 12 + Math.pow(frac, 0.75) * 38;
            lx = Math.cos(angle) * rad;
            ly = Math.sin(angle) * rad;
            lz = gaussian(rng) * 1.1;
          }
        }

        stars.push({
          lx,
          ly,
          lz,
          size,
          alpha,
          glyph,
          isCore,
          phase: rng() * Math.PI * 2,
          namedLabel: reactionName,
        });
      }

      return stars;
    }

    const bgRng = createRng(99173);
    const bgStars = Array.from({ length: 65 }, () => ({
      rx: bgRng() * 2 - 1,
      ry: bgRng() * 2 - 1,
      rz: -160 + bgRng() * 320,
      size: bgRng() > 0.7 ? 1.5 : 1,
      phase: bgRng() * Math.PI * 2,
    }));

    const galaxyData = GALAXIES.map((g, gi) => ({
      galaxy: g,
      stars: buildGalaxyStars(g, gi),
      projCx: 0,
      projCy: 0,
      projScale: 1,
    }));

    let width = 0;
    let height = 0;
    let tick = 0;
    let targetTiltX = 0;
    let targetTiltY = 0;
    let camTiltX = 0;
    let camTiltY = 0;
    let hoveredGalaxy = null;
    let hoveredStar = null;
    let projectedNamed = [];

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth || 720;
      height = canvas.clientHeight || 440;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function drawStarGlyph(x, y, size, glyph, color, twinkle, alpha) {
      ctx.globalAlpha = Math.max(0.06, Math.min(1, alpha));
      ctx.fillStyle = color;

      if (glyph === "pin" && !twinkle) {
        ctx.beginPath();
        ctx.arc(x, y, Math.max(0.9, size * 0.65), 0, Math.PI * 2);
        ctx.fill();
      } else if (glyph === "diamond" && !twinkle) {
        const r = Math.max(1.4, size * 1.05);
        ctx.beginPath();
        ctx.moveTo(x, y - r);
        ctx.lineTo(x + r, y);
        ctx.lineTo(x, y + r);
        ctx.lineTo(x - r, y);
        ctx.closePath();
        ctx.fill();
      } else {
        // Perfectly symmetric 4-point sparkle
        const r = Math.max(2.1, size * (twinkle ? 1.85 : 1.45));
        ctx.beginPath();
        ctx.moveTo(x, y - r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.quadraticCurveTo(x, y, x, y + r);
        ctx.quadraticCurveTo(x, y, x - r, y);
        ctx.quadraticCurveTo(x, y, x, y - r);
        ctx.closePath();
        ctx.fill();
        // Tiny symmetric core dot
        ctx.beginPath();
        ctx.arc(x, y, Math.max(0.75, r * 0.2), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function frame() {
      tick++;
      camTiltX += (targetTiltX - camTiltX) * 0.08;
      camTiltY += (targetTiltY - camTiltY) * 0.08;

      ctx.clearRect(0, 0, width, height);
      const light = document.documentElement.getAttribute("data-theme") === "light";
      const halfW = width * 0.5;
      const halfH = height * 0.5;
      const focal = 640;

      // Subtle background starfield with 3D parallax
      const bgColor = light ? "#64748b" : "#94a3b8";
      bgStars.forEach(bs => {
        const p = rotate3D(bs.rx * halfW * 1.1, bs.ry * halfH * 1.1, bs.rz, camTiltX * 0.65, camTiltY * 0.65);
        const scale = focal / (focal + p.z);
        const sx = halfW + p.x * scale;
        const sy = halfH + p.y * scale;
        const tw = 0.16 + 0.12 * Math.sin(tick * 0.04 + bs.phase);
        drawStarGlyph(sx, sy, bs.size * 0.75, "pin", bgColor, false, tw);
      });

      const drawList = [];
      projectedNamed = [];

      galaxyData.forEach(gd => {
        const g = gd.galaxy;
        const isHoveredGal = hoveredGalaxy === g;
        const isActiveGal = state.activeGalaxy === g.id;
        const baseColor = light ? g.lightColor : g.color;
        const coreColor = light ? g.lightColor : "#f8fafc";

        const gx0 = (g.rx - 0.5) * width;
        const gy0 = (g.ry - 0.5) * height;
        const gz0 = g.rz;
        const gCam = rotate3D(gx0, gy0, gz0, camTiltX, camTiltY);
        const gScale = focal / (focal + gCam.z);
        gd.projCx = halfW + gCam.x * gScale;
        gd.projCy = halfH + gCam.y * gScale;
        gd.projScale = gScale;

        // Soft nebula / bulge glow per galaxy
        const glowRadius = 56 * gScale;
        const grad = ctx.createRadialGradient(gd.projCx, gd.projCy, 2, gd.projCx, gd.projCy, glowRadius);
        const glowAlpha = isHoveredGal ? (light ? 0.14 : 0.18) : (light ? 0.07 : 0.09);
        ctx.save();
        ctx.globalAlpha = (state.activeGalaxy && !isActiveGal && !isHoveredGal) ? glowAlpha * 0.4 : glowAlpha;
        grad.addColorStop(0, baseColor);
        grad.addColorStop(1, "transparent");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(gd.projCx, gd.projCy, glowRadius, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        const spin = tick * g.spinSpeed;
        const cosSpin = Math.cos(spin);
        const sinSpin = Math.sin(spin);

        gd.stars.forEach(st => {
          // Local spin around galaxy's own Z axis
          const sx0 = st.lx * cosSpin - st.ly * sinSpin;
          const sy0 = st.lx * sinSpin + st.ly * cosSpin;
          const sz0 = st.lz;

          // Apply galaxy's own 3D inclination
          const tilted = rotate3D(sx0, sy0, sz0, g.tiltX, g.tiltY);

          // Translate to galaxy world coordinates & apply global OpenRouter-like 3D camera tilt
          const wx = gx0 + tilted.x;
          const wy = gy0 + tilted.y;
          const wz = gz0 + tilted.z;
          const camP = rotate3D(wx, wy, wz, camTiltX, camTiltY);
          const scale = focal / (focal + camP.z);
          const px = halfW + camP.x * scale;
          const py = halfH + camP.y * scale;

          const depthFade = Math.max(0.45, Math.min(1.1, scale));
          const isThisStarHover = hoveredStar && hoveredStar.star === st;

          // Gentle twinkle/shimmer when hovering over the galaxy
          const hoverShimmer = isHoveredGal
            ? 0.65 + 0.45 * Math.sin(tick * 0.16 + st.phase)
            : 1;
          const twinkle = Boolean(isThisStarHover || (isHoveredGal && Math.sin(tick * 0.16 + st.phase) > 0.72));
          const boost = isThisStarHover ? 1.5 : (isHoveredGal ? 1.28 * hoverShimmer : (isActiveGal ? 1.2 : 1));
          const dimOther = (state.activeGalaxy && !isActiveGal && !isHoveredGal) ? 0.58 : 1;

          const item = {
            x: px,
            y: py,
            z: camP.z,
            size: (isThisStarHover ? 3.2 : st.size * scale) * (isHoveredGal ? 1.08 : 1),
            glyph: isThisStarHover ? "sparkle" : st.glyph,
            color: st.isCore ? coreColor : baseColor,
            twinkle,
            alpha: st.alpha * depthFade * boost * dimOther,
          };
          drawList.push(item);

          if (st.namedLabel) {
            projectedNamed.push({ x: px, y: py, galaxy: g, star: st });
          }
        });
      });

      // Painter's algorithm: farthest stars first
      drawList.sort((a, b) => b.z - a.z);
      for (let i = 0; i < drawList.length; i++) {
        const d = drawList[i];
        drawStarGlyph(d.x, d.y, d.size, d.glyph, d.color, d.twinkle, d.alpha);
      }

      requestAnimationFrame(frame);
    }

    function updateTooltip(mx, my) {
      if (!hoveredGalaxy) {
        tooltip.style.display = "none";
        canvas.style.cursor = "crosshair";
        return;
      }
      canvas.style.cursor = "pointer";
      const matchCount = state.catalog.filter(p => problemMatchesGalaxy(p, hoveredGalaxy.id)).length;
      els.ttFam.textContent = `${hoveredGalaxy.label} · ${hoveredGalaxy.typeLabel}`;
      els.ttName.textContent = hoveredStar ? hoveredStar.star.namedLabel : hoveredGalaxy.label;
      const actionHint = state.activeGalaxy === hoveredGalaxy.id ? "Click to clear filter" : "Click to filter";
      els.ttMeta.textContent = `${matchCount} synthesis problem${matchCount === 1 ? "" : "s"} · ${actionHint}`;

      tooltip.style.display = "block";
      const left = Math.min(width - 245, Math.max(10, mx + 16));
      const top = Math.max(10, Math.min(height - 92, my - 18));
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    canvas.addEventListener("mousemove", e => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // Subtle OpenRouter-inspired 3D perspective tilt toward cursor
      const nx = (mx / Math.max(1, rect.width) - 0.5) * 2;
      const ny = (my / Math.max(1, rect.height) - 0.5) * 2;
      targetTiltY = nx * 0.24;
      targetTiltX = -ny * 0.20;

      // Hit-test named stars first
      let bestStar = null;
      let bestStarDist = 14;
      for (let i = 0; i < projectedNamed.length; i++) {
        const pn = projectedNamed[i];
        const d = Math.hypot(pn.x - mx, pn.y - my);
        if (d < bestStarDist) {
          bestStarDist = d;
          bestStar = pn;
        }
      }

      if (bestStar) {
        hoveredStar = bestStar;
        hoveredGalaxy = bestStar.galaxy;
      } else {
        hoveredStar = null;
        let bestGal = null;
        let bestGalDist = 64;
        for (let i = 0; i < galaxyData.length; i++) {
          const gd = galaxyData[i];
          const d = Math.hypot(gd.projCx - mx, gd.projCy - my);
          if (d < bestGalDist) {
            bestGalDist = d;
            bestGal = gd.galaxy;
          }
        }
        hoveredGalaxy = bestGal;
      }

      updateTooltip(mx, my);
    });

    canvas.addEventListener("mouseleave", () => {
      targetTiltX = 0;
      targetTiltY = 0;
      hoveredGalaxy = null;
      hoveredStar = null;
      tooltip.style.display = "none";
      canvas.style.cursor = "crosshair";
    });

    canvas.addEventListener("click", () => {
      if (hoveredGalaxy) {
        state.activeGalaxy = state.activeGalaxy === hoveredGalaxy.id ? null : hoveredGalaxy.id;
      } else if (state.activeGalaxy) {
        state.activeGalaxy = null;
      } else {
        return;
      }
      renderCatalog();
    });

    window.addEventListener("resize", resize);
    resize();
    requestAnimationFrame(frame);
  }

  initTheme();
  bindEvents();
  initGalaxyObservatory();
  loadCatalog();
})();
