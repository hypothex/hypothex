# PR27 macOS CI fixes: independent review

**LGTM** on the frozen eight-file diff against `f649629` recorded in `reviewed.diff` and `final-source-hashes.json`. No correctness, integrity, security, or regression findings remain in this bounded scope. This is a local review result; parent retains package and hosted CI verification.

## Scope and reasoning

- `src/hypothex/cli/main.py::_pair_host`: truncating the complete generated `hub:<hostname>` label makes the four-character prefix count toward the pairing API's 64-character limit. Ordinary names retain their labels; long names retain their prefix and first 60 hostname characters. The same-origin refusal remains before redemption, and token URL/name binding is unchanged. Parent's actual HTTP CLI tests inspect two stored host sessions through both `hosts pair` and `hosts add --pair`, using hostname lengths 3/60/61/64/200. The pre-fix log has the exact API device-length error for 61/64/200, and the affected 49-test CLI suite passes after the one-line fix. The two-line authentication documentation accurately describes it.
- `src/hypothex/demo_team.py::_LoopbackHTTPServer`: directly calling `socketserver.TCPServer.server_bind` retains socket binding, actual port/address and inherited reuse policy while excluding `HTTPServer.server_bind`'s reverse-DNS call. The subclass restores the HTTP server's explicit `server_name` and `server_port`. The actual server remains bound to 127.0.0.1; response and shutdown behavior are unchanged. Existing runtime regression checks forbid `socket.getfqdn`, receive actual HTTP 200 and verify the closed listener.
- `tests/fakes/smtp.py::FakeSmtp`: inspected the installed aiosmtpd controller implementation to confirm `server_hostname` supplies SMTP's greeting hostname separately from the bind hostname. Explicit localhost avoids machine-name DNS for plain, STARTTLS and implicit TLS. Failed `Controller.start` is cleaned up in the exception path because failed `__enter__` does not run `__exit__`. `stop(no_assert=True)` joins/cancels the controller; closing a remaining event loop covers the bind-failure path where aiosmtpd returns before its usual loop shutdown. Cleared controller/raw references make cleanup idempotent and permit the same fake instance to restart. Real trigger, factory and occupied-port failure regressions assert thread/loop/listener release. Final test-only annotation and non-None assertion changes were inspected; they do not weaken behavior checks.
- `tasks/lessons.md`: accurately records the prefix-budget, reverse-DNS and failed-entry cleanup lessons; no executable behavior is added.

## Independent runtime probes

**7 passed in 8.38 seconds** on macOS/Python 3.11, using active `tests.conftest` guard, synthetic homes, and loopback services only. Probe code and complete output are `test_independent_macos_probes.py` and `independent-probes.log`.

1. Two simultaneously active demo webhook instances start with reverse DNS forbidden, answer actual POST 200, expose correct explicit identities and distinct ports, and close both sockets/listeners.
2. The same FakeSmtp instance restarts twice in each of plain/STARTTLS/SSL modes with reverse DNS forbidden; actual messages arrive, both controller threads terminate, and every loop closes.
3. A real occupied-port bind failure cleans up controller state; the same FakeSmtp instance then starts on the released port, accepts a message and shuts down cleanly.
4. Actual host pairing HTTP validates the empty-hostname fallback (`hub:device`) and a 256-character hostname (complete label 64), retaining the host client type and saved host token.

Command:

```sh
PYTHONPATH=/tmp/hx-phase3-implementation PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -p tests.conftest -p no:cacheprovider /Users/shreyasv/Desktop/code/hypothex-phase3-evidence/implementation/ci-macos-review/test_independent_macos_probes.py -vv
```

A preliminary probe import typo is retained separately in `probe-import-error.log`; it was corrected in the external probe before the seven runtime cases ran. It is not a product failure.

## Inspected supporting evidence

- Parent CLI: `../pr27-host-label-red.log` (3 failed, 2 passed before fix), `../pr27-host-label-green.log` (49 passed in 21.36s after fix).
- Demo owner: `../ci-macos-team/regression-green.log` (32 passed in 32.74s), actual seeded serve result in `final-startup.log` (HTTP 200/user sv, zero reverse-DNS calls, child exited and descriptor removed). Independent guarded probes above establish the reviewed webhook behavior without relying solely on that worker result.
- SMTP owner: deterministic pre-fix blocked-resolver reproduction produced the exact CI timeout plus live thread/listener; after fix the reproducer succeeds with `resolver_entered=false`. `../ci-macos-smtp/06-regression-py311.log`: 123 passed in 63.07s; `07-regression-py313.log`: 123 passed in 64.78s on isolated macOS Python 3.13.15; `13-final-fakes-py313.log`: 15 passed in 7.08s after final test annotations. Scoped Ruff, formatting and ty logs are clean.
- Parent Sphinx `-W` result passed; independent `git diff --check` passed. Broad suites were not repeated for this review.

The exact final hashes cover every file in the eight-file diff, including uncommitted changes. `supporting-evidence-hashes.json` pins inspected parent/owner logs. No checkout edits, staging, commits, remote service calls, containers, or subagents were used during this review.
