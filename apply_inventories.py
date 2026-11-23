"""Installs the weapon-inventory add-on. Run from the project root after unzipping the add-on over the project:  python apply_inventories.py
Safe to run twice. Then run:  python manage.py migrate  and  python manage.py test apps.inventories"""
import pathlib
import sys

root = pathlib.Path(".")
fe, be = root / "frontend/src", root / "backend/config"
if not (be / "api_v1.py").exists() or not (root / "backend/apps/inventories/views.py").exists() or not (fe / "pages/Inventories.tsx").exists():
    sys.exit("Run this from the project root, after unzipping the add-on over the project.")


def patch(path, old, new, marker):
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    assert old in text, f"could not find the place to edit in {path}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


patch(be / "settings.py", '    "apps.integrations",\n', '    "apps.integrations",\n    "apps.inventories",\n', '"apps.inventories"')
patch(be / "api_v1.py", "from apps.integrations.views import", "from apps.inventories.views import InventoryViewSet\nfrom apps.integrations.views import", "InventoryViewSet")
patch(be / "api_v1.py", 'router.register("integrations/clients", IntegrationClientViewSet, basename="integration-client")\n',
      'router.register("integrations/clients", IntegrationClientViewSet, basename="integration-client")\nrouter.register("inventories", InventoryViewSet, basename="inventory")\n', 'register("inventories"')
patch(fe / "App.tsx", 'import { Weapons } from "./pages/Weapons";\n', 'import { Weapons } from "./pages/Weapons";\nimport { Inventories } from "./pages/Inventories";\n', "pages/Inventories")
patch(fe / "App.tsx", '        <Route path="weapons" element={<Weapons />} />\n', '        <Route path="weapons" element={<Weapons />} />\n        <Route path="inventories" element={<Inventories />} />\n', 'path="inventories"')
patch(fe / "components/Layout.tsx", '"/weapons", "/vehicles"', '"/weapons", "/inventories", "/vehicles"', '"/inventories"')
patch(fe / "components/Layout.tsx", '    { to: "/weapons", icon: "lock", label: "nav.weapons", show: can("weapons.view") },\n',
      '    { to: "/weapons", icon: "lock", label: "nav.weapons", show: can("weapons.view") },\n    { to: "/inventories", icon: "check", label: "nav.inventories", show: can("weapons.view") },\n', "nav.inventories")
patch(fe / "i18n/en.ts", '  "nav.weapons": "Weapon register",\n', '  "nav.weapons": "Weapon register",\n  "nav.inventories": "Weapon inventory",\n', "nav.inventories")
patch(fe / "i18n/so.ts", '  "nav.weapons": "Diiwaanka hubka",\n', '  "nav.weapons": "Diiwaanka hubka",\n  "nav.inventories": "Tirinta hubka",\n', "nav.inventories")
print("Weapon inventory installed. Next: python manage.py migrate, then python manage.py test apps.inventories")
