"""Regression guards for the Traia first-class OpenAI provider (fork commit
48794f1a3, re-homed onto v0.16).

Upstream hermes has NO bare "openai" entry in PROVIDER_REGISTRY — it only
aliases "openai" → OpenRouter in providers.py, a map the RUNTIME resolver
(auth.resolve_provider) does not consult. So resolve_provider("openai") fell
through to raise AuthError("Unknown provider 'openai'") and EVERY gpt-5.x run
died before a single LLM call (prod outage: steady-drifter logged it every
cron tick). These tests pin the fix so it cannot silently regress on a future
upstream rebase. The openai-provider patch had no tests on v0.13 either — added
here per the v0.16-unification adversarial review.
"""

from hermes_cli import auth as auth_mod
from hermes_cli import runtime_provider as rp

# A per-workspace callback token (not a real key) + the egress-proxy base_url,
# the shape a platform-tier openai agent actually sees on a proxied pod.
_CALLBACK = "uid.workspace.callbacktoken"
_PROXY = (
    "http://llm-egress-proxy.traia-system.svc.cluster.local"
    "/v1/runtime-callback/workspaces/me/platform-proxy-llm/openai/v1"
)


def test_resolve_provider_openai_is_first_class():
    """resolve_provider("openai") must return "openai" (not raise) and carry the
    OPENAI_BASE_URL env var so it routes through the Traia LLM egress proxy."""
    assert auth_mod.resolve_provider("openai") == "openai"
    pc = auth_mod.PROVIDER_REGISTRY["openai"]
    assert pc.auth_type == "api_key"
    assert pc.base_url_env_var == "OPENAI_BASE_URL"
    assert "OPENAI_API_KEY" in pc.api_key_env_vars


def test_explicit_openai_defaults_to_codex_responses_through_proxy():
    """GPT-5.x needs the Responses API. URL auto-detect only fires for a literal
    api.openai.com host, so a proxied base_url must still default to
    codex_responses — otherwise a proxied gpt-5.x agent hits the wrong endpoint."""
    resolved = rp._resolve_explicit_runtime(
        provider="openai",
        requested_provider="openai",
        model_cfg={},
        explicit_api_key=_CALLBACK,
        explicit_base_url=_PROXY,
    )
    assert resolved is not None
    assert resolved["provider"] == "openai"
    assert resolved["api_mode"] == "codex_responses"


def test_explicit_openai_config_api_mode_wins():
    """A config.yaml api_mode still overrides the codex_responses default for a
    rare chat_completions model."""
    resolved = rp._resolve_explicit_runtime(
        provider="openai",
        requested_provider="openai",
        model_cfg={"api_mode": "chat_completions"},
        explicit_api_key=_CALLBACK,
        explicit_base_url="https://api.openai.com/v1",
    )
    assert resolved is not None
    assert resolved["api_mode"] == "chat_completions"
