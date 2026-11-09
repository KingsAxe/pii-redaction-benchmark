// Supply the exact approved revision; never silently refresh a stale token.
export const code = async (inputs) => {
    if (!/^[0-9a-f]{32}$/.test(inputs.review_id) || !/^[0-9a-f]{64}$/.test(inputs.expected_revision)) {
        throw new Error('Supply a review ID and its expected approved revision');
    }
    const response = await fetch(`http://host.docker.internal:8000/reviews/${inputs.review_id}/output?expected_revision=${inputs.expected_revision}`);
    if (response.status !== 200) {
        const failure = await response.json().catch(() => null);
        const known = ['review_not_approved', 'stale_revision', 'review_rejected', 'review_missing_or_expired'];
        const reason = known.includes(failure?.detail?.code) ? failure.detail.code : 'request_failed';
        throw new Error(`Output denied: HTTP ${response.status} (${reason})`);
    }
    if (response.headers.get('X-Review-Revision') !== inputs.expected_revision) throw new Error('Output revision mismatch');
    return {review_id: inputs.review_id, revision_id: inputs.expected_revision, masked_text: await response.text()};
};
