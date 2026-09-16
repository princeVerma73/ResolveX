# Known Warnings & Bug Log

## 1. Upstream Supabase Client Deprecation Warnings

- **Step / Module**: Step 2 — Supabase Backend Connection (`tests/test_supabase_connection.py`)
- **Status**: Non-blocking (Investigated & Documented)
- **Test Result**: `2 passed, 2 warnings in 2.68s`

---

### Observed Warnings Log

When running `pytest tests/test_supabase_connection.py`, the following two deprecation warnings are output during the test `test_supabase_connection_reachability`:

```text
============================== warnings summary ===============================
tests/test_supabase_connection.py::test_supabase_connection_reachability
  supabase/_sync/client.py:264: DeprecationWarning: The 'timeout' parameter is deprecated. Please configure it in the http client instead.
    return SyncStorageClient(

tests/test_supabase_connection.py::test_supabase_connection_reachability
  supabase/_sync/client.py:264: DeprecationWarning: The 'verify' parameter is deprecated. Please configure it in the http client instead.
    return SyncStorageClient(
```

---

### Root Cause Analysis

1. **Origin**:
   - The warnings originate directly inside the installed third-party library `supabase` (specifically in `supabase._sync.client.Client.storage` at line 264 calling `SyncStorageClient`).
   - When `client.storage` is accessed, the `supabase` client passes default `timeout` and `verify` arguments into the underlying `storage3` / `httpx` client.
   
2. **Not in Application Code**:
   - Our test and backend code only invoke the public API method (`client.storage.list_buckets()`).
   - No custom or deprecated parameters are being passed by our application or test files.

---

### Why No Code Changes Are Required Now

- **Functionality Intact**: The warnings are standard Python `DeprecationWarning` notices emitted by the library's internal deprecation decorators. All HTTP requests, authentication, and responses succeed completely.
- **Upstream Maintenance**: This is an internal parameter forwarding deprecation within `supabase-py` and `storage3`. Future releases of `supabase` will refactor how client options are passed into `SyncStorageClient`.
- **Avoiding Hacks**: Modifying working, standard application code or monkey-patching third-party libraries for purely upstream deprecation notices adds unnecessary complexity and fragility.

---

### Conclusion & Action Plan

- **Conclusion**: The connection test passes with exit code `0`. The warnings are safe, expected, and non-blocking.
- **Action for Future Updates**: When updating `requirements.txt` to newer releases of `supabase-py`, verify if the upstream library has transitioned its internal storage client instantiation to resolve these warnings.
