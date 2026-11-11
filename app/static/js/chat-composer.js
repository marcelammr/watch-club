(function () {
  const sendOnEnter = document.documentElement.getAttribute("data-enter-sends") === "1";

  function bindSendOnEnter(input) {
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return;
      if (!sendOnEnter) return;
      if (event.shiftKey) return;
      event.preventDefault();
      const form = input.form || input.closest("form");
      if (form) form.requestSubmit();
    });
  }

  document.querySelectorAll(".js-chat-input, .js-dm-input").forEach(bindSendOnEnter);

  function bindDayFloat(log) {
    const wrap = log.closest(".js-chat-log-wrap");
    const floatEl = wrap && wrap.querySelector(".js-chat-day-float");
    if (!floatEl) return;
    let hideTimer;

    function nearBottom() {
      return log.scrollHeight - log.scrollTop - log.clientHeight < 32;
    }

    function labelForScroll() {
      const marks = log.querySelectorAll(".chat-day-mark");
      const top = log.scrollTop + 12;
      let label = "";
      marks.forEach((mark) => {
        if (mark.offsetTop <= top) label = (mark.textContent || "").trim();
      });
      return label;
    }

    function updateFloat() {
      if (nearBottom()) {
        floatEl.hidden = true;
        floatEl.classList.remove("is-on");
        return;
      }
      const label = labelForScroll();
      if (!label) {
        floatEl.hidden = true;
        floatEl.classList.remove("is-on");
        return;
      }
      floatEl.textContent = label;
      floatEl.hidden = false;
      floatEl.classList.add("is-on");
      window.clearTimeout(hideTimer);
      hideTimer = window.setTimeout(() => {
        floatEl.classList.remove("is-on");
      }, 1200);
    }

    log.addEventListener("scroll", updateFloat, { passive: true });
  }

  document.querySelectorAll(".js-chat-log-wrap .chat-log").forEach(bindDayFloat);

  const confirmDialog = document.getElementById("js-confirm-dialog");
  if (confirmDialog && typeof confirmDialog.showModal === "function") {
    let pendingForm = null;
    document.addEventListener("submit", (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.classList.contains("js-confirm-delete")) return;
      if (form.dataset.confirmed === "1") {
        form.dataset.confirmed = "0";
        return;
      }
      event.preventDefault();
      pendingForm = form;
      if (typeof confirmDialog.showModal === "function") confirmDialog.showModal();
    });
    confirmDialog.querySelector(".js-confirm-cancel")?.addEventListener("click", () => {
      pendingForm = null;
      confirmDialog.close();
    });
    confirmDialog.querySelector(".js-confirm-ok")?.addEventListener("click", () => {
      const form = pendingForm;
      pendingForm = null;
      confirmDialog.close();
      if (!form) return;
      form.dataset.confirmed = "1";
      form.requestSubmit();
    });
    confirmDialog.addEventListener("cancel", () => {
      pendingForm = null;
    });
  }

  const enterToggle = document.querySelector(".js-enter-sends");
  if (enterToggle) {
    const status = document.querySelector(".js-enter-sends-status");
    let statusTimer;

    function setStatus(text, isError) {
      if (!status) return;
      status.hidden = !text;
      status.textContent = text || "";
      status.classList.toggle("error", Boolean(isError));
      window.clearTimeout(statusTimer);
      if (text && !isError) {
        statusTimer = window.setTimeout(() => {
          status.hidden = true;
          status.textContent = "";
        }, 1600);
      }
    }

    function syncChecked() {
      enterToggle.setAttribute("aria-checked", enterToggle.checked ? "true" : "false");
    }

    syncChecked();
    enterToggle.addEventListener("change", async () => {
      const previous = !enterToggle.checked;
      syncChecked();
      setStatus("");
      try {
        const body = new URLSearchParams();
        body.set("enter_sends", enterToggle.checked ? "1" : "0");
        const response = await fetch("/conta/conversas", {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Watchclub-Pref": "1",
          },
          body,
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error();
        document.documentElement.setAttribute("data-enter-sends", enterToggle.checked ? "1" : "0");
        setStatus("Salvo", false);
      } catch (error) {
        enterToggle.checked = previous;
        syncChecked();
        setStatus("Não foi possível salvar.", true);
      }
    });
  }
})();
