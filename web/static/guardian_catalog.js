(() => {
  const input = document.querySelector("[data-guardian-search]");
  const catalogs = [...document.querySelectorAll("[data-guardian-catalog]")];
  if (!input || !catalogs.length) return;

  const catalogStates = catalogs.map((catalog) => {
    const storageKey = `lanaxy.guardianCategories.${catalog.dataset.guardianCatalog || "default"}`;
    const categories = [...catalog.querySelectorAll(".guardian-category")];
    const empty = catalog.querySelector(".guardian-search-empty");

    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
      categories.forEach((category) => {
        const key = category.dataset.category;
        if (Object.prototype.hasOwnProperty.call(saved, key)) category.open = Boolean(saved[key]);
        category.addEventListener("toggle", () => {
          const state = {};
          categories.forEach((item) => { state[item.dataset.category] = item.open; });
          localStorage.setItem(storageKey, JSON.stringify(state));
        });
      });
    } catch (_) {
      // Local storage is optional; grouping works without it.
    }

    return { catalog, categories, empty };
  });

  const filter = () => {
    const query = input.value.trim().toLocaleLowerCase("de");
    catalogStates.forEach(({ categories, empty }) => {
      let totalVisible = 0;
      categories.forEach((category) => {
        let categoryVisible = 0;
        category.querySelectorAll(".guardian-catalog-card").forEach((card) => {
          const matches = !query || (card.dataset.search || "").includes(query);
          card.hidden = !matches;
          if (matches) categoryVisible += 1;
        });
        category.hidden = categoryVisible === 0;
        const count = category.querySelector("[data-category-count]");
        if (count) count.textContent = String(categoryVisible);
        if (query && categoryVisible) category.open = true;
        totalVisible += categoryVisible;
      });
      if (empty) empty.hidden = totalVisible !== 0;
    });
  };

  input.addEventListener("input", filter);
  filter();
})();
