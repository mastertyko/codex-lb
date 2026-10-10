# desktop-voice-owner Specification

## Purpose

Define authenticated Desktop Voice routing through the exact stored user and workspace while preserving model-pool pause policy.

## Requirements

### Requirement: Separate gateway and caller credentials
The proxy MUST accept a registered proxy key in `X-Codex-LB-Key` alongside exactly one caller Bearer credential only on supported proxy routes. It MUST validate the proxy key regardless of global optional-auth configuration. Missing, empty, repeated or conflicting credentials MUST be rejected before upstream access. Ordinary legacy proxy-key authentication MUST remain compatible. The gateway key MUST NOT reach any upstream destination, and caller OAuth/account/attestation MUST NOT enter pooled model credential forwarding.

#### Scenario: Dual credentials preserve pooled model routing
- **WHEN** an authenticated client requests Models, HTTP Responses or WebSocket Responses with separate gateway and caller credentials
- **THEN** the proxy uses the existing key policy and account pool and strips caller credentials and the gateway header before existing upstream credential construction

#### Scenario: Duplicate gateway credential
- **WHEN** a request supplies two gateway-key headers or multiple Authorization values
- **THEN** it is denied without selecting an account or contacting an upstream

### Requirement: Authenticate the exact Desktop Voice principal
The explicit Desktop Voice lane MUST require an access-token user identity and workspace identity and MUST authenticate that exact caller bearer with the trusted native upstream before using any stored account credential. Verification MUST use a fixed trusted origin, bounded body and timeout, no redirects, no retries, strict HTTP 200 and a valid expected response. It MUST NOT log upstream body, credential, identity or raw transport error. Unverified JWT claims MUST NOT authorize stored-token use.

#### Scenario: Forged claims cannot select stored credentials
- **WHEN** a syntactically valid token names an existing account but upstream verification rejects it
- **THEN** the request is denied before stored credentials are decrypted or a Voice connection is opened

#### Scenario: Redirect or empty successful response
- **WHEN** the verifier receives a redirect, an empty object, invalid JSON or an unexpected response
- **THEN** it fails closed without following the redirect or trying another endpoint

### Requirement: Exact stored owner without pool fallback
After caller authentication, Desktop Voice MUST match both authenticated user and workspace to exactly one existing nondeleted LB account within the proxy key's account scope. It MUST freshly recheck owner identity and status before stored credential use. An account switch MUST select only the new exact authenticated owner or fail closed. Missing, ambiguous, out-of-scope, deleted or deactivated owners MUST be denied. The service MUST NOT fall back to any other account or silently replace the stored credential with caller OAuth.

#### Scenario: Shared workspace has multiple users
- **WHEN** two accounts share a workspace and only one matches the authenticated user
- **THEN** only that exact user/workspace account can be used

#### Scenario: Account changes before attachment
- **WHEN** the selected account is deleted, reauthenticated as a different user, deactivated or removed from key scope before attachment
- **THEN** no stored credential for the changed account is used

### Requirement: Voice may use a pool-paused owner explicitly
The explicit authenticated Desktop Voice lane MUST permit ACTIVE and PAUSED exact owners and MUST leave the stored PAUSED status and ordinary model-pool eligibility unchanged. It MUST retain exact-owner stream capacity admission and release its lease exactly once on success, failure or cancellation. Other unavailable account states MUST fail closed. Any token refresh MUST preserve the exact principal and MUST NOT unpause the account.

#### Scenario: Paused account is used only for its owner's Voice
- **WHEN** the authenticated Desktop user matches a PAUSED account
- **THEN** the explicit Voice request can use that account while ordinary pool requests still exclude it and its stored status remains PAUSED

### Requirement: Both Desktop creation modes preserve ownership
The proxy MUST provide explicit private endpoints for client-created call sideband and app-server-created Voice calls. The latter MUST create and attach using the same exact owner identity. Creation and attachment MUST preserve supported protocol/context fields, query ordering, subprotocol negotiation, text/binary frames and bounded close/cancellation behavior. Native failure MUST NOT trigger retries under a different identity. Live credentials, raw call identifiers, SDP and frames MUST NOT be persisted or logged.

#### Scenario: Client-created native call
- **WHEN** an authenticated Desktop caller attaches to an externally created call through the new lane
- **THEN** the proxy uses the exact matched stored owner's credentials at the fixed native Live endpoint without requiring or fabricating a pooled-call binding

#### Scenario: Legacy app-server-created call
- **WHEN** the client creates a Voice call through the new private creation endpoint
- **THEN** call creation and sideband use the same owner and the response contract remains compatible with the installed client

#### Scenario: Disconnect during handshake or streaming
- **WHEN** a downstream or upstream connection closes or its task is cancelled
- **THEN** all owned connections/tasks close within bounded cleanup and the exact-owner lease is released once

### Requirement: Bounded gateway rejection diagnostics
When the Desktop gateway credential boundary denies a request, it MUST emit one diagnostic event containing only a fixed rejection reason, the HTTP or WebSocket transport, and the ordinary or Voice lane. The reason MUST identify the failed credential category without logging header names or values, credentials, identities, attestation content, exception text, request paths, queries, call identifiers, or request and response bodies. Diagnostics MUST preserve the documented admission checks, denial status and public error envelope.

#### Scenario: Actual Desktop request is denied
- **WHEN** a Desktop HTTP or WebSocket request fails gateway header, caller header, Bearer syntax, account context, attestation, route support, or gateway key validation
- **THEN** one bounded diagnostic identifies the failed category and transport/lane without disclosing request data or changing the external denial

#### Scenario: Actual Desktop attestation is denied
- **WHEN** the attestation check denies a request
- **THEN** the fixed reason distinguishes cardinality, empty value, boundary whitespace, size, unsupported list syntax or character set using the documented validation order, without recording lengths or attestation data

#### Scenario: Valid credentials and legacy traffic
- **WHEN** a request passes the existing Desktop credential checks or uses ordinary legacy key authentication
- **THEN** no rejection diagnostic is emitted and routing and credential handling remain unchanged

### Requirement: Accept the native app-server attestation envelope
The credential boundary MUST accept the native version-one attestation JSON envelope in one bounded ASCII header, including its JSON commas. A successful envelope MUST have exactly `v`, `s`, and string `t` fields with integer `v=1` and integer `s=0`; a failure envelope MUST have exactly `v` and `s` fields with integer `v=1` and integer `s` from 1 through 4. Duplicate fields, extra or concatenated objects, invalid field types, unsupported version/status forms and arbitrary comma lists MUST remain denied. Existing non-list opaque attestation values MUST remain compatible. Header cardinality, empty/boundary-whitespace rejection, the 16 KiB bound and character checks MUST remain unchanged. Envelope syntax MUST NOT authorize a principal or replace gateway-key, caller-Bearer, account-context or exact-owner verification. Caller attestation MUST be stripped from ordinary pooled upstream requests and preserved byte-for-byte only for native Voice egress after normal owner verification.

#### Scenario: Native app-server envelope reaches pooled Responses
- **WHEN** a valid split-auth HTTP or WebSocket Responses request includes a native success or failure envelope
- **THEN** existing key policy and pool routing apply without an attestation rejection and no caller attestation reaches the pooled upstream

#### Scenario: Native envelope reaches exact-owner Voice
- **WHEN** a Voice creation or sideband request includes a native envelope and its caller and exact owner pass the existing verification
- **THEN** the same header is forwarded unchanged to the fixed native origin, preserving owner status and capacity cleanup

#### Scenario: Envelope cannot bypass caller verification
- **WHEN** an apparently valid envelope accompanies a caller rejected by the trusted verifier
- **THEN** no stored owner credential is decrypted and no Voice connection is opened
