(function () {
  function closePicker(wrap) {
    const popover = wrap.querySelector(".js-emoji-popover");
    const toggle = wrap.querySelector(".js-emoji-toggle");
    if (!popover || !toggle) return;
    popover.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }

  function closeAll(except) {
    document.querySelectorAll(".js-emoji-picker").forEach((wrap) => {
      if (wrap !== except) closePicker(wrap);
    });
  }

  document.querySelectorAll(".js-emoji-picker").forEach((wrap) => {
    const popover = wrap.querySelector(".js-emoji-popover");
    const toggle = wrap.querySelector(".js-emoji-toggle");
    if (!popover || !toggle) return;

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = popover.hidden;
      closeAll(wrap);
      popover.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    popover.querySelectorAll("[data-emoji]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        wrap.dispatchEvent(
          new CustomEvent("emoji-select", {
            bubbles: true,
            detail: { emoji: btn.dataset.emoji || "" },
          })
        );
        closePicker(wrap);
      });
    });
  });

  document.addEventListener("click", (event) => {
    document.querySelectorAll(".js-emoji-picker").forEach((wrap) => {
      const popover = wrap.querySelector(".js-emoji-popover");
      if (!popover || popover.hidden) return;
      if (wrap.contains(event.target)) return;
      closePicker(wrap);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = document.querySelector(".js-emoji-picker .js-emoji-popover:not([hidden])");
    if (!open) return;
    closePicker(open.closest(".js-emoji-picker"));
    event.preventDefault();
  });
})();
