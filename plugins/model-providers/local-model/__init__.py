"""Local GGUF backbone provider profile.

Registers ``local-model`` — the always-on, in-process backbone described in
``agent/llama_cpp_adapter.py`` and ``agent/local_model_manager.py``. Unlike
every other profile in ``plugins/model-providers/``, this one has no real
``base_url`` and no credential of any kind — ``auth_type="virtual"``, the
same classification the ``moa`` provider uses (see
``zeb_cli/providers.py::ZEB_OVERLAYS["moa"]``) for a provider with no real
endpoint to authenticate against. This also exempts it from the desktop
Providers-tab parity contract (``tests/zeb_cli/test_provider_parity.py``),
which only requires a Keys/Accounts card for providers that actually have
credentials to configure.
"""

from __future__ import annotations

from typing import Optional

from providers import register_provider
from providers.base import ProviderProfile


class LocalModelProfile(ProviderProfile):
    """In-process local model — no HTTP endpoint, so the generic HTTP-based
    health check and model-catalog fetch (which both assume a base_url)
    don't apply; override both with local-only equivalents.
    """

    def fetch_models(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 8.0,
    ) -> Optional[list[str]]:
        # No HTTP catalog to query — there's exactly one model: whatever
        # local_model.repo_id/quant (or local_model.path) in config.yaml
        # resolves to. See agent/local_model_manager.py.
        return ["zeb-local"]


local_model = LocalModelProfile(
    name="local-model",
    aliases=("zeb-local", "local-gguf", "offline"),
    display_name="Zeb Local Model (offline)",
    description=(
        "Always-on local quantized backbone baked into ZebOS — no API key, "
        "no network required. The default/fallback inference path."
    ),
    env_vars=(),
    base_url="",
    auth_type="virtual",
    supports_health_check=False,
    supports_vision=False,
    default_max_tokens=4096,
    default_aux_model="zeb-local",
)

register_provider(local_model)
