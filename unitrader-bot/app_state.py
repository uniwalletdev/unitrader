"""
app_state.py — Lightweight module for shared application-level state.

Kept separate from main.py to avoid circular imports between the lifespan
startup code and routers that need to read this state (e.g. health checks).
"""

# Set to True once the background DB init task completes successfully.
db_init_complete: bool = False

# Set to True if all retry attempts in the background DB init task are exhausted.
db_init_failed: bool = False
