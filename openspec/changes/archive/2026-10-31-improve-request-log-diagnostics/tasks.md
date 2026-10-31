## 1. Backend diagnostics

- [x] 1.1 Add request-kind and transport filters through the API, facets and count cache; verify route tests cover combined filters, pagination, unknown values and legacy warmup.
- [x] 1.2 Record attempted HTTP upstream transport for compaction and warmup; verify success, upstream error and pre-dispatch failure at the route boundary.
- [x] 1.3 Expose the four persisted phase timings; verify API serialization preserves null and zero.

## 2. Dashboard

- [x] 2.1 Add localized kind labels and URL-persisted filters with reset; verify component, hook and API tests.
- [x] 2.2 Show diagnostic fields, available phase timings and small positive costs; verify detail and table regressions.
- [x] 2.3 Investigate historical missing TTFT using bounded metadata; record verified conclusions without inferring missing measurements.

## 3. Verification and delivery

- [x] 3.1 Run focused backend/frontend checks, types, lint, build and strict OpenSpec validation; verify the rendered flows in a browser.
- [x] 3.2 Preserve the live private adaptations in a narrow image overlay; verify file hashes and deploy through the image-only cutover.
- [x] 3.3 Verify production health, request filters, details and a real search; sync the spec and archive only after successful verification.
