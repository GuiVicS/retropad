"""Todo ícone Lucide usado nas páginas precisa existir no sprite local (senão o botão fica sem ícone)."""
import glob
import os
import re

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
PATTERNS = (
    r"lucide\.svg#([a-z0-9-]+)",            # <use href="/static/lucide.svg#nome">
    r"\bico\('([a-z0-9-]+)'",               # ico('nome') no index.html
    r"\bicon\('([a-z0-9-]+)'",              # icon('nome') no app.js
    r"\bnote\('[a-z]+',\s*'([a-z0-9-]+)'",  # note('ok', 'nome', ...) na fila de envio
    r"\bsym\('([a-z0-9-]+)'",
)


def sprite_ids():
    return set(re.findall(r'<symbol id="([^"]+)"', open(os.path.join(STATIC, "lucide.svg"), encoding="utf-8").read()))


def used_icons():
    used = {}
    for path in glob.glob(os.path.join(STATIC, "*.html")) + glob.glob(os.path.join(STATIC, "*.js")):
        text = open(path, encoding="utf-8").read()
        for rx in PATTERNS:
            for name in re.findall(rx, text):
                used.setdefault(name, set()).add(os.path.basename(path))
    return used


def test_every_icon_in_use_exists_in_the_sprite():
    have = sprite_ids()
    missing = {n: sorted(f) for n, f in used_icons().items() if n not in have}
    assert not missing, f"ícones usados mas ausentes de static/lucide.svg: {missing}"


def test_login_icon_for_the_connect_button():
    # O botão "Conectar" ficou sem ícone por causa de um "log-in" que não estava no sprite.
    assert "log-in" in sprite_ids()
    assert "lucide.svg#log-in" in open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()


def test_audit_actually_finds_icons():
    assert len(used_icons()) > 20          # protege o próprio teste contra regex que não acha nada
