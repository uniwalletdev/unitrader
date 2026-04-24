# Tech Debt Log

Running list of known issues to clean up. Keep entries short and actionable.

## Active

### pytest hard-exit masks non-daemon thread leak on Windows
`tests/conftest.py` calls `os._exit()` in `pytest_sessionfinish` to avoid an
indefinite teardown hang on Windows. This bypasses stdout flush, so pytest's
`-ra` / traceback summary gets truncated — cost hours of debugging in
Phase B1 Session 2.

**Workaround:** set `UNITRADER_PYTEST_FORCE_EXIT=false` before running when
you need full traceback output.

**Root cause:** pytest teardown waits on a non-daemon thread started during
import. Likely candidates:
- `database.py` engine init / connection pool.
- A background scheduler started at module import somewhere (despite
  `UNITRADER_DISABLE_BACKGROUND_LOOPS` — that flag only suppresses loop
  startup, not threads that were already launched during import chains).

**Fix:** find the leaking thread (`threading.enumerate()` in a final
fixture), mark it `daemon=True` or shut it down explicitly in
`pytest_sessionfinish`. Then remove the `os._exit()` hammer.

Owner: TBD. Priority: medium (developer-experience; not user-facing).
