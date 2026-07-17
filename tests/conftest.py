"""Shared pytest configuration."""

import matplotlib

# Tests save figures without a display while library users keep their chosen backend.
matplotlib.use("Agg")
