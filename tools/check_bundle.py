#!/usr/bin/env python3
"""Vérifie statiquement un bundle Fusion avant soumission à l'Autodesk App Store.

Usage :  python tools/check_bundle.py NonModalParameters.bundle

Ce script contrôle ce qui peut l'être sans lancer Fusion (structure, cohérence des
fichiers, bonnes pratiques de démarrage). Il NE remplace PAS : la mesure du temps de
chargement dans Fusion, les tests sur une installation propre, ni la revue d'Autodesk.
"""
import ast
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

results = []  # (niveau, message)


def ok(msg): results.append(("OK", msg))
def warn(msg): results.append(("AVERTISSEMENT", msg))
def fail(msg): results.append(("ÉCHEC", msg))


GUID = re.compile(r"^\{[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}$")
UUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def check(bundle: Path):
    if not bundle.is_dir() or not bundle.name.endswith(".bundle"):
        fail("Le dossier racine doit se terminer par « .bundle ».")
        return
    ok(f"Dossier racine : {bundle.name}")

    # ---- PackageContents.xml
    pc = bundle / "PackageContents.xml"
    if not pc.is_file():
        fail("PackageContents.xml absent à la racine du bundle.")
        return
    try:
        root = ET.parse(pc).getroot()
    except ET.ParseError as e:
        fail(f"PackageContents.xml mal formé : {e}")
        return
    ok("PackageContents.xml est du XML valide.")

    if root.tag != "ApplicationPackage":
        fail("La racine de PackageContents.xml doit être <ApplicationPackage>.")
    for attr in ("Name", "AppVersion", "Description", "Author", "ProductCode", "UpgradeCode"):
        if not root.get(attr):
            fail(f"Attribut manquant sur <ApplicationPackage> : {attr}")
    if root.get("AutodeskProduct") != "Fusion360":
        warn(f"AutodeskProduct = « {root.get('AutodeskProduct')} » (attendu : Fusion360).")
    for attr in ("ProductCode", "UpgradeCode"):
        v = root.get(attr, "")
        if v and not GUID.match(v):
            fail(f"{attr} n'est pas un GUID entre accolades : {v}")
    app_version = root.get("AppVersion", "")
    if app_version and not SEMVER.match(app_version):
        fail(f"AppVersion doit être de la forme X.Y.Z : {app_version}")

    company = root.find("CompanyDetails")
    if company is None:
        warn("<CompanyDetails> absent.")
    else:
        for attr in ("Name", "Email"):
            v = company.get(attr, "")
            if not v or v.upper() == "TODO":
                warn(f"CompanyDetails/{attr} à renseigner avant la soumission.")
        if company.get("Url", "").upper() == "TODO":
            warn("CompanyDetails/Url vaut « TODO » : renseignez-la, laissez-la vide ou supprimez l'attribut.")

    entries = root.findall("./Components/ComponentEntry")
    if not entries:
        fail("Aucun <ComponentEntry> dans <Components>.")
        return
    if root.find("./Components/RuntimeRequirements") is None:
        fail("<RuntimeRequirements> absent dans <Components>.")

    for entry in entries:
        module = entry.get("ModuleName", "")
        target = (bundle / module).resolve() if module else None
        if not module or not target.is_file():
            fail(f"ModuleName introuvable : {module or '(vide)'}")
            continue
        ok(f"ModuleName trouvé : {module}")
        if not module.endswith(".manifest"):
            fail("ModuleName d'un add-in Fusion doit pointer vers le fichier .manifest.")
        if entry.get("Version") != app_version:
            warn(f"ComponentEntry/Version ({entry.get('Version')}) ≠ AppVersion ({app_version}).")
        check_addin(target, app_version)


def check_addin(manifest_path: Path, app_version: str):
    folder = manifest_path.parent
    stem = manifest_path.stem

    # ---- cohérence des noms
    if folder.name != stem:
        fail(f"Le dossier ({folder.name}) doit porter le même nom que le manifeste ({stem}).")
    py = folder / f"{stem}.py"
    if not py.is_file():
        fail(f"{stem}.py absent à côté du manifeste.")
    else:
        ok("Dossier, .py et .manifest portent le même nom.")

    # ---- manifeste
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Manifeste JSON invalide : {e}")
        return
    for key in ("autodeskProduct", "type", "id", "author", "description", "version",
                "runOnStartup", "supportedOS", "editEnabled"):
        if key not in m:
            fail(f"Clé manquante dans le manifeste : {key}")
    if m.get("type") != "addin":
        fail("Le champ « type » du manifeste doit valoir « addin ».")
    if m.get("autodeskProduct") != "Fusion":
        fail("Le champ « autodeskProduct » du manifeste doit valoir « Fusion ».")
    if m.get("id") and not UUID.match(m["id"]):
        fail("Le champ « id » du manifeste doit être un UUID.")
    if m.get("version") != app_version:
        fail(f"Version du manifeste ({m.get('version')}) ≠ AppVersion ({app_version}).")
    else:
        ok(f"Version cohérente partout : {app_version}")
    # Cohérence des systèmes d'exploitation entre manifeste et PackageContents.xml
    pc_root = ET.parse(manifest_path.parents[2] / "PackageContents.xml").getroot()
    req = pc_root.find("./Components/RuntimeRequirements")
    pc_mac = req is not None and "mac" in (req.get("OS") or "").lower()
    pc_win = req is not None and "win" in (req.get("OS") or "").lower()
    man_os = (m.get("supportedOS") or "").lower()
    man_mac, man_win = "mac" in man_os, "windows" in man_os
    if (pc_mac, pc_win) != (man_mac, man_win):
        fail(f"Systèmes incohérents : PackageContents OS={req.get('OS') if req is not None else None} "
             f"/ manifeste supportedOS={m.get('supportedOS')}.")
    else:
        ok("Systèmes pris en charge : " + ("Windows" if pc_win else "") + (" + macOS" if pc_mac else "")
           + " (identique dans PackageContents.xml et le manifeste).")
    if m.get("editEnabled") is True:
        warn("editEnabled = true : mettez false pour une version publiée.")
    if m.get("runOnStartup") is not True:
        warn("runOnStartup n'est pas true : le bouton n'apparaîtra qu'après un démarrage manuel.")

    # ---- script Python
    if py.is_file():
        check_python(py)

    # ---- HTML
    html = folder / "index.html"
    if html.is_file():
        check_html(html)
    else:
        warn("index.html absent (normal seulement si l'add-in n'a pas de palette).")

    # ---- icônes
    check_icons(folder / "resources")

    # ---- résidus de développement
    for junk in list(folder.rglob("__pycache__")) + list(folder.rglob(".DS_Store")) + list(folder.rglob("*.pyc")):
        fail(f"Fichier de développement à supprimer : {junk.relative_to(folder.parent.parent.parent)}")


def check_python(py: Path):
    src = py.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        fail(f"Erreur de syntaxe Python : {e}")
        return
    ok("Le script Python se compile.")

    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("run", "stop"):
        if name not in funcs:
            fail(f"Fonction {name}(context) absente.")

    # Imports de premier niveau : uniquement adsk
    for node in tree.body:
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        for mod in mods:
            if not mod.startswith("adsk"):
                warn(f"Import de premier niveau « {mod} » : à différer dans les fonctions pour un démarrage plus rapide.")

    # run() doit rester léger : pas de création de palette ni de lecture de fichier
    if "run" in funcs:
        run_src = ast.get_source_segment(src, funcs["run"]) or ""
        called = {n.func.id for n in ast.walk(funcs["run"])
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        heavy = [w for w in ("create_palette", "show_palette", "send_params", "open") if w in called]
        if heavy or "palettes.add" in run_src:
            fail(f"run() fait un travail lourd au démarrage : {', '.join(heavy) or 'palettes.add'}.")
        else:
            ok("run() se limite à la création de la commande (démarrage léger).")

    # Panneaux : jamais de nouveau panneau ni nouvel onglet
    if re.search(r"toolbarPanels\.add\(|toolbarTabs\.add\(", src):
        fail("Création d'un panneau/onglet de barre d'outils : utilisez un panneau existant.")
    else:
        ok("Aucun panneau ni onglet créé (utilise des panneaux existants).")

    # Pratiques à risque
    risky = {
        r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b": "exécution de commandes système",
        r"\burllib\b|\brequests\b|\bsocket\b|\bhttp\.client\b": "accès réseau",
        r"\beval\(|\bexec\(": "eval/exec",
        r"\bprint\(": "print() de débogage",
        r"[A-Za-z]:\\\\Users|[A-Za-z]:/Users|/Users/": "chemin absolu propre à une machine",
    }
    for pattern, label in risky.items():
        if re.search(pattern, src):
            fail(f"Script Python : {label} détecté.")
    ok("Pas de réseau, d'exécution système, d'eval ni de chemin en dur.")

    if "__file__" not in src:
        warn("Le chemin du HTML ne semble pas dérivé de __file__.")


def check_html(html: Path):
    src = html.read_text(encoding="utf-8")
    remote = re.findall(r"""(?:src|href)\s*=\s*["']https?://[^"']+""", src) + \
             re.findall(r"""url\(\s*["']?https?://""", src) + \
             re.findall(r"""fetch\(\s*["']https?://""", src)
    if remote:
        fail(f"Ressource distante dans index.html ({len(remote)}) : l'add-in doit fonctionner hors ligne.")
    else:
        ok("index.html ne charge aucune ressource distante.")
    if "fusionJavaScriptHandler" not in src:
        fail("index.html n'implémente pas window.fusionJavaScriptHandler (réception Python -> HTML).")
    if "fusionSendData" not in src:
        fail("index.html n'appelle pas adsk.fusionSendData (envoi HTML -> Python).")
    if re.search(r"\b(alert|confirm|prompt)\(", src):
        warn("alert/confirm/prompt peuvent ne pas fonctionner dans une palette Fusion.")
    if re.search(r"localStorage|sessionStorage", src):
        warn("Stockage navigateur utilisé : non persistant de façon fiable dans une palette.")
    if "TODO" in src:
        warn("Marqueur TODO présent dans index.html.")


def check_icons(res: Path):
    if not res.is_dir():
        fail("Dossier resources/ absent (icônes du bouton).")
        return
    try:
        from PIL import Image
    except ImportError:
        Image = None
        warn("Pillow absent : dimensions des icônes non vérifiées.")
    for size in (16, 32):
        for suffix in ("", "-dark"):
            f = res / f"{size}x{size}{suffix}.png"
            if not f.is_file():
                fail(f"Icône manquante : {f.name}")
            elif Image:
                with Image.open(f) as im:
                    if im.size != (size, size):
                        fail(f"{f.name} fait {im.size[0]}x{im.size[1]} (attendu {size}x{size}).")
    if not any(r[0] == "ÉCHEC" and "Icône" in r[1] for r in results):
        ok("Icônes 16x16 et 32x32 présentes, thèmes clair et sombre.")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    check(Path(sys.argv[1]))

    order = {"ÉCHEC": 0, "AVERTISSEMENT": 1, "OK": 2}
    for level, msg in sorted(results, key=lambda r: order[r[0]]):
        print(f"[{level}] {msg}")
    n_fail = sum(1 for r in results if r[0] == "ÉCHEC")
    n_warn = sum(1 for r in results if r[0] == "AVERTISSEMENT")
    print(f"\n{len(results) - n_fail - n_warn} OK, {n_warn} avertissement(s), {n_fail} échec(s).")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
