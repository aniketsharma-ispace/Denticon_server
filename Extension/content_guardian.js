/*
 * content_guardian.js
 * Guardian Anytime (guardiananytime.com) — Dental VOB extractor.
 *
 * VOB CAPTURE: still passive. Guardian's SPA fires POST
 * /gaprovider/api/dental-vob/ppo automatically when the "Dental Eligibility"
 * page loads. We read that response the same way as before — zero extra
 * requests for this part.
 *
 * PROCEDURE-CODE DERIVATION: no direct CDT API sweep is performed. Guardian's
 * Plan Options data is already captured from the page's own VOB response and
 * contains the service/category/coinsurance/limitation material needed to
 * derive the requested 59 CDT records locally. This avoids triggering the
 * Guardian security layer that blocks automated CDT POSTs with HTTP 403.
 *
 * ARCHITECTURE (dual-world, same as content_dd_toolkit.js):
 *   MAIN world     -> monkey-patches fetch()/XHR only to capture the VOB
 *                      response from the page's own request.
 *   ISOLATED world -> chrome.storage.local + popup messaging bridge, then
 *                      derives the 59 procedure records locally from Plan
 *                      Options; it makes no CDT network requests.
 *
 * manifest.json needs TWO content_scripts entries loading this file:
 *   { "matches": ["*://www.guardiananytime.com/*"], "js": ["content_guardian.js"], "run_at": "document_start", "world": "MAIN" },
 *   { "matches": ["*://www.guardiananytime.com/*"], "js": ["content_guardian.js"], "run_at": "document_start", "world": "ISOLATED" }
 *
 * USAGE: open the patient's "Dental Eligibility" page, wait for it to load
 * (VOB captured automatically), then click "Crawl & Download". The 59
 * procedure records are derived locally from the captured Plan Options data,
 * and the popup downloads the finished JSON automatically.
 */

(() => {
    "use strict";

    const PAGE_SOURCE = "guardian-page";
    const STORAGE_KEY = "guardian_data";
    const VOB_PATH = "/gaprovider/api/dental-vob/ppo";


    // Same list content_DD_INS.js searches for Delta Dental, batched the same way.
    const BATCH_1 = ["D0120", "D0180", "D0140", "D0150", "D0274", "D0210", "D0330", "D0220", "D0230", "D0240"];
    const BATCH_2 = ["D1110", "D1120", "D1206", "D1351", "D1510", "D2140", "D2331", "D2620", "D2740", "D2950"];
    const BATCH_3 = ["D3310", "D3330", "D3347", "D4260", "D4341", "D4355", "D4381", "D4910", "D5110", "D7953"];
    const BATCH_4 = ["D5740", "D6010", "D6056", "D6065", "D6194", "D6245", "D7140", "D7240", "D7210", "D6750"];
    const BATCH_5 = ["D7259", "D8010", "D8080", "D8090", "D9110", "D9222", "D9230", "D9243", "D9310", "D4346"];
    const BATCH_6 = ["D9944", "D0364", "D0431", "D2391", "D2962", "D4249", "D5860", "D9430", "D9239"];
    const CODE_BATCHES = [BATCH_1, BATCH_2, BATCH_3, BATCH_4, BATCH_5, BATCH_6];
    const ALL_CODES = CODE_BATCHES.flat();

    // Guardian Plan Options are service-level rows, not one row per CDT code.
    // This mapping tells the derivation layer which Plan Options row governs each
    // of the 59 requested CDT targets. It is a service mapping only; coverage,
    // category overrides, frequency and age restrictions remain message-derived.
    const PROCEDURE_SERVICE_MAP = Object.freeze({
        D0120: "Exams/Oral Evaluations", D0180: "Exams/Oral Evaluations", D0140: "Palliative Emergency Treatment",
        D0150: "Exams/Oral Evaluations", D0274: "X-Rays", D0210: "X-Rays", D0330: "X-Rays",
        D0220: "X-Rays", D0230: "X-Rays", D0240: "X-Rays", D1110: "Cleanings/Prophylaxis",
        D1120: "Cleanings/Prophylaxis", D1206: "Fluoride", D1351: "Sealants", D1510: "Other Preventive",
        D2140: "Fillings", D2331: "Fillings", D2620: "Crown/Inlay/Onlay", D2740: "Crown/Inlay/Onlay",
        D2950: "Crown/Inlay/Onlay", D3310: "Endodontics", D3330: "Endodontics", D3347: "Endodontics",
        D4260: "Periodontics", D4341: "Periodontics", D4355: "Periodontics", D4381: "Other Basic",
        D4910: "Periodontal Maintenance", D5110: "Bridge/Denture", D7953: "Oral Surgery",
        D5740: "Repair/Reline/Rebase", D6010: "Implants", D6056: "Implants", D6065: "Implants",
        D6194: "Implants", D6245: "Bridge/Denture", D7140: "Oral Surgery", D7240: "Oral Surgery",
        D7210: "Oral Surgery", D6750: "Bridge/Denture", D7259: "Oral Surgery", D8010: "Orthodontics",
        D8080: "Orthodontics", D8090: "Orthodontics", D9110: "Palliative Emergency Treatment",
        D9222: "Anesthesia", D9230: "Anesthesia", D9243: "Anesthesia", D9310: "Consultations",
        D4346: "Periodontics", D9944: "Other Basic", D0364: "X-Rays", D0431: "Other Basic",
        D2391: "Fillings", D2962: "Crown/Inlay/Onlay", D4249: "Periodontics", D5860: "Bridge/Denture",
        D9430: "Exams/Oral Evaluations", D9239: "Anesthesia"
    });

    const hasExtensionRuntime = Boolean(
        typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id
    );

    if (hasExtensionRuntime) {
        installIsolatedBridge();
    } else {
        installMainWorldCapture();
    }

    // =====================================================================
    // SHARED: per-code message parsing + record shape
    // =====================================================================

    const DEFAULT_FREQUENCY = "Frequency not available";
    const PROCEDURE_DERIVATION_VERSION = "1.35.11";

    const REQUIRE_EXPLICIT_CODE_MENTION = new Set();

    const KNOWN_CATEGORIES = [
        "Preventive", "Basic", "Periodontics", "Major", "Orthodontics",
        "TMJ", "Endodontics", "Oral Surgery", "Cosmetic"
    ];

    // Guardian frequently mixes several code-specific and service-level rules
    // inside a single Plan Options message. Evidence must therefore be split
    // into clauses/continuations before we decide whether a rule applies to the
    // requested CDT code.
    const CODE_RE = /\bD\d{4}\b/gi;
    const CODE_RANGE_RE = /\b(D\d{4})\s*-\s*(D\d{4})\b/gi;

    const COVERED_RE = /\b(?:is|are)\s+covered\b|\bcovered\b|\blimited\s+to\b|\ballowed\s+as\b|\bbenefit\s+is\s+allowable\b|\breceive\s+the\s+(?:alternate\s+)?benefit\s+of\b/i;
    const NOT_COVERED_RE = /\b(?:not\s+covered|not\s+a\s+covered\s+benefit|no\s+coverage)\b/i;

    // These prefixes usually mean the sentence is a continuation of the
    // previous code-specific statement (e.g. D9944 ... "Covered once per
    // lifetime."). Without this, the frequency would be lost because the
    // second sentence has no CDT code in it.
    const CONTINUATION_PREFIX_RE = /^(?:covered\b|limited\b|subject\b|when\b|if\b|provided\b|requires?\b|frequency\b|age\b|up\s+to\b|under\s+age\b|only\b|considered\b|otherwise\b|and\s+is\b|and\s+are\b)/i;

    // Period unit: tolerates "24 months", the hyphenated "24-month", "3 calendar
    // years" and "5 years" (no "consecutive"/"period" wording required).
    const FREQ_PERIOD = String.raw`\d+[\s-]+(?:consecutive\s+)?(?:calendar\s+)?(?:months|month|years|year)\b(?:\s+period)?`;
    const FREQ_COUNT = String.raw`(?:once|twice|three|four|five|one|two|\d+)`;
    // "in any 24 months" / "in 5 years" / "within a 12 month period" / "every 3 years"
    const FREQ_WINDOW = String.raw`(?:(?:in|within|during|over|every)\s+(?:(?:any|a|the)\s+)?${FREQ_PERIOD}|in\s+a\s+calendar\s+year\b|(?:per|each)\s+calendar\s+year\b)`;
    const FREQUENCY_PATTERNS = [
        new RegExp(String.raw`\b${FREQ_COUNT}\s+times?\s+per\s+[^.;,]+?\s+per\s+lifetime\b`, "i"),
        new RegExp(String.raw`\b${FREQ_COUNT}\s+per\s+[^.;,]+?\s+${FREQ_WINDOW}`, "i"),
        new RegExp(String.raw`\b${FREQ_COUNT}\s+per\s+[^.;,]+?\s+per\s+lifetime\b`, "i"),
        new RegExp(String.raw`\b${FREQ_COUNT}\s+(?:${FREQ_WINDOW}|per\s+lifetime)`, "i"),
        // "1 per 3 years", "one per 24 months", "once per 5 years"
        new RegExp(String.raw`\b${FREQ_COUNT}\s+per\s+${FREQ_PERIOD}`, "i"),
        new RegExp(String.raw`\b${FREQ_COUNT}\s+per\s+lifetime\b`, "i")
    ];

    const AGE_RE = /\b(?:up\s+to\s+age\s+\d+|under\s+(?:the\s+)?age\s+(?:of\s+)?\d+|age\s+\d+\s+(?:and\s+over|and\s+older|or\s+older|and\s+under|through\s+\d+))\b/i;

    function normalizeEvidenceText(value) {
        return String(value || "")
            .replace(/\u00a0/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    function expandCodesInText(text) {
        const normalized = normalizeEvidenceText(text).toUpperCase();
        const codes = new Set((normalized.match(CODE_RE) || []).map(c => c.toUpperCase()));

        CODE_RANGE_RE.lastIndex = 0;
        let range;
        while ((range = CODE_RANGE_RE.exec(normalized)) !== null) {
            const lo = Number(range[1].slice(1));
            const hi = Number(range[2].slice(1));
            if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi < lo || (hi - lo) > 1000) continue;
            for (let n = lo; n <= hi; n++) codes.add(`D${String(n).padStart(4, "0")}`);
        }

        return codes;
    }

    function clauseMentionsCode(text, wanted) {
        const target = String(wanted || "").toUpperCase();
        if (!target) return false;
        // Use the same primary-evidence parser as procedure derivation. This
        // excludes threshold ranges such as "consisting of cdt codes D2140-D7991"
        // while retaining real code listings and explicit code-specific clauses.
        return extractPrimaryCodes(text).has(target);
    }

    function splitEvidenceSentences(text) {
        const normalized = normalizeEvidenceText(text);
        if (!normalized) return [];

        // Guardian uses periods, semicolons and occasional colon-delimited
        // clauses inside long service messages. Keep punctuation attached so
        // the original wording can still be returned when appropriate.
        return normalized
            .split(/(?<=[.;])\s+/)
            .map(s => s.trim())
            .filter(Boolean);
    }

    function extractPrimaryCodes(text) {
        const normalized = normalizeEvidenceText(text).toUpperCase();
        const primary = new Set();

        // Parenthesized CDT lists are the strongest signal for the subject of a
        // Guardian benefit statement. This prevents a reference code in phrases
        // such as "D0180 is not covered ... as an allowed D4355" from being
        // incorrectly treated as another negative rule for D4355.
        const parenthesized = normalized.match(/\(([^)]*\bD\d{4}\b[^)]*)\)/g) || [];
        for (const group of parenthesized) {
            // A broad CDT range can occur inside a parenthesis as a condition
            // (e.g. "consisting of cdt codes D2140-D7991"). It is not a
            // benefit-code listing and must not make an endpoint look like a
            // specific code match.
            if (/\bconsisting\s+of\s+(?:cdt\s+)?codes?\s+D\d{4}\s*-\s*D\d{4}\b/i.test(group)) continue;
            for (const code of expandCodesInText(group)) primary.add(code);
        }

        if (primary.size > 0) return primary;

        // For unparenthesized statements such as "D0364-D0367 are not
        // covered", the first CDT occurrence (including a range) is the
        // subject. Only inspect the prefix before the main predicate.
        const firstVerb = normalized.search(/\b(?:IS|ARE|WAS|WERE)\b/);
        const subjectPrefix = firstVerb >= 0 ? normalized.slice(0, firstVerb) : normalized;
        const subjectCodes = expandCodesInText(subjectPrefix);
        if (subjectCodes.size > 0) return subjectCodes;

        return new Set();
    }

    function buildEvidenceBlocks(messages) {
        const blocks = [];

        for (const rawMessage of messages || []) {
            const sentences = splitEvidenceSentences(rawMessage);
            let inheritedCodes = new Set();

            for (const sentence of sentences) {
                const allCodes = expandCodesInText(sentence);
                let primaryCodes = extractPrimaryCodes(sentence);

                if (primaryCodes.size === 0 && inheritedCodes.size > 0 && CONTINUATION_PREFIX_RE.test(sentence)) {
                    primaryCodes = new Set(inheritedCodes);
                }

                blocks.push({
                    text: sentence,
                    codes: primaryCodes,
                    allCodes,
                    source_message: normalizeEvidenceText(rawMessage)
                });

                if (primaryCodes.size > 0 && allCodes.size > 0) {
                    inheritedCodes = new Set(primaryCodes);
                } else if (allCodes.size === 0 && !CONTINUATION_PREFIX_RE.test(sentence)) {
                    inheritedCodes = new Set();
                }
            }
        }

        return blocks;
    }

    function hasConditionalLanguage(text) {
        const t = normalizeEvidenceText(text);
        return /\b(?:when|if|unless|subject\s+to|provided(?:\s+that)?|only\s+when|only\s+if|on\s+the\s+same\s+day\s+as|same\s+day\s+as)\b/i.test(t);
    }

    function isConditionalNegativeClause(text) {
        const t = normalizeEvidenceText(text);
        return NOT_COVERED_RE.test(t) && hasConditionalLanguage(t);
    }

    // Guardian appends ", subject to all other plan provisions" to many rules. It is
    // boilerplate, not a real condition, so it must not stop a code-free service
    // clause (e.g. the Fillings 24-month rule) from applying to the row's codes.
    function stripPlanBoilerplate(text) {
        return normalizeEvidenceText(text)
            .replace(/,?\s*subject\s+to\s+all\s+other\s+(?:plan\s+)?(?:provisions|limitations)(?:\s+and\s+(?:plan\s+)?(?:provisions|limitations))?/gi, "")
            .trim();
    }

    function isUniversalServiceClause(text) {
        const t = stripPlanBoilerplate(text);
        if (!t || expandCodesInText(t).size > 0) return false;
        if (!COVERED_RE.test(t) && !NOT_COVERED_RE.test(t)) return false;

        // Code-free conditional prose is not blanket code coverage. Examples
        // include "the prosthesis ... will be considered if ..." and
        // "replacement ... is covered when ...". Those clauses require a
        // separate code/service mapping instead of being inherited by every CDT
        // code in the row.
        if (hasConditionalLanguage(t)) return false;
        if (/^(?:replacement|limited|considered|subject|provided|after|following|unless)\b/i.test(t)) {
            return false;
        }

        return true;
    }

    function blockAppliesToCode(block, code) {
        const target = String(code || "").toUpperCase();
        if (block.codes.has(target)) return true;
        if (REQUIRE_EXPLICIT_CODE_MENTION.has(target)) return false;
        return block.codes.size === 0 && isUniversalServiceClause(block.text);
    }

    function isLiteralCodeMention(text, code) {
        const target = String(code || "").toUpperCase();
        const t = normalizeEvidenceText(text).toUpperCase();
        return new RegExp(`(?<![\\w-])${target}(?![\\w])(?!\\s*-\\s*D\\d{4})(?<!D\\d{4}\\s*-\\s*${target})`).test(t);
    }

    function isListedBenefitClause(text) {
        const t = normalizeEvidenceText(text);
        return /^(?:single\s+crowns?|space\s+maintainers?|prefabricated\s+crowns?|maintenance\s+and\s+repair\b|endodontic\s+therapy|periodontal\s+scaling|full\s+mouth\s+debridement|occlusal\s+guard|implant\s+procedures?)\b/i.test(t);
    }

    function isCodeListingClause(text) {
        return /^includes\s+codes?\s*:/i.test(normalizeEvidenceText(text));
    }

    const ANESTHESIA_CODES = new Set([
        "D9222", "D9223", "D9224", "D9225", "D9230", "D9239",
        "D9243", "D9244", "D9245", "D9246", "D9247"
    ]);
    const IMPLANT_SURGICAL_CODES = new Set(["D6010", "D6013", "D6040", "D6050"]);
    const PROSTHESIS_SERVICES = new Set(["bridge/denture", "implants"]);
    const DEDICATED_SERVICE_OVERRIDES = Object.freeze({ D9944: "Other Basic" });

    // Conditions Guardian attaches to a code that a plain covered/not-covered
    // flag cannot express. Every rule is gated on the wording actually being
    // present in the plan messages, so nothing is emitted for plans that do
    // not carry the clause. `messages` may span every Plan Options row; `service`
    // is the governing row's service name (used for row-wide clauses).
    function extractConditionalExclusions(messages, code, service = null) {
        const target = String(code || "").toUpperCase();
        const msgs = Array.isArray(messages) ? messages : [];
        const fullText = normalizeEvidenceText(msgs.join(" "));
        const blocks = buildEvidenceBlocks(msgs);
        const svc = normalizeEvidenceText(service).toLowerCase();
        const out = [];
        const add = (text) => { if (text && !out.includes(text)) out.push(text); };

        // D0180 vs D4355 same-day rule.
        if (target === "D0180" && (
            /Comprehensive\s+periodontal\s+eval\s+\(D0180\)\s+is\s+not\s+covered\s+on\s+the\s+same\s+day\s+as\s+an\s+allowed\s+D4355/i.test(fullText) ||
            /\bD0180\b[^.]*\bnot\s+covered\b[^.]*\bsame\s+day\b[^.]*\bD4355\b/i.test(fullText))) {
            add("not covered on the same day as an allowed D4355");
        }

        // Periapical / occlusal x-rays: capped at the full-mouth-series allowance.
        if (target === "D0220" || target === "D0230" || target === "D0240") {
            if (/periapical[^.]*\bcovered\s+up\s+to\s+a\s+maximum\s+allowable\s+amount\s+of\s+a\s+full\s+mouth\s+series/i.test(fullText)) {
                add("benefit limited to the maximum allowable amount of a full mouth series of x-rays (D0210)");
            }
            if (/Fourteen\s+or\s+more\s+individual\s+x-rays[^.]*same\s+date\s+will\s+receive\s+the\s+benefit\s+of\s+a\s+full\s+mouth\s+series/i.test(fullText)) {
                add("14 or more individual x-rays (including bitewings) on the same date receive the benefit of a full mouth series (D0210)");
            }
        }

        // Posterior composites downgraded to the amalgam benefit.
        for (const block of blocks) {
            const m = block.text.match(/^(.*?)\breceives?\s+the\s+alternate\s+benefit\s+of\s+(.+?)\.?$/i);
            if (m && expandCodesInText(m[1]).has(target)) {
                add(`receives the alternate benefit of ${normalizeEvidenceText(m[2])}`);
            }
        }

        // Crowns / inlays / onlays / veneers / buildups.
        if (svc === "crown/inlay/onlay") {
            if (/CLINICAL\s+REVIEW\s+REQUIRED\s+FOR\s+CROWNS/i.test(fullText)) {
                add("clinical review required (submit diagnostic pre-operative x-ray, patient chart notes and any relevant intraoral photographs)");
            }
            if (target === "D2950") {
                if (/Core\s+buildup\s+\(D2950\)\s+is\s+considered\s+in\s+conjunction\s+with\s+a\s+covered\s+unit\s+of\s+a\s+crown\s+or\s+bridge\s+and\s+only\s+when\s+necessitated\s+by\s+substantial\s+loss/i.test(fullText)) {
                    add("core buildup considered only in conjunction with a covered crown or bridge and only when necessitated by substantial loss of natural tooth structure");
                }
            } else {
                const replacementMatch = fullText.match(/(?:^|[.!?]\s*)Replacement\s+of\s+an\s+inlay,\s+onlay,\s+crown\s+or\s+veneer\s+is\s+covered\s+when\s+it\s+is\s+at\s+least\s+(\d+)\s+years\s+old\s+and\s+is\s+no\s+longer\s+useable(?:[.!?]|$)/i);
                if (replacementMatch) {
                    add(`replacement covered only when the existing restoration is at least ${replacementMatch[1]} years old and no longer useable`);
                }
            }
        }

        // Bridges / dentures.
        if (svc === "bridge/denture") {
            const replacementMatch = fullText.match(/(?:^|[.!?]\s*)Replacement\s+of\s+a\s+denture\s+or\s+bridge\s+is\s+covered\s+when\s+it\s+is\s+at\s+least\s+(\d+)\s+years\s+old\s+and\s+is\s+no\s+longer\s+useable(?:[.!?]|$)/i);
            if (replacementMatch) {
                add(`replacement covered only when the existing denture or bridge is at least ${replacementMatch[1]} years old and no longer useable`);
            }
        }

        // Shared prophy/perio-maintenance visit limit.
        if (target === "D1110" || target === "D1120" || target === "D4910") {
            if (msgs.some((message) => /Prophylaxis\s+\(cleaning\)\s+\(D1110,\s*D1120\)\s+or\s+periodontal\s+maintenance\s+\(D4910\)\s+is\s+covered\s+once\s+in\s+any\s+6\s+consecutive\s+month\s+period/i.test(normalizeEvidenceText(message)))) {
                add("prophylaxis (D1110, D1120) and periodontal maintenance (D4910) share one limit of once in any 6 consecutive month period");
            }
            if (msgs.some((message) => /a\s+combined\s+maximum\s+is\s+applied\s+to\s+periodontal\s+maintenance\s+and\s+prophylaxis\s+for\s+a\s+total\s+of\s+4\s+in\s+12\s+months/i.test(normalizeEvidenceText(message)))) {
                add("combined maximum of 4 in 12 months applies to periodontal maintenance and prophylaxis");
            }
        }

        // Denture reline timing condition.
        if (target === "D5740") {
            for (const message of msgs) {
                const match = normalizeEvidenceText(message).match(/Denture\s+reline\s*\(([^)]*)\)\s+is\s+limited\s+to\s+relines\s+done\s+more\s+than\s+12\s+months\s+after\s+a\s+denture\s+rebase\s+or\s+the\s+insertion\s+of\s+the\s+original\s+denture(?:[.!?]|$)/i);
                if (!match) continue;
                const listedCodes = match[1].match(/D\d{4}/gi) || [];
                if (listedCodes.some((listedCode) => listedCode.toUpperCase() === target)) {
                    add("reline allowed only more than 12 months after a denture rebase or the insertion of the original denture");
                    break;
                }
            }
        }

        // Generic timing condition stated for this code, e.g. "Denture reline
        // (D5730-D5761) is covered when performed more than 6 months after the initial
        // insertion of the denture". Skipped when the plan-specific rule above already
        // captured a "more than N months" condition for this code.
        if (!out.some((t) => /more than/i.test(t))) {
            for (const block of blocks) {
                if (!block.codes.has(target)) continue;
                const timing = stripPlanBoilerplate(block.text).match(
                    /\b(?:covered|limited\s+to|allowed)\b[^.;]*?\bmore\s+than\s+(\d+)\s+(months?|years?)\s+after\s+(.+?)[.;]?$/i
                );
                if (timing) {
                    add(`covered only when performed more than ${timing[1]} ${timing[2]} after ${normalizeEvidenceText(timing[3])}`);
                    break;
                }
            }
        }

        // Missing-tooth clause (prostheses and implant-supported prostheses).
        if ((PROSTHESIS_SERVICES.has(svc) && !IMPLANT_SURGICAL_CODES.has(target)) &&
            /Dental\s+prostheses\s+needed\s+to\s+replace\s+teeth\s+missing\s+prior\s+to\s+being\s+insured[^.]*\bare\s+not\s+covered\s+unless\s+the\s+tooth\s+was\s+extracted\s+while\s+covered\s+by\s+the\s+prior\s+plan/i.test(fullText)) {
            add("prosthesis replacing a tooth missing before coverage under this plan is not covered unless the tooth was extracted while covered by the prior plan");
        }

        // Implants.
        if (svc === "implants") {
            if (/covered\s+without\s+review,?\s+when\s+there\s+is\s+a\s+liability/i.test(fullText)) {
                add("covered without review only when there is a liability");
            }
            if (!IMPLANT_SURGICAL_CODES.has(target) &&
                /The\s+dental\s+prosthesis\s+placed\s+on\s+the\s+implant\s+will\s+be\s+considered\s+if\s+the\s+tooth\s+was\s+extracted\s+while\s+insured\s+with\s+this\s+Guardian\s+plan\s+or\s+when\s+covered\s+by\s+the\s+prior\s+plan/i.test(fullText)) {
                add("prosthesis placed on the implant is considered only if the tooth was extracted while insured with this Guardian plan or while covered by the prior plan");
            }
        }

        // Anesthesia.
        if (ANESTHESIA_CODES.has(target)) {
            for (const block of blocks) {
                if (!block.codes.has(target)) continue;
                const general = block.text.match(/\bis\s+covered\s+when\s+performed\s+with\s+(.+?)\.?$/i);
                if (general) add(`covered only when performed with ${normalizeEvidenceText(general[1])}`);
                const child = block.text.match(/\bis\s+covered\s+on\s+children\s+under\s+age\s+(\d+)\s+when\s+performed\s+with\s+(.+?)\.?$/i);
                if (child) {
                    const cleaned = normalizeEvidenceText(child[2].replace(/\s*\(consisting[^)]*\)/i, ""));
                    add(`also covered on children under age ${child[1]} when performed with ${cleaned}`);
                }
            }
        }

        // Full mouth debridement.
        if (target === "D4355") {
            for (const block of blocks) {
                if (!block.codes.has("D4355")) continue;
                const m = block.text.match(/\bis\s+considered\s+once\s+in\s+any\s+36\s+consecutive\s+month\s+period,\s+when\s+(no\s+preventive.+?)\.?$/i);
                if (m) add(`considered only when ${normalizeEvidenceText(m[1])}`);
            }
            if (/Full\s+mouth\s+debridement\s+\(D4355\)\s+and\s+prophy\/perio\s+maintenance\s+rendered\s+on\s+the\s+same\s+day\s+are\s+considered\s+inclusive\s+and\s+allowed\s+as\s+D4355/i.test(fullText)) {
                add("when rendered on the same day as prophy/perio maintenance, considered inclusive and allowed as D4355 when the benefit is allowable");
            }
        }

        // Occlusal guard.
        if ((target === "D9944" || target === "D9945") &&
            /Occlusal\s+guard\s+\(night\s+guard\)\s+\(D9944,\s*D9945\)\s+is\s+covered\s+when\s+done\s+within\s+6\s+months\s+after\s+osseous\s+surgery/i.test(fullText)) {
            add("covered only when done within 6 months after osseous surgery");
        }

        return out.length ? out : null;
    }

    function extractFrequencyFromText(text) {
        // "once, per denture, in any 24-month period" -> "once per denture in any 24-month period"
        const normalized = normalizeEvidenceText(text)
            .replace(/,\s+per\s+/gi, " per ")
            .replace(/,\s+(?=in\s+(?:any|a)\s+\d)/gi, " ");
        for (const pattern of FREQUENCY_PATTERNS) {
            const match = normalized.match(pattern);
            if (match) return match[0].trim();
        }
        return null;
    }

    const FILLING_CODES = new Set([
        "D2140", "D2145", "D2150", "D2160", "D2161",
        "D2330", "D2331", "D2332", "D2335",
        "D2391", "D2392", "D2393", "D2394"
    ]);

    // Two-branch filling rule, e.g. "once per tooth surface in any 12 months for
    // covered persons up to age 19 and once per tooth surface in any 36 months for
    // all other covered persons". Ages and periods are read from the text; a plan
    // without this wording returns null and gets no age branch.
    function extractFillingFrequency(text) {
        const normalized = normalizeEvidenceText(text).replace(/,\s+per\s+/gi, " per ");
        const child = normalized.match(/(once\s+per\s+tooth\s+surface\s+in\s+any\s+\d+\s+months?)\s+for\s+covered\s+persons\s+up\s+to\s+age\s+(\d+)/i);
        const adult = normalized.match(/(once\s+per\s+tooth\s+surface\s+in\s+any\s+\d+\s+months?)\s+for\s+all\s+other\s+covered\s+persons/i);
        if (!child && !adult) return null;
        return {
            child: child ? extractFrequencyFromText(child[1]) : null,
            adult: adult ? extractFrequencyFromText(adult[1]) : null,
            childAge: child ? Number(child[2]) : null
        };
    }

    // Frequency stated for this exact code in ANY Plan Options row (e.g. D9944's
    // "Covered once per lifetime" lives in "Other Basic" even when the code is
    // governed by the Periodontics row). Only clauses that name the code count;
    // code-free service-level clauses are never borrowed across rows.
    function extractCodeSpecificFrequency(messages, code) {
        const target = String(code || "").toUpperCase();
        for (const block of buildEvidenceBlocks(messages)) {
            if (!block.codes.has(target)) continue;
            const frequency = extractFrequencyFromText(block.text);
            if (frequency) return frequency;
        }
        return null;
    }

    function extractFrequency(messages, code, patientAge = null) {
        const target = String(code || "").toUpperCase();
        const blocks = buildEvidenceBlocks(messages);

        if (FILLING_CODES.has(target)) {
            for (const block of blocks) {
                if (!blockAppliesToCode(block, target)) continue;
                const branches = extractFillingFrequency(block.text);
                if (!branches) continue;
                const childMax = Number.isFinite(branches.childAge) ? branches.childAge : 19;
                if (Number.isFinite(patientAge) && patientAge > childMax && branches.adult) return branches.adult;
                if (Number.isFinite(patientAge) && patientAge <= childMax && branches.child) return branches.child;
                // Without patient age, preserve the historical first branch so
                // the raw message remains authoritative and no age is guessed.
                if (branches.child) return branches.child;
            }
        }

        for (const block of blocks) {
            if (!blockAppliesToCode(block, target)) continue;
            const frequency = extractFrequencyFromText(block.text);
            if (frequency) return frequency;
        }
        return DEFAULT_FREQUENCY;
    }

    function extractAgeLimit(messages, code, patientAge = null) {
        const target = String(code || "").toUpperCase();
        const blocks = buildEvidenceBlocks(messages);
        if (FILLING_CODES.has(target) && Number.isFinite(patientAge)) {
            // The source filling sentence may contain two age branches. Only expose
            // the branch that applies to this patient, and only when the plan text
            // really has that branch (never invent an age limit the plan lacks).
            const branchBlock = blocks
                .filter(block => blockAppliesToCode(block, target))
                .map(block => extractFillingFrequency(block.text))
                .find(Boolean);
            if (branchBlock) {
                const childMax = Number.isFinite(branchBlock.childAge) ? branchBlock.childAge : 19;
                return patientAge > childMax ? null : `up to age ${childMax}`;
            }
        }

        const applicable = blocks.filter(block => blockAppliesToCode(block, target));
        const ageBlocks = applicable.filter(block => AGE_RE.test(normalizeEvidenceText(block.text)));
        if (!ageBlocks.length) return null;

        // A secondary age-specific clause must not become the code's overall age
        // limit when the same code also has a broader coverage clause. Guardian's
        // anesthesia wording is a canonical example: the first clause covers the
        // codes when paired with qualifying services; the under-age-8 clause adds
        // another qualifying path.
        const hasAgeFreePositive = applicable.some(block =>
            !AGE_RE.test(normalizeEvidenceText(block.text)) &&
            !isConditionalNegativeClause(block.text) &&
            (COVERED_RE.test(block.text) || isListedBenefitClause(block.text))
        );
        const hasSecondaryChildQualification = ageBlocks.some(block =>
            /\bchildren?\s+under\s+age\b/i.test(normalizeEvidenceText(block.text)) &&
            /\bwhen\s+performed\b/i.test(normalizeEvidenceText(block.text))
        );
        if (hasAgeFreePositive && hasSecondaryChildQualification) {
            return null;
        }

        return normalizeEvidenceText(ageBlocks[0].text).match(AGE_RE)[0].trim();
    }

    function evaluateAgeEligibility(ageLimit, code, patientAge) {
        if (!ageLimit || !Number.isFinite(patientAge)) return null;
        if (FILLING_CODES.has(String(code || "").toUpperCase())) return null;
        const t = normalizeEvidenceText(ageLimit).toLowerCase();
        let m;
        if ((m = t.match(/^under\s+(?:the\s+)?age\s+(?:of\s+)?(\d+)$/))) return patientAge < Number(m[1]);
        if ((m = t.match(/^age\s+(\d+)\s+(?:and\s+over|and\s+older|or\s+older)$/))) return patientAge >= Number(m[1]);
        if ((m = t.match(/^age\s+(\d+)\s+and\s+under$/))) return patientAge <= Number(m[1]);
        if ((m = t.match(/^up\s+to\s+age\s+(\d+)$/))) {
            const limit = Number(m[1]);
            if (patientAge < limit) return true;
            if (patientAge > limit) return false;
            return null;
        }
        return null;
    }

    const ROW_NAME_CATEGORY = {
        "other preventive": "Preventive",
        "other basic": "Basic",
        "other major": "Major"
    };

    function inferCategoryFromRowName(service) {
        return ROW_NAME_CATEGORY[normalizeEvidenceText(service).toLowerCase()] ?? null;
    }

    function extractCategoryOverride(messages, code, baseCategory) {
        const target = String(code || "").toUpperCase();
        for (const block of buildEvidenceBlocks(messages)) {
            if (!blockAppliesToCode(block, target)) continue;
            const match = normalizeEvidenceText(block.text).match(
                /\b(?:covered\s+under|under)\s+(?:the\s+)?(Preventive|Basic|Periodontics|Major|Orthodontics|TMJ|Endodontics|Oral\s+Surgery|Cosmetic)\s+(?:service\s+)?category\b/i
            );
            if (match) {
                const category = KNOWN_CATEGORIES.find(c => c.toLowerCase() === match[1].toLowerCase());
                return category || match[1];
            }
        }

        return baseCategory ?? null;
    }

    function basisPriority(basis) {
        if (basis === "code-specific") return 3;
        if (basis === "code-range") return 2;
        if (basis === "service-level") return 1;
        return 0;
    }

    function deriveCoverage(messages, code) {
        const target = String(code || "").toUpperCase();
        let positive = false;
        let negative = false;
        let positiveBasis = null;
        let negativeBasis = null;
        let negativeEvidence = null;

        for (const block of buildEvidenceBlocks(messages)) {
            if (!blockAppliesToCode(block, target)) continue;

            const isNegative = NOT_COVERED_RE.test(block.text) && !isConditionalNegativeClause(block.text);
            const isPositive = !isNegative && (COVERED_RE.test(block.text) || isListedBenefitClause(block.text) || isCodeListingClause(block.text));

            if (isNegative) {
                negative = true;
                const newBasis = block.codes.has(target)
                    ? (isLiteralCodeMention(block.text, target) ? "code-specific" : "code-range")
                    : "service-level";
                if (basisPriority(newBasis) > basisPriority(negativeBasis)) {
                    negativeBasis = newBasis;
                    negativeEvidence = block.text;
                }
            } else if (isPositive) {
                positive = true;
                const newBasis = block.codes.has(target)
                    ? (isLiteralCodeMention(block.text, target) ? "code-specific" : "code-range")
                    : "service-level";
                if (basisPriority(newBasis) > basisPriority(positiveBasis)) positiveBasis = newBasis;
            }
        }

        // An explicit negative statement for the requested code/range wins over
        // a generic service-level positive statement. This preserves Guardian's
        // conditional exclusions such as D0180 while preventing D0431/D4381
        // from contaminating D9944.
        if (negative) {
            return {
                covered: false,
                coverage_status: "Not Covered",
                coverage_basis: negativeBasis,
                negative_evidence: negativeEvidence
            };
        }
        if (positive) {
            return {
                covered: true,
                coverage_status: "Covered",
                coverage_basis: positiveBasis
            };
        }
        return {
            covered: null,
            coverage_status: "Not Determined",
            coverage_basis: null
        };
    }

    function extractCodeSpecificLastVisit(rawValue, code) {
        const raw = normalizeEvidenceText(rawValue);
        if (!raw) return null;
        if (!/[;:]/.test(raw)) return raw;

        const target = String(code || "").toUpperCase();
        const normalized = raw.replace(/\s+/g, " ");

        const labeledRules = [
            { codes: ["D0270", "D0271", "D0272", "D0273", "D0274", "D0275", "D0276", "D0277"], re: /(?:^|;)\s*Bitewings\s*:\s*([^;]+)/i },
            { codes: ["D0210", "D0330"], re: /(?:^|;)\s*FullMouth\/panoramic\s*:\s*([^;]+)/i },
            {
                codes: ["D4341", "D4342"],
                re: /(?:^|;)\s*Perio\s+scaling\s+&\s+root\s+planing\s*:\s*(UR-[^;]+)\s*;\s*(UL-[^;]+)\s*;\s*(LL-[^;]+)\s*;\s*(LR-[^;]+)(?:;|$)/i,
                transform: (match) => {
                    const entries = match.slice(1, 5).map(normalizeEvidenceText);
                    const values = entries.map((entry) => entry.replace(/^[A-Z]{2}-/i, ""));
                    return values.every((value) => /^date\s+not\s+found$/i.test(value))
                        ? "Date Not Found"
                        : entries.join(";");
                }
            }
        ];

        for (const rule of labeledRules) {
            if (rule.codes.includes(target)) {
                const match = normalized.match(rule.re);
                if (!match) return null;
                return rule.transform ? rule.transform(match) : normalizeEvidenceText(match[1]);
            }
        }

        // The target is not represented by any labeled component of a composite
        // last-visit field, so do not leak another code's history into it.
        return null;
    }

    function buildMissingProcedureRecord(code, reason = "Procedure lookup did not return data") {
        return {
            code,
            covered: null,
            coverage_status: reason === "Pending lookup"
                ? "Pending"
                : (reason === "Procedure lookup did not return data" ? "Not Determined" : "Lookup Failed"),
            coverage_basis: null,
            dental_service_category: null,
            dental_service: null,
            frequency: DEFAULT_FREQUENCY,
            age_limit: null,
            age_eligible: null,
            not_covered_reason: null,
            conditional_exclusions: null,
            deductible_waived: null,
            deductible_waived_evidence: null,
            coinsurance: [],
            last_visit_date: null,
            ehb_plan_indicator: null,
            message: [],
            lookup_status: reason
        };
    }

    function buildProcedureRecord(code, json, patientAge = null) {
        if (!json || !json.dental_service) {
            const messages = json?.message || [];
            const derived = deriveCoverage(messages, code);
            if (derived.covered === false) {
                const { negative_evidence: negEvidence, ...derivedFields } = derived;
                return {
                    ...buildMissingProcedureRecord(code),
                    ...derivedFields,
                    not_covered_reason: negEvidence ? `Not covered per Guardian plan message: ${negEvidence}` : null,
                    message: messages
                };
            }
            return buildMissingProcedureRecord(code);
        }

        const messages = Array.isArray(json.message) ? json.message : [];
        const { negative_evidence: _legacyNegEvidence, ...derived } = deriveCoverage(messages, code);
        const category = extractCategoryOverride(
            messages,
            code,
            json.dental_service_category ?? null
        ) ?? inferCategoryFromRowName(json.dental_service);
        const ageLimit = extractAgeLimit(messages, code, patientAge);
        const ageEligible = derived.covered === true ? evaluateAgeEligibility(ageLimit, code, patientAge) : null;

        return {
            code,
            covered: ageEligible === false ? false : derived.covered,
            coverage_status: ageEligible === false ? "Not Covered" : derived.coverage_status,
            coverage_basis: derived.coverage_basis,
            dental_service_category: category,
            dental_service: json.dental_service ?? null,
            frequency: derived.covered === false ? DEFAULT_FREQUENCY : extractFrequency(messages, code, patientAge),
            age_limit: ageLimit,
            age_eligible: ageEligible,
            not_covered_reason: ageEligible === false ? `Patient age ${patientAge} is outside the plan age limit (${ageLimit})` : null,
            conditional_exclusions: extractConditionalExclusions(messages, code, json.dental_service ?? null),
            deductible_waived: extractDeductibleWaiver(messages, code).waived,
            deductible_waived_evidence: extractDeductibleWaiver(messages, code).evidence,
            coinsurance: (json.coinsurance || []).map((c) => ({
                network: c.network_name ?? c.network ?? null,
                amount: c.coinsurance_amount ?? c.amount ?? null
            })),
            last_visit_date: extractCodeSpecificLastVisit(json.last_visit_date, code) ?? (
                /[;:]/.test(normalizeEvidenceText(json.last_visit_date)) ? null : (json.last_visit_date ?? null)
            ),
            ehb_plan_indicator: json.ehb_plan_indicator ?? null,
            message: messages
        };
    }

    function isCompletedProcedureRecord(record) {
        return Boolean(
            record &&
            record.lookup_status !== "Pending lookup" &&
            record.lookup_status !== "Lookup Failed" &&
            !record.error &&
            !record.blocked
        );
    }

    function needsProcedureLookup(record) {
        return !record || record.lookup_status === "Pending lookup" || record.error || record.blocked;
    }

    const CATEGORY_STATEMENT_RE = /\b(?:covered\s+under|under)\s+(?:the\s+)?(?:Preventive|Basic|Periodontics|Major|Orthodontics|TMJ|Endodontics|Oral\s+Surgery|Cosmetic)\s+(?:service\s+)?category\b/i;

    function inferOtherRowCoinsurance(row, category, allRows) {
        // "Other Basic/Major/Preventive" rows carry no coinsurance of their own;
        // they inherit the percentage of the category they belong to.
        if (!category || !Array.isArray(allRows)) return [];
        if (inferCategoryFromRowName(row?.service) !== category) return [];
        const sibling = allRows.find((r) => r !== row && r?.category === category &&
            Array.isArray(r.coinsurance) && r.coinsurance.length > 0);
        return sibling ? sibling.coinsurance.map((c) => ({ network: c?.network ?? null, amount: c?.amount ?? null })) : [];
    }

    // When a plan message moves a code into a different category than its service
    // row (e.g. X-Ray row is Preventive/100% but D0220/D0230 are "covered under the
    // Basic service category"), the payable percentage must come from that category's
    // own row, not from the row the code was found in.
    function coinsuranceForCategory(allRows, category) {
        if (!category || !Array.isArray(allRows)) return null;
        const wanted = normalizeEvidenceText(category).toLowerCase();
        const sibling = allRows.find((r) =>
            normalizeEvidenceText(r?.category).toLowerCase() === wanted &&
            Array.isArray(r.coinsurance) && r.coinsurance.length > 0 &&
            r.coinsurance.some((c) => c && c.amount !== null && c.amount !== undefined && String(c.amount).trim() !== ""));
        return sibling ? sibling.coinsurance.map((c) => ({ network: c?.network ?? null, amount: c?.amount ?? null })) : null;
    }

    // Code-specific deductible waiver, e.g. "PERIAPICAL RADIOGRAPHIC IMAGES (D0220,
    // D0230) ARE COVERED UNDER THE BASIC SERVICE CATEGORY WITH THE DEDUCTIBLE WAVIED"
    // (Guardian's own typo included). Only clauses that name the code count. Returns
    // null when the plan says nothing, so consumers fall back to the category default.
    const DEDUCTIBLE_WAIVED_RE = /\bdeductible\s+(?:is\s+|being\s+)?(?:waived|wavied|waiver)\b|\b(?:waived|wavied)\s+deductible\b|\bdeductible\s+(?:does|do)\s+not\s+apply\b|\bnot\s+subject\s+to\s+(?:the\s+)?deductible\b|\bno\s+deductible\b/i;
    function extractDeductibleWaiver(messages, code) {
        const target = String(code || "").toUpperCase();
        for (const block of buildEvidenceBlocks(messages)) {
            if (!block.codes.has(target)) continue;
            if (DEDUCTIBLE_WAIVED_RE.test(block.text)) return { waived: true, evidence: block.text };
        }
        return { waived: null, evidence: null };
    }

    function rowCodeEvidenceScore(row, code) {
        const target = String(code || "").toUpperCase();
        const messages = Array.isArray(row?.message) ? row.message : [];
        let explicitCategory = false;
        let positive = false;
        let negative = false;
        let directMention = false;
        // A row that states its own category (e.g. "...covered under the Major
        // service category") and then lists codes ("Includes codes: ...") has
        // explicitly homed those codes in that row.
        const rowStatesCategory = messages.some((m) => CATEGORY_STATEMENT_RE.test(normalizeEvidenceText(m)));

        for (const message of messages) {
            for (const block of buildEvidenceBlocks([message])) {
                if (!block.codes.has(target)) continue;
                directMention = true;
                if (rowStatesCategory && isCodeListingClause(block.text)) {
                    explicitCategory = true;
                    positive = true;
                }
                if (/\b(?:covered\s+under|under)\s+(?:the\s+)?(?:Preventive|Basic|Periodontics|Major|Orthodontics|TMJ|Endodontics|Oral\s+Surgery|Cosmetic)\s+(?:service\s+)?category\b/i.test(block.text)) {
                    explicitCategory = true;
                }
                if (NOT_COVERED_RE.test(block.text) && !isConditionalNegativeClause(block.text)) negative = true;
                else if (NOT_COVERED_RE.test(block.text) && isConditionalNegativeClause(block.text)) {
                    // A conditional exclusion is not a governing-row mapping signal
                    // by itself (e.g. D0180 excluded only when paired with D4355).
                    directMention = false;
                } else if (COVERED_RE.test(block.text) || isListedBenefitClause(block.text)) positive = true;
            }
        }

        // Highest score wins. We deliberately prefer an explicit category home
        // over an incidental co-mention in another row, then a positive listing,
        // then an explicit negative statement, before falling back to the static
        // service map.
        if (explicitCategory && positive) return 400;
        if (explicitCategory && negative) return 380;
        if (explicitCategory) return 360;
        if (positive) return 300;
        if (negative) return 200;
        return directMention ? 100 : 0;
    }

    function resolveGoverningRow(rows, code) {
        const target = String(code || "").toUpperCase();
        const dedicatedService = DEDICATED_SERVICE_OVERRIDES[target];
        if (dedicatedService) {
            const dedicatedRow = (rows || []).find((row) =>
                normalizeEvidenceText(row?.service).toLowerCase() === dedicatedService.toLowerCase() &&
                Array.isArray(row?.message) &&
                row.message.some((message) => isLiteralCodeMention(message, target))
            );
            if (dedicatedRow) return dedicatedRow;
        }

        const candidates = (rows || [])
            .map((row, index) => ({ row, index, score: rowCodeEvidenceScore(row, code) }))
            .filter((item) => item.score > 0);

        if (candidates.length) {
            candidates.sort((a, b) => b.score - a.score || a.index - b.index);
            return candidates[0].row;
        }

        const fallbackService = PROCEDURE_SERVICE_MAP[target] || null;
        if (!fallbackService) return null;
        return (rows || []).find((row) => row?.service === fallbackService) || null;
    }


    function buildProcedureRecordFromPlanOption(code, row, patientAge = null, allRows = null, orthoAgeLimit = null) {
        const messages = Array.isArray(row?.message) ? row.message : [];
        const exclusionMessages = Array.isArray(allRows)
            ? allRows.flatMap((r) => (Array.isArray(r?.message) ? r.message : []))
            : messages;
        const derived = deriveCoverage(messages, code);
        const target = String(code || "").toUpperCase();
        const rowCategory = inferCategoryFromRowName(row?.service);
        const category = target === "D9944" && rowCategory === "Basic"
            ? "Basic"
            : (extractCategoryOverride(messages, code, row?.category ?? null) ?? rowCategory);
        const rawLastVisit = normalizeEvidenceText(row?.last_visit_date);
        const hasNetworkBenefits = Array.isArray(row?.coinsurance) && row.coinsurance.some(c =>
            c && (c.amount !== null && c.amount !== undefined && String(c.amount).trim() !== "")
        );
        const hasServiceLevelBenefitRow = Boolean(row?.service && row?.category && hasNetworkBenefits);
        const { negative_evidence: negativeEvidence, ...derivedCoverage } = derived;
        const effectiveCoverage = derivedCoverage.covered === null && hasServiceLevelBenefitRow
            && !REQUIRE_EXPLICIT_CODE_MENTION.has(String(code || "").toUpperCase())
            ? { covered: true, coverage_status: "Covered", coverage_basis: "service-level" }
            : derivedCoverage;
        let ageLimit = extractAgeLimit(messages, code, patientAge);
        const orthoLimit = (typeof orthoAgeLimit === "number" && Number.isInteger(orthoAgeLimit))
            ? orthoAgeLimit
            : (/^\s*\d+\s*$/.test(String(orthoAgeLimit ?? "")) ? Number(orthoAgeLimit) : NaN);
        if (normalizeEvidenceText(row?.service).toLowerCase() === "orthodontics" &&
            (target === "D8010" || target === "D8080" || target === "D8090") &&
            Number.isInteger(orthoLimit) && orthoLimit < 99) {
            ageLimit = `up to age ${orthoLimit}`;
        }
        // Plan text does not say whether the orthodontic age limit N is inclusive,
        // so evaluateAgeEligibility intentionally leaves an exact-age match unknown.
        const ageEligible = effectiveCoverage.covered === true ? evaluateAgeEligibility(ageLimit, code, patientAge) : null;

        const finalCovered = ageEligible === false ? false : effectiveCoverage.covered;
        const isNotCovered = finalCovered === false;
        const isUndetermined = finalCovered === null;

        // Every not-covered record explains itself: age limit, or the plan's own sentence.
        let notCoveredReason = null;
        if (ageEligible === false) {
            notCoveredReason = `Patient age ${patientAge} is outside the plan age limit (${ageLimit})`;
        } else if (isNotCovered) {
            notCoveredReason = negativeEvidence
                ? `Not covered per Guardian plan message: ${negativeEvidence}`
                : "Not covered per Guardian plan message";
        }

        let frequency = effectiveCoverage.covered === false ? DEFAULT_FREQUENCY : extractFrequency(messages, code, patientAge);
        if (frequency === DEFAULT_FREQUENCY && effectiveCoverage.covered !== false) {
            frequency = extractCodeSpecificFrequency(exclusionMessages, code) ?? frequency;
        }

        // A code that is not covered (or could not be determined) has no
        // payable percentage, and an undetermined code must not present the
        // row's category / last visit as if the row governed it.
        let coinsurance = Array.isArray(row?.coinsurance) ? row.coinsurance.map((c) => ({
            network: c?.network ?? null,
            amount: c?.amount ?? null
        })) : [];
        if (!coinsurance.length && !isNotCovered && !isUndetermined) {
            coinsurance = inferOtherRowCoinsurance(row, category, allRows);
        }
        if (isNotCovered || isUndetermined) coinsurance = [];

        // Category moved by the message -> take the percentage from that category.
        if (!isNotCovered && !isUndetermined && row?.category && category &&
            normalizeEvidenceText(category).toLowerCase() !== normalizeEvidenceText(row.category).toLowerCase()) {
            const categoryCoinsurance = coinsuranceForCategory(allRows, category);
            if (categoryCoinsurance) coinsurance = categoryCoinsurance;
        }

        const deductible = (isNotCovered || isUndetermined)
            ? { waived: null, evidence: null }
            : extractDeductibleWaiver(messages, code);

        const lastVisit = extractCodeSpecificLastVisit(rawLastVisit, code) ?? (
            rawLastVisit && !/[;:]/.test(rawLastVisit) ? rawLastVisit : null
        );

        return {
            code,
            covered: finalCovered,
            coverage_status: ageEligible === false ? "Not Covered" : effectiveCoverage.coverage_status,
            coverage_basis: effectiveCoverage.coverage_basis,
            dental_service_category: isUndetermined ? null : category,
            dental_service: row?.service ?? PROCEDURE_SERVICE_MAP[code] ?? null,
            frequency,
            age_limit: ageLimit,
            age_eligible: ageEligible,
            not_covered_reason: notCoveredReason,
            conditional_exclusions: extractConditionalExclusions(exclusionMessages, code, row?.service ?? null),
            deductible_waived: deductible.waived,
            deductible_waived_evidence: deductible.evidence,
            coinsurance,
            last_visit_date: isUndetermined ? null : lastVisit,
            ehb_plan_indicator: row?.ehb_plan_indicator ?? null,
            message: messages,
            lookup_status: "Derived from Guardian Plan Options"
        };
    }

    function getPatientAge(result) {
        const dob = result?.plan_information?.date_of_birth;
        if (!dob) return null;
        const match = String(dob).match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
        if (!match) return null;
        const birthMonth = Number(match[1]);
        const birthDay = Number(match[2]);
        const birthYear = Number(match[3]);
        if (![birthMonth, birthDay, birthYear].every(Number.isFinite)) return null;

        const reference = new Date(result?.scraped_at || Date.now());
        if (Number.isNaN(reference.getTime())) return null;
        let age = reference.getUTCFullYear() - birthYear;
        const birthdayMonth = birthMonth - 1;
        if (
            reference.getUTCMonth() < birthdayMonth ||
            (reference.getUTCMonth() === birthdayMonth && reference.getUTCDate() < birthDay)
        ) age -= 1;
        return age >= 0 ? age : null;
    }

    // =====================================================================
    // ISOLATED WORLD: storage + popup messaging + local procedure derivation
    // =====================================================================
    function installIsolatedBridge() {
        if (globalThis.__GUARDIAN_ISOLATED_INSTALLED__) return;
        globalThis.__GUARDIAN_ISOLATED_INSTALLED__ = true;

        let latestResult = null;
        let patientKey = null;
        const procedureCodes = new Map();
        let sweepState = "idle"; // idle | running | done | failed
        let failureReason = null;
        let sweepProgress = { completed: 0, total: ALL_CODES.length };
        let restorePromise = Promise.resolve();
        let persistQueue = Promise.resolve();

        function patientKeyFromResult(result) {
            return [
                result?.plan_information?.group_number,
                result?.plan_information?.date_of_birth,
                result?.patient_name,
                result?.relation_to_member
            ].join("|");
        }

        window.addEventListener("message", (event) => {
            if (event.source !== window || event.origin !== window.location.origin) return;
            const msg = event.data;
            if (!msg || msg.source !== PAGE_SOURCE) return;

            if (msg.type === "RESULT") {
                const nextResult = msg.data || null;
                const nextPatientKey = patientKeyFromResult(nextResult);

                if (patientKey && nextPatientKey !== patientKey) {
                    // New patient in the same Guardian tab: never leak the
                    // previous patient's procedure-code results into this one.
                    procedureCodes.clear();
                    sweepProgress = { completed: 0, total: ALL_CODES.length };
                    sweepState = "idle";
                    failureReason = null;
                }

                latestResult = nextResult;
                patientKey = nextPatientKey;
                restorePromise = restoreStoredSweepState(nextPatientKey);
                restorePromise.then(() => persist()).catch(() => {});
            }
        });

        async function persistNow() {
            try {
                const stored = await chrome.storage.local.get(["audit_context", "guardian_patient_key"]);
                const context = stored.audit_context || {};
                const materializedProcedureCodes = ALL_CODES.map((code) =>
                    procedureCodes.get(code) || buildMissingProcedureRecord(code, "Pending lookup")
                );
                const successfulCount = ALL_CODES.filter((code) =>
                    isCompletedProcedureRecord(procedureCodes.get(code))
                ).length;

                context[STORAGE_KEY] = {
                    ...(latestResult || {}),
                    procedure_derivation_version: PROCEDURE_DERIVATION_VERSION,
                    procedure_codes_requested: ALL_CODES.length,
                    procedure_codes_present: materializedProcedureCodes.length,
                    procedure_codes_complete: successfulCount === ALL_CODES.length,
                    procedure_codes: materializedProcedureCodes
                };
                await chrome.storage.local.set({
                    audit_context: context,
                    guardian_patient_key: patientKey || stored.guardian_patient_key || null
                });
            } catch (err) {
                console.debug("Guardian: storage.local set failed", err);
            }
        }

        function persist() {
            // Queue snapshots so storage writes do not block the local
            // 59-code materialization loop.
            persistQueue = persistQueue.then(() => persistNow());
            return persistQueue;
        }

        async function restoreStoredSweepState(nextPatientKey) {
            try {
                const stored = await chrome.storage.local.get([
                    "audit_context",
                    "guardian_patient_key",
                    "guardian_progress"
                ]);

                if (stored.guardian_patient_key !== nextPatientKey) return;

                const saved = stored.audit_context?.[STORAGE_KEY];
                const savedVersion = saved?.procedure_derivation_version || null;
                const derivationMatches = savedVersion === PROCEDURE_DERIVATION_VERSION;

                // Old procedure records were produced by the message-wide
                // covered/not-covered heuristic. Never reuse them after a
                // derivation-rule upgrade; the VOB itself may still be reused.
                if (derivationMatches) {
                    const savedCodes = Array.isArray(saved?.procedure_codes) ? saved.procedure_codes : [];
                    for (const record of savedCodes) {
                        if (record?.code && ALL_CODES.includes(record.code)) {
                            procedureCodes.set(record.code, record);
                        }
                    }
                } else {
                    // A parser/schema upgrade invalidates the previous procedure
                    // records and any stale FAILED state from an older build.
                    procedureCodes.clear();
                    sweepState = "idle";
                    failureReason = null;
                    sweepProgress = { completed: 0, total: ALL_CODES.length };
                }

                const successfulCount = ALL_CODES.filter((code) =>
                    isCompletedProcedureRecord(procedureCodes.get(code))
                ).length;

                sweepProgress = { completed: successfulCount, total: ALL_CODES.length };

                if (successfulCount === ALL_CODES.length) {
                    sweepState = "done";
                    failureReason = null;
                } else if (derivationMatches && stored.guardian_progress?.state === "FAILED") {
                    // Only restore a failed state when it belongs to the current
                    // derivation version. Older 403/blocked status must not survive
                    // a code-only upgrade.
                    sweepState = "failed";
                    failureReason = stored.guardian_progress.failureReason ||
                        "The previous Guardian local derivation was interrupted. Retry the crawl.";
                } else {
                    sweepState = "idle";
                    failureReason = null;
                }
            } catch (err) {
                console.debug("Guardian: stored sweep restore failed", err);
            }
        }

        function sweepStatusText() {
            if (sweepState === "running") {
                return `[i] Guardian: capturing procedure codes... (${sweepProgress.completed}/${sweepProgress.total})`;
            }
            if (sweepState === "done") {
                return "[+] Guardian data + 59 procedure-code records built locally. Ready to download.";
            }
            if (sweepState === "failed") {
                return `[!] Guardian crawl paused. ${failureReason || "Retry the crawl."}`;
            }
            if (procedureCodes.size > 0) {
                return `[i] Guardian: ${sweepProgress.completed}/${sweepProgress.total} procedure codes already stored. Click Retry Crawl to resume.`;
            }
            if (latestResult) {
                return "[i] Guardian VOB captured. Click Crawl to build 59 procedure-code records.";
            }
            return "[i] Guardian: waiting for the page's own benefits call. " +
                "Reload the Dental Eligibility page if this doesn't update in a few seconds.";
        }

        function broadcastStatus() {
            const payload = {
                command: "STATUS_UPDATE",
                carrier: "GUARDIAN",
                state: sweepState.toUpperCase(),
                completed: sweepProgress.completed,
                total: sweepProgress.total,
                ready: sweepState === "done",
                failureReason,
                status: sweepStatusText()
            };
            chrome.storage.local.set({ guardian_progress: payload }).catch(() => {});
            if (chrome.runtime?.id) {
                try {
                    chrome.runtime.sendMessage(payload)?.catch(() => {});
                } catch (_) { /* popup not open */ }
            }
        }

        function buildLocalProcedureRecord(code) {
            const rows = Array.isArray(latestResult?.plan_options) ? latestResult.plan_options : [];
            const row = resolveGoverningRow(rows, code);
            const fallbackService = PROCEDURE_SERVICE_MAP[code] || null;

            if (!row) {
                return {
                    code,
                    covered: null,
                    coverage_status: "Not Determined",
                    coverage_basis: null,
                    dental_service_category: null,
                    dental_service: fallbackService,
                    frequency: DEFAULT_FREQUENCY,
                    age_limit: null,
                    age_eligible: null,
                    not_covered_reason: null,
                    conditional_exclusions: null,
                    deductible_waived: null,
                    deductible_waived_evidence: null,
                    coinsurance: [],
                    last_visit_date: null,
                    ehb_plan_indicator: null,
                    message: [],
                    lookup_status: "No matching Guardian Plan Options row",
                    error: "No Guardian Plan Options row explicitly names this CDT code, and no static service fallback exists."
                };
            }

            return buildProcedureRecordFromPlanOption(
                code,
                row,
                getPatientAge(latestResult),
                rows,
                latestResult?.plan_information?.orthodontics_age_limit
            );
        }

        async function runProcedureCodeSweep(force = false) {
            if (!latestResult || sweepState === "running") return;

            const pending = force
                ? ALL_CODES.slice()
                : ALL_CODES.filter((code) => {
                    const record = procedureCodes.get(code);
                    return !record || record.lookup_status !== "Derived from Guardian Plan Options" || record.error;
                });

            if (!pending.length) {
                sweepState = "done";
                failureReason = null;
                sweepProgress = { completed: ALL_CODES.length, total: ALL_CODES.length };
                await persist();
                broadcastStatus();
                return;
            }

            sweepState = "running";
            failureReason = null;
            sweepProgress = {
                completed: ALL_CODES.length - pending.length,
                total: ALL_CODES.length
            };
            broadcastStatus();

            for (const code of pending) {
                try {
                    const record = buildLocalProcedureRecord(code);
                    procedureCodes.set(code, record);
                } catch (err) {
                    procedureCodes.set(code, {
                        code,
                        covered: null,
                        coverage_status: "Not Determined",
                        coverage_basis: null,
                        dental_service_category: null,
                        dental_service: PROCEDURE_SERVICE_MAP[code] || null,
                        frequency: DEFAULT_FREQUENCY,
                        age_limit: null,
                        coinsurance: [],
                        last_visit_date: null,
                        ehb_plan_indicator: null,
                        message: [],
                        lookup_status: "Derivation Failed",
                        error: String(err)
                    });
                }

                sweepProgress.completed = ALL_CODES.filter((candidate) =>
                    isCompletedProcedureRecord(procedureCodes.get(candidate))
                ).length;
                await persist();
                broadcastStatus();
            }

            await persistQueue;
            const unresolved = ALL_CODES.filter((code) => {
                const record = procedureCodes.get(code);
                return !isCompletedProcedureRecord(record);
            });

            if (unresolved.length) {
                failureReason = `${unresolved.length} CDT record${unresolved.length === 1 ? "" : "s"} could not be materialized from Guardian Plan Options.`;
                sweepState = "failed";
                broadcastStatus();
                return;
            }

            sweepState = "done";
            sweepProgress = { completed: ALL_CODES.length, total: ALL_CODES.length };
            failureReason = null;
            await persist();
            broadcastStatus();
        }

        chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
            if (request?.command === "START_CRAWL") {
                restorePromise.then(() => {
                    if (!latestResult) {
                        sendResponse({ started: false, ready: false, status: sweepStatusText() });
                        return;
                    }

                    if (sweepState === "done" && !request.force) {
                        sendResponse({ started: false, ready: true, status: sweepStatusText() });
                        return;
                    }

                    if (sweepState !== "running") runProcedureCodeSweep(Boolean(request.force));
                    sendResponse({ started: true, ready: false, status: sweepStatusText() });
                }).catch((err) => {
                    sendResponse({ started: false, ready: false, status: `Guardian state restore failed: ${String(err)}` });
                });
                return true;
            }

            if (request?.command === "GET_GUARDIAN_STATUS") {
                restorePromise.then(() => {
                    sendResponse({
                        ready: sweepState === "done",
                        vobReady: Boolean(latestResult),
                        sweepState,
                        completed: sweepProgress.completed,
                        total: sweepProgress.total,
                        failureReason,
                        status: sweepStatusText()
                    });
                }).catch((err) => {
                    sendResponse({
                        ready: false,
                        vobReady: Boolean(latestResult),
                        sweepState,
                        completed: sweepProgress.completed,
                        total: sweepProgress.total,
                        failureReason: String(err),
                        status: sweepStatusText()
                    });
                });
                return true;
            }

            return false;
        });
    }

    // =====================================================================
    // MAIN WORLD: passive fetch/XHR capture of dental-vob/ppo only.
    // =====================================================================
    function installMainWorldCapture() {
        if (globalThis.__GUARDIAN_MAIN_INSTALLED__) return;
        globalThis.__GUARDIAN_MAIN_INSTALLED__ = true;

        const nativeFetch = globalThis.fetch ? globalThis.fetch.bind(globalThis) : null;
        const NativeXHR = globalThis.XMLHttpRequest;

        const isTarget = (url, path) => {
            try {
                return new URL(url, location.href).pathname.endsWith(path);
            } catch (_) {
                return String(url).includes(path);
            }
        };

        const handleVobJson = (json) => {
            try {
                const transformed = transformVobResponse(json);
                window.postMessage({ source: PAGE_SOURCE, type: "RESULT", data: transformed }, window.location.origin);
            } catch (err) {
                console.debug("Guardian: VOB transform failed", err);
            }
        };

        if (nativeFetch) {
            globalThis.fetch = async function guardianFetch(input, init) {
                const url = (typeof Request !== "undefined" && input instanceof Request) ? input.url : String(input);
                const response = await nativeFetch(input, init);
                if (isTarget(url, VOB_PATH)) {
                    try { response.clone().json().then(handleVobJson).catch(() => {}); } catch (_) {}
                }
                return response;
            };
        }

        if (NativeXHR && NativeXHR.prototype) {
            const originalOpen = NativeXHR.prototype.open;
            const originalSend = NativeXHR.prototype.send;

            NativeXHR.prototype.open = function (method, url, ...rest) {
                this.__guardianUrl = url;
                return originalOpen.call(this, method, url, ...rest);
            };

            NativeXHR.prototype.send = function (body) {
                const url = this.__guardianUrl;
                if (url && isTarget(url, VOB_PATH)) {
                    this.addEventListener("load", () => {
                        try { handleVobJson(JSON.parse(this.responseText)); } catch (_) {}
                    });
                }
                return originalSend.call(this, body);
            };
        }

        console.info("Guardian VOB extractor installed (passive VOB capture; no CDT requests from extension). ");
    }

    // =====================================================================
    // TRANSFORM: raw dental-vob/ppo JSON -> page-ordered output
    function deriveMissingToothExclusion(ppo) {
        // Guardian exposes this as its own "Missing tooth exclusion" plan
        // option/row with an explicit "applies: Yes/No" sentence — distinct
        // from the generic prostheses-exclusion boilerplate that shows up
        // under "Other Major" on every plan regardless of this flag. Only the
        // literal labeled sentence should set the structured boolean; a few
        // direct indicator-field names are also checked in case Guardian's
        // API surfaces the flag outside of plan_option message text.
        const candidateKeys = [
            "missing_tooth_exclusion_indicator",
            "missing_tooth_provision_indicator",
            "missing_tooth_clause_indicator",
            "missing_tooth_indicator"
        ];
        for (const key of candidateKeys) {
            if (key in ppo) {
                const val = String(ppo[key] ?? "").trim().toLowerCase();
                if (val === "yes" || val === "y" || val === "true") return true;
                if (val === "no" || val === "n" || val === "false") return false;
            }
        }
        for (const opt of ppo.plan_option || []) {
            for (const msg of opt.message || []) {
                const t = String(msg);
                if (/missing\s+tooth\s+exclusion\s+applies\s*:\s*yes/i.test(t)) return true;
                if (/missing\s+tooth\s+exclusion\s+applies\s*:\s*no/i.test(t)) return false;
            }
        }

        // Fallback: the plan's own prosthesis wording ("Other Major" row).
        //   "...prostheses needed to replace teeth missing prior to being insured ... are not covered unless..." -> applies
        //   "...prostheses replacing a tooth or teeth lost or extracted before being covered ... are covered"   -> does not apply
        const allText = (ppo.plan_option || [])
            .flatMap((opt) => opt.message || [])
            .map((m) => String(m).replace(/\s+/g, " "))
            .join(" ");
        if (/dental\s+prostheses\s+needed\s+to\s+replace\s+teeth\s+missing\s+prior\s+to\s+being\s+insured[^.]*?\bare\s+not\s+covered\b/i.test(allText)) return true;
        if (/dental\s+prostheses\s+replacing\s+a\s+tooth\s+or\s+teeth\s+lost\s+or\s+extracted\s+before\s+being\s+covered[^.]*?\bare\s+covered\b/i.test(allText)) return false;
        return null;
    }

    //
    // Key order below intentionally mirrors the on-screen top-to-bottom
    // layout: header -> Plan information -> Effective dates of coverage ->
    // Deductibles -> Plan Allowance -> MaxRollover summary -> Plan options.
    // Static/boilerplate page content that isn't in the API response (the
    // ADA-form / pre-determination callouts, the Coordination of Benefits
    // paragraph, the "mail us your claim" footer, footnote legends) is left
    // out — it's identical marketing/help copy on every patient's page, not
    // per-patient data.
    // =====================================================================
    function transformVobResponse(raw) {
        const ppo = (raw && raw.ppo_benefit && raw.ppo_benefit[0]) || {};
        const bi = ppo.benefit_information || {};
        const member = raw.member || {};
        const patient = raw.patient || {};
        const maxRollover = raw.max_rollover || {};

        return {
            source: "Guardian",
            scraped_at: new Date().toISOString(),
            patient_name: [patient.first_name, patient.last_name].filter(Boolean).join(" ") || null,
            relation_to_member: patient.relation ?? null,

            plan_information: {
                benefit_period: (bi.benefit_period_effective_date && bi.benefit_period_end_date)
                    ? `${bi.benefit_period_effective_date} - ${bi.benefit_period_end_date}`
                    : null,
                date_of_birth: formatDob(member.date_of_birth),
                dependent_age_limit: findAgeLimit(raw.age_limt, "dependent"),
                student_age_limit: findAgeLimit(raw.age_limt, "student"),
                orthodontics_age_limit: findAgeLimit(raw.age_limt, "orthodontics"),
                group_name: member.organization_name ?? null,
                group_number: member.group_policy_number ?? null,
                plan_type: bi.benefit_plan_type ?? null,
                missing_tooth_exclusion_applies: deriveMissingToothExclusion(ppo),
                out_of_network_note: bi.reasonable_and_customary_amount
                    ? `Out of Network benefits are ${bi.reasonable_and_customary_amount}`
                    : null
            },

            effective_dates_of_coverage: sortByOrder(
                bi.service_category_effective_date || [],
                [CATEGORY_DISPLAY_ORDER, (c) => c.dental_service_category]
            ).map((c) => ({
                service_category: c.dental_service_category ?? null,
                effective_date: c.effective_date ?? null,
                in_network_deductible_waived: c.in_network_deductible_waived ?? null,
                out_network_deductible_waived: c.out_network_deductible_waived ?? null,
                ehb_plan_indicator: c.ehb_plan_indicator ?? null,
                late_entrant_indicator: c.late_entrant_indicator ?? null
            })),

            deductibles: buildDeductibles(ppo.deductible || [], bi.service_category_effective_date || []),

            plan_allowance: buildPlanAllowance(ppo.plan_maximum || []),

            max_rollover_summary: Object.keys(maxRollover).length ? {
                threshold: maxRollover.threshold ?? null,
                maximum_rollover_amount: maxRollover.maximum_rollover_amount ?? null,
                rollover_amount_if_all_benefits_paid_in_network: maxRollover.maxrollover_amount ?? null,
                maximum_rollover_account_maximum: maxRollover.maximum_rollover_account_max ?? null,
                personal_maximum_rollover_account: maxRollover.rollover_amount_paid_benefits ?? null
            } : null,

            plan_options: sortByOrder(
                ppo.plan_option || [],
                [PLAN_OPTION_DISPLAY_ORDER, (o) => o.dental_service]
            ).map((o) => ({
                service: o.dental_service ?? null,
                category: (o.category && o.category[0] && o.category[0].category_type) ?? null,
                coinsurance: sortByOrder(
                    o.coinsurance || [],
                    [COINSURANCE_NETWORK_ORDER, (c) => c.network_name]
                ).map((c) => ({
                    network: c.network_name ?? null,
                    amount: c.coinsurance_amount ?? null
                })),
                message: o.message || [],
                last_visit_date: o.last_visit_date ?? null,
                ehb_plan_indicator: o.ehb_plan_indicator ?? null
            })),

            additional_info: {
                product: (raw.product && raw.product.product_name) ?? null,
                plan_type_indicator: raw.plan_type_indicator ?? null,
                network_config_code: raw.network_config_code ?? null,
                medically_necessary_cleaning_indicator: ppo.medically_necessary_cleaning_indicator ?? null
            }
        };
    }

    // The API does not return rows in on-screen order (it groups by network,
    // alphabetizes services, etc.). These are the literal on-screen sequences
    // observed across the "Effective dates of coverage", "Deductibles",
    // "Plan Allowance" and "Plan options" tables, used to re-sort every list
    // below so the JSON reads top-to-bottom the same way the page does.
    const CATEGORY_DISPLAY_ORDER = [
        "Preventive", "Basic", "Periodontics", "Major", "Orthodontics", "TMJ", "Endodontics", "Oral Surgery", "Cosmetic"
    ];
    const DEDUCTIBLE_TIER_ORDER = ["Individual Dental", "Family Dental"];
    const DEDUCTIBLE_NETWORK_ORDER = ["Out-Network", "DG Preferred", "In-Network"];
    const PLAN_ALLOWANCE_NETWORK_ORDER = ["Out-Network", "DG Preferred", "In-Network"];
    const COINSURANCE_NETWORK_ORDER = ["DG Preferred", "Out-Network"];
    const PLAN_OPTION_DISPLAY_ORDER = [
        "Cleanings/Prophylaxis", "Exams/Oral Evaluations", "Fluoride",
        "Palliative Emergency Treatment", "Sealants", "X-Rays", "Anesthesia",
        "Consultations", "Endodontics", "Fillings", "Oral Surgery",
        "Periodontal Maintenance", "Periodontics", "Bridge/Denture",
        "Crown/Inlay/Onlay", "Implants", "Repair/Reline/Rebase", "Orthodontics",
        "Other Basic", "Other Major", "Other Preventive", "TMJ", "Cosmetic"
    ];

    // Sorts by one or more (orderList, keyFn) pairs, most significant first.
    // Anything not found in an orderList sorts after everything that is,
    // in its original relative order — so an unrecognized category from a
    // future Guardian change is appended, never silently dropped.
    function sortByOrder(items, ...rankers) {
        const rank = (item) => rankers.map(([order, keyFn]) => {
            const idx = order.indexOf(keyFn(item));
            return idx === -1 ? order.length : idx;
        });
        return items
            .map((item, i) => ({ item, i, r: rank(item) }))
            .sort((a, b) => {
                for (let k = 0; k < a.r.length; k++) {
                    if (a.r[k] !== b.r[k]) return a.r[k] - b.r[k];
                }
                return a.i - b.i; // stable fallback
            })
            .map((x) => x.item);
    }

    function findAgeLimit(list, category) {
        // Guardian labels the orthodontic limit "ortho"; accept either spelling.
        const aliases = category === "orthodontics" ? ["ortho", "orthodontics", "orthodontic"] : [category];
        const hit = (list || []).find((a) => aliases.includes(String(a.benefit_category || "").toLowerCase()));
        return hit ? hit.age : null;
    }

    function formatDob(raw) {
        // Guardian sends MMDDYYYY, e.g. "04072000" -> "04/07/2000"
        if (!raw || raw.length !== 8) return raw ?? null;
        return `${raw.slice(0, 2)}/${raw.slice(2, 4)}/${raw.slice(4, 8)}`;
    }

    function toMoney(str) {
        if (typeof str !== "string") return null;
        const cleaned = str.replace(/[$,]/g, "").trim();
        const match = cleaned.match(/^-?\d+(?:\.\d+)?/);
        return match ? parseFloat(match[0]) : null;
    }

    function formatRemainingAmount(rawAmount, value) {
        if (value === null || !Number.isFinite(value)) return null;
        const raw = String(rawAmount ?? "").trim();
        if (raw.startsWith("$")) return `$${value.toFixed(2)}`;
        if (/^\d+(?:\.\d+)?\s+per\s+/i.test(raw)) return String(value);
        return String(value);
    }

    function isOutNetwork(network) {
        return normalizeEvidenceText(network).toLowerCase() === "out-network";
    }

    function buildDeductibles(list, effectiveDates) {
        const preventive = (effectiveDates || []).find((c) => c.dental_service_category === "Preventive") || {};
        const groups = new Map();

        for (const row of list || []) {
            const key = `${row.coverage_tier}|${row.network_name}`;
            if (!groups.has(key)) groups.set(key, { coverage_tier: row.coverage_tier, network: row.network_name });
            const g = groups.get(key);
            if (row.deductible_period === "Deductible") g.deductible_amount = row.amount;
            if (row.deductible_period === "Met-To-Date") g.met_to_date = row.amount;
        }

        const ordered = sortByOrder(
            Array.from(groups.values()),
            [DEDUCTIBLE_TIER_ORDER, (g) => g.coverage_tier],
            [DEDUCTIBLE_NETWORK_ORDER, (g) => g.network]
        );

        return ordered.map((g) => {
            const deductibleNum = toMoney(g.deductible_amount);
            const metNum = toMoney(g.met_to_date);
            const waived = isOutNetwork(g.network)
                ? (preventive.out_network_deductible_waived ?? null)
                : (preventive.in_network_deductible_waived ?? null);
            const remaining = (deductibleNum !== null && metNum !== null)
                ? deductibleNum - metNum
                : null;

            return {
                coverage: g.coverage_tier ?? null,
                network: g.network ?? null,
                deductible: g.deductible_amount ?? null,
                met_to_date: g.met_to_date ?? null,
                waived_for_preventive: waived,
                remaining_deductible: formatRemainingAmount(g.deductible_amount, remaining)
            };
        });
    }

    function buildPlanAllowance(list) {
        const groups = new Map();

        for (const row of list || []) {
            const coverage = row.plan_maximum_for_benefit ?? row.coverage_tier ?? row.coverage_type ?? row.coverage ?? null;
            const key = `${coverage}|${row.network_name}`;
            if (!groups.has(key)) groups.set(key, { coverage, network: row.network_name });
            const g = groups.get(key);
            if (row.time_qualifier === "Yearly-Plan-Limit") g.yearly_plan_limit = row.amount;
            if (row.time_qualifier === "Year-Met-To-Date") g.year_met_to_date = row.amount;
            if (row.time_qualifier === "Lifetime-Plan-Limit") g.lifetime_plan_limit = row.amount;
            if (row.time_qualifier === "Lifetime-Met-To-Date") g.lifetime_met_to_date = row.amount;
        }

        const coverageOrder = ["Dental", "Orthodontic", "Orthodontics"];
        const ordered = sortByOrder(
            Array.from(groups.values()),
            [coverageOrder, (g) => g.coverage || ""],
            [PLAN_ALLOWANCE_NETWORK_ORDER, (g) => g.network]
        );

        return ordered.map((g) => {
            const yearlyNum = toMoney(g.yearly_plan_limit);
            const yearMetNum = toMoney(g.year_met_to_date);
            const lifeNum = toMoney(g.lifetime_plan_limit);
            const lifeMetNum = toMoney(g.lifetime_met_to_date);

            return {
                coverage: g.coverage ?? null,
                network: g.network ?? null,
                yearly_plan_limit: g.yearly_plan_limit ?? null,
                year_met_to_date: g.year_met_to_date ?? null,
                remaining_individual_maximum: (yearlyNum !== null && yearMetNum !== null)
                    ? `$${(yearlyNum - yearMetNum).toFixed(2)}`
                    : null,
                lifetime_plan_limit: g.lifetime_plan_limit ?? null,
                lifetime_met_to_date: g.lifetime_met_to_date ?? null,
                remaining_lifetime_maximum: (lifeNum !== null && lifeMetNum !== null)
                    ? `$${(lifeNum - lifeMetNum).toFixed(2)}`
                    : null
            };
        });
    }

    // Expose for Node-side unit testing only; harmless no-op in the browser
    // (module is undefined there, so this whole block never runs).
    if (typeof module !== "undefined" && module.exports) {
        module.exports = { transformVobResponse, buildProcedureRecord, buildProcedureRecordFromPlanOption, extractFrequency, extractAgeLimit, extractConditionalExclusions, ALL_CODES, PROCEDURE_SERVICE_MAP, deriveCoverage, resolveGoverningRow, buildDeductibles, buildPlanAllowance, toMoney, isLiteralCodeMention, deriveMissingToothExclusion, evaluateAgeEligibility, inferCategoryFromRowName };
    }
})();
