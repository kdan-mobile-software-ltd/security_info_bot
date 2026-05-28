# Error Handling

Source: `src/utils/errors.py`, `src/fetchers/twcert.py`, `src/analyzer/gemini.py`.

## Exception types

### `TwcertLoginError`

Raised by `src/fetchers/twcert.py` when the TWCERT portal login API returns a non-success `returnCode`.

Flow:
1. Login attempt fails → `send_ops_alert("TWCERT 登入失敗", ...)` → `raise TwcertLoginError`.
2. `main.py` catches it at the top level, logs the error, and calls `sys.exit(1)`.
3. The GitHub Actions workflow step fails, causing the run to be marked failed.

### `GeminiQuotaExhausted`

Raised by `src/analyzer/gemini.py:analyze_intel` after exhausting retries on a `429 RESOURCE_EXHAUSTED` error.

Flow:
1. Each `429` response triggers exponential backoff: `wait = 2 ** (attempt + 1)` seconds (2s, 4s, 8s for `max_retries=3`).
2. After the final attempt: `send_ops_alert(...)` → `raise GeminiQuotaExhausted`.
3. `main.py:stage_analyze` catches it mid-loop, logs a warning, and **breaks** — items analyzed so far are returned and proceed to Stage 3. Remaining items are skipped until the next run.
4. If `GeminiQuotaExhausted` propagates to the top level (raised outside `stage_analyze`), `main.py` catches it and exits with code 1.

### Server errors (5xx)

`src/analyzer/gemini.py` also retries on `500`/`503` with the same exponential backoff. After `max_retries` failures the exception propagates as-is; `main.py` catches it as an unhandled `Exception` and exits with code 1.

## `send_ops_alert`

```python
def send_ops_alert(title: str, detail: str) -> None:
    log.error("[OPS] %s — %s", title, detail)
```

Call sites:
- `src/fetchers/twcert.py` — login failure, fetch exception.
- `src/analyzer/gemini.py` — quota exhausted after final retry.

## Unhandled exceptions

`main.py` wraps the entire `run()` call:

```python
except TwcertLoginError:
    log.error("TWCERT login failed, ops alert already sent")
    sys.exit(1)
except GeminiQuotaExhausted:
    log.error("Gemini quota exhausted, partial results may have been written")
    sys.exit(1)
except Exception as e:
    log.error("Unexpected error: %s", e, exc_info=True)
    sys.exit(1)
```

Any unhandled exception exits with code 1, which fails the GitHub Actions step.
