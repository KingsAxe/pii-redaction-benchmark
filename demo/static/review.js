// Browser selections use UTF-16 units; the API uses Unicode code points.
export function codePointOffset(text, offset) {
    if (!Number.isInteger(offset) || offset < 0) throw new Error("Invalid selection offset");
    let units = 0, points = 0;
    for (const character of text) {
        if (units === offset) return points;
        units += character.length;
        points += 1;
        if (units > offset) throw new Error("Selection splits a Unicode character");
    }
    if (units === offset) return points;
    throw new Error("Selection is outside the text");
}

export function selectionInterval(text, start, end) {
    const interval = [codePointOffset(text, start), codePointOffset(text, end)];
    if (interval[0] >= interval[1]) throw new Error("Select a nonempty text range");
    return interval;
}

export function reviewIdFromSearch(search) {
    if (!search) return null;
    const params = new URLSearchParams(search);
    const reviewId = params.get("review_id");
    if (params.size !== 1 || !reviewId || !/^[0-9a-f]{32}$/.test(reviewId)) {
        throw new Error("Invalid review link; use one 32-character lowercase hexadecimal review_id");
    }
    return reviewId;
}

export function showCoverage(container, text, intervals) {
    // Never parse submitted text as HTML, including text inside marked coverage.
    const points = Array.from(text);
    container.replaceChildren();
    let previous = 0;
    for (const [start, end] of intervals) {
        container.append(document.createTextNode(points.slice(previous, start).join("")));
        const mark = document.createElement("mark");
        mark.textContent = points.slice(start, end).join("");
        container.append(mark);
        previous = end;
    }
    container.append(document.createTextNode(points.slice(previous).join("")));
}

if (typeof document !== "undefined") {
    const element = (id) => document.getElementById(id);
    let current = null, activeId = null, busy = false, generation = 0;

    function controls() {
        const editable = current && current.status !== "rejected" && !busy;
        element("submit").disabled = busy;
        element("refresh").disabled = !activeId || busy;
        for (const id of ["add", "remove", "reject"]) element(id).disabled = !editable;
        element("approve").disabled = !editable || current.status !== "pending" || !element("approval-ack").checked;
        element("download").disabled = busy || !current || current.status !== "approved";
    }

    function clearOutput() {
        element("approved-output").textContent = "No approved output retrieved.";
        element("approval-ack").checked = false;
    }

    function display(review) {
        current = review;
        activeId = review.review_id;
        window.history.replaceState(null, "", `/?review_id=${review.review_id}`);
        clearOutput();
        element("review").hidden = false;
        element("input-panel").open = false;
        element("review").dataset.status = review.status;
        element("review-state").textContent = {pending: "Pending review", approved: "Approved", rejected: "Rejected"}[review.status] || "Review";
        element("original").value = review.canonical_original;
        element("proposal").value = review.masked_text;
        element("initial-proposal").textContent = review.masked_proposal;
        element("review-status").textContent = `Review ${review.review_id}; revision ${review.revision_number}; ${review.status}. Expires in about ${review.expires_in_seconds} seconds.`;
        element("intervals").textContent = JSON.stringify({detected: review.detected_mask_intervals, current: review.mask_intervals}, null, 2);
        element("counts").textContent = JSON.stringify({automatic_detections: review.detection_counts, current_coverage: review.coverage_counts}, null, 2);
        showCoverage(element("detected-text"), review.canonical_original, review.detected_mask_intervals);
        element("selection").textContent = "Select text in the canonical original.";
        controls();
    }

    async function request(path, method = "GET", body) {
        const response = await fetch(path, {method, cache: "no-store", headers: body ? {"Content-Type": "application/json"} : {},
            body: body ? JSON.stringify(body) : undefined});
        if (!response.ok) {
            const failure = await response.json().catch(() => null);
            const error = new Error(failure?.detail?.message || "Request failed; no output produced");
            error.status = response.status;
            throw error;
        }
        return response;
    }

    async function act(work) {
        if (busy) return;
        busy = true;
        clearOutput();
        controls();
        const epoch = generation;
        try {
            await work(epoch);
        } catch (error) {
            if (epoch === generation) {
                element("message").textContent = error.message;
                // Never keep approval controls/output live after a stale-state error.
                if ([404, 409].includes(error.status)) {
                    current = null;
                    element("review").hidden = true;
                }
            }
        } finally {
            busy = false;
            controls();
        }
    }

    for (const id of ["input-text", "synthetic"]) element(id).addEventListener("input", () => {
        generation += 1;
        current = null;
        activeId = null;
        window.history.replaceState(null, "", "/");
        clearOutput();
        element("review").hidden = true;
        element("message").textContent = "Input changed; create a new review.";
        controls();
    });

    element("submission").addEventListener("submit", (event) => {
        event.preventDefault();
        generation += 1;
        current = null;
        activeId = null;
        element("review").hidden = true;
        act(async (epoch) => {
            const response = await request("/reviews", "POST", {text: element("input-text").value, synthetic_input: element("synthetic").checked});
            const review = await response.json();
            if (epoch !== generation) return;
            display(review);
            element("message").textContent = "Review created. Inspect and correct it before approval.";
        });
    });

    element("refresh").addEventListener("click", () => act(async (epoch) => {
        const review = await (await request(`/reviews/${activeId}`)).json();
        if (epoch === generation) display(review);
    }));

    for (const operation of ["add", "remove"]) element(operation).addEventListener("click", () => act(async (epoch) => {
        const source = element("original");
        const interval = selectionInterval(source.value, source.selectionStart, source.selectionEnd);
        const body = {expected_revision: current.revision_id, operation, intervals: [interval]};
        const review = await (await request(`/reviews/${activeId}/mask`, "PATCH", body)).json();
        if (epoch !== generation) return;
        display(review);
        element("message").textContent = "Mask corrected; previous approval is invalidated.";
    }));

    element("original").addEventListener("select", () => {
        const source = element("original");
        try {
            const [start, end] = selectionInterval(source.value, source.selectionStart, source.selectionEnd);
            element("selection").textContent = `Selected code-point interval [${start}, ${end}).`;
        } catch {
            element("selection").textContent = "Select a complete, nonempty character range.";
        }
    });

    element("approval-ack").addEventListener("change", controls);
    for (const action of ["approve", "reject"]) element(action).addEventListener("click", () => act(async (epoch) => {
        const review = await (await request(`/reviews/${activeId}/${action}`, "POST", {expected_revision: current.revision_id})).json();
        if (epoch !== generation) return;
        display(review);
        element("message").textContent = action === "approve" ? "Current revision approved. Retrieve it from the server to download." : "Review rejected; output is unavailable.";
    }));

    element("download").addEventListener("click", () => act(async (epoch) => {
        const expected = current.revision_id;
        const response = await request(`/reviews/${activeId}/output?expected_revision=${encodeURIComponent(expected)}`);
        const text = await response.text();
        if (epoch !== generation || !current || current.revision_id !== expected) return;
        if (response.headers.get("X-Review-Revision") !== expected) throw new Error("Output revision mismatch");
        element("approved-output").textContent = text;
        const url = URL.createObjectURL(new Blob([text], {type: "text/plain;charset=utf-8"}));
        const link = document.createElement("a");
        link.href = url;
        link.download = "synthetic-reviewed.txt";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        element("message").textContent = "Approved output retrieved and download requested.";
    }));
    controls();
    try {
        const linkedId = reviewIdFromSearch(window.location.search);
        if (linkedId) {
            activeId = linkedId;
            act(async (epoch) => {
                const review = await (await request(`/reviews/${linkedId}`)).json();
                if (epoch !== generation) return;
                display(review);
                element("input-text").value = review.canonical_original;
                element("message").textContent = "Existing review loaded. Inspect the current revision before acting.";
            });
        }
    } catch (error) {
        element("message").textContent = error.message;
    }
}
