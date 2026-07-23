document.querySelectorAll(".card-menu").forEach((menu) => {
    const button = menu.querySelector(".kebab, .kebab-trigger");
    const panel = menu.querySelector(".card-menu-panel");
    if (!button || !panel) return;

    button.addEventListener("click", (event) => {
        event.stopPropagation();
        document.querySelectorAll(".card-menu-panel").forEach((other) => {
            if (other !== panel) {
                other.hidden = true;
                other.closest(".card-menu")
                    ?.querySelector(".kebab, .kebab-trigger")
                    ?.setAttribute("aria-expanded", "false");
            }
        });
        panel.hidden = !panel.hidden;
        button.setAttribute("aria-expanded", String(!panel.hidden));
    });
});

document.addEventListener("click", (event) => {
    if (event.target.closest(".card-menu")) return;
    document.querySelectorAll(".card-menu-panel").forEach((panel) => {
        panel.hidden = true;
    });
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".card-menu-panel").forEach((panel) => {
        panel.hidden = true;
    });
});
