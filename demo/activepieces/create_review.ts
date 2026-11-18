// Native Activepieces Code step. Invoke manually; retries stay disabled.
export const code = async (inputs) => {
    const response = await fetch('http://host.docker.internal:8000/reviews', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: inputs.text, synthetic_input: true}),
    });
    if (response.status !== 201) throw new Error(`Create review failed: HTTP ${response.status}`);
    const review = await response.json();
    if (!/^[0-9a-f]{32}$/.test(review.review_id)) throw new Error('Invalid review identifier');
    return {
        review_id: review.review_id,
        revision_id: review.revision_id,
        review_url: `http://127.0.0.1:8000/?review_id=${review.review_id}`,
        configuration: review.configuration,
        review_required: true,
    };
};
