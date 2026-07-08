"""PROVES the anthropic-proxy 401 fix (v4).

Incident (prod 2026-07-08): platform-tier Sonnet agents 401'd through the LLM
egress proxy while openai/xai (SAME workspace, SAME callback token) succeeded.
The token-shape diagnostic showed the anthropic leg was sending a REAL
``sk-ant-api`` key (108 chars, 0 dots) — i.e. ``ANTHROPIC_API_KEY`` in the pod
still carried a real provider key, while ``OPENAI_API_KEY``/``XAI_API_KEY`` held
the per-workspace callback token. The proxy correctly rejected the real key as a
malformed callback token.

v4 fix: when routed through our egress proxy, send the CANONICAL callback token
from ``TRAIA_GATEWAY_CALLBACK_TOKEN`` (always set to the callback token by the
sandbox template, independent of the ``*_API_KEY`` mapping) — never a real key
that leaked into ``ANTHROPIC_API_KEY``.
"""

import os
import importlib

PROXY = (
    "http://llm-egress-proxy.traia-system.svc.cluster.local"
    "/v1/runtime-callback/workspaces/me/platform-proxy-llm/anthropic"
)
CALLBACK = "b27ab1249ea4.d4c3b2a1deadbeefcafef00d"  # <uid>.<random>
REAL_KEY = "sk-ant-api03-" + ("A" * 95)  # a real Console API key polluting the slot
STALE_OAUTH = "sk-ant-oat01-STALE-CLAUDE-CODE-TOKEN"


def _adapter():
    import agent.anthropic_adapter as a
    return importlib.reload(a)


def _clear():
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN",
              "CLAUDE_CODE_OAUTH_TOKEN", "TRAIA_GATEWAY_CALLBACK_TOKEN"):
        os.environ.pop(k, None)


def test_proxied_uses_canonical_callback_over_polluted_api_key_and_oauth():
    # THE prod scenario: proxied, ANTHROPIC_API_KEY carries a REAL sk-ant-api key,
    # a stale OAuth token is around, and the canonical callback env is set.
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["ANTHROPIC_API_KEY"] = REAL_KEY            # the leaked real key (bug)
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = STALE_OAUTH   # priority-2 shadow
    os.environ["TRAIA_GATEWAY_CALLBACK_TOKEN"] = CALLBACK  # canonical callback token
    a = _adapter()
    assert a.resolve_anthropic_token() == CALLBACK, "must send the callback token, not the real key/OAuth"


def test_build_client_sends_callback_in_x_api_key_not_the_real_key():
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["ANTHROPIC_API_KEY"] = REAL_KEY
    os.environ["TRAIA_GATEWAY_CALLBACK_TOKEN"] = CALLBACK
    a = _adapter()
    # Even if a real key is passed in (as resolve would have), the proxied build
    # must overwrite it with the callback token on x-api-key.
    client = a.build_anthropic_client(REAL_KEY, PROXY)
    assert client.api_key == CALLBACK, f"x-api-key must be the callback token, got {client.api_key!r}"
    assert not getattr(client, "auth_token", None), "must NOT use Authorization: Bearer"
    hdrs = {k.lower(): v for k, v in client.auth_headers.items()}
    assert hdrs.get("x-api-key") == CALLBACK, f"auth_headers wrong: {client.auth_headers}"


def test_detection_uses_env_even_when_base_url_is_nonproxy():
    # base_url param non-proxy but ANTHROPIC_BASE_URL=proxy → must still detect
    # (the old code short-circuited on a truthy non-proxy base_url).
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["TRAIA_GATEWAY_CALLBACK_TOKEN"] = CALLBACK
    a = _adapter()
    assert a._egress_proxy_callback_token("https://api.anthropic.com") == CALLBACK


def test_gated_off_when_not_proxied():
    _clear()
    os.environ["ANTHROPIC_API_KEY"] = REAL_KEY
    os.environ["TRAIA_GATEWAY_CALLBACK_TOKEN"] = CALLBACK
    a = _adapter()
    assert a._egress_proxy_callback_token() is None, "no proxy env → no override"
    assert a._egress_proxy_callback_token("https://api.anthropic.com") is None


def test_build_client_leaves_byok_untouched():
    _clear()  # no proxy env
    a = _adapter()
    client = a.build_anthropic_client("sk-ant-api03-byok", "https://api.anthropic.com")
    assert client.api_key == "sk-ant-api03-byok", "BYOK/native path must be untouched"


def test_fallback_never_forwards_a_real_key():
    # Proxied, canonical env MISSING, ANTHROPIC_API_KEY holds a REAL key →
    # must NOT fall back to it (would 401); returns None so it isn't sent.
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["ANTHROPIC_API_KEY"] = REAL_KEY
    a = _adapter()
    assert a._egress_proxy_callback_token() is None, "must never forward a real sk-ant key"
    # But a callback-shaped ANTHROPIC_API_KEY (legacy correct render) is accepted.
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    a = _adapter()
    assert a._egress_proxy_callback_token() == CALLBACK


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
