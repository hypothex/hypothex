# PR27 macOS follow-up: independent review

**LGTM** on the frozen production, tests and documentation diff against `1e474e63b89717f246f8ef627789c2fd22e7297a`. No findings remain in this bounded review. Parent confirmed the source/test/docs freeze before this verdict. Exact reviewed input is `reviewed.diff`; file hashes are in `final-source-hashes.json`. Tracker/lessons reporting is parent-owned and may receive validation-only updates after this review; it is outside this runtime verdict.

## Storage capability-aware acceptance

The production storage module is byte-identical to the base (SHA256 `c282d9969fb93667c7f43af42c3f0c27448cbd16cd1056154b33fb928adc1a0f`). The change corrects the tests to distinguish native traversal descriptors, fallback enabled before planning, and fallback enabled after planning. It does not change deletion policy, add path-based deletion, emulate missing flags, or skip unsupported interpreters.

The revised tests remain strict: when `O_PATH` or `O_SEARCH` is exposed, native search-only traversal must succeed; every readable 0700 case must succeed even with the conservative fallback. When neither descriptor flag is available, inaccessible traversal must preserve exact payload bytes, report zero freed bytes, append no cleaned markers, return the expected refusal, and close tracked descriptors. Directory reporting in that case explicitly asserts `(0,0,None)` and a zero-byte plan; it does not interpret an unavailable measurement as an empty directory. The immediate 0300 parent is covered in native and forced-fallback modes. Documentation describes this existing conservative behavior and interpreter-build dependency accurately.

Independent challenge: on the local non-root macOS runtime with real `O_SEARCH`, I injected an internal opener regression to `O_RDONLY` while leaving the advertised capability visible. Both the reviewed file and directory tests correctly raised assertion failures. This proves the new branches do not silently accept broken native support. Four additional independent file/directory cases, with fallback before or after planning, verified actual retained payload bytes, zero freed bytes and empty cleaned markers. **6 independent probes passed in 1.26s**, in `storage-independent.log`.

The owner reproduced the same seven CI storage failures by hiding both flags before planning; the final native core/API suite passes 159 tests and the whole safety suite passes 54 tests with both flags absent from process start. Actual flag values were not captured on the GitHub Python 3.11.9 runner, so the exact capability difference is a strongly matching explanation rather than direct runner introspection. The revised tests correctly cover either supported outcome. Two optional test-file ty diagnostics were independently reproduced by the owner on unchanged base code; required source type checks pass.

## SMTP local greeting identity

`send_email` passes an explicit private constructor identity, preventing smtplib's local `getfqdn`/`gethostbyname` discovery before the caller can control it. After the socket connects, the real local socket address is parsed and rendered as an IPv4 or IPv6 address literal. IPv6 is compressed and its local scope suffix omitted. The identity is installed inside the SMTP context before STARTTLS, login or message delivery; the constructor placeholder is never sent as the greeting. Invalid/local socket identity errors become sanitized retryable connection failures, and the context closes the connected socket.

The configured remote host still drives connection establishment, SNI/certificate hostname verification and existing plaintext-loopback policy. TLS contexts, authentication, partial-recipient handling and delivery retry semantics are unchanged. The new documentation correctly distinguishes removed local-name lookup from configured remote server resolution.

**5 independent actual-wire probes passed in 1.37s**, in `smtp-independent.log`: IPv4 plain, STARTTLS and implicit TLS deliver with machine-name lookups forbidden and server-observed EHLO `[127.0.0.1]`; an actual IPv6 loopback server receives `[IPv6:::1]`. A separate implicit TLS probe trusts the CA but presents a certificate naming only 127.0.0.1/localhost to configured host ::1: delivery still fails with permanent `tls`. Thus the new local EHLO literal does not weaken remote certificate hostname verification.

Inspected owner tests cover all three security modes with authentication and forbidden local resolvers, five IPv4/IPv6 literal/scope cases, and connected socket lookup/malformed-address failures with actual socket closure. The controlled blocked-local-DNS reproduction invokes the original full notification E2E: before the fix it reaches the same first-delivery 30-second failure as CI; after the fix it completes without invoking the resolver, with the original wait unchanged. Final notification/E2E/secret-leak suites pass 133 tests on macOS Python 3.11.14 and 133 on isolated Python 3.13.15. Existing local baseline passing does not disprove the machine-dependent DNS stall; the controlled reproduction establishes the failure mechanism.

## Evidence and limits

Independent total: **11 probes passed**, using synthetic homes, active `tests.conftest` guard and loopback servers. The two mutation challenges intentionally expect the reviewed test's assertion failure under an injected production regression. All probe files and complete outputs are outside the checkout in this review directory.

```sh
PYTHONPATH=/tmp/hx-phase3-implementation PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -p tests.conftest -p no:cacheprovider /Users/shreyasv/Desktop/code/hypothex-phase3-evidence/implementation/ci-macos-followup-review/test_storage_independent.py -vv
PYTHONPATH=/tmp/hx-phase3-implementation PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -p tests.conftest -p no:cacheprovider /Users/shreyasv/Desktop/code/hypothex-phase3-evidence/implementation/ci-macos-followup-review/test_smtp_independent.py -vv
```

Inspected supporting logs are pinned in `supporting-evidence-hashes.json`, including the exact CI failure, capability reproduction, blocked-DNS red/green, final native/forced-fallback storage suites, final Python 3.11/3.13 notification suites and static/docs results. Source Ruff/format/ty and strict Sphinx evidence pass; independent `git diff --check` passes. `local-smtp-constructor.txt` records the local standard-library implementation and traversal flags used for the independent reasoning. `review-evidence-hashes.json` pins this report and external probes.

No checkout edits, staging, commits, child agents, containers, or real provider calls were performed. Broad suites were inspected rather than repeated. Package acceptance and hosted CI remain parent-owned; this verdict does not claim a new GitHub run has passed.
