"""
api/index.py

Vercel entry point. Vercel's Python runtime looks for a WSGI `app` here; we
simply re-export the Flask admin application. vercel.json rewrites every
route to this function, so "/" serves the page and "/api/..." the REST API.
"""

import os
import sys

# Make the project root importable (core/, data_access/, data_pipeline/, ...).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_app import app  # noqa: E402,F401  (Vercel picks up `app`)
