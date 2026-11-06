"""Quick Parameters - Fusion add-in.

Non-modal palette to view and edit user and model parameters, add and delete
user parameters. Opened from a button in SOLID > MODIFY.
"""
import adsk.core
import adsk.fusion

app = adsk.core.Application.get()
ui = app.userInterface

PALETTE_ID = "NonModalParamPalette"
CMD_ID = "NonModalParamShowCmd"
# Panneaux existants (on ne crée jamais de panneau) : SOLIDE > MODIFIER, sinon panneau Compléments
PANEL_IDS = ["SolidModifyPanel", "SolidScriptsAddinsPanel"]

# Langues proposées (les plus courantes) ; "auto" suit la langue de Fusion
LANGS = ['en', 'fr', 'de', 'es', 'it', 'pt', 'ja', 'zh']

# Textes côté Python : libellé du bouton / titre de palette, et infobulle.
# Les messages de la palette sont traduits dans index.html.
TXT = {
    'en': ('Quick Parameters', 'Show the palette to view, edit, add and delete parameters'),
    'fr': ('Paramètres rapides', 'Afficher la palette pour consulter, modifier, ajouter et supprimer les paramètres'),
    'de': ('Schnellparameter', 'Palette zum Anzeigen, Bearbeiten, Hinzufügen und Löschen von Parametern öffnen'),
    'es': ('Parámetros rápidos', 'Mostrar la paleta para ver, editar, añadir y eliminar parámetros'),
    'it': ('Parametri rapidi', 'Mostra la palette per visualizzare, modificare, aggiungere ed eliminare i parametri'),
    'pt': ('Parâmetros rápidos', 'Mostrar a paleta para ver, editar, adicionar e excluir parâmetros'),
    'ja': ('クイックパラメータ', 'パラメータの表示・編集・追加・削除を行うパレットを表示'),
    'zh': ('快速参数', '显示用于查看、编辑、添加和删除参数的面板'),
}

# Noms possibles de l'énumération adsk.core.UserLanguages selon les versions de l'API
FUSION_LANG_NAMES = {
    'fr': ['FrenchLanguage'],
    'de': ['GermanLanguage'],
    'es': ['SpanishLanguage'],
    'it': ['ItalianLanguage'],
    'ja': ['JapaneseLanguage'],
    'pt': ['PortugueseBrazilianLanguage', 'BrazilianPortugueseLanguage', 'PortugueseLanguage'],
    'zh': ['ChinesePRCLanguage', 'ChineseSimplifiedLanguage', 'ChinesesSimplifiedLanguage'],
}

GENERIC_ERROR = 'Quick Parameters: an error occurred.'

# Garder les handlers en mémoire globale, sinon ils sont détruits par le garbage collector
global_handlers = []
doc_handler = None
workspace_handler = None
palette_ready = False


# ---------------------------------------------------------------- Utilitaires

def fusion_lang():
    try:
        current = app.preferences.generalPreferences.userLanguage
        for code, names in FUSION_LANG_NAMES.items():
            for name in names:
                value = getattr(adsk.core.UserLanguages, name, None)
                if value is not None and current == value:
                    return code
    except:
        pass
    return 'en'


def ui_theme():
    """Thème de l'interface Fusion : classic, lightgray, darkblue, darkgray ou device."""
    try:
        prefs = app.preferences.generalPreferences
        try:
            theme = prefs.activeUserInterfaceTheme   # résout « thème de l'appareil » (API récente)
        except:
            theme = prefs.userInterfaceTheme
        themes = adsk.core.UserInterfaceThemes
        for name, code in (('ClassicUserInterfaceTheme', 'classic'),
                           ('LightGrayUserInterfaceTheme', 'lightgray'),
                           ('DarkBlueUserInterfaceTheme', 'darkblue'),
                           ('DarkGrayUserInterfaceTheme', 'darkgray'),
                           ('DeviceUserInterfaceTheme', 'device')):
            value = getattr(themes, name, None)
            if value is not None and theme == value:
                return code
    except:
        pass
    return 'darkgray'


def settings_path():
    import os
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    else:
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    return os.path.join(base, 'NonModalParameters', 'settings.json')


COLUMN_KEYS = ('name', 'unit', 'expr', 'val')


def load_settings():
    try:
        import json
        with open(settings_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except:
        return {}


def save_settings(update):
    try:
        import json
        import os
        data = load_settings()
        data.update(update)
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except:
        pass


def load_pref():
    value = load_settings().get('language', 'auto')
    return value if value in LANGS else 'auto'


def save_pref(value):
    if value == 'auto' or value in LANGS:
        save_settings({'language': value})


def clean_columns(raw):
    """Ne garde que les colonnes connues, avec une largeur numérique raisonnable."""
    cols = {}
    if isinstance(raw, dict):
        for key in COLUMN_KEYS:
            value = raw.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cols[key] = int(max(30, min(700, value)))
    return cols


def load_columns():
    return clean_columns(load_settings().get('columns'))


def save_columns(raw):
    merged = load_columns()
    merged.update(clean_columns(raw))
    save_settings({'columns': merged})


def current_lang():
    pref = load_pref()
    return pref if pref in LANGS else fusion_lang()


def T(key):
    name, tip = TXT[current_lang()]
    return {'cmd_name': name, 'palette_title': name, 'cmd_tip': tip}[key]


def alert(message):
    if ui:
        ui.messageBox(message)


def format_exc():
    import traceback
    return traceback.format_exc()


def last_error(default):
    try:
        msg = app.getLastError()[1]
        if msg:
            return msg
    except:
        pass
    return default


def get_design():
    return adsk.fusion.Design.cast(app.activeProduct)


# ---------------------------------------------------------------- Données

def fmt_value(param, units):
    try:
        return units.formatInternalValue(param.value, param.unit, True)
    except:
        try:
            return str(param.value)
        except:
            return ''


def param_info(param, units, is_model=False):
    info = {
        'name': param.name,
        'expression': param.expression,
        'value': fmt_value(param, units),
        'unit': param.unit or '',
        'comment': param.comment or '',
        'kind': 'model' if is_model else 'user',
        'favorite': False,
        'role': '',
        'creator': '',
    }
    try:
        info['favorite'] = bool(param.isFavorite)
    except:
        pass
    if is_model:
        try:
            mp = adsk.fusion.ModelParameter.cast(param)
            if mp:
                info['role'] = mp.role or ''
                info['creator'] = getattr(mp.createdBy, 'name', '') or ''
        except:
            pass
    return info


def collect_params(design):
    units = design.fusionUnitsManager
    items = []
    user_names = set()

    for p in design.userParameters:
        user_names.add(p.name)
        items.append(param_info(p, units))

    for p in design.allParameters:
        if p.name not in user_names:
            items.append(param_info(p, units, True))

    default_unit = 'mm'
    try:
        default_unit = units.defaultLengthUnits or 'mm'
    except:
        pass

    return {'items': items, 'fusionLang': fusion_lang(), 'langPref': load_pref(),
            'defaultUnit': default_unit, 'theme': ui_theme(),
            'columns': load_columns()}


def send_params(palette=None):
    import json
    palette = palette or ui.palettes.itemById(PALETTE_ID)
    if not palette:
        return
    design = get_design()
    if design:
        data = collect_params(design)
    else:
        data = {'items': [], 'fusionLang': fusion_lang(), 'langPref': load_pref(),
                'defaultUnit': 'mm', 'theme': ui_theme(), 'columns': load_columns()}
    palette.sendInfoToHTML('updateList', json.dumps(data))


# ---------------------------------------------------------------- HTML -> Python

# Mots reconnus dans une formule (fonctions et unités courantes). Sert uniquement à
# expliquer une erreur après un refus de Fusion, jamais à valider une formule.
KNOWN_WORDS = set((
    "sin cos tan asin acos atan atan2 sinh cosh tanh asinh acosh atanh sqrt cbrt pow exp "
    "log ln log10 abs min max floor ceil round sign pi e "
    "mm cm m km in ft yd mil deg rad ul degree degrees radian radians inch foot feet "
    "meter metre millimeter centimeter kg g lb oz s sec"
).split())


def explain_expression(design, own_name, expression):
    """Diagnostique une formule refusée par Fusion et renvoie un code d'erreur explicite."""
    import re
    expr = (expression or '').strip()
    if not expr:
        return {'error': 'e_empty'}
    if expr.count('(') != expr.count(')'):
        return {'error': 'e_parens'}

    stripped = re.sub(r'(?<!\w)\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?', ' ', expr)
    words = re.findall(r'[^\W\d]\w*', stripped)
    if own_name and own_name in words:
        return {'error': 'e_self'}

    known = set()
    try:
        known = set(p.name for p in design.allParameters)
    except:
        pass
    unknown = []
    for word in words:
        if word in known or word.lower() in KNOWN_WORDS or word in unknown:
            continue
        unknown.append(word)
    if unknown:
        return {'error': 'e_unknown', 'args': {'names': ', '.join(unknown)}}
    return {'error': 'e_formula'}


def formula_failure(design, name, field, own_name, expression):
    result = {'name': name, 'field': field, 'ok': False}
    result.update(explain_expression(design, own_name, expression))
    raw = last_error('')
    if raw:
        result['fusion'] = raw
    return result


def find_param(design, name):
    return design.allParameters.itemByName(name) if design else None


def handle_modify(design, info):
    name = info['name']
    result = {'name': name, 'field': 'expression', 'ok': False, 'error': 'e_no_design'}
    if design:
        param = find_param(design, name)
        if not param:
            result['error'] = 'e_not_found'
        else:
            try:
                param.expression = info['value']
                result = {'name': name, 'field': 'expression', 'ok': True}
            except:
                result = formula_failure(design, name, 'expression', name, info['value'])
    return result


def handle_comment(design, info):
    name = info['name']
    result = {'name': name, 'field': 'comment', 'ok': False, 'error': 'e_no_design'}
    if design:
        param = find_param(design, name)
        if not param:
            result['error'] = 'e_not_found'
        else:
            try:
                param.comment = info.get('comment') or ''
                result = {'name': name, 'field': 'comment', 'ok': True}
            except:
                result['error'] = last_error('e_formula')
    return result


def handle_favorite(design, info):
    name = info['name']
    result = {'name': name, 'field': 'favorite', 'ok': False, 'error': 'e_no_design'}
    if design:
        param = find_param(design, name)
        if not param:
            result['error'] = 'e_not_found'
        else:
            try:
                param.isFavorite = bool(info.get('value'))
                result = {'name': name, 'field': 'favorite', 'ok': True}
            except:
                result['error'] = last_error('e_formula')
    return result


def handle_add(design, info):
    import re
    name = (info.get('name') or '').strip()
    expression = (info.get('expression') or '').strip()
    unit = info.get('unit') or ''
    comment = info.get('comment') or ''
    result = {'name': name, 'ok': False, 'error': 'e_no_design'}
    if design:
        if not name or not expression:
            result['error'] = 'e_missing'
        elif not re.match(r'^[^\W\d]\w*$', name):
            result['error'] = 'e_name'
        elif design.allParameters.itemByName(name):
            result['error'] = 'e_exists'
        else:
            try:
                value = adsk.core.ValueInput.createByString(expression)
                param = design.userParameters.add(name, value, unit, comment)
                if info.get('favorite'):
                    try:
                        param.isFavorite = True
                    except:
                        pass
                result = {'name': name, 'ok': True}
            except:
                result = formula_failure(design, name, 'expression', name, expression)
    return result


def handle_delete(design, info):
    name = info.get('name') or ''
    result = {'name': name, 'ok': False, 'error': 'e_no_design'}
    if design:
        param = design.userParameters.itemByName(name)
        if not param:
            if design.allParameters.itemByName(name):
                result['error'] = 'e_not_user'
            else:
                result['error'] = 'e_not_found'
        else:
            deleted = False
            try:
                deleted = param.deleteMe()
            except:
                deleted = False
            if deleted:
                result = {'name': name, 'ok': True}
            else:
                result['error'] = 'e_in_use'
    return result


class HTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            import json
            html_args = adsk.core.HTMLEventArgs.cast(args)
            html_args.returnData = 'OK'

            palette = ui.palettes.itemById(PALETTE_ID)
            if not palette:
                return
            action = html_args.action
            design = get_design()

            if action == 'getParams':
                send_params(palette)
                return

            if action == 'setLanguage':
                save_pref(json.loads(html_args.data).get('lang'))
                send_params(palette)
                return

            if action == 'setColumns':
                save_columns(json.loads(html_args.data))
                return

            if action == 'modifyParam':
                result = handle_modify(design, json.loads(html_args.data))
                reply = 'paramResult'
            elif action == 'setComment':
                result = handle_comment(design, json.loads(html_args.data))
                reply = 'paramResult'
            elif action == 'setFavorite':
                result = handle_favorite(design, json.loads(html_args.data))
                reply = 'paramResult'
            elif action == 'addParam':
                result = handle_add(design, json.loads(html_args.data))
                reply = 'addResult'
            elif action == 'deleteParam':
                result = handle_delete(design, json.loads(html_args.data))
                reply = 'deleteResult'
            else:
                return

            palette.sendInfoToHTML(reply, json.dumps(result))
            if result.get('ok'):
                # Les valeurs dépendantes ont pu changer
                send_params(palette)
        except:
            alert(GENERIC_ERROR + '\n' + format_exc())


# ---------------------------------------------------------------- Palette (créée à la demande)

class DocActivatedHandler(adsk.core.DocumentEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            refresh_if_visible()
        except:
            pass


class WorkspaceActivatedHandler(adsk.core.WorkspaceEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            refresh_if_visible()
        except:
            pass


def refresh_if_visible():
    palette = ui.palettes.itemById(PALETTE_ID)
    if palette and palette.isVisible:
        send_params(palette)


def connect_app_events():
    global doc_handler, workspace_handler
    if not doc_handler:
        doc_handler = DocActivatedHandler()
        app.documentActivated.add(doc_handler)
    if not workspace_handler:
        workspace_handler = WorkspaceActivatedHandler()
        ui.workspaceActivated.add(workspace_handler)


def disconnect_app_events():
    global doc_handler, workspace_handler
    if doc_handler:
        app.documentActivated.remove(doc_handler)
        doc_handler = None
    if workspace_handler:
        ui.workspaceActivated.remove(workspace_handler)
        workspace_handler = None


def create_palette():
    global palette_ready
    import os
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
    html_url = html_path.replace('\\', '/')

    palette = ui.palettes.add(
        PALETTE_ID,
        T('palette_title'),
        html_url,
        True,   # isVisible
        True,   # showCloseButton
        True,   # isResizable
        420,    # width
        520     # height
    )
    palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight

    handler = HTMLEventHandler()
    palette.incomingFromHTML.add(handler)
    global_handlers.append(handler)
    palette_ready = True
    connect_app_events()
    return palette


def show_palette():
    palette = ui.palettes.itemById(PALETTE_ID)
    if palette and not palette_ready:
        # Palette héritée d'une session précédente, sans handler : on la recrée
        palette.deleteMe()
        palette = None
    if not palette:
        palette = create_palette()
    palette.isVisible = True
    send_params(palette)


# ---------------------------------------------------------------- Bouton de barre d'outils

class ShowCmdExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            show_palette()
        except:
            alert(GENERIC_ERROR + '\n' + format_exc())


class ShowCmdCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
            on_execute = ShowCmdExecuteHandler()
            cmd.execute.add(on_execute)
            global_handlers.append(on_execute)
        except:
            alert(GENERIC_ERROR + '\n' + format_exc())


def add_toolbar_button():
    old_def = ui.commandDefinitions.itemById(CMD_ID)
    if old_def:
        old_def.deleteMe()

    # Fusion attend un chemin relatif au dossier du complément
    cmd_def = None
    for icon_dir in ('./resources', 'resources', ''):
        try:
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                CMD_ID, T('cmd_name'), T('cmd_tip'), icon_dir)
            break
        except:
            continue
    if not cmd_def:
        raise RuntimeError('Could not create the toolbar command.')

    on_created = ShowCmdCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    global_handlers.append(on_created)

    for panel_id in PANEL_IDS:
        panel = ui.allToolbarPanels.itemById(panel_id)
        if panel:
            old_ctrl = panel.controls.itemById(CMD_ID)
            if old_ctrl:
                old_ctrl.deleteMe()
            ctrl = panel.controls.addCommand(cmd_def)
            ctrl.isPromoted = True          # visible directement dans la barre d'outils
            ctrl.isPromotedByDefault = True
            return


def remove_toolbar_button():
    for panel_id in PANEL_IDS:
        panel = ui.allToolbarPanels.itemById(panel_id)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        cmd_def.deleteMe()


# ---------------------------------------------------------------- Cycle de vie
# run() se limite à créer la commande : la palette n'est construite qu'au premier clic
# (consigne Autodesk : démarrage de l'add-in le plus léger possible).

def run(context):
    try:
        add_toolbar_button()
    except:
        alert(GENERIC_ERROR + '\n' + format_exc())


def stop(context):
    global palette_ready
    try:
        disconnect_app_events()
        remove_toolbar_button()
        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()
        palette_ready = False
        global_handlers.clear()
    except:
        alert(GENERIC_ERROR + '\n' + format_exc())
