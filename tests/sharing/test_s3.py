"""S3 publication contracts with controlled clients and no cloud access."""

from __future__ import annotations

import hashlib
import importlib
import io
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from hypothex.sharing.models import (
    MANIFEST_PATH,
    MAX_MANIFEST_BYTES,
    FileEntry,
    HuggingFaceTarget,
    Manifest,
    Reference,
    S3Target,
    SharingError,
)
from hypothex.sharing.s3 import S3Provider


@pytest.fixture(autouse=True)
def isolated_aws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent SDK tests from discovering ambient credentials or metadata."""
    for key in tuple(os.environ):
        if key.startswith("AWS_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing-secret-key")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))


class FakeS3:
    """Record only the transfer and signing methods the adapter may use."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: str | None = None
        self.body: io.BytesIO | None = None

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((method, kwargs))
        if self.fail == method:
            raise RuntimeError("sensitive-token-and-endpoint-details")

    def upload_file(self, Filename: str, Bucket: str, Key: str, **kwargs: Any) -> None:
        self._record("upload_file", {"Bucket": Bucket, "Key": Key, **kwargs})
        self.objects[Bucket, Key] = Path(Filename).read_bytes()

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self._record("put_object", kwargs)
        self.objects[kwargs["Bucket"], kwargs["Key"]] = kwargs["Body"]
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._record("get_object", kwargs)
        value = self.objects[kwargs["Bucket"], kwargs["Key"]]
        self.body = io.BytesIO(value)
        return {"Body": self.body, "ContentLength": len(value)}

    def download_fileobj(self, Bucket: str, Key: str, Fileobj: Any) -> None:
        self._record("download_fileobj", {"Bucket": Bucket, "Key": Key})
        Fileobj.write(self.objects[Bucket, Key])

    def generate_presigned_url(self, ClientMethod: str, **kwargs: Any) -> str:
        self._record("generate_presigned_url", {"ClientMethod": ClientMethod, **kwargs})
        return "https://s3.example.invalid/signed-test-link"


def _snapshot(tmp_path: Path, *, two: bool = False) -> tuple[Path, Manifest]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    names = ["nested/data.bin", "model.bin"] if two else ["nested/data.bin"]
    files = []
    for name in names:
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = name.encode()
        path.write_bytes(contents)
        files.append(
            FileEntry(path=name, size=len(contents), sha256=hashlib.sha256(contents).hexdigest())
        )
    return snapshot, Manifest(kind="dataset", files=tuple(files))


def test_publish_manifest_last_and_retry_preserves_unrelated_keys(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path, two=True)
    client = FakeS3()
    client.objects["test-bucket", "unrelated"] = b"leave alone"
    provider = S3Provider(client)
    target = S3Target(
        bucket="test-bucket",
        prefix="datasets/demo",
        endpoint_url="https://s3.example.invalid",
        region="us-east-2",
    )
    reference = provider.publish(snapshot, manifest, target)
    assert reference.revision == manifest.digest
    assert reference.endpoint_url == target.endpoint_url and reference.region == target.region
    prefix = f"{target.prefix}/{manifest.digest}"
    assert [method for method, _ in client.calls] == ["upload_file", "upload_file", "put_object"]
    for entry, (_, call) in zip(manifest.files, client.calls, strict=False):
        assert call["Key"] == f"{prefix}/files/{entry.path}"
        assert call["ExtraArgs"] == {"Metadata": {"sha256": entry.sha256}}
    assert client.objects[target.bucket, f"{prefix}/{MANIFEST_PATH}"] == manifest.to_bytes()
    original = dict(client.objects)
    assert provider.publish(snapshot, manifest, target) == reference
    assert client.objects == original


@pytest.mark.parametrize("failure", ["upload_file", "put_object"])
def test_failed_publish_has_no_completion_marker(tmp_path: Path, failure: str) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    client.fail = failure
    with pytest.raises(SharingError) as caught:
        S3Provider(client).publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    assert "sensitive" not in str(caught.value)
    assert all(not key.endswith(MANIFEST_PATH) for _, key in client.objects)


def test_manifest_and_file_reads_are_pinned(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    assert provider.load_manifest(reference) == manifest.to_bytes()
    assert client.body is not None and client.body.closed
    destination = tmp_path / "downloaded"
    provider.download_file(reference, manifest.files[0], destination)
    assert destination.read_bytes() == (snapshot / manifest.files[0].path).read_bytes()
    assert client.calls[-1][1]["Key"] == f"{manifest.digest}/files/{manifest.files[0].path}"


def test_manifest_size_limit_and_stream_close(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    client.objects[reference.location, f"{reference.revision}/{MANIFEST_PATH}"] = b"x" * (
        MAX_MANIFEST_BYTES + 1
    )
    with pytest.raises(SharingError, match="manifest"):
        provider.load_manifest(reference)
    assert client.body is not None and client.body.closed


def test_share_single_entry_get_only_and_provider_access(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    link = provider.share(reference, manifest, None, 604800)
    assert link.bearer and link.expires_in == 604800 and link.file == manifest.files[0].path
    assert client.calls[-1] == (
        "generate_presigned_url",
        {
            "ClientMethod": "get_object",
            "Params": {
                "Bucket": "test-bucket",
                "Key": f"{manifest.digest}/files/{manifest.files[0].path}",
            },
            "ExpiresIn": 604800,
            "HttpMethod": "GET",
        },
    )
    count = len(client.calls)
    assert provider.access(reference).visibility == "provider-managed"
    with pytest.raises(SharingError, match="IAM|bucket"):
        provider.set_visibility(reference, private=False)
    assert len(client.calls) == count


@pytest.mark.parametrize("expires", [0, -1, 604801, True, 1.5])
def test_share_rejects_invalid_expiry(tmp_path: Path, expires: Any) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    with pytest.raises(SharingError, match="expiry"):
        provider.share(reference, manifest, None, expires)
    assert all(method != "generate_presigned_url" for method, _ in client.calls)


def test_share_requires_member_selection_and_matching_manifest(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path, two=True)
    provider = S3Provider(FakeS3())
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    with pytest.raises(SharingError, match="--file"):
        provider.share(reference, manifest, None, 60)
    with pytest.raises(SharingError, match="file"):
        provider.share(reference, manifest, "../other", 60)
    assert (
        provider.share(reference, manifest, manifest.files[1].path, 1).file
        == manifest.files[1].path
    )
    changed = manifest.model_copy(update={"kind": "model"})
    with pytest.raises(SharingError, match="manifest"):
        provider.share(reference, changed, manifest.files[0].path, 60)


def test_optional_dependency_is_lazy_and_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    original = importlib.import_module

    def no_boto(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "boto3":
            raise ImportError("sensitive-import-details")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", no_boto)
    provider = S3Provider()
    reference = Reference(provider="s3", kind="dataset", location="test-bucket", revision="a" * 64)
    assert provider.access(reference).visibility == "provider-managed"
    with pytest.raises(SharingError, match=r"hypothex\[s3\]"):
        provider.load_manifest(reference)


def test_rejects_foreign_provider_before_transfers(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    with pytest.raises(SharingError, match="S3"):
        provider.publish(snapshot, manifest, HuggingFaceTarget(repo_id="team/data"))
    reference = Reference(provider="hf", kind="dataset", location="team/data", revision="a" * 40)
    with pytest.raises(SharingError, match="S3"):
        provider.load_manifest(reference)
    assert not client.calls


@pytest.mark.parametrize("contents", [b"x" * 100, b"short"])
def test_download_limits_bytes_before_writing(tmp_path: Path, contents: bytes) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    entry = manifest.files[0]
    client.objects[reference.location, f"{reference.revision}/files/{entry.path}"] = contents
    destination = tmp_path / "bounded"
    with pytest.raises(SharingError, match="size"):
        provider.download_file(reference, entry, destination)
    assert destination.stat().st_size <= entry.size


def test_download_refuses_existing_destination(tmp_path: Path) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    destination = tmp_path / "existing"
    destination.write_bytes(b"keep")
    with pytest.raises(SharingError):
        provider.download_file(reference, manifest.files[0], destination)
    assert destination.read_bytes() == b"keep"


@pytest.mark.parametrize("operation", ["get_object", "download_fileobj", "generate_presigned_url"])
def test_read_and_sign_errors_are_redacted(tmp_path: Path, operation: str) -> None:
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    provider = S3Provider(client)
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    client.fail = operation
    with pytest.raises(SharingError) as caught:
        if operation == "get_object":
            provider.load_manifest(reference)
        elif operation == "download_fileobj":
            provider.download_file(reference, manifest.files[0], tmp_path / "download")
        else:
            provider.share(reference, manifest, None, 60)
    assert "sensitive" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_connection_defaults_are_preserved_and_target_overrides_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boto3 = pytest.importorskip("boto3")
    snapshot, manifest = _snapshot(tmp_path)
    client = FakeS3()
    sessions: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []

    class Session:
        def __init__(self, **kwargs: Any) -> None:
            sessions.append(kwargs)

        def client(self, service: str, **kwargs: Any) -> FakeS3:
            assert service == "s3"
            assert kwargs.pop("config").signature_version == "s3v4"
            connections.append(kwargs)
            return client

    monkeypatch.setattr(boto3, "Session", Session)
    provider = S3Provider(
        profile="synthetic", endpoint_url="https://default.example.invalid", region="us-east-1"
    )
    reference = provider.publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    assert reference.endpoint_url == "https://default.example.invalid"
    assert reference.region == "us-east-1"
    assert provider.load_manifest(reference) == manifest.to_bytes()
    assert sessions == [{"profile_name": "synthetic"}]
    target = S3Target(
        bucket="test-bucket", endpoint_url="https://override.example.invalid", region="us-west-2"
    )
    reference = provider.publish(snapshot, manifest, target)
    assert reference.endpoint_url == target.endpoint_url and reference.region == target.region
    assert connections == [
        {"endpoint_url": "https://default.example.invalid", "region_name": "us-east-1"},
        {"endpoint_url": "https://override.example.invalid", "region_name": "us-west-2"},
    ]


def test_client_initialization_errors_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boto3 = pytest.importorskip("boto3")

    def broken(**kwargs: Any) -> Any:
        raise RuntimeError("sensitive-credential-details")

    monkeypatch.setattr(boto3, "Session", broken)
    reference = Reference(provider="s3", kind="dataset", location="test-bucket", revision="a" * 64)
    with pytest.raises(SharingError) as caught:
        S3Provider().load_manifest(reference)
    assert "sensitive" not in str(caught.value)


def _sdk_client() -> Any:
    boto3 = pytest.importorskip("boto3")
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="https://s3.example.invalid",
        aws_access_key_id="testing-access-key",
        aws_secret_access_key="testing-secret-key",
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_supported",
        ),
    )


def test_real_sdk_multipart_upload_finishes_before_manifest(tmp_path: Path) -> None:
    client = _sdk_client()
    from botocore.stub import ANY, Stubber

    snapshot = tmp_path / "large"
    snapshot.mkdir()
    contents = b"x" * (9 * 1024 * 1024)
    (snapshot / "model.bin").write_bytes(contents)
    entry = FileEntry(
        path="model.bin", size=len(contents), sha256=hashlib.sha256(contents).hexdigest()
    )
    manifest = Manifest(kind="model", files=(entry,))
    key = f"models/{manifest.digest}/files/model.bin"
    with Stubber(client) as stub:
        stub.add_response(
            "create_multipart_upload",
            {"UploadId": "controlled"},
            {"Bucket": "test-bucket", "Key": key, "Metadata": {"sha256": entry.sha256}},
        )
        for part in (1, 2):
            stub.add_response(
                "upload_part",
                {"ETag": f"part-{part}"},
                {
                    "Bucket": "test-bucket",
                    "Key": key,
                    "UploadId": "controlled",
                    "PartNumber": ANY,
                    "Body": ANY,
                },
            )
        stub.add_response(
            "complete_multipart_upload",
            {},
            {"Bucket": "test-bucket", "Key": key, "UploadId": "controlled", "MultipartUpload": ANY},
        )
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "test-bucket",
                "Key": f"models/{manifest.digest}/{MANIFEST_PATH}",
                "Body": manifest.to_bytes(),
                "ContentType": "application/json",
            },
        )
        reference = S3Provider(client).publish(
            snapshot, manifest, S3Target(bucket="test-bucket", prefix="models")
        )
        assert reference.revision == manifest.digest
        stub.assert_no_pending_responses()


def test_real_sdk_bounded_download_and_presign(tmp_path: Path) -> None:
    client = _sdk_client()
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    contents = b"exact bytes"
    entry = FileEntry(
        path="weights.bin", size=len(contents), sha256=hashlib.sha256(contents).hexdigest()
    )
    manifest = Manifest(kind="model", files=(entry,))
    reference = Reference(
        provider="s3", kind="model", location="test-bucket", revision=manifest.digest
    )
    params = {"Bucket": "test-bucket", "Key": f"{manifest.digest}/files/weights.bin"}
    with Stubber(client) as stub:
        stub.add_response("head_object", {"ContentLength": len(contents)}, params)
        stub.add_response(
            "get_object",
            {
                "Body": StreamingBody(io.BytesIO(contents), len(contents)),
                "ContentLength": len(contents),
            },
            params,
        )
        provider = S3Provider(client)
        destination = tmp_path / "downloaded"
        provider.download_file(reference, entry, destination)
        assert destination.read_bytes() == contents
        link = provider.share(reference, manifest, None, 60)
        parsed = urlsplit(link.url)
        assert parsed.hostname == "s3.example.invalid"
        assert parsed.path == f"/test-bucket/{manifest.digest}/files/weights.bin"
        query = parse_qs(parsed.query)
        assert query["X-Amz-Expires"] == ["60"]
        assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        stub.assert_no_pending_responses()


def test_sdk_discovered_endpoint_and_region_are_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boto3 = pytest.importorskip("boto3")
    snapshot, manifest = _snapshot(tmp_path)
    fake = FakeS3()
    original = boto3.session.Session.client
    clients: list[Any] = []

    def controlled(self: Any, *args: Any, **kwargs: Any) -> Any:
        client = original(self, *args, **kwargs)
        client.upload_file = fake.upload_file
        client.put_object = fake.put_object
        client.get_object = fake.get_object
        clients.append(client)
        return client

    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://original.example.invalid")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-1")
    monkeypatch.setattr(boto3.session.Session, "client", controlled)
    reference = S3Provider().publish(snapshot, manifest, S3Target(bucket="test-bucket"))
    assert reference.endpoint_url == "https://original.example.invalid"
    assert reference.region == "us-west-1"
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://other.example.invalid")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    assert S3Provider().load_manifest(reference) == manifest.to_bytes()
    assert clients[-1].meta.endpoint_url == "https://original.example.invalid"
    assert clients[-1].meta.region_name == "us-west-1"


def test_real_sdk_failed_multipart_aborts_without_completion_marker(tmp_path: Path) -> None:
    client = _sdk_client()
    from boto3.s3.transfer import TransferConfig
    from botocore.stub import ANY, Stubber

    real_upload = client.upload_file

    def serial_upload(**kwargs: Any) -> None:
        real_upload(**kwargs, Config=TransferConfig(use_threads=False))

    client.upload_file = serial_upload
    snapshot = tmp_path / "large"
    snapshot.mkdir()
    contents = b"x" * (9 * 1024 * 1024)
    (snapshot / "model.bin").write_bytes(contents)
    entry = FileEntry(
        path="model.bin", size=len(contents), sha256=hashlib.sha256(contents).hexdigest()
    )
    manifest = Manifest(kind="model", files=(entry,))
    key = f"{manifest.digest}/files/model.bin"
    with Stubber(client) as stub:
        stub.add_response(
            "create_multipart_upload",
            {"UploadId": "controlled"},
            {"Bucket": "test-bucket", "Key": key, "Metadata": {"sha256": entry.sha256}},
        )
        stub.add_client_error(
            "upload_part",
            service_error_code="AccessDenied",
            service_message="sensitive-test-details",
            expected_params={
                "Bucket": "test-bucket",
                "Key": key,
                "UploadId": "controlled",
                "PartNumber": 1,
                "Body": ANY,
            },
        )
        stub.add_response(
            "abort_multipart_upload",
            {},
            {"Bucket": "test-bucket", "Key": key, "UploadId": "controlled"},
        )
        with pytest.raises(SharingError) as caught:
            S3Provider(client).publish(snapshot, manifest, S3Target(bucket="test-bucket"))
        assert "sensitive" not in str(caught.value)
        stub.assert_no_pending_responses()


def test_real_sdk_oversized_download_stops_before_writing(tmp_path: Path) -> None:
    client = _sdk_client()
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    entry = FileEntry(path="file.bin", size=1, sha256=hashlib.sha256(b"x").hexdigest())
    manifest = Manifest(kind="dataset", files=(entry,))
    reference = Reference(
        provider="s3", kind="dataset", location="test-bucket", revision=manifest.digest
    )
    params = {"Bucket": reference.location, "Key": f"{reference.revision}/files/{entry.path}"}
    body = StreamingBody(io.BytesIO(b"oversized"), 9)
    with Stubber(client) as stub:
        stub.add_response("head_object", {"ContentLength": 9}, params)
        stub.add_response("get_object", {"Body": body, "ContentLength": 9}, params)
        destination = tmp_path / "bounded"
        with pytest.raises(SharingError, match="size"):
            S3Provider(client).download_file(reference, entry, destination)
        assert destination.stat().st_size == 0
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("bucket", ["test-bucket", "test.bucket"])
@pytest.mark.parametrize("region", ["us-west-2", "us-east-1"])
@pytest.mark.parametrize("head_denied", [True, False])
def test_native_share_resolves_region_after_sdk_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bucket: str,
    region: str,
    head_denied: bool,
) -> None:
    boto3 = pytest.importorskip("boto3")
    from botocore.awsrequest import AWSResponse
    from botocore.config import Config

    from hypothex.sharing import publish, share

    class Raw(io.BytesIO):
        def stream(self, amt: int | None = None, **kwargs: Any) -> Any:
            while part := self.read(amt or 65536):
                yield part

    objects: dict[str, bytes] = {}
    calls: list[tuple[str, str, str]] = []

    def send(request: Any, **kwargs: Any) -> Any:
        auth = request.headers.get("Authorization", b"")
        if isinstance(auth, bytes):
            auth = auth.decode()
        scope = auth.split("Credential=", 1)[1].split(",", 1)[0].split("/")
        calls.append((request.method, urlsplit(request.url).hostname or "", scope[2]))
        headers = {"x-amz-bucket-region": region}
        if scope[2] != region:
            body = (
                f"<Error><Code>PermanentRedirect</Code><Region>{region}</Region></Error>"
            ).encode()
            return AWSResponse(request.url, 301, headers, Raw(body))
        if request.method == "HEAD":
            return AWSResponse(request.url, 403 if head_denied else 200, headers, Raw(b""))
        path = urlsplit(request.url).path
        # Dotted buckets use path addressing and ordinary buckets virtual hosts.
        if path.startswith(f"/{bucket}/"):
            path = path[len(bucket) + 1 :]
        if request.method == "PUT":
            contents = request.body
            if hasattr(contents, "read"):
                contents = contents.read()
            objects[path] = contents
            return AWSResponse(request.url, 200, {"etag": '"controlled"'}, Raw(b""))
        assert request.method == "GET"
        contents = objects[path]
        return AWSResponse(request.url, 200, {"content-length": str(len(contents))}, Raw(contents))

    original = boto3.session.Session.client

    def controlled(self: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["config"] = kwargs["config"].merge(
            Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )
        )
        client = original(self, *args, **kwargs)
        client.meta.events.register("before-send.s3", send)
        return client

    monkeypatch.setattr(boto3.session.Session, "client", controlled)
    source = tmp_path / "data.bin"
    source.write_bytes(b"controlled publication")
    provider = S3Provider(region="us-east-1")
    receipt = publish(
        source,
        S3Target(bucket=bucket),
        kind="dataset",
        home=tmp_path / "home",
        provider=provider,
    )
    assert receipt.reference.region == "us-east-1"
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://other.example.invalid")
    for signer in (provider, S3Provider()):
        url = share(receipt.reference, provider=signer).url
        parts = urlsplit(url)
        credential = parse_qs(parts.query)["X-Amz-Credential"][0]
        assert credential.split("/")[2] == region
        expected_host = f"s3.{region}.amazonaws.com"
        assert parts.hostname == (expected_host if "." in bucket else f"{bucket}.{expected_host}")
    assert any(method == "HEAD" for method, _, _ in calls)
    assert all("example.invalid" not in host for _, host, _ in calls)
    if region != "us-east-1":
        assert any(signed_region == "us-east-1" for _, _, signed_region in calls)
        assert any(signed_region == region for _, _, signed_region in calls)


@pytest.mark.parametrize("head_result", ["wrong-region", "no-region", "global-url", "correct"])
def test_native_injected_signer_requires_verified_region_and_regional_url(
    tmp_path: Path, head_result: str
) -> None:
    boto3 = pytest.importorskip("boto3")
    from botocore.config import Config
    from botocore.stub import Stubber

    _, manifest = _snapshot(tmp_path)
    reference = Reference(
        provider="s3", kind=manifest.kind, location="test-bucket", revision=manifest.digest
    )
    region = "us-east-1" if head_result == "wrong-region" else "us-west-2"
    client = boto3.client(
        "s3",
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "auto" if head_result == "global-url" else "virtual"},
        ),
    )
    response = {} if head_result == "no-region" else {"BucketRegion": "us-west-2"}
    with Stubber(client) as stub:
        stub.add_response("head_bucket", response, {"Bucket": reference.location})
        if head_result == "correct":
            link = S3Provider(client).share(reference, manifest, file=None, expires_in=60)
            assert urlsplit(link.url).hostname == "test-bucket.s3.us-west-2.amazonaws.com"
        else:
            with pytest.raises(SharingError, match="region"):
                S3Provider(client).share(reference, manifest, file=None, expires_in=60)
        stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://s3.example.invalid",
        "https://s3.us-west-2.amazonaws.com:8443",
        "http://s3.us-west-2.amazonaws.com",
        "https://s3-fips.us-west-2.amazonaws.com",
        "https://s3.dualstack.us-west-2.amazonaws.com",
        "https://vpce-example.s3.us-west-2.vpce.amazonaws.com",
    ],
)
def test_custom_network_endpoint_preserved_without_head(tmp_path: Path, endpoint: str) -> None:
    from types import SimpleNamespace

    _, manifest = _snapshot(tmp_path)
    reference = Reference(
        provider="s3", kind=manifest.kind, location="test-bucket", revision=manifest.digest
    )
    client: Any = FakeS3()
    client.meta = SimpleNamespace(endpoint_url=endpoint, region_name="us-west-2")
    link = S3Provider(client).share(reference, manifest, file=None, expires_in=60)
    assert link.url == "https://s3.example.invalid/signed-test-link"
    assert [method for method, _ in client.calls] == ["generate_presigned_url"]
