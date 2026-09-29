(() => {
  "use strict";

  /*
   * Delta Dental of Wisconsin - single-file content script
   *
   * Based on the supplied HAR + HTML:
   *   1) Patient search POST:
   *      /dentist/patient-information/benefits-and-claims/process
   *   2) Benefits page:
   *      /dentist/patient-information/benefits-and-claims/benefits-and-claims
   *   3) Procedure page:
   *      /dentist/patient-information/procedure-code-search/procedure-code-search
   *   4) Procedure search POST:
   *      procedure-code-search-process
   *
   * No background/service worker/popup is required.
   */

  const DEBUG = true;
  /*
   * DD-WI rate-limit protection.
   * Categories are intentionally serialized and throttled. If the portal
   * returns a 429/Too Many Requests page, the same category is retried with
   * exponential backoff instead of restarting the crawl.
   */
  const DD_WI_RATE_LIMIT = {
    CATEGORY_DELAY_MIN_MS: 3500,
    CATEGORY_DELAY_MAX_MS: 5000,
    INTER_PATIENT_COOLDOWN_MS: 45000,
    RETRY_DELAYS_MS: [15000, 30000, 60000],
    MAX_429_RETRIES: 3
  };

  const AUTO_OPEN_PROCEDURE_SEARCH = true;

  const STORAGE = {
    PATIENT: "DD_WI_TARGET_PATIENT",
    STATE: "DD_WI_SCRAPER_STATE",
    RESULT: "DD_WI_FINAL_JSON",
    BENEFITS_RESULT: "DD_WI_BENEFITS_RESULT",
    RUN_ACTIVE: "DD_WI_RUN_ACTIVE",
    RATE_LIMIT_RETRY: "DD_WI_RATE_LIMIT_RETRY",
    LAST_COMPLETED_AT: "DD_WI_LAST_COMPLETED_AT",
    INITIALIZED: "DD_WI_CONTENT_INITIALIZED"
  };

  /*
   * PROCEDURE CRAWL MODE
   *
   * The Delta Dental WI Procedure Code Search page provides a Category
   * dropdown. We crawl the portal category-by-category instead of issuing
   * one request per procedure code.
   *
   * The category values are intentionally NOT hard-coded. They are read
   * from #category on the live page, so if Delta Dental adds/removes or
   * renames a category the crawler follows the current portal.
   */
  const PROCEDURE_CRAWL_MODE = "CATEGORY";

  const CATEGORY_STORAGE = {
    QUEUE: "DD_WI_PROCEDURE_CATEGORY_QUEUE",
    INDEX: "DD_WI_PROCEDURE_CATEGORY_INDEX",
    ACTIVE: "DD_WI_ACTIVE_PROCEDURE_CATEGORY"
  };

  const PROCEDURE_RESULT_DEFAULTS = {
    coverage_percentage: "N/A",
    deductible_applies: "N/A",
    waiting_period: "N/A",
    alternate_benefit: "N/A",
    frequency: "N/A",
    age_limit: "N/A"
  };

  if (window.__DD_WI_CONTENT_INITIALIZED) {
    return;
  }
  window.__DD_WI_CONTENT_INITIALIZED = true;

  const log = (...args) => {
    if (DEBUG) console.log("[DD-WI]", ...args);
  };

  const warn = (...args) => console.warn("[DD-WI]", ...args);
  const error = (...args) => console.error("[DD-WI]", ...args);

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  function getState() {
    try {
      return sessionStorage.getItem(STORAGE.STATE) || "WAITING_FOR_PATIENT";
    } catch (_) {
      return "WAITING_FOR_PATIENT";
    }
  }

  function setState(state) {
    try {
      sessionStorage.setItem(STORAGE.STATE, state);
    } catch (_) {}
    log("state:", state);
  }

  function isCrawlActive() {
    try {
      return sessionStorage.getItem(STORAGE.RUN_ACTIVE) === "1";
    } catch (_) {
      return false;
    }
  }

  function setCrawlActive(active) {
    try {
      if (active) {
        sessionStorage.setItem(STORAGE.RUN_ACTIVE, "1");
      } else {
        sessionStorage.removeItem(STORAGE.RUN_ACTIVE);
      }
    } catch (_) {}
    log("crawl active:", active);
  }

  function getRateLimitRetryCount() {
    const value = Number(loadJSON(STORAGE.RATE_LIMIT_RETRY, 0));
    return Number.isFinite(value) && value >= 0 ? value : 0;
  }

  function setRateLimitRetryCount(value) {
    saveJSON(STORAGE.RATE_LIMIT_RETRY, Math.max(0, Number(value) || 0));
  }

  function clearRateLimitRetryCount() {
    removeStorage(STORAGE.RATE_LIMIT_RETRY);
  }

  function getLastCompletedAt() {
    const value = Number(loadJSON(STORAGE.LAST_COMPLETED_AT, 0));
    return Number.isFinite(value) ? value : 0;
  }

  function setLastCompletedAt() {
    saveJSON(STORAGE.LAST_COMPLETED_AT, Date.now());
  }

  function getCategoryDelayMs() {
    const min = DD_WI_RATE_LIMIT.CATEGORY_DELAY_MIN_MS;
    const max = DD_WI_RATE_LIMIT.CATEGORY_DELAY_MAX_MS;
    return Math.floor(min + Math.random() * (max - min + 1));
  }

  function isRateLimitedPage() {
    const title = cleanText(document.title || "");
    const body = cleanText(
      document.body?.innerText || document.body?.textContent || ""
    );
    const combined = `${title}\n${body}`;

    return (
      (/\b429\b/.test(combined) &&
        /too\s+many\s+requests|rate\s*limit|request\s*limit/i.test(combined)) ||
      /too\s+many\s+requests/i.test(title) ||
      /rate\s*limit(?:ed|ing)?/i.test(title)
    );
  }

  function rateLimitMessageText() {
    const title = cleanText(document.title || "");
    const body = cleanText(
      document.body?.innerText || document.body?.textContent || ""
    );
    const lines = body.split(/\n+/)
      .map(cleanText)
      .filter(Boolean)
      .filter(line => /429|too\s+many\s+requests|rate\s*limit/i.test(line));
    return [title, ...lines].filter(Boolean).slice(0, 5).join(" | ");
  }

  async function handleRateLimitedProcedurePage() {
    const retryCount = getRateLimitRetryCount();

    if (retryCount >= DD_WI_RATE_LIMIT.MAX_429_RETRIES) {
      setCrawlActive(false);
      crawlStarted = false;
      setState("ERROR");
      throw new Error(
        `Delta Dental WI rate limit persisted after ${DD_WI_RATE_LIMIT.MAX_429_RETRIES} retries. ` +
        `The crawl was stopped safely. Wait a few minutes and click Crawl again.`
      );
    }

    const waitMs = DD_WI_RATE_LIMIT.RETRY_DELAYS_MS[retryCount];
    const nextRetry = retryCount + 1;

    setRateLimitRetryCount(nextRetry);
    setState("RATE_LIMITED");

    warn(
      `DD-WI rate limited (429). Retry ${nextRetry}/` +
      `${DD_WI_RATE_LIMIT.MAX_429_RETRIES} in ${Math.round(waitMs / 1000)}s.`,
      rateLimitMessageText()
    );

    /*
     * Keep the category index and active category untouched. After the
     * controlled cooldown, reload once so the portal can serve the same
     * category again. We never restart from Diagnostic.
     */
    await sleep(waitMs);
    location.reload();
  }

  function saveJSON(key, value) {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      error("sessionStorage write failed:", e);
    }
  }

  function loadJSON(key, fallback = null) {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function removeStorage(key) {
    try {
      sessionStorage.removeItem(key);
    } catch (_) {}
  }

  function cleanText(value) {
    return String(value ?? "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeName(value) {
    return cleanText(value)
      .toUpperCase()
      .replace(/[.,']/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeDOB(value) {
    const v = cleanText(value);
    if (!v) return "";

    const m = v.match(/(\d{1,2})\s*[\/\-]\s*(\d{1,2})\s*[\/\-]\s*(\d{4})/);
    if (!m) return v;

    return `${String(m[1]).padStart(2, "0")}/${String(m[2]).padStart(2, "0")}/${m[3]}`;
  }

  function text(el) {
    return el ? cleanText(el.textContent) : "";
  }

  function value(selector) {
    const el = document.querySelector(selector);
    return el ? cleanText(el.value) : "";
  }

  function fireChange(el) {
    if (!el) return;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function waitForElement(selector, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(selector);
      if (existing) {
        resolve(existing);
        return;
      }

      const started = Date.now();

      const observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) {
          observer.disconnect();
          resolve(el);
          return;
        }

        if (Date.now() - started >= timeout) {
          observer.disconnect();
          reject(new Error(`Timed out waiting for ${selector}`));
        }
      });

      observer.observe(document.documentElement, {
        childList: true,
        subtree: true
      });

      setTimeout(() => {
        observer.disconnect();
        const el = document.querySelector(selector);
        if (el) resolve(el);
        else reject(new Error(`Timed out waiting for ${selector}`));
      }, timeout);
    });
  }

  function isBenefitsSearchPage() {
    const path = location.pathname;
    return (
      path.includes("/dentist/patient-information/benefits-and-claims") &&
      !path.includes("/benefits-and-claims/benefits-and-claims")
    );
  }

  function isBenefitsResultPage() {
    return location.pathname.includes(
      "/dentist/patient-information/benefits-and-claims/benefits-and-claims"
    );
  }

  function isProcedurePage() {
    return location.pathname.includes(
      "/dentist/patient-information/procedure-code-search/procedure-code-search"
    );
  }

  function isLoggedInDeltaDentalPage() {
    return location.hostname === "www4.deltadentalwi.com";
  }

  function findField(form, names) {
    for (const name of names) {
      const el = form.querySelector(`[name="${name}"]`);
      if (el) return el;
      const byId = form.querySelector(`#${CSS.escape(name)}`);
      if (byId) return byId;
    }
    return null;
  }

  function looksLikePatientSearchForm(form) {
    if (!form) return false;

    const action = (form.getAttribute("action") || "").toLowerCase();
    const hasFirst = !!findField(form, ["firstName"]);
    const hasLast = !!findField(form, ["lastName"]);
    const hasDOB = !!findField(form, ["dobOne", "dob", "dateOfBirth"]);
    const hasMember = !!findField(form, ["memberNumber"]);

    return (
      action.includes("/benefits-and-claims/process") ||
      (hasFirst && hasLast && hasDOB) ||
      (hasFirst && hasLast && hasMember)
    );
  }

  function capturePatientFromForm(form) {
    const first = findField(form, ["firstName", "first_name"]);
    const last = findField(form, ["lastName", "last_name"]);
    const dob = findField(form, ["dobOne", "dob", "dateOfBirth"]);
    const member = findField(form, ["memberNumber", "memberID", "memberId"]);

    const firstName = cleanText(first?.value);
    const lastName = cleanText(last?.value);
    const dateOfBirth = normalizeDOB(dob?.value);
    const memberNumber = cleanText(member?.value);

    if (!firstName || !lastName || !dateOfBirth) {
      warn("Patient form was submitted but required patient fields were not found.");
      return null;
    }

    const patient = {
      firstName,
      lastName,
      dob: dateOfBirth,
      member_id_entered: memberNumber,
      normalizedName: normalizeName(`${firstName} ${lastName}`)
    };

    saveJSON(STORAGE.PATIENT, patient);
    setState("PATIENT_CAPTURED");
    log("Target patient captured:", {
      name: patient.normalizedName,
      dob: patient.dob
    });

    return patient;
  }

  let crawlStarted = false;

  /*
   * NEW DD-WI PATIENT SELECTION FLOW
   *
   * The patient is entered BEFORE the crawl starts. Once the portal reaches
   * the Benefits page, clicking "Crawl Full Insurance Plan" opens a selector
   * containing the family members shown in #eligibility.
   *
   * Only the member explicitly selected by the user becomes DD_WI_TARGET_PATIENT.
   * Nothing is crawled until that selection is confirmed.
   */

  function getFamilyMembersFromEligibility() {
    /*
     * Build the selector from ONLY patient name + Birthdate.
     * Some portal rows contain table headings in the same text node as the
     * first member, so the entire row text must never become the patient name.
     */
    const sectionSelectors = ["#eligibility", "#maxandded"];
    const members = [];
    const seen = new Set();

    const addMember = (nameRaw, dobRaw) => {
      let name = normalizeName(nameRaw);
      const dob = normalizeDOB(dobRaw);
      if (!name || !dob) return;

      // Remove obvious flattened table-heading text.
      const headingWords = new Set([
        "NAME", "AND", "COVERAGE", "DATES", "REGULAR", "ANNUAL",
        "DEDUCTIBLE", "SATISFIED", "MAXIMUM", "MAXIMUMS", "USED",
        "ORTHODONTIC", "LIFETIME", "CUSTOM", "OUT", "OF", "POCKET",
        "FAMILY", "BENEFIT", "BENEFITS"
      ]);

      let parts = name.split(/\s+/).filter(Boolean);

      // Keep the trailing patient-name portion if headings were prepended.
      const lastHeadingIndex = parts.reduce(
        (last, part, index) => headingWords.has(part) ? index : last,
        -1
      );

      if (lastHeadingIndex >= 0 && lastHeadingIndex < parts.length - 1) {
        const candidate = parts.slice(lastHeadingIndex + 1);
        if (candidate.length >= 2) parts = candidate;
      }

      // Never let a leading heading word survive.
      while (parts.length > 2 && headingWords.has(parts[0])) {
        parts.shift();
      }

      name = parts.join(" ").trim();
      if (!name) return;

      const key = `${name}::${dob}`;
      if (seen.has(key)) return;
      seen.add(key);

      const nameParts = name.split(/\s+/);
      members.push({
        firstName: nameParts[0] || "",
        lastName: nameParts.slice(1).join(" "),
        normalizedName: name,
        dob
      });
    };

    const extractFromRow = (row) => {
      if (!row) return;

      const cells = [...row.querySelectorAll("td, th")];

      for (const cell of cells) {
        const cellText = cleanText(cell.textContent || "");
        const dobMatch = cellText.match(
          /Birthdate\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i
        );
        if (!dobMatch) continue;

        let beforeDob = cellText.slice(0, dobMatch.index).trim();

        // Prefer visual lines: in the portal the patient name is normally
        // immediately above "Birthdate".
        const lines = String(cell.innerText || "")
          .split(/\r?\n/)
          .map(v => cleanText(v))
          .filter(Boolean);

        const birthLineIndex = lines.findIndex(line =>
          /Birthdate\s*[:\-]?\s*\d{1,2}\/\d{1,2}\/\d{4}/i.test(line)
        );

        if (birthLineIndex > 0) {
          beforeDob = lines[birthLineIndex - 1];
        } else if (lines.length) {
          // If headings and the patient name are flattened into one line,
          // take only the trailing name-like portion.
          const tokens = normalizeName(beforeDob).split(/\s+/);
          const candidate = tokens.slice(-4);
          if (candidate.length >= 2) {
            beforeDob = candidate.join(" ");
          }
        }

        addMember(beforeDob, dobMatch[1]);
        return;
      }

      // Fallback for unusual row structures.
      const rowLines = String(row.innerText || row.textContent || "")
        .split(/\r?\n/)
        .map(v => cleanText(v))
        .filter(Boolean);

      for (let i = 0; i < rowLines.length; i++) {
        const dobMatch = rowLines[i].match(
          /^Birthdate\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})$/i
        );
        if (dobMatch && i > 0) {
          addMember(rowLines[i - 1], dobMatch[1]);
          return;
        }
      }
    };

    for (const selector of sectionSelectors) {
      for (const section of [...document.querySelectorAll(selector)]) {
        for (const row of [...section.querySelectorAll("tr")]) {
          extractFromRow(row);
        }
      }
    }

    // Strict page-text fallback: only a line immediately before Birthdate.
    if (!members.length) {
      const lines = String(document.body?.innerText || "")
        .split(/\r?\n/)
        .map(v => cleanText(v))
        .filter(Boolean);

      for (let i = 0; i < lines.length; i++) {
        const dobMatch = lines[i].match(
          /^Birthdate\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})$/i
        );
        if (dobMatch && i > 0) {
          addMember(lines[i - 1], dobMatch[1]);
        }
      }
    }

    return members;
  }

  function removePatientSelectionModal() {
    const existing = document.getElementById("dd-wi-patient-selector");
    if (existing) existing.remove();
  }

  function showPatientSelectionModal() {
    removePatientSelectionModal();

    const members = getFamilyMembersFromEligibility();

    if (!members.length) {
      throw new Error(
        "No family members were found on the Benefits page. " +
        "The crawler was not started."
      );
    }

    const overlay = document.createElement("div");
    overlay.id = "dd-wi-patient-selector";

    Object.assign(overlay.style, {
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      background: "rgba(0,0,0,0.45)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "Arial, sans-serif"
    });

    const modal = document.createElement("div");
    Object.assign(modal.style, {
      width: "430px",
      maxWidth: "90vw",
      maxHeight: "80vh",
      overflow: "auto",
      background: "#fff",
      borderRadius: "8px",
      boxShadow: "0 8px 30px rgba(0,0,0,.35)",
      padding: "22px",
      boxSizing: "border-box"
    });

    const title = document.createElement("div");
    title.textContent = "Select Patient to Crawl";
    Object.assign(title.style, {
      fontSize: "20px",
      fontWeight: "700",
      marginBottom: "7px",
      color: "#333"
    });

    const subtitle = document.createElement("div");
    subtitle.textContent =
      "Select the one patient whose benefits and procedure information should be crawled.";
    Object.assign(subtitle.style, {
      fontSize: "13px",
      lineHeight: "1.4",
      marginBottom: "16px",
      color: "#555"
    });

    const list = document.createElement("div");

    members.forEach((member, index) => {
      const label = document.createElement("label");
      label.dataset.ddWiPatientIndex = String(index);

      Object.assign(label.style, {
        display: "flex",
        alignItems: "flex-start",
        gap: "10px",
        padding: "11px 10px",
        marginBottom: "7px",
        border: "1px solid #ddd",
        borderRadius: "5px",
        cursor: "pointer",
        background: "#fafafa"
      });

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.ddWiPatientIndex = String(index);
      checkbox.style.marginTop = "3px";
      checkbox.style.width = "16px";
      checkbox.style.height = "16px";

      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          // Only one family member may be selected.
          list
            .querySelectorAll('input[type="checkbox"]')
            .forEach(other => {
              if (other !== checkbox) other.checked = false;
            });
        }
        updateStartButton();
      });

      const details = document.createElement("div");

      const nameEl = document.createElement("div");
      nameEl.textContent = member.normalizedName;
      Object.assign(nameEl.style, {
        fontWeight: "700",
        color: "#222",
        fontSize: "14px"
      });

      const dobEl = document.createElement("div");
      dobEl.textContent = `Birthdate: ${member.dob}`;
      Object.assign(dobEl.style, {
        marginTop: "3px",
        color: "#555",
        fontSize: "12px"
      });

      details.appendChild(nameEl);
      details.appendChild(dobEl);

      label.appendChild(checkbox);
      label.appendChild(details);
      list.appendChild(label);
    });

    const status = document.createElement("div");
    status.textContent = "Select one patient.";
    Object.assign(status.style, {
      minHeight: "18px",
      margin: "12px 0 10px",
      fontSize: "12px",
      color: "#b3261e"
    });

    const buttons = document.createElement("div");
    Object.assign(buttons.style, {
      display: "flex",
      justifyContent: "flex-end",
      gap: "9px"
    });

    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    Object.assign(cancel.style, {
      padding: "9px 16px",
      border: "1px solid #aaa",
      borderRadius: "4px",
      background: "#fff",
      cursor: "pointer"
    });

    cancel.addEventListener("click", () => {
      removePatientSelectionModal();
      crawlStarted = false;
      setCrawlActive(false);
      setState("WAITING_FOR_PATIENT_SELECTION");
    });

    const start = document.createElement("button");
    start.type = "button";
    start.textContent = "Start Crawling";
    Object.assign(start.style, {
      padding: "9px 16px",
      border: "0",
      borderRadius: "4px",
      background: "#2f6fa3",
      color: "#fff",
      fontWeight: "700",
      cursor: "pointer",
      opacity: "0.5"
    });
    start.disabled = true;

    function getSelectedMember() {
      const selected = list.querySelector(
        'input[type="checkbox"]:checked'
      );
      if (!selected) return null;

      const index = Number(selected.dataset.ddWiPatientIndex);
      return Number.isInteger(index) ? members[index] || null : null;
    }

    function updateStartButton() {
      const selected = getSelectedMember();
      start.disabled = !selected;
      start.style.opacity = selected ? "1" : "0.5";
      status.textContent = selected
        ? `Selected: ${selected.normalizedName} (${selected.dob})`
        : "Select one patient.";
      status.style.color = selected ? "#287a32" : "#b3261e";
    }

    start.addEventListener("click", async () => {
      const selected = getSelectedMember();

      if (!selected) {
        status.textContent = "Please select one patient.";
        return;
      }

      start.disabled = true;
      cancel.disabled = true;
      status.textContent = `Starting crawl for ${selected.normalizedName}...`;
      status.style.color = "#333";

      try {
        beginSelectedPatientCrawl(selected);
        removePatientSelectionModal();

        // The Benefits page is already loaded, so continue immediately.
        await processBenefitsPage();
      } catch (e) {
        error("Failed to start selected-patient crawl:", e);
        removePatientSelectionModal();
        setCrawlActive(false);
        crawlStarted = false;
        setState("ERROR");
        alert(`Delta Dental WI crawl could not start: ${e.message}`);
      }
    });

    buttons.appendChild(cancel);
    buttons.appendChild(start);

    modal.appendChild(title);
    modal.appendChild(subtitle);
    modal.appendChild(list);
    modal.appendChild(status);
    modal.appendChild(buttons);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    updateStartButton();
    log(
      "Patient selector opened. Family members found:",
      members.map(m => `${m.normalizedName} ${m.dob}`)
    );
  }

  function beginSelectedPatientCrawl(patient) {
    /*
     * Start a completely fresh one-patient run only after the user chooses
     * the family member. This is the only point where RUN_ACTIVE becomes 1.
     */
    crawlStarted = true;
    setCrawlActive(true);
    clearRateLimitRetryCount();

    removeStorage(STORAGE.RESULT);
    removeStorage(STORAGE.BENEFITS_RESULT);
    removeStorage(STORAGE.PATIENT);

    // Clear category state so a previous patient can never leak into this run.
    removeStorage(CATEGORY_STORAGE.QUEUE);
    removeStorage(CATEGORY_STORAGE.INDEX);
    removeStorage(CATEGORY_STORAGE.ACTIVE);

    try {
      if (typeof chrome !== "undefined" && chrome.storage?.local) {
        chrome.storage.local.remove([
          "audit_context",
          "dd_wi_data",
          "DD_WI_FINAL_JSON"
        ]);
      }
    } catch (_) {}

    saveJSON(STORAGE.PATIENT, patient);
    setState("PATIENT_CAPTURED");

    log("Selected target patient:", {
      name: patient.normalizedName,
      dob: patient.dob
    });
  }

  function startCrawlFromPopup() {
    /*
     * NEW FLOW:
     * Patient details are entered before the crawl starts.
     * Clicking Crawl only opens the family-member selector.
     */
    if (crawlStarted || isCrawlActive()) {
      log("Crawl already active.");
      return { ok: true, alreadyStarted: true };
    }

    /*
     * Cool down between completed patient crawls. This prevents a user
     * from immediately starting another full Benefits + category crawl.
     */
    const lastCompletedAt = getLastCompletedAt();
    if (lastCompletedAt) {
      const elapsed = Date.now() - lastCompletedAt;
      const remaining =
        DD_WI_RATE_LIMIT.INTER_PATIENT_COOLDOWN_MS - elapsed;

      if (remaining > 0) {
        const seconds = Math.ceil(remaining / 1000);
        return {
          ok: false,
          error:
            `Delta Dental WI cooldown is active. Please wait about ` +
            `${seconds} second${seconds === 1 ? "" : "s"} before starting another patient.`
        };
      }
    }

    /*
     * Do not depend on one exact Benefits-page URL shape. The portal can
     * render the same family Benefits page under slightly different paths.
     * The presence of the family-member table is the authoritative signal
     * that the patient selector can be opened.
     */
    const familyMembers = getFamilyMembersFromEligibility();
    if (!familyMembers.length) {
      return {
        ok: false,
        error:
          "No family members were found on this Benefits page. Open the family Benefits page first, then click Crawl Full Insurance Plan."
      };
    }

    try {
      showPatientSelectionModal();
      setState("WAITING_FOR_PATIENT_SELECTION");
      log("Waiting for user to select the patient to crawl.");
      return { ok: true, selectionRequired: true };
    } catch (e) {
      error("Unable to open patient selector:", e);
      return { ok: false, error: e.message };
    }
  }

  function installPatientSearchCapture() {
    const forms = [...document.forms].filter(looksLikePatientSearchForm);

    if (!forms.length) {
      log("No patient search form detected on this page.");
      return;
    }

    for (const form of forms) {
      if (form.dataset.ddWiBound === "1") continue;

      form.dataset.ddWiBound = "1";

      form.addEventListener("submit", () => {
        capturePatientFromForm(form);
        /*
         * Do not preventDefault.
         * The site's own POST/navigation must continue normally.
         */
      }, true);

      log("Patient search listener installed.");
    }

    log("Patient search listener ready. Waiting for Crawl button.");
  }

  function parseNameAndDOBFromMemberText(raw) {
    const cleaned = cleanText(raw);
    const match = cleaned.match(/^(.*?)\s*--\s*DOB:\s*(\d{1,2}\/\d{1,2}\/\d{4})$/i);

    if (match) {
      return {
        name: normalizeName(match[1]),
        dob: normalizeDOB(match[2])
      };
    }

    return {
      name: normalizeName(cleaned.replace(/\s*--.*$/, "")),
      dob: ""
    };
  }

  function memberMatchesTarget(name, dob, target) {
    if (!target) return false;

    const n = normalizeName(name);
    const d = normalizeDOB(dob);

    return (
      n === normalizeName(target.normalizedName || `${target.firstName} ${target.lastName}`) &&
      (!target.dob || !d || d === normalizeDOB(target.dob))
    );
  }

  function findTargetMemberRow(section, target) {
    if (!section || !target) return null;

    const targetName = normalizeName(
      target.normalizedName || `${target.firstName} ${target.lastName}`
    );
    const targetDOB = normalizeDOB(target.dob);

    const rows = [...section.querySelectorAll("tr")];

    /*
     * Delta Dental does not render the eligibility/member row identically
     * for every patient/plan. In some responses the member name + Birthdate
     * are in the first cell; in others they are split across cells.
     *
     * The previous implementation only inspected:
     *   td[headers="mbrName"] / td:first-child
     *
     * That caused a false "patient not found" for valid patients such as
     * DAVID MELENDEZ even though the Benefits page was for that patient.
     *
     * Keep the one-patient safety requirement: accept a row only when the
     * exact target name AND exact target DOB are present in the SAME row.
     */
    for (const row of rows) {
      const rawRow = cleanText(row.textContent);
      if (!rawRow) continue;

      const normalizedRow = normalizeName(rawRow);

      if (!normalizedRow.includes(targetName)) {
        continue;
      }

      // Prefer an explicitly labelled Birthdate, if present.
      const labelledDOB = rawRow.match(
        /Birthdate\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i
      )?.[1] || "";

      // Some portal variants render the DOB without the "Birthdate" label.
      // In that case, require the exact captured DOB to occur in the row.
      const exactTargetDOBPresent =
        !!targetDOB &&
        normalizeName(rawRow).includes(normalizeName(targetDOB));

      const rowDOB = normalizeDOB(labelledDOB || (exactTargetDOBPresent ? targetDOB : ""));

      if (targetDOB && rowDOB !== targetDOB) {
        continue;
      }

      if (memberMatchesTarget(targetName, rowDOB, target)) {
        return row;
      }
    }

    return null;
  }

  function parseSubscriberInfo() {
    const qualifier = document.querySelector("table.member");
    const result = {
      subscriber_name: "",
      coverage_type: "",
      member_number: "",
      group_number: "",
      group_name: "",
      electronic_claims_payer_id: ""
    };

    if (!qualifier) return result;

    const cells = [...qualifier.querySelectorAll("td")];

    for (const cell of cells) {
      const raw = cleanText(cell.textContent);

      if (/SUBSCRIBER NAME:/i.test(raw)) {
        result.subscriber_name = raw.replace(/^.*?SUBSCRIBER NAME:\s*/i, "");
      } else if (/COVERAGE TYPE:/i.test(raw)) {
        result.coverage_type = raw.replace(/^.*?COVERAGE TYPE:\s*/i, "");
      } else if (/MEMBER NUMBER:/i.test(raw)) {
        result.member_number = raw.replace(/^.*?MEMBER NUMBER:\s*/i, "");
      } else if (/GROUP NUMBER:/i.test(raw)) {
        result.group_number = raw.replace(/^.*?GROUP NUMBER:\s*/i, "");
      } else if (/GROUP NAME:/i.test(raw)) {
        result.group_name = raw.replace(/^.*?GROUP NAME:\s*/i, "");
      } else if (/ELECTRONIC CLAIMS PAYER ID:/i.test(raw)) {
        result.electronic_claims_payer_id =
          raw.replace(/^.*?ELECTRONIC CLAIMS PAYER ID:\s*/i, "");
      }
    }

    return result;
  }

  function parsePlanMaxDed() {
    const section = document.querySelector("#maxandded");
    const output = [];

    if (!section) return output;

    const table = [...section.querySelectorAll("table")].find(t =>
      t.querySelector("#maxDedDesc")
    );

    if (!table) return output;

    const headers = [...table.querySelectorAll("tr:first-child th")]
      .map(th => cleanText(th.textContent));

    for (const tr of [...table.querySelectorAll("tr")].slice(1)) {
      const cells = [...tr.children].map(td => cleanText(td.textContent));
      if (cells.length < 2) continue;

      const item = {
        category: cells[0],
        delta_dental_ppo: cells[1] || "",
        delta_dental_premier: cells[2] || "",
        out_of_network: cells[3] || ""
      };

      if (item.category) output.push(item);
    }

    return output;
  }

  function moneyNumber(value) {
    const n = parseFloat(String(value || "").replace(/[$,]/g, ""));
    return Number.isFinite(n) ? n : null;
  }

  function moneyString(value) {
    if (value == null) return "";
    return `$${value.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  }

  function calculateRemaining(total, used) {
    const t = moneyNumber(total);
    const u = moneyNumber(used);

    if (t == null || u == null) return "N/A";
    return moneyString(Math.max(0, t - u));
  }

  function parseMemberAccumulation() {
    const section = document.querySelector("#eligibility");
    const result = {
      target_row: null,
      benefit_year: "",
      member_values: {}
    };

    if (!section) return result;

    const yearText = text(section.querySelector("p"));
    const yearMatch = yearText.match(
      /Benefit Year[^:]*defined as:\s*([0-9/]+\s*-\s*[0-9/]+)/i
    );
    if (yearMatch) result.benefit_year = yearMatch[1];

    const target = loadJSON(STORAGE.PATIENT);
    const row = findTargetMemberRow(section, target);

    if (!row) {
      throw new Error("Target patient was not found in Eligibility and Accumulations.");
    }

    const cells = [...row.children].map(td => cleanText(td.textContent));

    result.target_row = {
      name_and_coverage_dates: cells[0] || "",
      regular_annual_deductible_satisfied: cells[1] || "",
      regular_annual_maximum_used: cells[2] || "",
      orthodontic_annual_maximum_used: cells[3] || "",
      orthodontic_lifetime_maximum_used: cells[4] || "",
      custom_annual_maximum_used: cells[5] || "",
      out_of_pocket_maximum_satisfied: cells[6] || ""
    };

    result.member_values = {
      regular_annual_deductible_satisfied: result.target_row.regular_annual_deductible_satisfied,
      regular_annual_maximum_used: result.target_row.regular_annual_maximum_used,
      orthodontic_annual_maximum_used: result.target_row.orthodontic_annual_maximum_used,
      orthodontic_lifetime_maximum_used: result.target_row.orthodontic_lifetime_maximum_used,
      custom_annual_maximum_used: result.target_row.custom_annual_maximum_used,
      out_of_pocket_maximum_satisfied: result.target_row.out_of_pocket_maximum_satisfied
    };

    return result;
  }

  function buildFinancials(memberAccumulation, planMaxDed) {
    const used = memberAccumulation.member_values || {};

    const getPlanValue = category => {
      const row = planMaxDed.find(
        x => normalizeName(x.category) === normalizeName(category)
      );
      return row ? row.delta_dental_ppo : "N/A";
    };

    const maximums = [
      {
        category: "Annual Maximum",
        total: getPlanValue("Annual Maximums"),
        used: used.regular_annual_maximum_used || "N/A",
        remaining: calculateRemaining(
          getPlanValue("Annual Maximums"),
          used.regular_annual_maximum_used
        )
      },
      {
        category: "Orthodontic Annual Maximum",
        total: getPlanValue("Ortho Annual Maximums"),
        used: used.orthodontic_annual_maximum_used || "N/A",
        remaining: calculateRemaining(
          getPlanValue("Ortho Annual Maximums"),
          used.orthodontic_annual_maximum_used
        )
      },
      {
        category: "Orthodontic Lifetime Maximum",
        total: getPlanValue("Ortho Lifetime Maximums"),
        used: used.orthodontic_lifetime_maximum_used || "N/A",
        remaining: calculateRemaining(
          getPlanValue("Ortho Lifetime Maximums"),
          used.orthodontic_lifetime_maximum_used
        )
      },
      {
        category: "Custom Annual Maximum",
        total: getPlanValue("Custom Annual Maximums"),
        used: used.custom_annual_maximum_used || "N/A",
        remaining: calculateRemaining(
          getPlanValue("Custom Annual Maximums"),
          used.custom_annual_maximum_used
        )
      },
      {
        category: "Out of Pocket Maximum",
        total: "N/A",
        used: used.out_of_pocket_maximum_satisfied || "N/A",
        remaining: "N/A"
      }
    ];

    const deductibles = [
      {
        category: "Individual Deductible",
        total: getPlanValue("Annual Deductibles"),
        used: used.regular_annual_deductible_satisfied || "N/A",
        remaining: calculateRemaining(
          getPlanValue("Annual Deductibles"),
          used.regular_annual_deductible_satisfied
        )
      },
      {
        category: "Orthodontic Deductible",
        total: getPlanValue("Ortho Annual Deductibles"),
        used: "N/A",
        remaining: "N/A"
      }
    ];

    return { maximums, deductibles };
  }

  function parseCoverageAges() {
    const section = document.querySelector("#frequency");
    const result = {
      child_coverage_age: "",
      student_coverage_age: "",
      adult_orthodontic: "",
      dependent_orthodontic_age: ""
    };

    if (!section) return result;

    const allCells = [...section.querySelectorAll("td")];

    for (const td of allCells) {
      const raw = cleanText(td.textContent);

      if (/Child Coverage Age:/i.test(raw)) {
        result.child_coverage_age = raw.replace(/^.*?Child Coverage Age:\s*/i, "");
      } else if (/Student Coverage Age:/i.test(raw)) {
        result.student_coverage_age = raw.replace(/^.*?Student Coverage Age:\s*/i, "");
      } else if (/Adult Orthodontic:/i.test(raw)) {
        result.adult_orthodontic = raw.replace(/^.*?Adult Orthodontic:\s*/i, "");
      } else if (/Dependent Orthodontic Age:/i.test(raw)) {
        result.dependent_orthodontic_age =
          raw.replace(/^.*?Dependent Orthodontic Age:\s*/i, "");
      }
    }

    return result;
  }

  function parseFrequencyAgeLimitations() {
    const table = document.querySelector(
      "#frequency table.bcnolines tr th#frqServices"
    )?.closest("table");

    if (!table) return [];

    return [...table.querySelectorAll("tbody > tr")]
      .slice(1)
      .map(tr => {
        const cells = [...tr.children].map(td => cleanText(td.textContent));
        if (!cells[0]) return null;

        return {
          service: cells[0] || "",
          frequency_and_other_benefit_limitations: cells[1] || "",
          age_limitations: cells[2] || ""
        };
      })
      .filter(Boolean);
  }

  function parseBenefitLevels() {
    const table = document.querySelector(
      "#benefits table.bcnolines tr th#benServices"
    )?.closest("table");

    if (!table) return [];

    return [...table.querySelectorAll("tbody tr")]
      .map(tr => {
        // Only parse actual data rows. Header rows contain <th>, not <td>.
        const cells = [...tr.querySelectorAll("td")].map(td => cleanText(td.textContent));
        if (cells.length < 3 || !cells[0]) return null;

        return {
          service: cells[0],
          delta_dental_ppo: {
            benefit_level: cells[1] || "",
            deductible_applies: cells[2] || ""
          }
        };
      })
      .filter(Boolean);
  }

  function parseExtraBenefits() {
    const section = document.querySelector("#ebicpDiv");
    if (!section) return [];

    return [{
      description: text(section),
      enrolled_action_available: !!section.querySelector("#ebicp-button")
    }];
  }

  function findNamedBlock(section, target) {
    if (!section || !target) return null;

    const targetName = normalizeName(target.normalizedName);

    const bolds = [...section.querySelectorAll("p.bold")];

    for (const p of bolds) {
      if (normalizeName(text(p)) === targetName) {
        return p;
      }
    }

    const allElements = [...section.querySelectorAll("*")];

    for (const el of allElements) {
      if (el.children.length === 0 && normalizeName(text(el)) === targetName) {
        return el;
      }
    }

    return null;
  }

  function tablesAfterNamedBlock(section, target) {
    const marker = findNamedBlock(section, target);
    if (!marker) return [];

    const tables = [];
    let node = marker.nextElementSibling;

    while (node) {
      if (node.matches && node.matches("p.bold")) break;

      if (node.matches && node.matches("table")) {
        tables.push(node);
      }

      if (node.querySelectorAll) {
        for (const table of node.querySelectorAll("table")) {
          if (!tables.includes(table)) tables.push(table);
        }
      }

      node = node.nextElementSibling;
    }

    return tables;
  }

  function parsePreventiveHistory(target) {
    const section = document.querySelector("#history");
    if (!section) return [];

    const tables = tablesAfterNamedBlock(section, target);
    const output = [];

    /*
     * Preventive History tables contain a header row such as:
     *
     *   Procedure | DOS
     *
     * Do not scrape that row as actual patient history.
     */
    const HEADER_VALUES = new Set([
      "PROCEDURE",
      "DOS",
      "DATE OF SERVICE",
      "SERVICE DATE"
    ]);

    for (const table of tables) {
      const rows = [...table.querySelectorAll("tbody > tr, tr")];

      for (const tr of rows) {
        const cells = [...tr.children]
          .map(td => cleanText(td.textContent))
          .filter(Boolean);

        if (!cells.length) continue;

        // Skip <thead> rows and rows whose cells are the table headings.
        if (tr.closest("thead")) continue;

        const normalizedCells = cells.map(v => normalizeName(v));

        if (
          normalizedCells.length >= 2 &&
          HEADER_VALUES.has(normalizedCells[0]) &&
          HEADER_VALUES.has(normalizedCells[1])
        ) {
          continue;
        }

        // Also skip any repeated header row containing "Procedure" / "DOS".
        if (
          normalizedCells.some(v => v === "PROCEDURE") &&
          normalizedCells.some(v => v === "DOS")
        ) {
          continue;
        }

        /*
         * The actual history table is Procedure/DOS pairs.
         * Only accept a pair when the first cell is not a heading.
         */
        for (let i = 0; i + 1 < cells.length; i += 2) {
          const procedure = cleanText(cells[i]);
          const dos = cleanText(cells[i + 1]);

          if (!procedure || !dos) continue;

          const procedureNormalized = normalizeName(procedure);
          const dosNormalized = normalizeName(dos);

          if (
            procedureNormalized === "PROCEDURE" ||
            dosNormalized === "DOS" ||
            (procedureNormalized === "PROCEDURE" &&
             dosNormalized === "DATE OF SERVICE") ||
            (procedureNormalized === "PROCEDURE" &&
             dosNormalized === "SERVICE DATE")
          ) {
            continue;
          }

          output.push({
            procedure,
            dos
          });
        }
      }
    }

    return output;
  }


  function parseClaims(target) {
    const section = document.querySelector("#claims");
    if (!section) return [];

    const tables = tablesAfterNamedBlock(section, target);

    return tables.flatMap(table => {
      const headers = [...table.querySelectorAll("tr:first-child th")]
        .map(th => cleanText(th.textContent));

      return [...table.querySelectorAll("tbody > tr")]
        .slice(1)
        .map(tr => {
          const cells = [...tr.children].map(td => cleanText(td.textContent));
          if (!cells.length) return null;

          const view = tr.querySelector("a[href*='claim-detail']");
          return {
            detail: view ? "View" : cells[0] || "",
            detail_url: view?.href || "",
            from_date: cells[1] || "",
            to_date: cells[2] || "",
            amount_charged: cells[3] || "",
            delta_dental_payment: cells[4] || "",
            patient_pays: cells[5] || "",
            orthodontic_schedule: cells[6] || "",
            status: cells[7] || ""
          };
        })
        .filter(Boolean);
    });
  }

  function parseWaitingPeriods(target) {
    const section = document.querySelector("#waiting");
    if (!section) return [];

    const table = section.querySelector("table");
    if (!table) return [];

    const rows = [...table.querySelectorAll("tbody tr")];
    const result = [];

    for (const tr of rows) {
      const leftService = tr.querySelector("td[headers='waitServices']");
      const leftDuration = tr.querySelector("td[headers='waitDuration']");
      const leftMembers = tr.querySelector("td[headers='waitMembers']");

      const rightService = tr.querySelector("td[headers='waitServices2']");
      const rightDuration = tr.querySelector("td[headers='waitDuration2']");
      const rightMembers = tr.querySelector("td[headers='waitMembers2']");

      if (leftService) {
        const service = cleanText(leftService.textContent);
        if (service) {
          result.push({
            service,
            waiting_period_duration: cleanText(leftDuration?.textContent || ""),
            members: cleanText(leftMembers?.textContent || "")
          });
        }
      }

      if (rightService) {
        const service = cleanText(rightService.textContent);
        if (service) {
          result.push({
            service,
            waiting_period_duration: cleanText(rightDuration?.textContent || ""),
            members: cleanText(rightMembers?.textContent || "")
          });
        }
      }
    }

    return result;
  }

  function parseOrthoSchedule(target) {
    const section = document.querySelector("#ortho");
    if (!section) return [];

    const name = normalizeName(target.normalizedName);

    /*
     * Ortho Schedule is member-oriented. Use a text/name boundary so
     * another family member's orthodontic schedule is not mixed in.
     */
    const textContent = text(section);
    if (!textContent.toUpperCase().includes(name)) {
      return [];
    }

    return [...section.querySelectorAll("table")].map(table => {
      const rows = [...table.querySelectorAll("tr")].map(tr =>
        [...tr.children].map(td => cleanText(td.textContent))
      );

      return {
        rows
      };
    }).filter(x => x.rows.length);
  }

  function parseMissingToothClause() {
    const bodyText = text(document.body);

    const patterns = [
      /missing tooth(?: clause)?\s*[:\-]\s*(yes|no)/i,
      /missing teeth(?: clause)?\s*[:\-]\s*(yes|no)/i,
      /missing tooth[^.]{0,80}\b(yes|no)\b/i
    ];

    for (const pattern of patterns) {
      const m = bodyText.match(pattern);
      if (m) return m[1];
    }

    return "";
  }

  function parseTargetPatientFromEligibility(target) {
    const section = document.querySelector("#eligibility");
    const row = findTargetMemberRow(section, target);

    if (!row) return null;

    // Read the complete matched row because the portal can split member
    // information across multiple <td> elements.
    const raw = cleanText(row.textContent);

    const dob = normalizeDOB(
      raw.match(
        /Birthdate\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i
      )?.[1] || target.dob
    );

    const start = normalizeDOB(
      raw.match(
        /Start\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i
      )?.[1] || ""
    );

    const endMatch = raw.match(
      /End\s*[:\-]?\s*(\d{1,2}\/\d{1,2}\/\d{4})/i
    );
    const end = endMatch ? normalizeDOB(endMatch[1]) : "Present";

    /*
     * Do not derive the patient's name from arbitrary row text. We already
     * matched the exact target name + DOB in this row, so use the captured
     * patient name as the authoritative name.
     */
    const name = target.normalizedName ||
      `${target.firstName} ${target.lastName}`;

    return {
      name,
      dob,
      start,
      end
    };
  }

  function extractBenefits() {
    const target = loadJSON(STORAGE.PATIENT);

    if (!target) {
      throw new Error("No target patient is stored.");
    }

    const subscriber = parseSubscriberInfo();
    const eligibilityPatient = parseTargetPatientFromEligibility(target);

    if (!eligibilityPatient) {
      /*
       * Diagnostic only. Do not fall back to another patient or scrape
       * blindly. The crawl must remain one-patient-only.
       */
      warn(
        "Target patient validation failed on Benefits page.",
        {
          target_name: target.normalizedName,
          target_dob: target.dob,
          benefits_heading: cleanText(
            document.querySelector("h1, h2, h3")?.textContent || ""
          )
        }
      );

      throw new Error(
        `Target patient ${target.normalizedName} ${target.dob} was not found on Benefits page.`
      );
    }

    const planMaxDed = parsePlanMaxDed();
    const accumulation = parseMemberAccumulation();
    const coverageAges = parseCoverageAges();

    const result = {
      patient: {
        name: eligibilityPatient.name,
        subscriber_name: subscriber.subscriber_name,
        member_id: subscriber.member_number,
        dob: eligibilityPatient.dob || target.dob,
        relationship: ""
      },

      plan_details: {
        employer_group: subscriber.group_name,
        group_number: subscriber.group_number,
        effective_date: eligibilityPatient.start || "",
        termination_date: eligibilityPatient.end || "Present",
        network_status: "",
        coverage_type: subscriber.coverage_type,
        plan_type: ""
      },

      financials: buildFinancials(accumulation, planMaxDed),

      benefit_categories: [],

      missing_tooth_clause: parseMissingToothClause(),

      dependent_age_limit: parseInt(
        String(coverageAges.child_coverage_age || "").match(/\d+/)?.[0] || "",
        10
      ) || null,

      coverage_ages: coverageAges,

      frequency_age_limitations: parseFrequencyAgeLimitations(),

      benefit_levels: parseBenefitLevels(),

      extra_benefits_levels: parseExtraBenefits(),

      waiting_periods: parseWaitingPeriods(target),

      preventive_history: parsePreventiveHistory(target),

      claims: parseClaims(target),

      ortho_schedule: parseOrthoSchedule(target),

      benefit_coverage: {
        procedures: []
      },

      ddri_data: true,

      _source: {
        benefits_page: location.href,
        as_of_date: value("#datepicker"),
        benefit_verification_number:
          (() => {
            const m = text(document.body).match(
              /Benefit Verification Number:\s*([A-Za-z0-9-]+)/i
            );
            return m ? m[1] : "";
          })()
      }
    };

    /*
     * network_status / plan_type are not represented in the supplied
     * Benefits HTML. Do not fabricate them. They remain empty unless
     * the live page provides a corresponding value.
     */

    saveJSON(STORAGE.BENEFITS_RESULT, result);
    setState("BENEFITS_SCRAPED");

    log("Benefits scraped successfully.");
    return result;
  }

  function getProcedureForm() {
    return (
      document.querySelector("form#form[action*='procedure-code-search-process']") ||
      document.querySelector("form[action*='procedure-code-search-process']")
    );
  }

  function getProcedurePatientSelect() {
    return document.querySelector("#depNbrBandID");
  }

  function selectTargetProcedurePatient() {
    const target = loadJSON(STORAGE.PATIENT);
    const select = getProcedurePatientSelect();

    if (!target || !select) {
      throw new Error("Procedure patient selector #depNbrBandID was not found.");
    }

    const options = [...select.options];

    const match = options.find(option => {
      if (!option.value) return false;

      const parsed = parseNameAndDOBFromMemberText(option.textContent);
      return memberMatchesTarget(parsed.name, parsed.dob, target);
    });

    if (!match) {
      throw new Error(
        `Target patient ${target.normalizedName} ${target.dob} was not found in #depNbrBandID.`
      );
    }

    select.value = match.value;
    fireChange(select);

    const selected = select.options[select.selectedIndex];
    const selectedParsed = parseNameAndDOBFromMemberText(selected.textContent);

    if (!memberMatchesTarget(selectedParsed.name, selectedParsed.dob, target)) {
      throw new Error("Procedure patient validation failed after selection.");
    }

    setState("PROCEDURE_PATIENT_SELECTED");

    log("Procedure patient selected:", selected.textContent.trim());

    return selected;
  }

  function validateProcedurePatient() {
    const target = loadJSON(STORAGE.PATIENT);
    const select = getProcedurePatientSelect();

    if (!target || !select || select.selectedIndex < 0) {
      return false;
    }

    const option = select.options[select.selectedIndex];
    const parsed = parseNameAndDOBFromMemberText(option.textContent);

    const valid = memberMatchesTarget(
      parsed.name,
      parsed.dob,
      target
    );

    if (!valid) {
      error(
        "STOP: procedure patient mismatch.",
        {
          target: `${target.normalizedName} ${target.dob}`,
          selected: `${parsed.name} ${parsed.dob}`
        }
      );
      setState("ERROR");
    }

    return valid;
  }

  function getCategoryQueueFromDOM() {
    const select = document.querySelector("#category");
    if (!select) return [];

    return [...select.options]
      .map(option => ({
        value: cleanText(option.value),
        label: cleanText(option.textContent)
      }))
      .filter(item => item.value && item.label);
  }

  function categoryQueue() {
    const saved = loadJSON(CATEGORY_STORAGE.QUEUE);
    if (Array.isArray(saved) && saved.length) return saved;

    const current = getCategoryQueueFromDOM();

    if (current.length) {
      saveJSON(CATEGORY_STORAGE.QUEUE, current);
    }

    return current;
  }

  function getCategoryIndex() {
    const raw = sessionStorage.getItem(CATEGORY_STORAGE.INDEX);
    const n = parseInt(raw || "0", 10);
    return Number.isFinite(n) ? n : 0;
  }

  function setCategoryIndex(index) {
    sessionStorage.setItem(CATEGORY_STORAGE.INDEX, String(index));
  }

  function setActiveCategory(category) {
    saveJSON(CATEGORY_STORAGE.ACTIVE, category || null);
  }

  function getActiveCategory() {
    return loadJSON(CATEGORY_STORAGE.ACTIVE, null);
  }

  function initializeCategoryCrawl() {
    const queue = getCategoryQueueFromDOM();

    if (!queue.length) {
      throw new Error("No procedure categories were found in #category.");
    }

    /*
     * Always initialize a fresh category crawl after Benefits scraping.
     * This prevents a previous patient's category index from leaking into
     * the current run.
     */
    saveJSON(CATEGORY_STORAGE.QUEUE, queue);
    setCategoryIndex(0);
    setActiveCategory(null);

    log(`Loaded ${queue.length} procedure categories from #category.`);
    return queue;
  }

  function getCurrentCategory() {
    const queue = categoryQueue();
    const index = getCategoryIndex();
    return queue[index] || null;
  }

  function normalizeHeader(header) {
    return cleanText(header)
      .toUpperCase()
      .replace(/[*:]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function findProcedureResultTables() {
    const candidates = [...document.querySelectorAll("table")];

    return candidates.filter(table => {
      const headerText = normalizeHeader(
        [...table.querySelectorAll("thead th, tr:first-child th, tr:first-child td")]
          .map(cell => cell.textContent)
          .join(" | ")
      );

      const hasProcedure =
        /\bPROCEDURE\b/.test(headerText) ||
        /\bPROCEDURE CODE\b/.test(headerText);

      const hasBenefit =
        /DELTA DENTAL PPO/.test(headerText) ||
        /BENEFIT LEVEL/.test(headerText) ||
        /COMMENTS/.test(headerText) ||
        /OTHER BENEFIT LIMITATIONS/.test(headerText);

      return hasProcedure && hasBenefit;
    });
  }

  function getTableHeaders(table) {
    const headerRow =
      table.querySelector("thead tr") ||
      table.querySelector("tr:first-child");

    if (!headerRow) return [];

    return [...headerRow.children].map(cell => normalizeHeader(cell.textContent));
  }

  function findHeaderIndex(headers, patterns) {
    return headers.findIndex(header =>
      patterns.some(pattern => pattern.test(header))
    );
  }

  function extractProcedureCode(raw) {
    const value = cleanText(raw);

    /*
     * CDT procedure codes are normally D + four digits, but the portal may
     * expose other identifiers. Prefer a CDT code and fall back to a
     * five-character numeric code if that is what the portal returned.
     */
    const m = value.match(/\bD\d{4}\b/i);
    if (m) return m[0].toUpperCase();

    const numeric = value.match(/\b\d{5}\b/);
    if (numeric) return numeric[0];

    return value.split(/\s+/)[0] || "";
  }

  function extractProcedureRowsFromTable(table, category) {
    const headers = getTableHeaders(table);

    const codeIndex = findHeaderIndex(headers, [
      /^PROCEDURE$/,
      /^PROCEDURE CODE$/,
      /PROCEDURE\s+CODE/
    ]);

    const descriptionIndex = findHeaderIndex(headers, [
      /PROCEDURE DESCRIPTION/,
      /^DESCRIPTION$/
    ]);

    const typeIndex = findHeaderIndex(headers, [/^TYPE$/]);

    const ppoIndex = findHeaderIndex(headers, [
      /DELTA DENTAL PPO/,
      /^PPO NETWORK$/,
      /PPO/
    ]);

    const premierIndex = findHeaderIndex(headers, [
      /DELTA DENTAL PREMIER/,
      /^PREMIER NETWORK$/,
      /PREMIER/
    ]);

    const oonIndex = findHeaderIndex(headers, [
      /OUT OF NETWORK/,
      /^OUT OF NETWORK$/
    ]);

    const waitingIndex = findHeaderIndex(headers, [
      /WAITING PERIOD/
    ]);

    const frequencyIndex = findHeaderIndex(headers, [
      /FREQUENCY/
    ]);

    const ageIndex = findHeaderIndex(headers, [
      /AGE LIMIT/
    ]);

    // Only use a dedicated Alternate Benefit column for alternate_benefit.
    // COMMENTS must never be treated as alternate benefits because comments
    // commonly contain deductible/frequency text that is mapped separately.
    const alternateIndex = findHeaderIndex(headers, [
      /ALTERNATE BENEFIT/,
      /OTHER BENEFIT LIMITATIONS/,
      /BENEFIT LIMITATIONS/
    ]);

    const commentsIndex = findHeaderIndex(headers, [
      /COMMENTS/
    ]);

    const rows = [...table.querySelectorAll("tbody tr")];

    return rows.map(tr => {
      const cells = [...tr.children].map(td => cleanText(td.textContent));

      if (!cells.length) return null;

      const codeCell =
        codeIndex >= 0
          ? cells[codeIndex]
          : cells.find(cell => /\bD\d{4}\b/i.test(cell) || /\b\d{5}\b/.test(cell));

      if (!codeCell) return null;

      const procedureCode = extractProcedureCode(codeCell);

      if (!procedureCode) return null;

      const description =
        descriptionIndex >= 0
          ? cells[descriptionIndex]
          : "";

      const ppo =
        ppoIndex >= 0
          ? cells[ppoIndex]
          : "";

      const premier =
        premierIndex >= 0
          ? cells[premierIndex]
          : "";

      const oon =
        oonIndex >= 0
          ? cells[oonIndex]
          : "";

      const comments =
        commentsIndex >= 0
          ? cells[commentsIndex]
          : "";

      const alternate =
        alternateIndex >= 0
          ? cells[alternateIndex]
          : "";

      const waiting =
        waitingIndex >= 0
          ? cells[waitingIndex]
          : "";

      const frequency =
        frequencyIndex >= 0
          ? cells[frequencyIndex]
          : "";

      const age =
        ageIndex >= 0
          ? cells[ageIndex]
          : "";

      const rawComment =
        comments ||
        alternate ||
        [waiting, frequency, age].filter(Boolean).join(" ");

      const commentInfo = parseProcedureComment(rawComment);

      /*
       * Category result tables can expose three benefit columns. If all
       * three are None/N/A, classify the procedure as NOT COVERED.
       */
      const benefitValues = [ppo, premier, oon].map(cleanText);
      const hasAnyBenefit = benefitValues.some(v =>
        v &&
        !/^(none|n\/a|na|-|not covered)$/i.test(v)
      );

      const coverageStatus = hasAnyBenefit
        ? "COVERED"
        : "NOT COVERED";

      return {
        procedure_code: procedureCode,
        description: description || "N/A",
        type: typeIndex >= 0 ? cells[typeIndex] : "",
        coverage_status: coverageStatus,
        coverage_percentage:
          ppo && !/^(none|n\/a|na|-|not covered)$/i.test(ppo)
            ? ppo
            : "N/A",
        deductible_applies:
          parseDeductibleFromCells(ppo, premier, oon, rawComment),
        waiting_period:
          waiting || commentInfo.waiting_period || "N/A",
        alternate_benefit:
          alternate || commentInfo.alternate_benefit || "N/A",
        frequency:
          frequency || commentInfo.frequency || "N/A",
        age_limit:
          age || commentInfo.age_limit || "N/A",
        history: [],
        network_values: {
          delta_dental_ppo: ppo || "None",
          delta_dental_premier: premier || "None",
          out_of_network: oon || "None"
        },
        comments: rawComment || "",
        category: category?.label || ""
      };
    }).filter(Boolean);
  }

  function parseDeductibleFromCells(ppo, premier, oon, comment) {
    /*
     * The portal's authoritative deductible information is often in
     * Comments, e.g.:
     *   "Deductible Applies."
     *   "Deductible does not apply."
     *
     * Always evaluate the explicit comment wording first.
     */
    const commentText = cleanText(comment);

    if (/deductible\s+does\s+not\s+apply/i.test(commentText)) {
      return "No";
    }

    if (/deductible\s+applies/i.test(commentText)) {
      return "Yes";
    }

    const values = [ppo, premier, oon]
      .map(cleanText)
      .filter(Boolean);

    if (values.some(v => /\bYES\b/i.test(v) && /deductible/i.test(v))) {
      return "Yes";
    }

    if (values.some(v => /\bNO\b/i.test(v) && /deductible/i.test(v))) {
      return "No";
    }

    return "N/A";
  }

  function parseProcedureCategoryResults(category) {
    const tables = findProcedureResultTables();

    if (!tables.length) {
      return [];
    }

    const results = [];

    for (const table of tables) {
      const rows = extractProcedureRowsFromTable(table, category);
      for (const row of rows) {
        /*
         * A procedure code can legitimately have multiple Types
         * (for example Ortho and Non-Ortho). Keep both rows.
         * Only suppress an exact duplicate of code + type.
         */
        const rowCode = normalizeName(row.procedure_code);
        const rowType = normalizeName(row.type || "");

        if (
          !results.some(existing =>
            normalizeName(existing.procedure_code) === rowCode &&
            normalizeName(existing.type || "") === rowType
          )
        ) {
          results.push(row);
        }
      }
    }

    return results;
  }

  function mergeProcedureResults(procedures) {
    const result = loadJSON(STORAGE.BENEFITS_RESULT, null);

    if (!result) {
      throw new Error("Benefits result was not found while merging procedure data.");
    }

    if (!result.benefit_coverage) {
      result.benefit_coverage = { procedures: [] };
    }

    for (const procedure of procedures) {
      const code = normalizeName(procedure.procedure_code);

      if (!code) continue;

      const procedureType = normalizeName(procedure.type || "");

      const existingIndex =
        result.benefit_coverage.procedures.findIndex(
          p =>
            normalizeName(p.procedure_code) === code &&
            normalizeName(p.type || "") === procedureType
        );

      if (existingIndex >= 0) {
        /*
         * Keep the richer result if the same code appears in another
         * category/result block.
         */
        const existing = result.benefit_coverage.procedures[existingIndex];

        result.benefit_coverage.procedures[existingIndex] = {
          ...existing,
          ...procedure,
          description:
            procedure.description &&
            procedure.description !== "N/A"
              ? procedure.description
              : existing.description || "N/A"
        };
      } else {
        result.benefit_coverage.procedures.push(procedure);
      }
    }

    saveJSON(STORAGE.BENEFITS_RESULT, result);
    return result;
  }

  function recordCategoryWithNoResults(category) {
    const result = loadJSON(STORAGE.BENEFITS_RESULT, null);
    if (!result) {
      throw new Error("Benefits result was not found while recording empty category.");
    }

    if (!Array.isArray(result.procedure_categories)) {
      result.procedure_categories = [];
    }

    const existing = result.procedure_categories.find(
      item => item.value === category.value
    );

    const entry = {
      value: category.value,
      label: category.label,
      procedure_count: 0
    };

    if (existing) {
      Object.assign(existing, entry);
    } else {
      result.procedure_categories.push(entry);
    }

    saveJSON(STORAGE.BENEFITS_RESULT, result);
  }

  function recordCategorySummary(category, count) {
    const result = loadJSON(STORAGE.BENEFITS_RESULT, null);
    if (!result) return;

    if (!Array.isArray(result.procedure_categories)) {
      result.procedure_categories = [];
    }

    const existing = result.procedure_categories.find(
      item => item.value === category.value
    );

    const entry = {
      value: category.value,
      label: category.label,
      procedure_count: count
    };

    if (existing) {
      Object.assign(existing, entry);
    } else {
      result.procedure_categories.push(entry);
    }

    saveJSON(STORAGE.BENEFITS_RESULT, result);
  }

  function getProcedureResultDescriptionFromSingleResult() {
    const p = document.querySelector(".codesearchresults p");
    if (!p) return "";

    const raw = cleanText(p.textContent);
    return raw.replace(/^[A-Za-z0-9-]+\s*-\s*/, "").trim();
  }

  function parseSingleProcedureResultFallback() {
    const table = findProcedureResultTables()[0];
    if (!table) return null;

    const category = getActiveCategory();
    const rows = extractProcedureRowsFromTable(table, category);

    if (!rows.length) return null;

    const row = rows[0];

    const description = getProcedureResultDescriptionFromSingleResult();

    if (description) {
      row.description = description;
    }

    return row;
  }
  function getCurrentProcedureResultCode() {
    const heading = document.querySelector(".codesearchresults h3");
    const m = text(heading).match(/Procedure Code:\s*([A-Za-z0-9-]+)/i);
    if (m) return cleanText(m[1]);

    const p = document.querySelector(".codesearchresults p");
    const pm = text(p).match(/^([A-Za-z0-9-]+)\s*-/);
    return pm ? cleanText(pm[1]) : "";
  }

  function parseProcedureComment(comment) {
    const c = cleanText(comment);

    let deductible = "N/A";
    if (/deductible does not apply/i.test(c)) {
      deductible = "No";
    } else if (/deductible applies/i.test(c)) {
      deductible = "Yes";
    }

    // Alternate benefit is optional. Do not put deductible/frequency text
    // into this field. Only populate it when an actual alternate-benefit
    // statement is present in a dedicated column or in the comments.
    let alternate = "N/A";
    const alternateMatch = c.match(/(?:^|[.;])\s*([^.;]*alternate benefit[^.;]*)/i);
    if (alternateMatch) {
      const statement = cleanText(alternateMatch[1]);
      alternate = /no alternate benefit/i.test(statement) ? "N/A" : statement;
    }

    let waiting = "None";
    const waitingMatch = c.match(
      /waiting(?: period)?\s*(?:is|:|-)?\s*([^.;]+)/i
    );
    if (waitingMatch) waiting = cleanText(waitingMatch[1]);

    let ageLimit = "N/A";
    const ageMatch = c.match(
      /\b(?:age|ages|children under|dependent children under)\b[^.;]*/i
    );
    if (ageMatch) ageLimit = cleanText(ageMatch[0]);

    let frequency = "N/A";

    const frequencyPatterns = [
      /(\d+\s+in\s+a\s+benefit\s+year)/i,
      /(\d+\s+per\s+(?:calendar\s+year|benefit\s+year))/i,
      /(once\s+every\s+\d+\s+(?:months|years?))/i,
      /(once\s+per\s+[^.;]+)/i,
      /(twice\s+per\s+[^.;]+)/i,
      /(one\s+procedure\s+per\s+[^.;]+)/i,
      /(once\s+per\s+[^.;]+)/i,
      /(for\s+dependent\s+children[^.;]+)/i
    ];

    for (const pattern of frequencyPatterns) {
      const m = c.match(pattern);
      if (m) {
        frequency = cleanText(m[1]);
        break;
      }
    }

    if (frequency === "N/A" && /deductible does not apply/i.test(c)) {
      const stripped = c
        .replace(/deductible does not apply\.?/i, "")
        .trim();
      if (stripped) frequency = stripped;
    }

    return {
      deductible_applies: deductible,
      waiting_period: waiting,
      alternate_benefit: alternate,
      frequency,
      age_limit: ageLimit,
      raw_comments: c
    };
  }

  function parseProcedureResult() {
    const resultTable = document.querySelector(
      ".codesearchresults + table"
    );

    if (!resultTable) {
      /*
       * Fallback: find the table whose first header contains Procedure
       * and which appears inside the form.
       */
      const form = getProcedureForm();
      const candidate = [...(form?.querySelectorAll("table") || [])]
        .find(table => {
          const headers = [...table.querySelectorAll("tr:first-child th")]
            .map(th => normalizeName(th.textContent));
          return headers[0] === "PROCEDURE" &&
            headers.includes("TYPE") &&
            headers.includes("COMMENTS");
        });

      if (!candidate) return null;
      return parseProcedureTable(candidate);
    }

    return parseProcedureTable(resultTable);
  }

  function parseProcedureTable(table) {
    const rows = [...table.querySelectorAll("tbody > tr")];

    if (!rows.length) return null;

    const firstData = rows[0];
    const cells = [...firstData.children].map(td => cleanText(td.textContent));

    if (cells.length < 6) return null;

    const codeFromPage = getCurrentProcedureResultCode();
    const code = codeFromPage || cells[0];

    const parsedComment = parseProcedureComment(cells[5]);

    return {
      procedure_code: code,
      description: "",
      coverage_status:
        /none/i.test(cells[2]) && /none/i.test(cells[3]) && /none/i.test(cells[4])
          ? "NOT COVERED"
          : "COVERED",
      coverage_percentage:
        cells[2] && !/^none$/i.test(cells[2]) ? cells[2] : "N/A",
      deductible_applies: parsedComment.deductible_applies,
      waiting_period: parsedComment.waiting_period,
      alternate_benefit: parsedComment.alternate_benefit,
      frequency: parsedComment.frequency,
      age_limit: parsedComment.age_limit,
      history: [],
      network_values: {
        delta_dental_ppo: cells[2] || "",
        delta_dental_premier: cells[3] || "",
        out_of_network: cells[4] || ""
      },
      comments: cells[5] || ""
    };
  }

  function parseProcedureDescription() {
    const p = document.querySelector(".codesearchresults p");
    if (!p) return "";

    const raw = cleanText(p.textContent);
    return raw.replace(/^[A-Za-z0-9-]+\s*-\s*/, "").trim();
  }

  function mergeProcedureResult(procedure) {
    const result = loadJSON(STORAGE.BENEFITS_RESULT, null);

    if (!result) {
      throw new Error("Benefits result was not found while merging procedure data.");
    }

    if (!result.benefit_coverage) {
      result.benefit_coverage = { procedures: [] };
    }

    const description = parseProcedureDescription();
    if (description) procedure.description = description;

    const code = normalizeName(procedure.procedure_code);

    const procedureType = normalizeName(procedure.type || "");

    const existingIndex = result.benefit_coverage.procedures.findIndex(
      p =>
        normalizeName(p.procedure_code) === code &&
        normalizeName(p.type || "") === procedureType
    );

    if (existingIndex >= 0) {
      result.benefit_coverage.procedures[existingIndex] = procedure;
    } else {
      result.benefit_coverage.procedures.push(procedure);
    }

    saveJSON(STORAGE.BENEFITS_RESULT, result);
    return result;
  }

  function submitProcedureCategory(category) {
    const form = getProcedureForm();

    if (!form) {
      throw new Error("Procedure search form was not found.");
    }

    if (!validateProcedurePatient()) {
      throw new Error("Procedure patient mismatch; category submission blocked.");
    }

    const categoryInput = document.querySelector("#category");
    const codeInput = document.querySelector("#procedureCode");
    const keyword = document.querySelector("#keyword");

    if (!categoryInput) {
      throw new Error("#category was not found.");
    }

    categoryInput.value = category.value;

    if (codeInput) codeInput.value = "";
    if (keyword) keyword.value = "";

    fireChange(categoryInput);
    if (codeInput) fireChange(codeInput);
    if (keyword) fireChange(keyword);

    setActiveCategory(category);
    setState("PROCEDURE_CATEGORY_RESULTS");

    log(
      `Submitting procedure category ${category.label} (${category.value})`
    );

    const submitButton =
      document.querySelector("#procCodeSubmit") ||
      form.querySelector("[name='procCodeSubmit']");

    if (typeof form.requestSubmit === "function" && submitButton) {
      form.requestSubmit(submitButton);
    } else if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      form.submit();
    }
  }

  function getProcedureNotFoundMessage() {
    /*
     * Delta Dental can return an empty category without using a dedicated
     * result table.  The exact wording can vary between page versions, so
     * inspect the procedure-result area first and then fall back to common
     * alert/message containers.  Return the actual message text when one is
     * present, otherwise return an empty string.
     */
    const selectors = [
      ".codesearchresults",
      "#codesearchresults",
      ".procedurecode",
      ".alert",
      ".error",
      ".message",
      ".notification",
      ".validation-summary-errors"
    ];

    const seen = new Set();
    const messages = [];

    for (const selector of selectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (seen.has(el)) continue;
        seen.add(el);

        const value = cleanText(el.textContent);
        if (!value) continue;

        /* Do not treat the search form labels/dropdowns themselves as an
         * empty-result message. */
        const lower = value.toLowerCase();
        const looksEmpty =
          /no\s+(?:procedure(?:s)?|results?|records?|codes?)/i.test(value) ||
          /(?:procedure|code|category).*(?:not found|not available)/i.test(value) ||
          /no matching/i.test(value) ||
          /nothing found/i.test(value) ||
          /0\s+(?:procedure(?:s)?|results?|records?)/i.test(value);

        if (looksEmpty) {
          messages.push(value);
        }
      }
    }

    /* Also inspect visible page text for portal variants that are not
     * wrapped in a stable message class. */
    const bodyText = cleanText(document.body?.innerText || document.body?.textContent || "");
    if (bodyText) {
      const lines = bodyText
        .split(/\n+/)
        .map(cleanText)
        .filter(Boolean);

      for (const line of lines) {
        if (
          /no\s+(?:procedure(?:s)?|results?|records?|codes?)/i.test(line) ||
          /(?:procedure|code|category).*(?:not found|not available)/i.test(line) ||
          /no matching/i.test(line) ||
          /nothing found/i.test(line)
        ) {
          messages.push(line);
        }
      }
    }

    return [...new Set(messages)].join(" | ");
  }

  function looksLikeProcedureCategoryResultPage() {
    return (
      isProcedurePage() &&
      (
        findProcedureResultTables().length > 0 ||
        getProcedureNotFoundMessage()
      )
    );
  }

  async function processProcedurePage() {
    if (isRateLimitedPage()) {
      await handleRateLimitedProcedurePage();
      return;
    }

    const target = loadJSON(STORAGE.PATIENT);

    if (!target) {
      throw new Error("Target patient is missing on procedure page.");
    }

    await waitForElement("#depNbrBandID", 15000);

    /*
     * The supplied HTML shows that the page heading/hidden memberName can
     * refer to the subscriber while #depNbrBandID contains the actual
     * selected patient. The dropdown remains authoritative.
     */
    selectTargetProcedurePatient();

    if (!validateProcedurePatient()) {
      throw new Error("Target patient failed procedure-page validation.");
    }

    /*
     * Category crawl starts from the live dropdown, not a hard-coded list.
     */
    let queue = categoryQueue();

    if (!queue.length) {
      queue = initializeCategoryCrawl();
    }

    let index = getCategoryIndex();
    const active = getActiveCategory();

    /*
     * If this is a category result page, scrape ALL rows returned for the
     * current category before advancing.
     */
    const hasCategoryResults = findProcedureResultTables().length > 0;
    const notFound = getProcedureNotFoundMessage();

    if (hasCategoryResults || notFound) {
      clearRateLimitRetryCount();
    }

    if (active && (hasCategoryResults || notFound)) {
      let procedures = [];

      if (hasCategoryResults) {
        procedures = parseProcedureCategoryResults(active);

        /*
         * Some portal responses may use the single-code result layout.
         * Use the fallback only when category parsing found no rows.
         */
        if (!procedures.length) {
          const fallback = parseSingleProcedureResultFallback();
          if (fallback) procedures = [fallback];
        }
      }

      if (procedures.length) {
        mergeProcedureResults(procedures);
      }

      recordCategorySummary(active, procedures.length);

      /*
       * Whether a category returns 1 row, 100 rows, or no rows, it is a
       * completed category. Never stop the entire crawl because a category
       * is empty or has an error message.
       */
      index += 1;
      setCategoryIndex(index);
      setActiveCategory(null);

      log(
        `Completed category ${active.label}: ${procedures.length} procedure(s).`
      );
    }

    const nextCategory = queue[index];

    if (!nextCategory) {
      finish();
      return;
    }

    /*
     * Submit exactly one category, then let the portal navigate to the
     * category result page. The next content-script execution resumes at
     * the same category index.
     */
    const categoryDelay = getCategoryDelayMs();
    log(
      `Waiting ${Math.round(categoryDelay / 1000)}s before category ` +
      `${nextCategory.label}.`
    );
    await sleep(categoryDelay);
    submitProcedureCategory(nextCategory);
  }
  function openProcedureSearch() {
    if (!AUTO_OPEN_PROCEDURE_SEARCH) return;

    const button =
      document.querySelector("#proc-search") ||
      document.querySelector("[name='procCodeButton']");

    if (!button) {
      warn("Procedure search button not found on Benefits page.");
      return;
    }

    setState("PROCEDURE_PAGE");

    log("Opening Procedure Code Search.");

    /*
     * Use the portal's own procedure-search action instead of constructing
     * an unrelated request.
     */
    button.click();
  }

  /*
   * FINAL OUTPUT FILTER
   *
   * The portal is crawled completely first. Only after the full crawl do we
   * reduce the result to the exact JSON requested by the application.
   */
  const FINAL_PROCEDURE_CODES = [
    "00180", "00120", "00140", "00150", "00210",
    "00220", "00230", "00240", "00274", "00330",
    "01510", "01110", "01120", "01206", "01351",
    "02140", "02331", "02620", "02740", "02950",
    "02991", "03347", "03310", "03330", "04260",
    "04341", "04355", "04381", "04910", "05860",
    "05110", "05740", "05982", "06194", "06010",
    "06056", "06065", "06245", "07259", "07140",
    "07240", "08010", "08080", "08090", "09430",
    "09110", "09222", "09239", "09310", "09944"
  ];

  const FINAL_CATEGORY_ORDER = [
    "Diagnostic",
    "Preventive",
    "Sealant",
    "Restorations",
    "Crowns",
    "Misc Restorative",
    "Non-surgical Endodontics",
    "Surgical Endodontics",
    "Surgical Periodontics",
    "Non-surgical Periodontics",
    "Dentures/removable Prosth",
    "Denture Repairs & Adj",
    "Denture Reline & Rebase",
    "Implants",
    "Bridges/fixed Prosth",
    "Bridge Repair",
    "Simple Extractions",
    "Orthodontic Extractions",
    "Oral Surgery",
    "Orthodontics",
    "Ancillary"
  ];

  function canonicalProcedureCode(code) {
    const raw = cleanText(code).toUpperCase();
    const numeric = raw.replace(/^D/, "");

    // Requested output uses five numeric digits. Portal may return D0180.
    if (/^D\d{4}$/.test(raw)) return `0${numeric}`;
    if (/^\d{5}$/.test(numeric)) return numeric;
    return numeric;
  }

  function categoryOrderIndex(category) {
    const normalized = normalizeName(category || "");
    const exact = FINAL_CATEGORY_ORDER.findIndex(
      item => normalizeName(item) === normalized
    );
    if (exact >= 0) return exact;

    // Portal labels can vary slightly in capitalization/spelling.
    const partial = FINAL_CATEGORY_ORDER.findIndex(item =>
      normalized.includes(normalizeName(item)) ||
      normalizeName(item).includes(normalized)
    );
    return partial >= 0 ? partial : FINAL_CATEGORY_ORDER.length;
  }

  function filterAndFinalizeOutput(result) {
    if (!result || typeof result !== "object") return result;

    // 1. Keep PPO only in financials. buildFinancials already creates PPO
    //    totals; normalize the structure here so no Premier/OON fields survive.
    if (result.financials) {
      result.financials.maximums = Array.isArray(result.financials.maximums)
        ? result.financials.maximums.map(item => ({
            category: item.category || "",
            total: item.total || "",
            used: item.used || "",
            remaining: item.remaining || ""
          }))
        : [];

      result.financials.deductibles = Array.isArray(result.financials.deductibles)
        ? result.financials.deductibles.map(item => ({
            category: item.category || "",
            total: item.total || "",
            used: item.used || "",
            remaining: item.remaining || ""
          }))
        : [];
    }

    // 2. Remove all table-header rows from frequency/age and benefit levels.
    result.frequency_age_limitations = Array.isArray(result.frequency_age_limitations)
      ? result.frequency_age_limitations.filter(row =>
          row && row.service &&
          !/^services(?:\s*\(sample code displayed\))?$/i.test(cleanText(row.service))
        )
      : [];

    result.benefit_levels = Array.isArray(result.benefit_levels)
      ? result.benefit_levels.filter(row =>
          row && row.service &&
          !/^services(?:\s*\(sample code displayed\))?$/i.test(cleanText(row.service))
        )
      : [];

    // 3. Waiting Periods: preserve both halves of the real portal table,
    //    but never include its heading row.
    result.waiting_periods = Array.isArray(result.waiting_periods)
      ? result.waiting_periods.filter(row =>
          row && row.service &&
          !/^services$/i.test(cleanText(row.service))
        )
      : [];

    // 4. Remove sections explicitly not requested.
    delete result.extra_benefits_levels;
    delete result.claims;
    delete result.ortho_schedule;
    delete result.procedure_categories;
    delete result._source;
    delete result.ddri_data;

    // 5. Keep only the requested procedure codes AFTER all categories have
    //    been crawled. Arrange them by the category returned by the portal.
    const wanted = new Set(FINAL_PROCEDURE_CODES);
    const allProcedures = Array.isArray(result.benefit_coverage?.procedures)
      ? result.benefit_coverage.procedures
      : [];

    const selected = allProcedures
      .map(procedure => {
        const outputCode = canonicalProcedureCode(procedure.procedure_code);
        if (!wanted.has(outputCode)) return null;

        return {
          ...procedure,
          procedure_code: outputCode,
          description: cleanText(procedure.description) || "N/A",
          category: cleanText(procedure.category) || ""
        };
      })
      .filter(Boolean);

    /*
     * Deduplicate by procedure code + type.
     * The portal can return two legitimate rows for the same code,
     * such as Ortho and Non-Ortho. Both must remain in the final JSON.
     */
    const byCodeAndType = new Map();
    for (const procedure of selected) {
      const key =
        `${procedure.procedure_code}::${normalizeName(procedure.type || "")}`;

      if (!byCodeAndType.has(key)) {
        byCodeAndType.set(key, procedure);
      }
    }

    const FINAL_CODE_CATEGORY = {
      "00180": "Diagnostic", "00120": "Diagnostic", "00140": "Diagnostic",
      "00150": "Diagnostic", "00210": "Diagnostic", "00220": "Diagnostic",
      "00230": "Diagnostic", "00240": "Diagnostic", "00274": "Diagnostic",
      "00330": "Diagnostic",
      "01510": "Preventive", "01110": "Preventive", "01120": "Preventive",
      "01206": "Preventive",
      "01351": "Sealant",
      "02140": "Restorations", "02331": "Restorations", "02620": "Restorations",
      "02740": "Crowns",
      "02950": "Misc Restorative", "02991": "Misc Restorative",
      "03347": "Non-surgical Endodontics", "03310": "Non-surgical Endodontics",
      "03330": "Non-surgical Endodontics",
      "04260": "Surgical Periodontics",
      "04341": "Non-surgical Periodontics", "04355": "Non-surgical Periodontics",
      "04381": "Non-surgical Periodontics", "04910": "Non-surgical Periodontics",
      "05860": "Dentures/removable Prosth", "05110": "Dentures/removable Prosth",
      "05740": "Denture Reline & Rebase", "05982": "Dentures/removable Prosth",
      "06194": "Implants", "06010": "Implants", "06056": "Implants", "06065": "Implants",
      "06245": "Bridges/fixed Prosth",
      "07259": "Oral Surgery", "07140": "Simple Extractions", "07240": "Oral Surgery",
      "08010": "Orthodontics", "08080": "Orthodontics", "08090": "Orthodontics",
      "09430": "Ancillary", "09110": "Ancillary", "09222": "Ancillary",
      "09239": "Ancillary", "09310": "Ancillary", "09944": "Ancillary"
    };

    const finalProcedures = [...byCodeAndType.values()]
      .sort((a, b) => {
        const categoryA = a.category || FINAL_CODE_CATEGORY[a.procedure_code] || "";
        const categoryB = b.category || FINAL_CODE_CATEGORY[b.procedure_code] || "";
        const categoryDiff =
          categoryOrderIndex(categoryA) - categoryOrderIndex(categoryB);
        if (categoryDiff !== 0) return categoryDiff;
        return FINAL_PROCEDURE_CODES.indexOf(a.procedure_code) -
          FINAL_PROCEDURE_CODES.indexOf(b.procedure_code);
      })
      .map(procedure => {
        const outputCategory =
          cleanText(procedure.category) || FINAL_CODE_CATEGORY[procedure.procedure_code] || "";

        // Remove internal/network-only fields that were useful during crawl.
        const {
          network_values,
          comments,
          ...cleanProcedure
        } = procedure;

        return {
          ...cleanProcedure,
          type: cleanText(procedure.type) || "N/A",
          category: outputCategory
        };
      });

    // Add requested codes that were not returned by any category. They are
    // valid requested targets but absent from the portal response, so the
    // final output must explicitly mark them as NOT COVERED rather than
    // silently dropping them.
    for (const code of FINAL_PROCEDURE_CODES) {
      if (finalProcedures.some(item => item.procedure_code === code)) continue;

      finalProcedures.push({
        procedure_code: code,
        description: "N/A",
        coverage_status: "NOT COVERED",
        coverage_percentage: "N/A",
        deductible_applies: "N/A",
        waiting_period: "N/A",
        alternate_benefit: "N/A",
        frequency: "N/A",
        age_limit: "N/A",
        history: [],
        category: FINAL_CODE_CATEGORY[code] || ""
      });
    }

    // Sort again after adding missing codes so the output remains category-wise.
    finalProcedures.sort((a, b) => {
      const categoryDiff =
        categoryOrderIndex(a.category) - categoryOrderIndex(b.category);
      if (categoryDiff !== 0) return categoryDiff;
      return FINAL_PROCEDURE_CODES.indexOf(a.procedure_code) -
        FINAL_PROCEDURE_CODES.indexOf(b.procedure_code);
    });

    if (!result.benefit_coverage) result.benefit_coverage = {};
    result.benefit_coverage.procedures = finalProcedures;

    // 6. Final procedure count is based only on the filtered output.
    result.procedure_count = finalProcedures.length;

    // 7. No crawl metadata/source metadata should be exposed in final JSON.
    delete result.procedure_crawl_mode;
    delete result.procedure_category_count;

    return result;
  }

  function downloadFinalJSONAutomatically(result) {
    try {
      if (!result || typeof result !== "object") {
        throw new Error("Final JSON object is empty.");
      }

      /*
       * Content scripts cannot directly call chrome.downloads.download().
       * Use the browser's normal HTML download mechanism so the completed
       * JSON appears in the browser Downloads section.
       */
      const patientName = cleanText(
        result.patient?.name || "Delta_Dental_WI_Patient"
      )
        .replace(/[^a-z0-9]+/gi, "_")
        .replace(/^_+|_+$/g, "")
        .slice(0, 80) || "Delta_Dental_WI_Patient";

      const filename =
        `DD_WI_${patientName}_Insurance_Audit_${new Date()
          .toISOString()
          .replace(/[:.]/g, "-")}.json`;

      const blob = new Blob(
        [JSON.stringify(result, null, 2)],
        { type: "application/json;charset=utf-8" }
      );

      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");

      anchor.href = url;
      anchor.download = filename;
      anchor.style.display = "none";
      anchor.rel = "noopener";

      document.documentElement.appendChild(anchor);

      // Trigger exactly ONE browser download.
      anchor.click();
      anchor.remove();

      setTimeout(() => URL.revokeObjectURL(url), 10000);

      log("Final JSON download triggered:", filename);

      return { ok: true, filename };
    } catch (e) {
      error("Automatic JSON download failed:", e);
      return { ok: false, error: e.message };
    }
  }

  async function finish() {
    const result = loadJSON(STORAGE.BENEFITS_RESULT, null);

    if (!result) {
      error("No final result available.");
      setState("ERROR");
      return;
    }

    // IMPORTANT: crawling is already complete here. Apply all requested
    // output filters only now, immediately before JSON serialization/download.
    const filteredResult = filterAndFinalizeOutput(result);
    const finalJson = JSON.stringify(filteredResult, null, 2);

    // Keep it in sessionStorage for the current tab.
    saveJSON(STORAGE.RESULT, filteredResult);

    // IMPORTANT: the common popup reads `audit_context` from
    // chrome.storage.local. Store the completed Delta WI JSON there so the
    // existing common Download Patient JSON button can export it.
    try {
      if (typeof chrome !== "undefined" && chrome.storage?.local) {
        await new Promise((resolve) => {
          chrome.storage.local.set(
            {
              audit_context: filteredResult,
              dd_wi_data: filteredResult,
              DD_WI_FINAL_JSON: filteredResult
            },
            () => {
              if (chrome.runtime?.lastError) {
                error("Failed to save final JSON to chrome.storage.local:", chrome.runtime.lastError.message);
              } else {
                log("Final JSON saved to common audit_context storage.");
              }
              resolve();
            }
          );
        });
      }
    } catch (e) {
      error("chrome.storage.local save failed:", e);
    }

    /*
     * Automatically download the completed JSON only after the entire
     * category crawl and final storage write have completed.
     */
    const downloadResult = downloadFinalJSONAutomatically(filteredResult);

    /*
     * Start the inter-patient cooldown only after the final JSON download
     * has been triggered successfully.
     */
    if (downloadResult.ok) {
      setLastCompletedAt();
    }
    clearRateLimitRetryCount();

    /*
     * TERMINAL STATE:
     * Once the final JSON download has been triggered, this run is over.
     * Navigation/re-rendering must NOT resume the crawler.
     * A new run can only be started by clicking Crawl Full Insurance Plan
     * again in the common popup.
     */
    setCrawlActive(false);
    crawlStarted = false;
    removeStorage(CATEGORY_STORAGE.ACTIVE);

    setState("COMPLETE");
    window.__DD_WI_RESULT = filteredResult;

    if (!downloadResult.ok) {
      warn(
        "Crawl completed, but automatic browser download failed. " +
        "The JSON remains available in chrome.storage.local.audit_context."
      );
    }

    // Always print a complete, copyable JSON object to DevTools.
    console.log("[DD-WI] FINAL JSON:");
    console.log(finalJson);
    console.log("[DD-WI] FINAL JSON OBJECT:", result);

    log(
      "Complete. Procedure records:",
      result.benefit_coverage?.procedures?.length || 0
    );

    // Small non-PHI completion indicator. The actual JSON remains in the
    // common extension storage and is available from the popup Download
    // button.
    try {
      const old = document.getElementById("dd-wi-complete-indicator");
      if (old) old.remove();
      const indicator = document.createElement("div");
      indicator.id = "dd-wi-complete-indicator";
      indicator.textContent = "Delta Dental WI crawl complete — JSON ready in extension.";
      Object.assign(indicator.style, {
        position: "fixed",
        right: "20px",
        bottom: "20px",
        zIndex: "2147483647",
        padding: "12px 16px",
        background: "#2f7d32",
        color: "#fff",
        fontSize: "13px",
        fontFamily: "Arial, sans-serif",
        borderRadius: "4px",
        boxShadow: "0 2px 8px rgba(0,0,0,.25)"
      });
      document.body.appendChild(indicator);
      setTimeout(() => indicator.remove(), 8000);
    } catch (_) {}
  }

  async function processBenefitsPage() {
    if (!isCrawlActive()) {
      log("Benefits page reached, but no active crawl exists. Waiting for Crawl button.");
      return;
    }

    const target = loadJSON(STORAGE.PATIENT);

    if (!target) {
      warn(
        "Benefits page loaded without DD_WI_TARGET_PATIENT. " +
        "The extension will not scrape a patient blindly."
      );
      return;
    }

    setState("BENEFITS_PAGE");

    try {
      await waitForElement("#eligibility", 15000);
      await waitForElement("#frequency", 15000);
      await waitForElement("#benefits", 15000);

      const result = extractBenefits();

      log("Target patient validated on Benefits page:", result.patient.name);

      /*
       * Initialize the category crawl only after Benefits data has been
       * successfully scraped. The actual category list is read later from
       * #category on the live Procedure Code Search page.
       */
      removeStorage(CATEGORY_STORAGE.QUEUE);
      removeStorage(CATEGORY_STORAGE.INDEX);
      removeStorage(CATEGORY_STORAGE.ACTIVE);

      if (AUTO_OPEN_PROCEDURE_SEARCH) {
        await sleep(1500);
        openProcedureSearch();
      } else {
        finish();
      }
    } catch (e) {
      error("Benefits scraping failed:", e);
      setCrawlActive(false);
      crawlStarted = false;
      setState("ERROR");
    }
  }

  async function processProcedurePageSafe() {
    if (!isCrawlActive()) {
      log("Procedure page reached, but crawl is inactive. Waiting for Crawl button.");
      return;
    }

    try {
      await processProcedurePage();
    } catch (e) {
      error("Procedure scraping failed:", e);
      setState("ERROR");
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || !message.command) return;

    if (message.command === "START_CRAWL") {
      try {
        sendResponse(startCrawlFromPopup());
      } catch (e) {
        error("Failed to start Delta Dental WI crawl:", e);
        sendResponse({ ok: false, error: e.message });
      }
      return true;
    }

    if (message.command === "DOWNLOAD_DD_WI_JSON") {
      const result = loadJSON(STORAGE.RESULT, null) || window.__DD_WI_RESULT || null;
      if (!result) {
        sendResponse({ ok: false, error: "No Delta Dental WI result available." });
        return true;
      }

      const blob = new Blob([JSON.stringify(result, null, 2)], {
        type: "application/json"
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `DD_WI_Insurance_Audit_${Date.now()}.json`;
      document.documentElement.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);

      sendResponse({ ok: true });
      return true;
    }
  });

  function boot() {
    if (!isLoggedInDeltaDentalPage()) return;

    log("initialized on:", location.href);

    /*
     * IMPORTANT:
     * Content scripts execute again after each portal navigation.
     * Never resume an old crawl automatically. The persistent RUN_ACTIVE
     * flag is set only by START_CRAWL from the common popup and is cleared
     * as soon as the final JSON download is triggered or the run errors.
     */
    if (!isCrawlActive()) {
      if (isBenefitsSearchPage()) {
        log("No active crawl. Waiting for Crawl Full Insurance Plan.");
      } else {
        log("No active crawl. Not scraping this page.");
      }
      return;
    }

    if (isBenefitsSearchPage()) {
      // Do not show the patient popup or bind the search form on page load.
      // The common extension popup controls when the crawl begins.
      log("Benefits search page detected. Waiting for Crawl Full Insurance Plan.");
      return;
    }

    if (isBenefitsResultPage()) {
      processBenefitsPage();
      return;
    }

    if (isProcedurePage()) {
      processProcedurePageSafe();
      return;
    }

    // Do not auto-start on unrelated pages. The common popup controls the crawl.
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
