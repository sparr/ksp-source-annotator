"""Merging documentation sources against a small set of symbols."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from ksp_source_annotator.apidocs import Symbol, Symbols, merge_docs
from ksp_source_annotator.apidocs.doc import STEPS
from ksp_source_annotator.apidocs.game import load_localization
from ksp_source_annotator.apidocs.symbols import canon_type, split_top
from ksp_source_annotator.apidocs.wiki import wiki_arg_types, wiki_args, wiki_templates, wiki_text


def symbol(
    id: str,
    kind: str,
    name: str,
    type: str = "",
    *,
    ptypes: list[str] | None = None,
    pnames: list[str] | None = None,
    loc: list[list[str]] | None = None,
) -> Symbol:
    """A symbols.json row; full is derived from the ID."""
    return {
        "id": id,
        "asm": "Assembly-CSharp",
        "kind": kind,
        "mkind": "Ordinary" if kind == "Method" else None,
        "name": name,
        "type": type,
        "full": id[2:].split("(")[0],
        "ptypes": ptypes,
        "pnames": pnames,
        "prefs": ["None"] * len(ptypes) if ptypes is not None else None,
        "tparams": 0 if kind == "Method" else None,
        "acc": "Public",
        "loc": loc,
    }


SYMBOLS = [
    symbol("T:Vessel", "NamedType", "Vessel"),
    symbol("M:Vessel.GetName", "Method", "GetName", "Vessel", ptypes=[], pnames=[]),
    symbol("M:Vessel.Load(System.Int32)", "Method", "Load", "Vessel", ptypes=["int"], pnames=["index"]),
    symbol("M:Vessel.Load(System.String)", "Method", "Load", "Vessel", ptypes=["string"], pnames=["name"]),
    symbol("F:Vessel.mass", "Field", "mass", "Vessel", loc=[["KSPField", "guiName", "#autoLOC_1"]]),
    symbol("F:Vessel.id", "Field", "id", "Vessel"),
]

DOXYGEN = """<?xml version='1.0' encoding='UTF-8'?>
<doxygen><compounddef id="class_vessel" kind="class">
  <compoundname>Vessel</compoundname>
  <briefdescription><para>A craft in R&D or in flight.</para></briefdescription>
  <sectiondef kind="public-func">
    <memberdef kind="function" id="class_vessel_load" static="no">
      <name>Load</name><argsstring>(int index)</argsstring>
      <param><type>int</type><declname>index</declname></param>
      <briefdescription><para>Loads by index. See <ref refid="class_vessel">Vessel</ref>.</para></briefdescription>
      <detaileddescription><para><parameterlist kind="param"><parameteritem>
        <parameternamelist><parametername>index</parametername></parameternamelist>
        <parameterdescription><para>Which one.</para></parameterdescription>
      </parameteritem></parameterlist></para></detaileddescription>
    </memberdef>
    <memberdef kind="function" id="class_vessel_gone" static="no">
      <name>Gone</name><argsstring>()</argsstring>
      <briefdescription><para>Removed since.</para></briefdescription>
    </memberdef>
  </sectiondef>
</compounddef></doxygen>
"""

ANATID = """<?xml version="1.0"?>
<doc><members>
  <member name="M:Vessel.Load(System.Int32)"><summary>Lower priority.</summary></member>
  <member name="M:Vessel.GetName(System.Boolean)"><summary>The name.</summary></member>
  <member name="M:Vessel.Load(System.String)"><summary>Loads by name.</summary></member>
</members></doc>
"""

WIKI = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page><title>API:Vessel</title><revision><timestamp>2020-05-06T00:00:00Z</timestamp>
    <text>{{Field|name=id|desc=The '''unique''' [[API:Guid|id]].}}
{{Field|name=mass|desc=Description goes here.}}</text></revision></page>
  <page><title>Tutorial</title><revision><timestamp>2020-05-06T00:00:00Z</timestamp>
    <text>{{Field|name=id|desc=Not an API page.}}</text></revision></page>
</mediawiki>
"""


def write_sources(tmp_path: Path) -> dict[str, Path]:
    """Write one small file per source and return merge_docs's keyword arguments."""
    official = tmp_path / "xml.zip"
    with zipfile.ZipFile(official, "w") as z:
        z.writestr("xml/class_vessel.xml", DOXYGEN)
    anatid = tmp_path / "anatid.xml"
    _ = anatid.write_text(ANATID)
    wiki = tmp_path / "wiki.xml"
    _ = wiki.write_text(WIKI)
    loc = tmp_path / "GameData" / "Squad" / "Localization"
    loc.mkdir(parents=True)
    _ = (loc / "dictionary.cfg").write_text(
        "Localization\n{\n\ten-us\n\t{\n\t\t#autoLOC_1 = Total Mass\n\t}\n}\n", encoding="utf-8-sig"
    )
    return {"official": official, "anatid": anatid, "wiki": wiki, "gamedata": tmp_path / "GameData"}


def test_merge_priority_and_output(tmp_path: Path) -> None:
    out = tmp_path / "out"
    report = merge_docs(Symbols(SYMBOLS), out, **write_sources(tmp_path))

    members = {m.get("name"): m for m in ET.parse(out / "Assembly-CSharp.xml").getroot().iter("member")}
    assert sorted(k for k in members if k) == sorted(s["id"] for s in SYMBOLS)

    def xml(sid: str) -> str:
        return "".join(ET.tostring(c, encoding="unicode") for c in members[sid])

    # The bare "&" in the Doxygen file is repaired and comes out escaped.
    assert xml("T:Vessel") == "<summary>A craft in R&amp;D or in flight.</summary>"
    # official wins over anatid; its cross-reference and parameter are converted.
    assert xml("M:Vessel.Load(System.Int32)") == (
        '<summary>Loads by index. See <see cref="T:Vessel" />.</summary><param name="index">Which one.</param>'
    )
    # An anatid ID with an outdated signature is remapped to the member of that name.
    assert "The name." in xml("M:Vessel.GetName")
    assert "Loads by name." in xml("M:Vessel.Load(System.String)")
    assert xml("F:Vessel.id").startswith("<summary>The unique id.</summary>")
    assert "last edited 2020-05-06" in xml("F:Vessel.id")
    # The wiki placeholder is ignored, so the game's label is what documents mass.
    assert xml("F:Vessel.mass").startswith("<summary>In-game label: Total Mass</summary>")

    assert report.stats["anatid: already documented by a higher-priority source"] == 1
    assert report.stats["anatid: entries remapped to a moved or changed symbol"] == 1
    assert report.stats["output: Assembly-CSharp.xml entries"] == len(SYMBOLS)
    assert report.unmatched == [("official", "type exists, no member with this name", "Vessel.Gone()")]
    assert (out / "UNMATCHED.txt").read_text() == ("official\ttype exists, no member with this name\tVessel.Gone()\n")
    assert (out / "REPORT.txt").read_text() == report.format() + "\n"
    groups = [line.split(None, 1)[1].split(":")[0] for line in report.format().splitlines()]
    assert list(dict.fromkeys(groups)) == ["official", "anatid", "wiki", "game", "output"]
    # Every count has a place in the step order, and the funnel adds up.
    assert all(k.partition(": ")[2] in STEPS for k in report.stats if not k.startswith("output: "))
    lines = [line.split(None, 1)[1] for line in report.format().splitlines()]
    wiki = [line for line in lines if line.startswith("wiki: ")]
    assert wiki == [
        "wiki: API pages",
        "wiki: entries",
        "wiki: entries with no description",
        "wiki: symbols documented",
        "wiki: entries written",
    ]


def test_merge_skips_absent_sources(tmp_path: Path) -> None:
    report = merge_docs(Symbols(SYMBOLS), tmp_path, anatid=write_sources(tmp_path)["anatid"])
    assert report.stats["anatid: entries written"] == 3
    assert not any(k.startswith(("official", "wiki", "game")) for k in report.stats)


def test_merge_reports_are_independent(tmp_path: Path) -> None:
    sources = write_sources(tmp_path)
    first = merge_docs(Symbols(SYMBOLS), tmp_path / "a", **sources)
    second = merge_docs(Symbols(SYMBOLS), tmp_path / "b", **sources)
    assert first.unmatched == second.unmatched
    assert first.stats == second.stats


def test_symbols_load(tmp_path: Path) -> None:
    path = tmp_path / "symbols.json"
    _ = path.write_text(json.dumps(SYMBOLS))
    syms = Symbols.load(path)
    assert syms.find_member("Vessel", "Load", "Method", 1, ["System.String"])[0] == SYMBOLS[3]
    assert syms.find_member("Vessel", "Load", "Method", 1)[1] == (
        "2 members with this name, 2 fit the signature equally"
    )


def test_type_helpers() -> None:
    assert split_top("a, Dictionary<string, int>, b[,]") == ["a", " Dictionary<string, int>", " b[,]"]
    assert canon_type("System.Collections.Generic.List{System.Int32}@") == "List<int>"


def test_wiki_helpers() -> None:
    text = "{{Method|name=Foo|args={{arg|int|count}}, {{arg|string|names|array=[]}}|desc=x}}"
    templates = dict(wiki_templates(text))
    assert templates["Method"]["name"] == "Foo"
    assert wiki_arg_types(templates["Method"]["args"]) == ["int", "string[]"]
    assert wiki_text("See [[API:Part|parts]]:<source lang='c'>a < b</source>") == ("See parts: <code>a &lt; b</code>")


def test_unparseable_doxygen_file_is_counted(tmp_path: Path) -> None:
    official = tmp_path / "xml.zip"
    with zipfile.ZipFile(official, "w") as z:
        z.writestr("xml/broken.xml", "<doxygen><unclosed></doxygen>")
    report = merge_docs(Symbols(SYMBOLS), tmp_path / "out", official=official)
    assert report.stats == {"official: unparseable files": 1}


def test_wiki_plain_text() -> None:
    # Inline tags leave no gap before punctuation; block tags separate words.
    assert wiki_text("Same as <code>orbit</code>.<br>See ''also'' <i>this</i>") == "Same as orbit. See also this"
    # Entities are decoded once, then escaped for XML like any other text.
    assert wiki_text("a direct orbit&mdash;or not, if a &lt; b") == "a direct orbit—or not, if a &lt; b"
    # Angle brackets that are not markup are text.
    assert wiki_text("a List<Part> or <Part subclass><!-- todo -->") == "a List&lt;Part&gt; or &lt;Part subclass&gt;"


def test_wiki_formula_braces_do_not_end_templates(tmp_path: Path) -> None:
    formula = r"As &lt;math&gt;\frac{M_{\mathrm{p}}}{2}&lt;/math&gt;.|x=y"
    wiki = tmp_path / "wiki.xml"
    _ = wiki.write_text(WIKI.replace("The '''unique''' [[API:Guid|id]].", formula))
    report = merge_docs(Symbols(SYMBOLS), tmp_path / "out", wiki=wiki)
    assert report.stats["wiki: entries written"] == 1
    xml = (tmp_path / "out" / "Assembly-CSharp.xml").read_text()
    assert r"<summary>As \frac{M_{\mathrm{p} } } {2}.</summary>" in xml


def members_of(path: Path) -> dict[str, str]:
    """Each <member> of an XML documentation file, as its inner XML keyed by ID."""
    return {
        m.get("name", ""): "".join(ET.tostring(c, encoding="unicode") for c in m)
        for m in ET.parse(path).getroot().iter("member")
    }


def test_wiki_lowercase_class_returns_and_params(tmp_path: Path) -> None:
    syms = [
        *SYMBOLS,
        symbol(
            "M:Vessel.Find(System.String,System.Int32)",
            "Method",
            "Find",
            "Vessel",
            ptypes=["string", "int"],
            pnames=["key", "arrayIndex"],
        ),
    ]
    page = (
        "{{class|name=Vessel|summary=A craft.}}\n"
        "{{Method|returntype=int|name=Find|args={{arg|string|key|desc=What to find}}, {{arg|int|arrayIndex}}"
        "|desc=Finds one.|returndesc=Its index.}}\n"
        "{{Method|returntype=string|name=GetName|args=|desc=The name.|returndesc=}}"
    )
    wiki = tmp_path / "wiki.xml"
    _ = wiki.write_text(WIKI.replace(WIKI[WIKI.index("<text>") + 6 : WIKI.index("</text>")], page, 1))
    _ = merge_docs(Symbols(syms), tmp_path / "out", wiki=wiki)
    members = members_of(tmp_path / "out" / "Assembly-CSharp.xml")
    source = "<remarks>Source: KSP wiki page API:Vessel, last edited 2020-05-06.</remarks>"
    # MediaWiki template names are case-insensitive in their first letter.
    assert members["T:Vessel"] == "<summary>A craft.</summary>" + source
    assert members["M:Vessel.Find(System.String,System.Int32)"] == (
        '<summary>Finds one.</summary><param name="key">What to find</param><returns>Its index.</returns>' + source
    )
    # An empty returndesc adds nothing.
    assert members["M:Vessel.GetName"] == "<summary>The name.</summary>" + source


def test_wiki_args() -> None:
    assert wiki_args("{{arg|int|arrayIndex}}, {{Arg|byte|data|array=[]|desc=The bytes}}, Vector3d pos") == [
        ("int", "arrayIndex", ""),
        ("byte[]", "data", "The bytes"),
        ("Vector3d", "pos", ""),
    ]


def test_anatid_text_is_escaped(tmp_path: Path) -> None:
    anatid = tmp_path / "anatid.xml"
    _ = anatid.write_text(
        '<doc><members><member name="F:Vessel.id">Mass &amp; size &lt; 3<summary>x</summary></member></members></doc>'
    )
    report = merge_docs(Symbols(SYMBOLS), tmp_path / "out", anatid=anatid)
    assert report.stats["anatid: entries written"] == 1
    xml = (tmp_path / "out" / "Assembly-CSharp.xml").read_text()
    assert '<member name="F:Vessel.id">Mass &amp; size &lt; 3<summary>x</summary>' in xml


def test_doxygen_operators(tmp_path: Path) -> None:
    syms = [
        symbol("T:Vec", "NamedType", "Vec"),
        symbol("M:Vec.op_UnaryNegation(Vec)", "Method", "op_UnaryNegation", "Vec", ptypes=["Vec"], pnames=["a"]),
        symbol(
            "M:Vec.op_Subtraction(Vec,Vec)", "Method", "op_Subtraction", "Vec", ptypes=["Vec", "Vec"], pnames=["a", "b"]
        ),
        symbol(
            "M:Vec.op_Implicit(Vec)~UnityEngine.Vector3", "Method", "op_Implicit", "Vec", ptypes=["Vec"], pnames=["v"]
        ),
    ]

    def member(id: str, kind: str, type: str, name: str, *params: str) -> str:
        ps = "".join(f"<param><type>Vec</type><declname>{p}</declname></param>" for p in params)
        return (
            f'<memberdef kind="function" id="{id}" static="yes"><type>{type}</type><name>{name}</name>{ps}'
            f"<briefdescription><para>{kind}.</para></briefdescription></memberdef>"
        )

    official = tmp_path / "xml.zip"
    with zipfile.ZipFile(official, "w") as z:
        z.writestr(
            "xml/struct_vec.xml",
            '<doxygen><compounddef id="struct_vec" kind="struct">'
            "<compoundname>Vec</compoundname>"
            + member("neg", "Negation", "Vec", "operator-", "a")
            + member("sub", "Subtraction", "Vec", "operator-", "a", "b")
            + member("conv", "Conversion", "implicit", "operator Vector3", "v")
            + "</compounddef></doxygen>",
        )
    report = merge_docs(Symbols(syms), tmp_path / "out", official=official)
    assert report.unmatched == []
    members = members_of(tmp_path / "out" / "Assembly-CSharp.xml")
    assert members["M:Vec.op_UnaryNegation(Vec)"] == "<summary>Negation.</summary>"
    assert members["M:Vec.op_Subtraction(Vec,Vec)"] == "<summary>Subtraction.</summary>"
    assert members["M:Vec.op_Implicit(Vec)~UnityEngine.Vector3"] == "<summary>Conversion.</summary>"


def test_parameter_types_resolve_in_declaring_scope() -> None:
    syms = Symbols(
        [
            symbol(
                "M:Ns.Outer.Name(System.String,Ns.Outer.Gender)",
                "Method",
                "Name",
                "Ns.Outer",
                ptypes=["string", "Outer.Gender"],
            ),
            symbol(
                "M:Ns.Outer.Name(System.String,Other.Gender)",
                "Method",
                "Name",
                "Ns.Outer",
                ptypes=["string", "Other.Gender"],
            ),
            symbol("M:Ns.Outer.Inner.Set(Ns.Outer.Gender)", "Method", "Set", "Ns.Outer.Inner", ptypes=["Outer.Gender"]),
            symbol("M:Ns.Outer.Inner.Set(Other.Gender)", "Method", "Set", "Ns.Outer.Inner", ptypes=["Other.Gender"]),
        ]
    )
    # An unqualified name means the type nested in the declaring type, as in C#.
    found, _ = syms.find_member("Ns.Outer", "Name", "Method", 2, ["string", "Gender"])
    assert found is not None and found["id"] == "M:Ns.Outer.Name(System.String,Ns.Outer.Gender)"
    found, _ = syms.find_member("Ns.Outer", "Name", "Method", 2, ["string", "Other.Gender"])
    assert found is not None and found["id"] == "M:Ns.Outer.Name(System.String,Other.Gender)"
    # Or nested in a type that encloses the declaring type.
    found, _ = syms.find_member("Ns.Outer.Inner", "Set", "Method", 1, ["Gender"])
    assert found is not None and found["id"] == "M:Ns.Outer.Inner.Set(Ns.Outer.Gender)"


def test_localization_reads_only_stock_dirs(tmp_path: Path) -> None:
    for i, folder in enumerate(("Squad", "SquadExpansion/Serenity", "SquadTweaks", "Mod/Squad")):
        loc = tmp_path / folder / "Localization"
        loc.mkdir(parents=True)
        _ = (loc / "dictionary.cfg").write_text(
            f"Localization\n{{\n\ten-us\n\t{{\n\t\t#autoLOC_{i} = {folder}\n\t}}\n}}\n"
        )
    assert load_localization(tmp_path) == {"#autoloc_0": "Squad", "#autoloc_1": "SquadExpansion/Serenity"}
