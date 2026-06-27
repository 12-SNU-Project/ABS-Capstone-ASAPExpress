(function () {
  function asElement(target) {
    if (!target) {
      return null;
    }
    if (target.nodeType === 1) {
      return target;
    }
    return target.parentElement || null;
  }

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
    }, 420);
  }

  function openMenu(menu) {
    if (!menu) {
      return;
    }
    delete menu.dataset.closing;
    menu.setAttribute("open", "");
    window.setTimeout(function () {
      updateWheel(menu);
    }, 0);
  }

  function replayMenu(menu) {
    if (!menu) {
      return;
    }
    menu.removeAttribute("open");
    delete menu.dataset.closing;
    window.requestAnimationFrame(function () {
      openMenu(menu);
    });
  }

  function scrollMenu(event) {
    const target = asElement(event.target);
    const menu = target ? target.closest(".candidate-branch-menu") : null;
    if (!menu) {
      return;
    }
    const maxScroll = menu.scrollHeight - menu.clientHeight;
    if (maxScroll <= 0) {
      return;
    }
    const nextScroll = Math.max(0, Math.min(maxScroll, menu.scrollTop + event.deltaY));
    if (nextScroll === menu.scrollTop) {
      return;
    }
    event.preventDefault();
    menu.scrollTop = nextScroll;
    window.requestAnimationFrame(function () {
      updateWheel(menu);
    });
  }

  document.addEventListener("click", function (event) {
    const target = asElement(event.target);
    if (!target) {
      return;
    }
    const openMenus = document.querySelectorAll(".candidate-result-card-wrap[open]");
    const currentMenu = target.closest(".candidate-result-card-wrap");
    const clickedSummary = target.closest(".candidate-result-summary");
    if (clickedSummary && currentMenu) {
      event.preventDefault();
      openMenus.forEach(function (menu) {
        if (menu !== currentMenu) {
          closeMenu(menu);
        }
      });
      if (currentMenu.hasAttribute("open")) {
        replayMenu(currentMenu);
      } else {
        openMenu(currentMenu);
      }
      return;
    }
    openMenus.forEach(function (menu) {
      if (menu !== currentMenu) {
        closeMenu(menu);
      }
    });
    if (target.closest(".candidate-branch-menu-button") && currentMenu) {
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

  document.addEventListener("wheel", scrollMenu, { passive: false });

  document.addEventListener("focusin", function (event) {
    const target = asElement(event.target);
    const menu = target ? target.closest(".candidate-branch-menu") : null;
    if (menu) {
      updateWheel(menu);
    }
  });
}());
