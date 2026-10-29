"""Edge nginx (docker/nginx/templates/cti.conf.template): hanya jalur API mesin yang ke `api`."""

import re
from pathlib import Path

TEMPLATE = Path(__file__).parents[2] / "docker/nginx/templates/cti.conf.template"


def _locations() -> dict[str, str]:
    """Peta `path location` -> isi blok (tanpa komentar); blok location tidak bersarang."""
    text = re.sub(r"#.*", "", TEMPLATE.read_text())
    return {
        m.group(1): m.group(2) for m in re.finditer(r"location\s+([^\s{]+)\s*\{([^}]*)\}", text)
    }


def test_nginx_exposes_only_machine_api_paths() -> None:
    to_api = {p for p, body in _locations().items() if "http://api:8000" in body}
    assert to_api == {"/taxii2/", "/api/v2/"}


def test_machine_api_locations_keep_forwarded_headers_and_dynamic_resolve() -> None:
    locs = _locations()
    for path in ("/taxii2/", "/api/v2/"):
        body = locs[path]
        # variabel + proxy_pass $var: nginx resolve ulang `api` (sama seperti `web`)
        assert "set $cti_api http://api:8000;" in body
        assert "proxy_pass $cti_api;" in body
        assert "X-Forwarded-For $proxy_add_x_forwarded_for" in body
        assert "Host $http_host" in body
        assert "X-Forwarded-Proto $scheme" in body
