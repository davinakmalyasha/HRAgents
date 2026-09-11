import pytest
from pydantic import SecretStr, ValidationError

from hr_agents.providers import (
    Capability,
    ProviderConfig,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderSpec,
    mask_secrets,
)


class SampleConfig(ProviderConfig):
    api_key: SecretStr | None = None
    model: str = "sample"


def sample_spec(**overrides: object) -> ProviderSpec:
    defaults: dict[str, object] = {
        "id": "demo.sample",
        "capability": Capability.LLM,
        "display_name": "Sample",
        "config_model": SampleConfig,
        "build": lambda config: ("built", config),
        "health_check": lambda config: ProviderHealth.ok("fine"),
    }
    defaults.update(overrides)
    return ProviderSpec(**defaults)  # type: ignore[arg-type]


def test_mask_secrets_reveals_last_four_only() -> None:
    masked = mask_secrets({"api_key": SecretStr("sk-1234567890abcd"), "model": "gpt"})
    assert masked == {"api_key": "…abcd", "model": "gpt"}


def test_mask_secrets_short_value() -> None:
    assert mask_secrets(SecretStr("abc")) == "…"


def test_mask_secrets_nested_structures() -> None:
    payload = {
        "list": [SecretStr("token-9999")],
        "nested": {"secret": SecretStr("key-0000"), "plain": 1},
    }
    masked = mask_secrets(payload)
    assert masked == {"list": ["…9999"], "nested": {"secret": "…0000", "plain": 1}}


def test_config_masked_method() -> None:
    config = SampleConfig(api_key=SecretStr("secret-abcd"))
    assert config.masked()["api_key"] == "…abcd"


def test_health_constructors() -> None:
    assert ProviderHealth.ok().status is ProviderHealthStatus.OK
    assert ProviderHealth.misconfigured("missing key").status is ProviderHealthStatus.MISCONFIGURED
    assert ProviderHealth.unavailable("down").status is ProviderHealthStatus.UNAVAILABLE


async def test_default_health_check_when_undeclared() -> None:
    spec = sample_spec(health_check=None)
    result = await spec.check_health(spec.make_config({}))
    assert result.status is ProviderHealthStatus.OK


async def test_async_health_check_supported() -> None:
    async def checker(config: ProviderConfig) -> ProviderHealth:
        return ProviderHealth(status=ProviderHealthStatus.DEGRADED, detail="slow")

    spec = sample_spec(health_check=checker)
    result = await spec.check_health(spec.make_config({}))
    assert result.status is ProviderHealthStatus.DEGRADED


def test_make_config_validation_failure() -> None:
    class Strict(ProviderConfig):
        model: str

    spec = sample_spec(config_model=Strict)
    with pytest.raises(ValidationError):
        spec.make_config({})


def test_apply_requires_build() -> None:
    spec = sample_spec(build=None)
    with pytest.raises(NotImplementedError, match="build"):
        spec.apply(spec.make_config({}))


def test_provider_id_format_enforced() -> None:
    with pytest.raises(ValidationError):
        sample_spec(id="InvalidID")


def test_unknown_config_field_rejected() -> None:
    spec = sample_spec()
    with pytest.raises(ValidationError):
        spec.make_config({"mystery": True})
