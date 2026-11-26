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
  };

  const els = {
    catalogView: document.getElementById("catalogView"),
    problemView: document.getElementById("problemView"),
    updatedLabel: document.getElementById("updatedLabel"),
    searchInput: document.getElementById("searchInput"),
    difficultyFilter: document.getElementById("difficultyFilter"),
    journalFilter: document.getElementById("journalFilter"),
    progressFilter: document.getElementById("progressFilter"),
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

  function renderCatalog() {
    const q = els.searchInput.value.trim().toLowerCase();
    const diff = els.difficultyFilter.value.toLowerCase();
    const journal = els.journalFilter.value;
    const prog = els.progressFilter.value;

    const filtered = state.catalog.filter(item => {
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

    const solvedCount = state.catalog.filter(i => getStatus(i.id).solved).length;
    els.statsRow.textContent = `Showing ${filtered.length} of ${state.catalog.length} total syntheses · ${solvedCount} solved`;

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

    window.addEventListener("hashchange", handleRoute);
  }

  initTheme();
  bindEvents();
  loadCatalog();
})();
