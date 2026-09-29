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

  global.PathForgeCore = Object.freeze({
    apiUrl,
    fetchWithTimeout,
    getSessionStatus
  });
})(window);
