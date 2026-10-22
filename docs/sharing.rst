Dataset and model publishing
============================

Publish local datasets/models to Hugging Face Hub or S3, keep pinned receipts,
download verified files, and generate provider sharing links. These integrations
use existing provider permissions; they do not create Hypothex task/run shares
or organization access grants.

Install and authenticate
------------------------

Enable either or both optional integrations from a checkout:

.. code-block:: bash

   uv sync --extra hf --extra s3
   uv run --extra hf hf auth login

For a tool installation after building the UI, use
``uv tool install '.[hf,s3]'``. Base installations can inspect local receipts
and show command help without the SDKs.

Hugging Face uses SDK login or ``HF_TOKEN`` and the official
``https://huggingface.co`` endpoint. S3 uses boto3 credential discovery,
including environment variables, shared profiles and workload roles.
``--profile NAME`` selects an AWS profile. Tokens are not Hypothex command
arguments and are never saved to receipts.

Publish
-------

.. code-block:: bash

   uv run --extra hf hx artifacts publish ./data --kind dataset --to hf://my-team/my-data
   uv run --extra hf hx artifacts publish ./checkpoint --kind model --to hf://my-team/my-model
   uv run --extra s3 hx artifacts publish ./checkpoint --kind model --to s3://my-bucket/models/demo

No registered project or running server is required. Run the command on the
machine holding the files; for a tracked remote checkpoint, use ``hx pull``
first or publish on the owning machine. Existing dataset and run artifact
filesystem paths are not rewritten.

Directories publish their contents using relative paths; single files keep
their basename. Repeatable ``--include`` and ``--exclude`` use case-sensitive
``fnmatch`` patterns over the whole relative POSIX path (``*`` matches slashes).
Exclusions take precedence:

.. code-block:: bash

   hx artifacts publish ./checkpoint --kind model --to hf://my-team/my-model \
      --include '*.safetensors' --include '*.json' --include 'README.md' \
      --exclude 'optimizer/*' --metadata project=classifier --metadata run_id=RUN_ID

``.git``, ``.hg``, ``.svn``, ``.venv``, ``__pycache__``, ``.env`` and
``.env.*`` are always excluded at every depth. This is not a general secret
scanner: use a prepared directory or selection patterns. Symlinks and special
files are refused. The top-level ``.hypothex`` path is reserved. Empty
directories are not recorded; empty selections are refused.

Hypothex copies selected files to a private temporary snapshot and streams full
SHA-256 hashes over the exact uploaded bytes. Files changing during their copy
are refused. This requires temporary disk space approximately equal to the
selection; it does not freeze a changing directory as one transaction. Publish
completed checkpoints and stable datasets. Limits are 10,000 files, an 8 MiB
manifest, and 32 explicit metadata string pairs (128 characters per key,
4,096 per value).

Hugging Face
------------

Files live at the native repository root for use by ordinary Hub clients.
New repositories are **private by default**. ``--public`` requests a public
repository only when creating it. Existing visibility is preserved.

A publication is one atomic commit containing files and the manifest; its full
commit SHA pins the receipt. Concurrent branch updates reject the commit;
retry from the new head. ``--revision`` defaults to ``main``; another branch
must already exist. Hub per-commit limits and account quotas still apply;
Hypothex does not split uploads into partially visible commits.

Later publications delete only paths listed in the previous Hypothex manifest
that are missing from the new selection. These paths remain managed even if
edited outside Hypothex. Unmanaged repository files are retained. Hypothex
downloads only the current inventory; old receipts remain pinned to old commits.

Explicit visibility changes affect the **entire repository and all revisions**:

.. code-block:: bash

   hx artifacts access RECEIPT_ID --json
   hx artifacts visibility RECEIPT_ID public
   hx artifacts visibility RECEIPT_ID private
   hx artifacts share RECEIPT_ID

Sharing returns a canonical commit-pinned URL, granting no new permissions.
Private/gated repositories require recipient access. Manage collaborators,
organizations and gating on Hugging Face.

S3
--

The layout is ``s3://BUCKET/PREFIX/MANIFEST_SHA256/files/<relative path>``
with a completion manifest at
``s3://BUCKET/PREFIX/MANIFEST_SHA256/.hypothex/manifest.json``.

Managed SDK transfers support multipart uploads. The manifest is written only
after every file upload succeeds. Interrupted uploads may leave unreferenced
objects but produce no completed local receipt. Retrying the same snapshot uses
the same content-addressed prefix. Hypothex never changes bucket policies,
ACLs or public-access settings, and never deletes unrelated keys. Bucket owners
can still change/remove objects; downloads reject changed bytes.

Compatible stores accept ``--endpoint-url https://s3.example.org`` and
``--region REGION``. Receipts retain non-secret connection information for
downloads on another machine. Credentials stay local.

Access is reported as ``provider-managed``; IAM, bucket/access-point policies,
organization controls and other AWS rules determine effective access. S3 has
no Hypothex ``visibility public`` operation.

.. code-block:: bash

   hx artifacts share RECEIPT_ID --file model.safetensors --expires-in 3600

The URL grants temporary GET access to one object. Select a file for multi-file
publications. Expiry is 1 through 604800 seconds; temporary signing credentials
may expire earlier. Treat the URL as a bearer credential. It is printed only
for the explicit share request and never saved to receipts. Sharing a receipt
does not grant access; recipients downloading a whole publication need their
own provider credentials.

Before signing for standard public AWS S3 endpoints, Hypothex resolves the bucket's actual region
with `HeadBucket <https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadBucket.html>`_.
It can use the region header on a denied response without
requiring an additional ``ListBucket`` grant. This handles older receipts and
uploads that succeeded through an SDK regional redirect. If the region cannot
be determined, sharing fails explicitly. Compatible and constrained endpoints
(including VPC, FIPS and dualstack routes) retain their configured endpoint and
signing region; configure the bucket's correct region for those routes.
Python callers injecting an SDK client must supply a correctly regional client;
Hypothex refuses a mismatched injected client instead of cloning its credentials.

Receipts and verified downloads
--------------------------------

Receipts live at ``<home>/publications/<id>.json`` with private file permissions.
They retain the manifest, hashes, explicit provenance and provider reference,
without source paths or signed URLs. If saving a receipt fails after remote
completion, the command reports that distinction without rolling back remote
files.

.. code-block:: bash

   hx artifacts list --json
   hx artifacts show RECEIPT_ID --json > publication.json
   # On a machine with provider credentials and the relevant extra installed:
   hx artifacts download publication.json ./restored --max-bytes 10000000000
   hx artifacts download RECEIPT_ID ./another-copy

Downloads validate bounded manifests, reject traversal and path collisions,
stage all files, and verify full SHA-256 and byte counts before installation.
Existing destinations, even empty directories/symlinks, are refused. Concurrent
creation of the destination is also refused atomically. Non-overwriting
installation supports Linux and macOS. Failed transfers discard staging data.
``--max-bytes`` checks total declared content size before file transfers.
The Hugging Face SDK may also retain its normal local download cache.

Python API
----------

.. code-block:: python

   from pathlib import Path
   from hypothex.sharing import HuggingFaceTarget, S3Target, download, publish, share

   data = publish(Path("./data"), HuggingFaceTarget(repo_id="my-team/my-data"),
                  kind="dataset", metadata={"project": "classifier"})
   download(data.reference, Path("./restored-data"))

   model = publish(Path("./model.safetensors"),
                   S3Target(bucket="my-bucket", prefix="models"),
                   kind="model", profile="research")
   link = share(model.reference, expires_in=3600, profile="research")

.. automodule:: hypothex.sharing.service
   :members: publish, download, read_manifest, list_receipts, load_receipt, access, share, set_visibility

Provider references
-------------------

See `Hugging Face atomic commits
<https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.create_commit>`_,
`boto3 managed S3 uploads
<https://docs.aws.amazon.com/boto3/latest/guide/s3-uploading-files.html>`_, and
`AWS presigned URL behavior
<https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html>`_.
