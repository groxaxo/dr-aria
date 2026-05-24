#!/usr/bin/env python3
"""
Patch webrtcvad.py to work with modern setuptools (80+) where
pkg_resources is no longer a top-level module.
Run once after: uv pip install -r requirements.txt
"""
import sys, pathlib

site_pkgs = pathlib.Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
wvad = site_pkgs / "webrtcvad.py"
if not wvad.exists():
    print("webrtcvad.py not found, skipping"); sys.exit(0)

src = wvad.read_text()
if "try:" in src and "pkg_resources" in src and "except Exception" in src:
    print("webrtcvad.py already patched"); sys.exit(0)

patched = src.replace(
    "import pkg_resources\n\nimport _webrtcvad",
    "try:\n    import pkg_resources\n    _version = pkg_resources.get_distribution('webrtcvad').version\nexcept Exception:\n    _version = '2.0.10'\n\nimport _webrtcvad",
).replace(
    "__version__ = pkg_resources.get_distribution('webrtcvad').version",
    "__version__ = _version",
)
wvad.write_text(patched)
print(f"Patched {wvad}")
