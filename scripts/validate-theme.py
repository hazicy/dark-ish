#!/usr/bin/env python3
"""Validate Dark-ish without dependencies; optionally check official reference Markdown."""

import argparse
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = set("namespace class enum interface struct typeParameter type parameter variable "
            "property enumMember decorator event function method macro label comment string "
            "keyword number regexp operator".split())
MODIFIERS = set("declaration definition readonly static deprecated abstract async "
                "modification documentation defaultLibrary".split())
HEX = re.compile(r"#[\da-fA-F]{6}(?:[\da-fA-F]{2})?")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def luminance(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


def validate(args):
    manifest = read_json(ROOT / "package.json")
    icon = ROOT / manifest["icon"]
    assert icon.suffix.lower() == ".png", "Marketplace icon must use the PNG export"
    icon_data = icon.read_bytes()
    assert icon_data[:8] == b"\x89PNG\r\n\x1a\n" and icon_data[12:16] == b"IHDR", "Invalid PNG icon"
    width, height = struct.unpack(">II", icon_data[16:24])
    assert width == height and width >= 256, "Marketplace icon must be square and at least 256px"
    theme_path = ROOT / manifest["contributes"]["themes"][0]["path"]
    theme = read_json(theme_path)
    colors, semantic = theme["colors"], theme["semanticTokenColors"]
    assert theme["$schema"] == "vscode://schemas/color-theme"
    assert theme["type"] == "dark" and theme["semanticHighlighting"] is True
    assert "contrastBorder" not in colors, "Reserve global contrast borders for high contrast themes"
    island_surfaces = ("sideBar.background", "activityBar.background", "panel.background",
                       "editorGroupHeader.tabsBackground", "tab.inactiveBackground",
                       "surface.background", "modernActivityBar.background", "notebook.editorBackground")
    assert all(colors[key] == colors["editor.background"] for key in island_surfaces), "Content island surfaces must match"
    frame_surfaces = ("modernUI.shellBackground", "modernUI.inactiveShellBackground", "titleBar.activeBackground",
                      "titleBar.inactiveBackground", "statusBar.background", "statusBar.noFolderBackground")
    assert len({colors[key] for key in frame_surfaces}) == 1, "Window frame surfaces must match"
    assert luminance(colors[frame_surfaces[0]]) < luminance(colors["editor.background"]), "Window frame must be darker than content islands"
    for key, value in colors.items():
        assert isinstance(value, str) and HEX.fullmatch(value), f"Invalid color: {key}"

    base_types = {key for key in semantic if "." not in key and ":" not in key}
    assert base_types == TYPES, f"Missing/extra standard types: {base_types ^ TYPES}"
    for selector, value in semantic.items():
        assert re.fullmatch(r"(?:\*|[\w]+)(?:\.[\w]+)*(?::[\w+-]+)?", selector), selector
        parts = selector.split(":")[0].split(".")
        assert parts[0] in TYPES | {"*"}, selector
        assert set(parts[1:]) <= MODIFIERS, selector
        settings = {"foreground": value} if isinstance(value, str) else value
        assert set(settings) <= {"foreground", "bold", "italic", "underline", "strikethrough"}, selector
        if "foreground" in settings:
            assert re.fullmatch(r"#[\da-fA-F]{6}", settings["foreground"]), selector
        for key in set(settings) - {"foreground"}:
            assert isinstance(settings[key], bool), selector

    syntax_ratios = []
    for rule in theme["tokenColors"]:
        scopes = rule["scope"]
        assert scopes and (isinstance(scopes, str) or all(isinstance(s, str) for s in scopes))
        settings = rule["settings"]
        assert set(settings) <= {"foreground", "background", "fontStyle"}, rule["name"]
        assert set(settings.get("fontStyle", "").split()) <= {"italic", "bold", "underline", "strikethrough"}
        if "foreground" in settings:
            assert re.fullmatch(r"#[\da-fA-F]{6}", settings["foreground"]), rule["name"]
            ratio = contrast(settings["foreground"], colors["editor.background"])
            assert ratio >= 4.5, f"Low syntax contrast: {rule['name']} ({ratio:.2f})"
            syntax_ratios.append(ratio)
    for selector, value in semantic.items():
        foreground = value if isinstance(value, str) else value.get("foreground")
        if foreground:
            assert contrast(foreground, colors["editor.background"]) >= 4.5, selector

    # Tokenization switches must preserve the same visual roles.
    textmate = {rule["name"]: rule["settings"] for rule in theme["tokenColors"]}
    for rule_name, selector in {
        "Functions": "function", "Types": "type", "Properties": "property",
        "Variables": "variable", "Function parameters": "parameter", "Keywords": "keyword",
        "Comments": "comment", "Documentation comments": "comment.documentation",
        "Strings": "string", "Numbers and constants": "number", "Regular expressions": "regexp",
        "Readonly bindings": "variable.readonly", "Enum members": "enumMember",
    }.items():
        value = semantic[selector]
        foreground = value if isinstance(value, str) else value["foreground"]
        assert textmate[rule_name]["foreground"] == foreground, f"TextMate/semantic mismatch: {selector}"
    for icon in ("property", "field", "key"):
        assert colors[f"symbolIcon.{icon}Foreground"] == semantic["property"], icon

    text_pairs = [
        ("editor.foreground", "editor.background"),
        ("sideBar.foreground", "sideBar.background"),
        ("input.foreground", "input.background"),
        ("input.placeholderForeground", "input.background"),
        ("editorInlayHint.foreground", "editorInlayHint.background"),
        ("editorCodeLens.foreground", "editor.background"),
        ("editorGhostText.foreground", "editor.background"),
        ("button.foreground", "button.background"),
        ("button.foreground", "button.hoverBackground"),
        ("button.secondaryForeground", "button.secondaryBackground"),
        ("button.secondaryForeground", "button.secondaryHoverBackground"),
        ("statusBar.foreground", "statusBar.background"),
        ("statusBar.debuggingForeground", "statusBar.debuggingBackground"),
        ("statusBarItem.remoteForeground", "statusBarItem.remoteBackground"),
        ("statusBarItem.errorForeground", "statusBarItem.errorBackground"),
        ("statusBarItem.warningForeground", "statusBarItem.warningBackground"),
        ("list.activeSelectionForeground", "list.activeSelectionBackground"),
        ("list.inactiveSelectionForeground", "list.inactiveSelectionBackground"),
        ("list.focusForeground", "list.focusBackground"),
        ("menu.selectionForeground", "menu.selectionBackground"),
        ("editorSuggestWidget.selectedForeground", "editorSuggestWidget.selectedBackground"),
        ("quickInputList.focusForeground", "quickInputList.focusBackground"),
        ("peekViewResult.selectionForeground", "peekViewResult.selectionBackground"),
    ]
    for fg, bg in text_pairs:
        assert contrast(colors[fg], colors[bg]) >= 4.5, f"Low UI text contrast: {fg} on {bg}"
    for bg in ("editor.background", "input.background", "list.focusBackground"):
        assert contrast(colors["focusBorder"], colors[bg]) >= 3, f"Low focus contrast: {bg}"

    for role, keys in {
        "warning": ["editorWarning.foreground", "list.warningForeground", "problemsWarningIcon.foreground",
                    "notificationsWarningIcon.foreground", "editorOverviewRuler.warningForeground",
                    "minimap.warningHighlight", "inputValidation.warningBorder", "statusBarItem.warningBackground"],
        "error": ["editorError.foreground", "list.errorForeground", "problemsErrorIcon.foreground",
                  "notificationsErrorIcon.foreground", "editorOverviewRuler.errorForeground", "minimap.errorHighlight"],
        "info": ["editorInfo.foreground", "problemsInfoIcon.foreground", "notificationsInfoIcon.foreground",
                 "editorOverviewRuler.infoForeground", "minimap.infoHighlight"],
        "modified": ["gitDecoration.modifiedResourceForeground", "editorGutter.modifiedBackground",
                     "editorOverviewRuler.modifiedForeground", "gitDecoration.stageModifiedResourceForeground"],
    }.items():
        assert len({colors[key] for key in keys}) == 1, f"Inconsistent {role} role"

    # These official definitions require translucent overlays to preserve other decorations.
    for key in ("editor.selectionHighlightBackground", "editor.wordHighlightBackground",
                "editor.wordHighlightStrongBackground", "editor.wordHighlightTextBackground",
                "editor.findMatchHighlightBackground", "diffEditor.insertedTextBackground",
                "diffEditor.removedTextBackground", "diffEditor.insertedLineBackground",
                "diffEditor.removedLineBackground", "merge.currentContentBackground",
                "merge.incomingContentBackground", "merge.commonContentBackground",
                "commandCenter.debuggingBackground", "chat.linesAddedForeground",
                "chat.linesRemovedForeground"):
        assert len(colors[key]) == 9 and 0 < int(colors[key][-2:], 16) < 255, key

    # Validate extension entry points and bundled icon font paths as well.
    for entry in manifest["contributes"]["productIconThemes"]:
        icon_path = ROOT / entry["path"]
        icons = read_json(icon_path)
        font_ids = {font["id"] for font in icons["fonts"]}
        for font in icons["fonts"]:
            for src in font["src"]:
                assert (icon_path.parent / src["path"]).is_file(), src["path"]
        for definition in icons["iconDefinitions"].values():
            assert definition["fontId"] in font_ids
            assert re.fullmatch(r"\\[\da-fA-F]+", definition["fontCharacter"])

    if args.colors_reference:
        documented = set(re.findall(r"`([\w.-]+)`\s*:", args.colors_reference.read_text()))
        assert len(documented) > 500, "Incomplete official color reference"
        assert not set(colors) - documented, f"Undocumented colors: {set(colors) - documented}"
        print(f"Official color reference: {len(colors)}/{len(colors)} keys recognized")
    if args.semantic_reference:
        source = args.semantic_reference.read_text()
        types_section = source.split("Standard token types:", 1)[1].split("Standard token modifiers:", 1)
        types = set(re.findall(r"\|\s*`(\w+)`", types_section[0]))
        modifiers = set(re.findall(r"\|\s*`(\w+)`", types_section[1].split("### Custom token", 1)[0]))
        assert types == TYPES and modifiers == MODIFIERS, "Official semantic definitions changed"
        print(f"Official semantic reference: {len(types)} types, {len(modifiers)} modifiers")
    print(f"PASS: {len(colors)} UI colors; {len(theme['tokenColors'])} TextMate rules; "
          f"{len(TYPES)}/{len(TYPES)} semantic types; {len(semantic)} selectors")
    print(f"PASS: {len(text_pairs)} UI text pairs >= 4.5:1; focus pairs >= 3:1; "
          f"minimum syntax foreground contrast {min(syntax_ratios):.2f}:1")
    print("Scope: static validation only; overlays, language grammars and runtime UI need visual inspection.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--colors-reference", type=Path, help="Official theme-color.md download")
    parser.add_argument("--semantic-reference", type=Path, help="Official semantic-highlight-guide.md download")
    validate(parser.parse_args())
