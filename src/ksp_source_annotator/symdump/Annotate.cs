// symdump annotate <ManagedDir> <Assembly.xml> <SourceDir>
//   Writes the entries of an XML documentation file into the decompiled
//   source of that assembly as /// comments, in place. Declarations are
//   matched by the documentation comment ID Roslyn computes for them.
//   Existing /// comments on declarations are replaced, so it can be re-run.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

static class Annotate
{
    const int Width = 100;

    public static int Run(string managed, string xmlPath, string srcDir)
    {
        string asm = Path.GetFileNameWithoutExtension(xmlPath);
        var docs = new Dictionary<string, XElement>();
        foreach (var m in XDocument.Load(xmlPath, LoadOptions.PreserveWhitespace).Descendants("member"))
            docs[(string)m.Attribute("name")] = m;

        var parse = new CSharpParseOptions(LanguageVersion.CSharp7_3, DocumentationMode.Parse);
        var trees = new List<SyntaxTree>();
        foreach (string f in Directory.EnumerateFiles(srcDir, "*.cs", SearchOption.AllDirectories))
        {
            string rel = Path.GetRelativePath(srcDir, f);
            if (rel.StartsWith("obj" + Path.DirectorySeparatorChar) || rel.StartsWith("bin" + Path.DirectorySeparatorChar))
                continue;
            trees.Add(CSharpSyntaxTree.ParseText(SourceText.From(File.ReadAllText(f), Encoding.UTF8), parse, f));
        }

        var refs = new List<MetadataReference>();
        foreach (string dll in Directory.GetFiles(managed, "*.dll"))
        {
            if (Path.GetFileNameWithoutExtension(dll) == asm) continue;
            try { refs.Add(MetadataReference.CreateFromFile(dll)); }
            catch (Exception) { /* native or otherwise unreadable dll */ }
        }
        var comp = CSharpCompilation.Create(asm, trees, refs,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, allowUnsafe: true));

        var used = new HashSet<string>();
        int files = 0;
        foreach (var tree in trees)
        {
            var model = comp.GetSemanticModel(tree);
            var text = tree.GetText();
            var edits = new List<(int start, int end, string text)>();
            foreach (var node in tree.GetRoot().DescendantNodes())
            {
                if (!IsDeclaration(node)) continue;
                var token = node.GetFirstToken();
                var line = text.Lines.GetLineFromPosition(token.SpanStart);
                string indent = text.ToString(TextSpan.FromBounds(line.Start, token.SpanStart));
                if (indent.Trim().Length != 0) continue;

                foreach (var t in token.LeadingTrivia)
                    if (t.IsKind(SyntaxKind.SingleLineDocumentationCommentTrivia)
                        || t.IsKind(SyntaxKind.MultiLineDocumentationCommentTrivia))
                        edits.Add((text.Lines.GetLineFromPosition(t.FullSpan.Start).Start, t.FullSpan.End, ""));

                string id = DocId(node, model, docs);
                if (id == null || !used.Add(id)) continue;
                edits.Add((line.Start, line.Start, Format(docs[id], indent)));
            }
            if (edits.Count == 0) continue;

            var sb = new StringBuilder(text.ToString());
            foreach (var e in edits.OrderByDescending(e => e.start).ThenByDescending(e => e.end))
            {
                sb.Remove(e.start, e.end - e.start);
                sb.Insert(e.start, e.text);
            }
            string result = sb.ToString();
            if (result == text.ToString()) continue;
            File.WriteAllText(tree.FilePath, result);
            files++;
        }

        Console.WriteLine($"{asm}: {used.Count} of {docs.Count} documentation entries written into {files} files");
        return 0;
    }

    static bool IsDeclaration(SyntaxNode n) =>
        n is BaseTypeDeclarationSyntax || n is DelegateDeclarationSyntax
        || n is BaseMethodDeclarationSyntax || n is BasePropertyDeclarationSyntax
        || n is BaseFieldDeclarationSyntax || n is EnumMemberDeclarationSyntax;

    static string DocId(SyntaxNode node, SemanticModel model, Dictionary<string, XElement> docs)
    {
        if (node is BaseFieldDeclarationSyntax field)
        {
            // "int a, b;" carries one comment; use the first variable that has one.
            foreach (var v in field.Declaration.Variables)
            {
                string vid = model.GetDeclaredSymbol(v)?.GetDocumentationCommentId();
                if (vid != null && docs.ContainsKey(vid)) return vid;
            }
            return null;
        }
        string id = model.GetDeclaredSymbol(node)?.GetDocumentationCommentId();
        return id != null && docs.ContainsKey(id) ? id : null;
    }

    static string Format(XElement member, string indent)
    {
        var sb = new StringBuilder();
        void Line(string s) => sb.Append(indent).Append("/// ").Append(s).Append('\n');

        foreach (var el in member.Elements())
        {
            string open = "<" + el.Name.LocalName + string.Concat(el.Attributes().Select(a => " " + a)) + ">";
            string close = "</" + el.Name.LocalName + ">";
            string inner = string.Concat(el.Nodes().Select(n => n.ToString(SaveOptions.DisableFormatting)));

            if (inner.Contains("<code>"))
            {
                // Code samples keep their line breaks.
                Line(open);
                foreach (string l in inner.Trim().Split('\n')) Line(l.TrimEnd());
                Line(close);
                continue;
            }
            inner = Regex.Replace(inner, @"\s+", " ").Trim();
            string oneLine = open + inner + close;
            if (el.Name.LocalName != "summary" && indent.Length + 4 + oneLine.Length <= Width)
            {
                Line(oneLine);
                continue;
            }
            Line(open);
            // Wrap between words; a tag such as <see cref="..."/> stays whole.
            var cur = new StringBuilder();
            foreach (Match m in Regex.Matches(inner, @"<[^>]+>|[^\s<]+|\s+"))
            {
                string tok = m.Value;
                if (tok.Trim().Length == 0)
                {
                    if (cur.Length > 0) cur.Append(' ');
                    continue;
                }
                if (cur.Length > 0 && indent.Length + 4 + cur.Length + tok.Length > Width)
                {
                    Line(cur.ToString().TrimEnd());
                    cur.Clear();
                }
                cur.Append(tok);
            }
            if (cur.Length > 0) Line(cur.ToString().TrimEnd());
            Line(close);
        }
        return sb.ToString();
    }
}
