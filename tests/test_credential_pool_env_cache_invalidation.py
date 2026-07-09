"""PROVES the credential-pool env-cache-invalidation fix (2026-07-08 anthropic 401).

Pre-cutover agents cached the REAL anthropic key into auth.json's credential_pool
(source="env:ANTHROPIC_API_KEY", access_token=<real sk-ant-api>). The LLM-egress-
proxy cutover swapped ANTHROPIC_API_KEY env to the per-workspace callback token, but
the persisted cache kept serving the stale real key → proxy 401 → entry marked
'exhausted'. Fix: an env:-sourced credential FOLLOWS its env var — on load, refresh
the cached token from the live env and clear the stale exhausted/error state; also
re-read at serve time. Heals every migrated agent, no per-agent data surgery.
"""

import os
import importlib

CALLBACK = "b27ab1249ea4.d4c3b2a1deadbeefcafef00d"  # current env value (<uid>.<rand>)
STALE_REAL = "sk-ant-api03-" + ("A" * 95)  # the cached pre-cutover real key


def _mod():
    import agent.credential_pool as m
    return importlib.reload(m)


def _stale_entry_payload():
    # mirrors the real /data/.hermes/profiles/<agent>/auth.json entry
    return {
        "id": "90e84f",
        "label": "ANTHROPIC_API_KEY",
        "auth_type": "api_key",
        "priority": 0,
        "source": "env:ANTHROPIC_API_KEY",
        "access_token": STALE_REAL,
        "last_status": "exhausted",
        "last_status_at": 1783493614.0,
        "last_error_code": 401,
        "last_error_message": "gateway_callback_auth_failed",
        "base_url": "http://llm-egress-proxy.../platform-proxy-llm/anthropic",
    }


def test_from_dict_refreshes_access_token_and_clears_exhausted():
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    try:
        m = _mod()
        c = m.PooledCredential.from_dict("anthropic", _stale_entry_payload())
        # BOTH the field the run path reads directly AND the property must be the
        # live callback token — a stale access_token is what reached the wire in prod.
        assert c.access_token == CALLBACK, f"stale cached key must be refreshed, got {c.access_token!r}"
        assert c.runtime_api_key == CALLBACK, f"must serve the callback token, got {c.runtime_api_key!r}"
        # Stale exhausted/error state cleared so the entry is selectable again.
        assert c.last_status is None, "stale exhausted status must be cleared when env changed"
        assert c.last_error_code is None
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_runtime_api_key_reads_live_env_even_if_cache_stale():
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    try:
        m = _mod()
        c = m.PooledCredential(
            provider="anthropic", id="x", label="ANTHROPIC_API_KEY",
            auth_type="api_key", priority=0, source="env:ANTHROPIC_API_KEY",
            access_token=STALE_REAL,
        )
        assert c.runtime_api_key == CALLBACK, "serve-time must re-read env, not the stale token"
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_empty_env_keeps_cached_token():
    # env NOT populated → must fall back to the cached token (don't break agents)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    m = _mod()
    c = m.PooledCredential.from_dict("anthropic", _stale_entry_payload())
    assert c.access_token == STALE_REAL, "empty env must not wipe the cached token"
    assert c.runtime_api_key == STALE_REAL


def test_non_env_source_untouched():
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    try:
        m = _mod()
        p = _stale_entry_payload()
        p["source"] = "manual"
        c = m.PooledCredential.from_dict("anthropic", p)
        assert c.access_token == STALE_REAL, "manual-source creds must not be env-refreshed"
        assert c.runtime_api_key == STALE_REAL
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_matching_env_is_noop_no_status_churn():
    # env == cached (normal post-cutover agent): no change, status preserved
    os.environ["ANTHROPIC_API_KEY"] = CALLBACK
    try:
        m = _mod()
        p = _stale_entry_payload()
        p["access_token"] = CALLBACK
        p["last_status"] = "ok"
        c = m.PooledCredential.from_dict("anthropic", p)
        assert c.access_token == CALLBACK
        assert c.last_status == "ok", "no churn when env already matches"
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
