"""Regression guardrail: the openai/xai client build MUST send the per-workspace
callback token — NOT a real/stale pooled key — when routing through Traia's LLM
egress proxy.

2026-07-08 incident: a freshly-provisioned platform-tier agent chatting on grok
(xai) sent a raw ``xai-…`` platform key (llm_proxy diag token_shape ``class=opaque
len=84 dots=0``) to the egress proxy in the ``Authorization: Bearer`` header. The
proxy validates that header as a callback token (``<uid>.<random>`` /
``<uid>.<agent>.<sig>``), so a raw key is ``callback_auth.malformed_token`` → 401
``gateway_callback_auth_failed`` → the agent can't chat. The anthropic_messages
path already re-asserts the callback token under the proxy (2026-07-07/08 fix),
but its comments wrongly assumed "openai/xai read the env key directly" — the
OpenAI-client path takes the passed ``api_key`` (credential-chain-resolved real
key).

``_create_openai_client`` is the single choke point every openai/xai client build
flows through (init / switch_model / fallback). The override reuses the anthropic
adapter's canonical resolver, which reads ``TRAIA_GATEWAY_CALLBACK_TOKEN`` (always
set by the sandbox template, independent of the ``*_API_KEY`` mapping) and never
forwards a raw key. This test pins: under the proxy the callback token wins; off
the proxy (native endpoints) the passed key is untouched.
"""

from unittest.mock import MagicMock, patch

from run_agent import AIAgent

_PROXY = "http://llm-egress-proxy.traia-system.svc.cluster.local/v1/runtime-callback/workspaces/me/platform-proxy-llm"
_CALLBACK = "abc123def456.Xy90random_workspace_callback_token_value_here"  # <uid>.<random>
_REAL_XAI = "xai-Ny905IoAnj1QrldlXaW9Hq93NvpQhBdhREALPOOLKEYvalue0000"  # dots=0 pooled key


def _agent(base_url: str, provider: str):
    return AIAgent(
        api_key="init-key",
        base_url=base_url,
        model="grok-4.20-reasoning",
        provider=provider,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )


def _capture_openai():
    """Fake ``OpenAI`` recording the api_key it was constructed with."""
    seen = {}

    def _factory(**kwargs):
        seen["api_key"] = kwargs.get("api_key")
        seen["base_url"] = kwargs.get("base_url")
        return MagicMock(name="FakeOpenAI")

    return _factory, seen


def test_xai_proxy_uses_callback_token_not_real_key(monkeypatch):
    monkeypatch.setenv("TRAIA_GATEWAY_CALLBACK_TOKEN", _CALLBACK)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    agent = _agent(f"{_PROXY}/xai/v1", "xai")
    factory, seen = _capture_openai()
    with patch("run_agent.OpenAI", factory):
        agent._create_openai_client(
            {"api_key": _REAL_XAI, "base_url": f"{_PROXY}/xai/v1"},
            reason="test",
            shared=False,
        )
    assert seen["api_key"] == _CALLBACK, (
        "under the egress proxy the canonical TRAIA_GATEWAY_CALLBACK_TOKEN must win "
        f"over the passed real key; got {seen['api_key']!r}"
    )


def test_openai_proxy_uses_callback_token(monkeypatch):
    monkeypatch.setenv("TRAIA_GATEWAY_CALLBACK_TOKEN", _CALLBACK)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    agent = _agent(f"{_PROXY}/openai/v1", "openai")
    factory, seen = _capture_openai()
    with patch("run_agent.OpenAI", factory):
        agent._create_openai_client(
            {"api_key": "sk-REALopenaipoolkey000000000000", "base_url": f"{_PROXY}/openai/v1"},
            reason="test",
            shared=False,
        )
    assert seen["api_key"] == _CALLBACK


def test_native_xai_endpoint_is_untouched(monkeypatch):
    # Off our proxy (native api.x.ai): the passed key is correct and MUST NOT be
    # overridden — gate is on THIS client's base_url, not a stray env.
    monkeypatch.setenv("TRAIA_GATEWAY_CALLBACK_TOKEN", _CALLBACK)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    agent = _agent("https://api.x.ai/v1", "xai")
    factory, seen = _capture_openai()
    with patch("run_agent.OpenAI", factory):
        agent._create_openai_client(
            {"api_key": _REAL_XAI, "base_url": "https://api.x.ai/v1"},
            reason="test",
            shared=False,
        )
    assert seen["api_key"] == _REAL_XAI, "native endpoint key must pass through unchanged"


def test_proxy_without_callback_token_falls_back_to_passed_key(monkeypatch):
    # Defensive: no canonical token + no callback-shaped fallback → don't blank
    # the key (the resolver returns None; leave whatever was passed).
    monkeypatch.delenv("TRAIA_GATEWAY_CALLBACK_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    agent = _agent(f"{_PROXY}/xai/v1", "xai")
    factory, seen = _capture_openai()
    with patch("run_agent.OpenAI", factory):
        agent._create_openai_client(
            {"api_key": _REAL_XAI, "base_url": f"{_PROXY}/xai/v1"},
            reason="test",
            shared=False,
        )
    assert seen["api_key"] == _REAL_XAI
