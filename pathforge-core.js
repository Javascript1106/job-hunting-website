(function initializePathForgeCore(global) {
  "use strict";

  const isLocalFrontend = ["localhost", "127.0.0.1"].includes(
    global.location.hostname
  ) && global.location.port !== "8000";
  const apiOrigin = global.PATHFORGE_API_ORIGIN || (
    isLocalFrontend
      ? "http://127.0.0.1:8000"
      : global.location.origin
  );

  function apiUrl(path) {
    const normalizedPath = String(path || "").startsWith("/")
      ? String(path)
      : `/${path}`;
    return `${apiOrigin}${normalizedPath}`;
  }

  let sessionStatusPromise = null;

  function getSessionStatus() {
    if (!sessionStatusPromise) {
      sessionStatusPromise = global.fetch(apiUrl("/session-status"), {
        credentials: "include"
      })
        .then(response => {
          if (!response.ok) throw new Error("Session status could not be checked.");
          return response.json();
        })
        .catch(error => {
          sessionStatusPromise = null;
          throw error;
        });
    }
    return sessionStatusPromise;
  }

  async function fetchWithTimeout(
    url,
    options = {},
    timeoutMilliseconds = 15000
  ) {
    const controller = new AbortController();
    const timeout = global.setTimeout(
      () => controller.abort(),
      timeoutMilliseconds
    );
    try {
      return await global.fetch(url, { ...options, signal: controller.signal });
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error(
          "This is taking longer than expected. Check your connection and try again."
        );
      }
      throw error;
    } finally {
      global.clearTimeout(timeout);
    }
  }

  function initializePageTransitions() {
    if (global.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    global.addEventListener("pageshow", () => {
      document.body?.classList.remove("pf-page-leaving");
    });

    document.addEventListener("click", event => {
      if (
        event.defaultPrevented
        || event.button !== 0
        || event.metaKey
        || event.ctrlKey
        || event.shiftKey
        || event.altKey
      ) {
        return;
      }

      const link = event.target.closest?.("a[href]");
      if (!link || link.hasAttribute("download")) return;
      if (link.target && link.target.toLowerCase() !== "_self") return;

      const destination = new URL(link.href, global.location.href);
      if (destination.origin !== global.location.origin) return;
      if (!["http:", "https:"].includes(destination.protocol)) return;
      if (
        destination.pathname === global.location.pathname
        && destination.search === global.location.search
        && destination.hash
      ) {
        return;
      }

      event.preventDefault();
      document.body.classList.add("pf-page-leaving");
      global.setTimeout(() => global.location.assign(destination.href), 120);
    });
  }

  initializePageTransitions();

  global.PathForgeCore = Object.freeze({
    apiUrl,
    fetchWithTimeout,
    getSessionStatus
  });
})(window);
