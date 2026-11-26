(function () {
  "use strict";

  const STORAGE_KEY = "synthesis_finder_progress_v1";
  const THEME_KEY = "synthesis_finder_theme";

  const state = {
    catalog: [],
    generatedAt: null,
    currentProblem: null,
    progress: loadProgress(),
    filters: {
      search: "",
      difficulty: "all",
      journal: "all",
      year: "all",
      status: "all",
      sort: "newest",
    },
    study: {
      hideReagents: false,
      hideProducts: false,
      stepMode: false,
      revealedStep: 0,
      revealedReagents: new Set(),
      revealedProducts: new Set(),
    },
  };

  // DOM refs
  const catalogView = document.getElementById("catalog-view");
  const solverView = document.getElementById("solver-view");
  const catalogGrid = document.getElementById("catalog-grid");
  const catalogEmpty = document.getElementById("catalog-empty");
  const resultsCount = document.getElementById("results-count");
  const catalogUpdated = document.getElementById("catalog-updated");
  const statsPills = document.getElementById("stats-pills");

  const searchInput = document.getElementById("search-input");
  const sortSelect = document.getElementById("sort-select");
  const filterDifficulty = document.getElementById("filter-difficulty");
  const filterJournal = document.getElementById("filter-journal");
  const filterYear = document.getElementById("filter-year");
  const filterStatus = document.getElementById("filter-status");
  const resetFiltersBtn = document.getElementById("reset-filters-btn");
  const emptyResetBtn = document.getElementById("empty-reset-btn");

  const backToCatalogBtn = document.getElementById("back-to-catalog");
  const problemHeader = document.getElementById("problem-header");
  const synthesisSequence = document.getElementById("synthesis-sequence");
  const solverBookmarkBtn = document.getElementById("solver-bookmark-btn");
  const snakeActions = document.getElementById("snake-actions");

  const toggleHideReagents = document.getElementById("toggle-hide-reagents");
  const toggleHideProducts = document.getElementById("toggle-hide-products");
  const toggleStepMode = document.getElementById("toggle-step-mode");
  const stepControls = document.getElementById("step-controls");
  const prevStepBtn = document.getElementById("prev-step-btn");
  const nextStepBtn = document.getElementById("next-step-btn");
  const revealAllBtn = document.getElementById("reveal-all-btn");
  const stepCounter = document.getElementById("step-counter");

  const themeToggle = document.getElementById("theme-toggle");
  const themeIcon = document.getElementById("theme-icon");

  function loadProgress() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function saveProgress() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.progress));
    } catch {
      // ignore storage quota errors
    }
  }

  function getProblemProgress(id) {
    return state.progress[id] || { status: "unsolved", bookmarked: false };
  }

  function setProblemStatus(id, status) {
    const cur = getProblemProgress(id);
    state.progress[id] = { ...cur, status };
    saveProgress();
    renderStatsPills();
  }

  function toggleBookmark(id) {
    const cur = getProblemProgress(id);
    state.progress[id] = { ...cur, bookmarked: !cur.bookmarked };
    saveProgress();
    renderStatsPills();
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY) || "light";
    document.documentElement.setAttribute("data-theme", saved);
    themeIcon.textContent = saved === "dark" ? "☀️" : "🌙";
  }

  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_KEY, next);
    themeIcon.textContent = next === "dark" ? "☀️" : "🌙";
  });

  function resolveDataPath(relPath) {
    if (!relPath) return "";
    if (/^https?:\/\//i.test(relPath)) return relPath;
    const clean = relPath.replace(/^\/+/, "");
    return clean.startsWith("data/") ? clean : `data/${clean}`;
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function difficultyBadgeClass(diff) {
    const d = (diff || "").toLowerCase();
    if (d.includes("intro")) return "badge-intro";
    if (d.includes("adv")) return "badge-adv";
    return "badge-inter";
  }

  function renderStatsPills() {
    const total = state.catalog.length;
    let solved = 0;
    let bookmarked = 0;
    for (const item of state.catalog) {
      const p = getProblemProgress(item.id);
      if (p.status === "solved") solved += 1;
      if (p.bookmarked) bookmarked += 1;
    }
    statsPills.innerHTML = `
      <span class="stat-pill">${total} Problems</span>
      <span class="stat-pill solved">${solved} Solved</span>
      <span class="stat-pill">${bookmarked} ★</span>
    `;
  }

  function populateFilterOptions() {
    const journals = [...new Set(state.catalog.map((p) => p.journal).filter(Boolean))].sort();
    const years = [...new Set(state.catalog.map((p) => p.year).filter(Boolean))].sort((a, b) => b - a);

    filterJournal.innerHTML = `<option value="all">All Journals</option>` +
      journals.map((j) => `<option value="${escapeHtml(j)}">${escapeHtml(j)}</option>`).join("");

    filterYear.innerHTML = `<option value="all">All Years</option>` +
      years.map((y) => `<option value="${y}">${y}</option>`).join("");
  }

  function getFilteredCatalog() {
    const q = state.filters.search.trim().toLowerCase();
    const filtered = state.catalog.filter((item) => {
      const prog = getProblemProgress(item.id);

      if (state.filters.difficulty !== "all" && item.difficulty !== state.filters.difficulty) return false;
      if (state.filters.journal !== "all" && item.journal !== state.filters.journal) return false;
      if (state.filters.year !== "all" && String(item.year) !== state.filters.year) return false;
      if (state.filters.status === "bookmarked" && !prog.bookmarked) return false;
      if (["unsolved", "in_progress", "solved"].includes(state.filters.status) && prog.status !== state.filters.status) {
        return false;
      }

      if (q) {
        const haystack = [
          item.target_molecule,
          item.title,
          item.journal,
          item.doi,
          String(item.year || ""),
          ...(item.authors || []),
          ...(item.tags || []),
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });

    filtered.sort((a, b) => {
      switch (state.filters.sort) {
        case "year-desc":
          return (b.year || 0) - (a.year || 0);
        case "steps-asc":
          return (a.num_steps || 0) - (b.num_steps || 0);
        case "steps-desc":
          return (b.num_steps || 0) - (a.num_steps || 0);
        case "newest":
        default:
          return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      }
    });

    return filtered;
  }

  function renderCatalog() {
    const items = getFilteredCatalog();
    resultsCount.textContent = `Showing ${items.length} of ${state.catalog.length} problems`;
    if (state.generatedAt) {
      catalogUpdated.textContent = `Updated: ${new Date(state.generatedAt).toLocaleDateString()}`;
    }

    if (items.length === 0) {
      catalogGrid.innerHTML = "";
      catalogEmpty.classList.remove("hidden");
      return;
    }

    catalogEmpty.classList.add("hidden");
    catalogGrid.innerHTML = items
      .map((item) => {
        const prog = getProblemProgress(item.id);
        const authors = (item.authors || []).join(", ");
        const doiUrl = item.doi ? `https://doi.org/${encodeURIComponent(item.doi)}` : item.source_url;
        const statusBadge =
          prog.status === "solved"
            ? `<span class="badge badge-solved">✓ Solved</span>`
            : prog.status === "in_progress"
            ? `<span class="badge badge-progress">In Progress</span>`
            : "";

        return `
          <article class="problem-card">
            <div class="card-top">
              <h3 class="target-name">${escapeHtml(item.target_molecule || "Unknown Target")}</h3>
              <button
                type="button"
                class="bookmark-btn ${prog.bookmarked ? "active" : ""}"
                data-bookmark-id="${escapeHtml(item.id)}"
                title="${prog.bookmarked ? "Remove bookmark" : "Bookmark problem"}"
              >${prog.bookmarked ? "★" : "☆"}</button>
            </div>
            <h4 class="card-title">${escapeHtml(item.title)}</h4>
            <div class="card-meta">
              ${escapeHtml(item.journal || "Unknown Journal")} (${escapeHtml(item.year || "—")})
              ${authors ? `<br/><span>${escapeHtml(authors)}</span>` : ""}
            </div>
            <div class="badges-row">
              <span class="badge ${difficultyBadgeClass(item.difficulty)}">${escapeHtml(item.difficulty || "Intermediate")}</span>
              <span class="badge">${item.num_steps ?? "?"} steps</span>
              ${statusBadge}
            </div>
            ${
              item.tags && item.tags.length
                ? `<div class="tags-row">${item.tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>`
                : ""
            }
            <div class="card-actions">
              <div class="ext-links">
                ${doiUrl ? `<a class="btn btn-ghost btn-sm" href="${escapeHtml(doiUrl)}" target="_blank" rel="noopener">DOI ↗</a>` : ""}
                ${item.pdf_url ? `<a class="btn btn-ghost btn-sm" href="${escapeHtml(item.pdf_url)}" target="_blank" rel="noopener">PDF ↗</a>` : ""}
              </div>
              <a class="btn btn-primary btn-sm" href="#/problem/${encodeURIComponent(item.id)}">Open Problem →</a>
            </div>
          </article>
        `;
      })
      .join("");
  }

  catalogGrid.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-bookmark-id]");
    if (!btn) return;
    toggleBookmark(btn.getAttribute("data-bookmark-id"));
    renderCatalog();
  });

  // Solver view
  async function openProblem(id) {
    const entry = state.catalog.find((p) => p.id === id);
    const problemPath = entry?.problem_file ? resolveDataPath(entry.problem_file) : `data/problems/${encodeURIComponent(id)}.json`;

    catalogView.classList.add("hidden");
    solverView.classList.remove("hidden");
    problemHeader.innerHTML = `<p class="muted">Loading synthesis problem...</p>`;
    synthesisSequence.innerHTML = "";

    try {
      const res = await fetch(problemPath);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const problem = await res.json();
      state.currentProblem = { ...problem, html_file: entry?.html_file || problem.html_file };
      state.study.revealedStep = state.study.stepMode ? 0 : (problem.steps || []).length;
      state.study.revealedReagents.clear();
      state.study.revealedProducts.clear();

      renderSolverHeader();
      renderStepControls();
      renderSynthesisSequence();
    } catch (err) {
      problemHeader.innerHTML = `
        <h1>Failed to load problem</h1>
        <p class="muted">${escapeHtml(err.message)}</p>
      `;
    }
  }

  function renderSolverHeader() {
    const p = state.currentProblem;
    if (!p) return;
    const prog = getProblemProgress(p.id);
    const doiUrl = p.doi ? `https://doi.org/${encodeURIComponent(p.doi)}` : p.source_url;
    const authors = (p.authors || []).join(", ");

    // Update segmented status buttons
    document.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-status") === prog.status);
    });
    solverBookmarkBtn.textContent = prog.bookmarked ? "★ Bookmarked" : "☆ Bookmark";

    problemHeader.innerHTML = `
      <h1>${escapeHtml(p.target_molecule || p.title)}</h1>
      <h2>${escapeHtml(p.title)}</h2>
      <div class="card-meta">
        <strong>${escapeHtml(p.journal || "")}</strong> (${escapeHtml(p.year || "—")})
        ${authors ? ` • ${escapeHtml(authors)}` : ""}
        • ${(p.steps || []).length} steps
      </div>
      <div class="problem-links">
        ${doiUrl ? `<a class="btn btn-outline btn-sm" href="${escapeHtml(doiUrl)}" target="_blank" rel="noopener">Original Paper / DOI ↗</a>` : ""}
        ${p.pdf_url ? `<a class="btn btn-outline btn-sm" href="${escapeHtml(p.pdf_url)}" target="_blank" rel="noopener">Open-Access PDF ↗</a>` : ""}
      </div>
    `;

    const htmlPath = p.html_file ? resolveDataPath(p.html_file) : "";
    snakeActions.innerHTML = htmlPath
      ? `
        <a class="btn btn-outline btn-sm" href="${escapeHtml(htmlPath)}" target="_blank" rel="noopener">🐍 Open Snake Flashcard</a>
        <a class="btn btn-ghost btn-sm" href="${escapeHtml(htmlPath)}" download>⬇ Download HTML</a>
      `
      : "";
  }

  function renderStepControls() {
    const total = (state.currentProblem?.steps || []).length;
    if (!state.study.stepMode) {
      stepControls.classList.add("hidden");
      return;
    }
    stepControls.classList.remove("hidden");
    stepCounter.textContent = `Step ${state.study.revealedStep} / ${total}`;
    prevStepBtn.disabled = state.study.revealedStep <= 0;
    nextStepBtn.disabled = state.study.revealedStep >= total;
  }

  function renderSynthesisSequence() {
    const p = state.currentProblem;
    if (!p) return;

    const steps = p.steps || [];
    const maxVisibleStep = state.study.stepMode ? state.study.revealedStep : steps.length;

    let html = `
      <div class="mol-card">
        <div class="mol-card-header">
          <span class="mol-label">Starting Material</span>
        </div>
        <div class="svg-frame">
          ${p.start_svg || `<span class="muted">SMILES: ${escapeHtml(p.start_smiles || "N/A")}</span>`}
        </div>
        ${
          p.start_smiles
            ? `<div class="smiles-row"><span>${escapeHtml(p.start_smiles)}</span><button type="button" class="btn btn-ghost btn-sm" data-copy="${escapeHtml(p.start_smiles)}">Copy</button></div>`
            : ""
        }
      </div>
    `;

    steps.forEach((step, idx) => {
      const stepNum = step.step_index ?? idx + 1;
      if (idx + 1 > maxVisibleStep) {
        return;
      }

      const hideReag = state.study.hideReagents && !state.study.revealedReagents.has(stepNum);
      const hideProd = state.study.hideProducts && !state.study.revealedProducts.has(stepNum);

      html += `
        <div class="step-row">
          <div class="reaction-box">
            <div class="step-header">
              <span class="step-badge">Step ${stepNum}</span>
              ${step.yield ? `<span class="yield-badge">${escapeHtml(step.yield)}</span>` : ""}
            </div>
            ${
              hideReag
                ? `<div class="flashcard-cover" data-reveal-reagent="${stepNum}">
                     <span>🧪 Reagents &amp; Conditions Hidden</span>
                     <span class="muted">Click to reveal</span>
                   </div>`
                : `
                   ${step.named_reaction ? `<div class="named-rxn">${escapeHtml(step.named_reaction)}</div>` : ""}
                   <div class="reagents-text">${escapeHtml(step.reagents || "—")}</div>
                   ${step.conditions ? `<div class="conditions-text">${escapeHtml(step.conditions)}</div>` : ""}
                   ${step.notes ? `<div class="notes-text">${escapeHtml(step.notes)}</div>` : ""}
                  `
            }
          </div>

          <div class="mol-card">
            <div class="mol-card-header">
              <span class="mol-label">${idx === steps.length - 1 ? `Target: ${escapeHtml(p.target_molecule || "Final Product")}` : `Intermediate ${stepNum}`}</span>
            </div>
            ${
              hideProd
                ? `<div class="flashcard-cover" data-reveal-product="${stepNum}">
                     <span>⬡ Product Structure Hidden</span>
                     <span class="muted">Click to reveal</span>
                   </div>`
                : `
                   <div class="svg-frame">
                     ${step.product_svg || `<span class="muted">SMILES: ${escapeHtml(step.product_smiles || "N/A")}</span>`}
                   </div>
                   ${
                     step.product_smiles
                       ? `<div class="smiles-row"><span>${escapeHtml(step.product_smiles)}</span><button type="button" class="btn btn-ghost btn-sm" data-copy="${escapeHtml(step.product_smiles)}">Copy</button></div>`
                       : ""
                   }
                  `
            }
          </div>
        </div>
      `;
    });

    if (state.study.stepMode && maxVisibleStep < steps.length) {
      html += `
        <div class="card" style="padding: 18px; text-align: center;">
          <p class="muted" style="margin: 0 0 10px;">${steps.length - maxVisibleStep} step(s) remaining</p>
          <button type="button" class="btn btn-primary" id="inline-next-step">Reveal Step ${maxVisibleStep + 1} →</button>
        </div>
      `;
    }

    synthesisSequence.innerHTML = html;
  }

  // Event listeners for solver
  synthesisSequence.addEventListener("click", (e) => {
    const reagCover = e.target.closest("[data-reveal-reagent]");
    if (reagCover) {
      state.study.revealedReagents.add(Number(reagCover.getAttribute("data-reveal-reagent")));
      renderSynthesisSequence();
      return;
    }

    const prodCover = e.target.closest("[data-reveal-product]");
    if (prodCover) {
      state.study.revealedProducts.add(Number(prodCover.getAttribute("data-reveal-product")));
      renderSynthesisSequence();
      return;
    }

    const copyBtn = e.target.closest("[data-copy]");
    if (copyBtn) {
      const text = copyBtn.getAttribute("data-copy");
      navigator.clipboard?.writeText(text).then(() => {
        copyBtn.textContent = "Copied!";
        setTimeout(() => (copyBtn.textContent = "Copy"), 1200);
      });
      return;
    }

    if (e.target.id === "inline-next-step") {
      state.study.revealedStep += 1;
      renderStepControls();
      renderSynthesisSequence();
    }
  });

  document.querySelectorAll(".seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!state.currentProblem) return;
      setProblemStatus(state.currentProblem.id, btn.getAttribute("data-status"));
      renderSolverHeader();
    });
  });

  solverBookmarkBtn.addEventListener("click", () => {
    if (!state.currentProblem) return;
    toggleBookmark(state.currentProblem.id);
    renderSolverHeader();
  });

  toggleHideReagents.addEventListener("change", () => {
    state.study.hideReagents = toggleHideReagents.checked;
    state.study.revealedReagents.clear();
    renderSynthesisSequence();
  });

  toggleHideProducts.addEventListener("change", () => {
    state.study.hideProducts = toggleHideProducts.checked;
    state.study.revealedProducts.clear();
    renderSynthesisSequence();
  });

  toggleStepMode.addEventListener("change", () => {
    state.study.stepMode = toggleStepMode.checked;
    const total = (state.currentProblem?.steps || []).length;
    state.study.revealedStep = state.study.stepMode ? 0 : total;
    renderStepControls();
    renderSynthesisSequence();
  });

  prevStepBtn.addEventListener("click", () => {
    if (state.study.revealedStep > 0) {
      state.study.revealedStep -= 1;
      renderStepControls();
      renderSynthesisSequence();
    }
  });

  nextStepBtn.addEventListener("click", () => {
    const total = (state.currentProblem?.steps || []).length;
    if (state.study.revealedStep < total) {
      state.study.revealedStep += 1;
      renderStepControls();
      renderSynthesisSequence();
    }
  });

  revealAllBtn.addEventListener("click", () => {
    const total = (state.currentProblem?.steps || []).length;
    state.study.revealedStep = total;
    state.study.revealedReagents.clear();
    state.study.revealedProducts.clear();
    toggleHideReagents.checked = false;
    toggleHideProducts.checked = false;
    state.study.hideReagents = false;
    state.study.hideProducts = false;
    renderStepControls();
    renderSynthesisSequence();
  });

  backToCatalogBtn.addEventListener("click", () => {
    window.location.hash = "#/";
  });

  // Catalog filter listeners
  searchInput.addEventListener("input", () => {
    state.filters.search = searchInput.value;
    renderCatalog();
  });
  sortSelect.addEventListener("change", () => {
    state.filters.sort = sortSelect.value;
    renderCatalog();
  });
  filterDifficulty.addEventListener("change", () => {
    state.filters.difficulty = filterDifficulty.value;
    renderCatalog();
  });
  filterJournal.addEventListener("change", () => {
    state.filters.journal = filterJournal.value;
    renderCatalog();
  });
  filterYear.addEventListener("change", () => {
    state.filters.year = filterYear.value;
    renderCatalog();
  });
  filterStatus.addEventListener("change", () => {
    state.filters.status = filterStatus.value;
    renderCatalog();
  });

  function resetFilters() {
    state.filters = {
      search: "",
      difficulty: "all",
      journal: "all",
      year: "all",
      status: "all",
      sort: "newest",
    };
    searchInput.value = "";
    sortSelect.value = "newest";
    filterDifficulty.value = "all";
    filterJournal.value = "all";
    filterYear.value = "all";
    filterStatus.value = "all";
    renderCatalog();
  }

  resetFiltersBtn.addEventListener("click", resetFilters);
  emptyResetBtn.addEventListener("click", resetFilters);

  // Hash router
  function handleRoute() {
    const hash = window.location.hash || "#/";
    const match = hash.match(/^#\/problem\/(.+)$/);
    if (match) {
      openProblem(decodeURIComponent(match[1]));
    } else {
      state.currentProblem = null;
      solverView.classList.add("hidden");
      catalogView.classList.remove("hidden");
      renderCatalog();
    }
  }

  window.addEventListener("hashchange", handleRoute);

  // Boot
  async function init() {
    initTheme();
    try {
      const res = await fetch("data/catalog.json");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.catalog = data.problems || [];
      state.generatedAt = data.generated_at || null;
      populateFilterOptions();
      renderStatsPills();
      handleRoute();
    } catch (err) {
      resultsCount.textContent = `Error loading catalog: ${err.message}`;
    }
  }

  init();
})();
