import os

# Set before the base settings load so a developer's real backend/.env key never reaches tests.
os.environ["DJANGO_DEBUG"] = "true"
os.environ["TOMTOM_API_KEY"] = "test-key-not-real"

from config.settings import *  # noqa: E402, F403
