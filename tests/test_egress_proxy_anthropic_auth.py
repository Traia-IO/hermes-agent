"""PROVES the 2026-07-07 anthropic-proxy 401 fix.

Incident: platform-tier Sonnet agents 401'd (`gateway_callback_auth_failed`,
`malformed_token`) on every run through the LLM egress proxy, while openai/xai
worked. Root cause: `resolve_anthropic_token()` returns a Claude Code OAuth token
(`sk-ant-oat01…`, priority 1-3) AHEAD of `ANTHROPIC_API_KEY` (priority 4 = the
per-workspace callback token the proxy validates). The OAuth token rode x-api-key
(our proxy URL classifies as a third-party endpoint) but its VALUE is not a valid
`<uid>.<random>` callback token → proxy 401.

Fix: when routed through our egress proxy, force the callback token in
ANTHROPIC_API_KEY at both the resolver and the build choke point.
"""

import os
import importlib

PROXY = (
    "http://llm-egress-proxy.traia-system.svc.cluster.local"
    "/v1/runtime-callback/workspaces/me/platform-proxy-llm/anthropic"
)
CALLBACK = "b27ab1249ea4.d4c3b2a1deadbeefcafef00d"  # <uid>.<random>
STALE_OAUTH = "sk-ant-oat01-STALE-CLAUDE-CODE-TOKEN-shadowing-the-callback"


def _adapter():
    import agent.anthropic_adapter as a
    return importlib.reload(a)


def _clear(monkeypatch=None):
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN",
              "CLAUDE_CODE_OAUTH_TOKEN"):
        os.environ.pop(k, None)


def test_resolve_prefers_callback_token_over_oauth_when_proxied():
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = STALE_OAUTH  # priority-2 shadow
    a = _adapter()
    tok = a.resolve_anthropic_token()
    assert tok == CALLBACK, f"proxied resolve must return callback token, got {tok!r}"


def test_proxy_bypass_is_gated_and_hermetic():
    # The bypass helper must fire ONLY when proxied, and only when the callback
    # token is present. (Hermetic: exercises the exact gate we added, without
    # depending on the machine's real ~/.claude credentials.)
    _clear()
    a = _adapter()
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    assert a._egress_proxy_callback_token() is None, "no proxy env → no bypass"
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    assert a._egress_proxy_callback_token() == CALLBACK, "proxied → bypass returns callback token"
    os.environ.pop("ANTHROPIC_API_KEY")
    assert a._egress_proxy_callback_token() is None, "proxied but no key → fall through, no crash"


def test_build_client_sends_callback_token_in_x_api_key_when_proxied():
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    a = _adapter()
    # Simulate the bug input: the OAuth token was resolved and passed in.
    client = a.build_anthropic_client(STALE_OAUTH, PROXY)
    # The wire credential must be the callback token, on x-api-key (not Bearer).
    assert client.api_key == CALLBACK, f"x-api-key must be callback token, got {client.api_key!r}"
    assert not getattr(client, "auth_token", None), "must NOT use Authorization: Bearer"
    hdrs = {k.lower(): v for k, v in client.auth_headers.items()}
    assert hdrs.get("x-api-key") == CALLBACK, f"auth_headers x-api-key wrong: {client.auth_headers}"
    assert "authorization" not in hdrs, f"unexpected bearer: {client.auth_headers}"


def test_build_client_leaves_byok_untouched():
    _clear()  # no proxy env at all
    a = _adapter()
    client = a.build_anthropic_client("sk-ant-api03-byok", "https://api.anthropic.com")
    assert client.api_key == "sk-ant-api03-byok", "BYOK/native path must be untouched"


def test_build_client_native_base_url_in_proxied_pod_not_overridden():
    # In a proxied pod ANTHROPIC_BASE_URL=proxy, but a client explicitly built
    # against native anthropic (base_url param wins) must NOT get the callback
    # token (it would 401 against real anthropic). Precision guard.
    _clear()
    os.environ["ANTHROPIC_BASE_URL"] = PROXY
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    a = _adapter()
    client = a.build_anthropic_client("sk-ant-api03-byok", "https://api.anthropic.com")
    assert client.api_key == "sk-ant-api03-byok", "explicit native base_url must not be overridden"


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
