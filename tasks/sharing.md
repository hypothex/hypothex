# Dataset and model publishing integrations

User confirmed first-version scope on 2026-10-22: publish datasets/models through
Hugging Face and S3 permissions. Hypothex-managed task/run/org sharing is outside
this version. Based on origin/main a078838, isolated feat/artifact-sharing checkout
at /tmp/hx-artifact-sharing. Earlier PR #28 remains a separate feature.

## Outcome

- Python API and CLI to publish local files/directories as datasets or models,
  fetch a pinned publication, inspect provider access, and obtain sharing links.
- Hugging Face Hub adapter for native dataset/model repositories. Private by
  default for new repositories; existing visibility is preserved. Commit IDs pin
  downloads. Explicit repository visibility changes are separate from uploads.
- S3 adapter with multipart-capable transfers and optional S3-compatible endpoints.
  Content-addressed publication prefixes and a final manifest mark complete uploads.
  Bucket/IAM policy controls access; links can be presigned with bounded expiry.
- Provider interface supports later adapters without embedding provider SDKs in
  the base runtime. Optional hf and s3 dependency extras, credential discovery via
  provider SDK environment/profile/login mechanisms; secrets are not configuration
  or receipt fields.
- Full streamed SHA-256 manifests, staging of the exact uploaded bytes, safe relative
  paths, no following symlinks/special files, explicit file selection, and bounded
  metadata. Failed uploads produce no completed local receipt. Failed downloads
  preserve any existing destination and install only verified complete data.
- Durable local publication receipts retain provider reference, kind, manifest,
  sizes/digests and optional explicit provenance. No run/data relocation or changes
  to existing DatasetSpec.path/Artifact.path filesystem meaning.
- CLI/Python support is the first usable surface; cloud uploads will be tested with
  controlled provider clients, not actual accounts or buckets.

## Reference evidence

Harbor sharing docs: https://docs.harborframework.com/harbor-hub/sharing
Harbor source checkout /tmp/hx-harbor-reference at209a48a7424218828465c3c716b042f2b381dbed.
Its CLI defaults private and separates publish/visibility/grants; actual org/RLS
permissions are service-side. Its lower-level publisher defaults public: do not copy.
HF APIs: https://huggingface.co/docs/huggingface_hub/guides/upload
https://huggingface.co/docs/huggingface_hub/package_reference/hf_api
S3 transfers: https://docs.aws.amazon.com/boto3/latest/guide/s3-uploading-files.html
S3 links: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html
Existing Hypothex dataset fingerprints use sampling for large inputs; publication
integrity needs new complete SHA-256 hashing. Existing local artifact references
and provider publication references remain separate.

## Work and verification

- [x] Inspect reference code/current architecture and confirm initial scope.
- [x] Specify public transfer models, provider interface and CLI contract.
- [x] Snapshot, hashing, receipt and verified-download core with failure tests.
- [x] Hugging Face provider and focused client-contract tests.
- [x] S3 provider and multipart/failure/access/link tests.
- [x] CLI, Python examples, Sphinx docs and agent guidance.
- [x] Affected tests, Ruff/format/ty/Sphinx and independent review.

## Implementation and current evidence

Public API: `hypothex.sharing` exposes typed targets, manifests, references and
receipts plus publish/download/access/share/visibility/list/load operations.
CLI: `hx artifacts publish|list|show|download|access|share|visibility`.
Exported receipt JSON is the portable cross-machine download input; it carries
connection options but no provider credentials. Filesystem run paths stay local.

Provider workers have non-overlapping ownership: HF adapter/tests by wandb_reader;
S3 adapter/tests by wandb_review. Parent owns models/core/CLI/docs/dependencies.
Independent read-only review by pr_review covered the full uncommitted diff,
including untracked files, followed by a focused correction review. No real
cloud account calls were used.

Review round 1 completed NOT LGTM with one reproduced P2: S3 successful regional
redirects do not update `client.meta.region_name`; presigned links can retain the
wrong signing region even after a successful manifest GET. Durable evidence:
`/Users/shreyasv/.codex/reports/hypothex-sharing/review-r1.md` and
`s3-region-probe.py` in the same directory. S3 owner is correcting this with a
real-botocore regional redirect regression; the focused re-review below closed it.
The review's minor show-command help mismatch was corrected (show accepts local
IDs; the download/share/access commands also accept exported JSON receipts).

Verified so far on 2026-10-22:
- Final provider coverage: 27 HF tests and 45 S3 tests with controlled clients,
  real SDK signatures, botocore Stubber multipart/abort/signing contracts and
  real before-send regional redirects/HeadBucket responses.
- Final complete sharing suite: 128 passed (`/tmp/hx-sharing-final.log`).
- Same 128 tests passed with SDK floors huggingface-hub 1.0.0 and boto3 1.40.0
  in an isolated environment (`/tmp/hx-sharing-sdk-floor-final.log`). Installed
  SDK versions were independently printed and confirmed in that environment.
- Base install without SDK extras: sharing + existing CLI tests, 133 passed,
  31 optional-provider cases skipped (`/tmp/hx-sharing-base-final.log`).
- Repository Ruff lint/format (325 files), ty src and Sphinx -W passed.
- Full normal Python suite with both extras: 3,878 passed, 3 skipped, 29
  docker/package tests deselected in 969.51 seconds (`/tmp/hx-sharing-pytest.log`).
  This run covers the initial adapters; final focused sharing checks and
  re-review must cover the subsequent S3 regional-signing correction. Two
  additional snapshot edge tests passed in a separate 35-test core/CLI run.

S3 correction: standard public AWS endpoints discover bucket region using
HeadBucket, accepting region headers on denied responses. Provider-managed
clients reuse the public boto3 Session to sign for a regional endpoint and
correct credential scope. Explicit custom/constrained endpoints keep their
route; injected clients with wrong regions/global signed URLs fail explicitly.
Independent focused review round 2: **LGTM, zero outstanding defects**.
Report: `/Users/shreyasv/.codex/reports/hypothex-sharing/review-r2.md`.
The reviewer independently ran 45 S3 tests and six public API probes over
freshly loaded receipts, multiple AWS regions, normal/dotted buckets, denied
HeadBucket responses, compatible endpoints and injected-client refusals.
Both regional hostname and signing credential scope were verified. Original
P2 is closed. Local feature is ready for user testing. No cloud-account test,
merge or deployment was performed for this feature.

Limits documented in docs/sharing.rst: stable source directories; temporary
snapshot disk space; Linux/macOS non-overwriting install; provider quotas; HF
existing non-main branches; native access/gating; S3 unreferenced partial uploads,
bearer-link lifetime, and lost acknowledgement/local receipt write distinction.

## PR handoff

On 2026-10-22 the user explicitly requested committing/pushing these changes,
opening a PR and having review agents review the published PR. That is the
current authorized handoff. Review the exact pushed diff and resolve reproduced
findings before reporting completion. Do not merge or contact real cloud accounts
to test transfers.
