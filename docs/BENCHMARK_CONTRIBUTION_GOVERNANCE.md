# THRIVE cross-organisation benchmark contribution programme

**Status: closed.** No real organisation contributions are currently accepted,
and no sector result is currently verified or published. Existing seeded
records are internal illustrative examples only. Their placeholder contributor
counts, seeded values, and any legacy noise logic are not evidence of observed
sector results or a privacy guarantee.

This document defines the proposed programme that must be implemented and
validated before it is opened. A UI checkbox, hashed identifier, cohort count,
or noise function alone is not sufficient approval.

## Proposed contributor experience

1. An authorized tenant administrator opens the contribution settings page.
   Sharing starts disabled for every tenant and every metric.
2. The administrator reviews a plain-language consent statement listing the
   exact workforce aggregates, sector, employee-size band, reporting period,
   release cadence, retention, privacy budget, withdrawal limitations, and
   support contact. No employee-level rows, names, free text, or uploaded files
   are included.
3. The administrator explicitly opts in per tenant and scope. The application
   records the consent version, administrator, tenant, timestamp, selected
   metrics, and reporting period before any contribution is submitted.
4. The administrator can review active scopes, pause future submissions, or
   withdraw. Withdrawal immediately prevents future submissions and deletes
   the tenant's unreleased contribution. After a differentially private
   aggregate has been published, the already released aggregate cannot be
   recalled or mathematically subtracted; the consent screen must say this
   before opt-in. A withdrawal excludes the tenant from future releases.
5. A contribution receipt shows scope, state, consent version, and withdrawal
   status. It never reveals other tenants or intermediate cohort values.

## Aggregation and publication gates

- Aggregate once per distinct tenant, sector, employee-size band, metric set,
  and reporting period. Reject duplicate submissions for the same scope/period.
- Accept only bounded, organization-level aggregate metrics. Define per-metric
  clipping bounds and contribution sensitivity in the release specification;
  never accept employee-level records in this service.
- Require at least **five distinct opted-in tenants** in each exact release
  cohort. Deduplicate by the authenticated tenant ID, not a caller-supplied
  organization identifier. Do not expose cohort membership, exact counts below
  the threshold, or arbitrary small slices.
- A release is unavailable until the cohort gate, input validation, DP
  accounting, release review, and audit record all pass. The release must be
  immutable and versioned; no query-time re-noising or repeated differencing
  queries are allowed.

## Differential privacy parameters

Proposed starting budget: organization-level **(ε=0.5, δ=10⁻⁶) per released
cohort and reporting period**, with a hard cumulative tenant budget of
**ε≤2.0 and δ≤10⁻⁵ in any rolling 12 months**. These are design limits, not
currently active guarantees. The implementation must:

- Use a reviewed Gaussian mechanism with sensitivity derived from the clipping
  and one-tenant-per-cohort contribution bound.
- Use a vetted privacy accountant to compose releases and refuse a release
  that would exceed a tenant's cumulative budget.
- Persist the release ID, metric bounds, sensitivity, ε/δ spend, accountant
  version, and mechanism version with the approved output.
- Validate the actual implementation and release process before making any
  privacy claim. The current independent Gaussian-noise helper is not a
  validated DP mechanism and must not be represented as one.

## Tenant isolation, retention, and audit evidence

- Resolve tenant identity only from the authenticated server-side session.
  Scope consent, contribution deduplication, withdrawal, and audit lookups to
  that tenant. Never accept a tenant or organization identity from request
  payloads as authority.
- Store contribution records under tenant-scoped access controls. Aggregation
  workers may read only the cohort inputs they need and must not return
  per-tenant inputs or membership through APIs.
- Retain unreleased contribution aggregates for at most **12 months** from
  receipt; delete them on withdrawal or expiry. Retain consent/withdrawal and
  release audit metadata for **24 months**, without contribution values.
  Published DP release snapshots may be retained for **24 months**; document
  that withdrawal cannot retract already released outputs.
- Audit evidence must include consent version and timestamps, tenant-scoped
  contribution receipt IDs, withdrawal/deletion events, cohort-threshold
  decision, validation result, release ID, metric bounds, accountant/mechanism
  versions, privacy-budget spend, and approving operator. Audit evidence must
  not contain employee rows, raw uploads, or unreleased metric values.

## Readiness checklist

Do not open the programme until all of the following exist and pass review:

- Tenant-admin consent and withdrawal screens, versioned consent, and an
  auditable default-off state.
- Tenant-derived identity and isolation tests for contribution, withdrawal,
  duplicate submissions, and cohort jobs.
- Validated clipping, aggregation, the privacy accountant, budget enforcement,
  release approval, and suppression tests.
- An approved release response must include explicit verification metadata;
  `is_seeded=false` by itself is not evidence of a verified release.
- Retention/deletion jobs and evidence that withdrawn unreleased data is
  removed.
- User-facing disclosure that already published DP releases cannot be recalled.
- Independent privacy/security review and operational audit evidence.
