(function () {
  function updateWheel(menu) {
    if (!menu) {
      return;
    }
    const list = menu.matches(".candidate-branch-menu")
      ? menu
      : menu.querySelector(".candidate-branch-menu");
    if (!list) {
      return;
    }
    const buttons = Array.from(list.querySelectorAll(".candidate-branch-menu-button"));
    if (!buttons.length) {
      return;
    }
    const centerY = list.getBoundingClientRect().top + (list.clientHeight / 2);
    const ranked = buttons
      .map(function (button) {
        const rect = button.getBoundingClientRect();
        return {
          button: button,
          distance: Math.abs((rect.top + (rect.height / 2)) - centerY),
        };
      })
      .sort(function (a, b) {
        return a.distance - b.distance;
      });
    buttons.forEach(function (button) {
      button.classList.remove("wheel-center", "wheel-near");
    });
    ranked[0].button.classList.add("wheel-center");
    ranked.slice(1, 3).forEach(function (entry) {
      entry.button.classList.add("wheel-near");
    });
  }

  function closeMenu(menu) {
    if (!menu || !menu.hasAttribute("open") || menu.dataset.closing === "1") {
      return;
    }
    menu.dataset.closing = "1";
    window.setTimeout(function () {
      menu.removeAttribute("open");
      delete menu.dataset.closing;
    }, 380);
  }

  document.addEventListener("click", function (event) {
    const openMenus = document.querySelectorAll(".candidate-result-card-wrap[open]");
    const currentMenu = event.target.closest(".candidate-result-card-wrap");
    openMenus.forEach(function (menu) {
      if (menu !== currentMenu) {
        closeMenu(menu);
      }
    });
    if (event.target.closest(".candidate-branch-menu-button") && currentMenu) {
      window.setTimeout(function () {
        closeMenu(currentMenu);
      }, 0);
    }
    window.setTimeout(function () {
      document
        .querySelectorAll(".candidate-result-card-wrap[open] .candidate-branch-menu")
        .forEach(updateWheel);
    }, 0);
  });

  document.addEventListener("scroll", function (event) {
    if (!event.target.matches || !event.target.matches(".candidate-branch-menu")) {
      return;
    }
    window.requestAnimationFrame(function () {
      updateWheel(event.target);
    });
  }, true);

  document.addEventListener("focusin", function (event) {
    const menu = event.target.closest
      ? event.target.closest(".candidate-branch-menu")
      : null;
    if (menu) {
      updateWheel(menu);
    }
  });
}());
