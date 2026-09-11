"""Storage capability providers.

``storage.local_disk`` is the self-host default (a mounted volume — simple,
backup-friendly, can point at an office NAS mount). ``storage.s3`` covers
MinIO/R2/AWS in the compose stack and cloud deployments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr

from hr_agents.providers.base import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderSpec,
)


class LocalDiskConfig(ProviderConfig):
    root: str = Field(default="data/documents")
    max_file_mb: int = Field(default=25, ge=1, le=500)


class S3Config(ProviderConfig):
    endpoint_url: str = "http://localhost:9000"
    access_key: str
    secret_key: SecretStr
    bucket: str = "hragents-documents"
    region: str = "us-east-1"
    use_path_style: bool = True


def _build_local(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, LocalDiskConfig)
    return {"transport": "local_disk", "root": str(Path(config.root))}


def _build_s3(config: ProviderConfig) -> dict[str, Any]:
    assert isinstance(config, S3Config)
    return {
        "transport": "s3",
        "endpoint_url": config.endpoint_url,
        "bucket": config.bucket,
        "region": config.region,
        "use_path_style": config.use_path_style,
    }


def _health_local(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, LocalDiskConfig)
    root = Path(config.root)
    if root.exists() and not root.is_dir():
        return ProviderHealth.misconfigured(f"{root} exists but is not a directory")
    return ProviderHealth.ok(f"local storage at {root}")


def _health_s3(config: ProviderConfig) -> ProviderHealth:
    assert isinstance(config, S3Config)
    if not config.access_key:
        return ProviderHealth.misconfigured("access_key is required")
    return ProviderHealth.ok(
        f"configured for {config.endpoint_url}/{config.bucket} (probe in Phase 7)"
    )


def storage_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            id="storage.local_disk",
            capability=Capability.STORAGE,
            display_name="Local disk / mounted volume",
            description=(
                "Store documents on a local disk or mounted network volume. "
                "Self-host default; backup-friendly."
            ),
            config_model=LocalDiskConfig,
            build=_build_local,
            health_check=_health_local,
        ),
        ProviderSpec(
            id="storage.s3",
            capability=Capability.STORAGE,
            display_name="S3-compatible object storage",
            description="MinIO, Cloudflare R2, AWS S3, or any compatible endpoint.",
            config_model=S3Config,
            build=_build_s3,
            health_check=_health_s3,
            requires_network=True,
            secret_fields=["secret_key"],
        ),
    ]
