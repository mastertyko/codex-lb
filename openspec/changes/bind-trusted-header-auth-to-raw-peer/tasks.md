## 1. Full-request regression coverage

- [x] 1.1 Prove a trusted raw proxy peer can supply the configured dashboard identity while forwarding the end-client address.
- [x] 1.2 Prove an untrusted raw peer cannot authenticate by projecting an address inside the trusted-proxy CIDR.

## 2. Raw-peer authorization

- [x] 2.1 Bind dashboard identity-header sanitization to the preserved raw socket peer.
- [x] 2.2 Bind trusted-header principal attribution to the preserved raw socket peer.

## 3. Verification

- [x] 3.1 Run the focused trusted-header integration tests plus lint, formatting, and proportionate type checks for affected files.
- [x] 3.2 Run strict change validation, strict main-spec validation, and verify the OpenSpec change against the implementation.
