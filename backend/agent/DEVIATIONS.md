# Deviations from ARCHITECTURE.md

1. **`extraction_error` is a top-level key** of the `/v1/extract` response (`null` on success). The contract says it is "set" without naming where.
2. **Duplicate sample expectation.** `duplicate_of_clean_1.pdf` is byte-identical, so the API's idempotency rule returns clean_1's case (`X-Cache: HIT`) rather than raising `CORE-DUPLICATE-DOC`. `ground_truth.json` therefore expects no findings for it. Proving `CORE-DUPLICATE-DOC` needs the same file uploaded under a different `caseType` or inside a multi-file case.
3. **Explain drop reasons** add `no_quote`, `unknown_finding` and `invalid_model_output` alongside the contract's `quote_not_found`.
4. **Lenient parsing for small models.** Currency symbols (`₹`, `Rs`) are mapped to ISO codes before validation, and an explain answer that is a single bare note is wrapped as `{summary: "", notes: [note]}`. Both were needed for `llama3.2` (3B) to pass validation; quote verification still applies.
5. **Agent errors** use FastAPI's `{"detail": ...}` body, not RFC 9457. The contract applies problem+json to the API service; the API should map agent errors.
