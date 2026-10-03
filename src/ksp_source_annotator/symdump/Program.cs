// symdump dump   <ManagedDir> <out.json> <Assembly>...
//   Writes every symbol in the named assemblies with the documentation
//   comment ID Roslyn assigns it, for the Python merge to match against.
// symdump verify <ManagedDir> <XmlDir> <Assembly>...
//   Loads <XmlDir>/<Assembly>.xml the way the language server does and
//   reports how many symbols resolve to documentation.
// symdump annotate: see Annotate.cs.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

static class Program
{
    static readonly SymbolDisplayFormat Full = SymbolDisplayFormat.CSharpErrorMessageFormat;
    // MinimallyQualifiedFormat's type options, except that types keep their
    // containing types, so that two nested types with the same name
    // (Outer1.Gender, Outer2.Gender) stay distinct.
    static readonly SymbolDisplayFormat Short = new SymbolDisplayFormat(
        globalNamespaceStyle: SymbolDisplayGlobalNamespaceStyle.Omitted,
        typeQualificationStyle: SymbolDisplayTypeQualificationStyle.NameAndContainingTypes,
        genericsOptions: SymbolDisplayGenericsOptions.IncludeTypeParameters,
        miscellaneousOptions: SymbolDisplayMiscellaneousOptions.EscapeKeywordIdentifiers
            | SymbolDisplayMiscellaneousOptions.UseSpecialTypes
            | SymbolDisplayMiscellaneousOptions.UseAsterisksInMultiDimensionalArrays
            | SymbolDisplayMiscellaneousOptions.UseErrorTypeSymbolName);

    static int Main(string[] args)
    {
        if (args.Length == 4 && args[0] == "annotate")
            return Annotate.Run(args[1], args[2], args[3]);
        if (args.Length < 4 || (args[0] != "dump" && args[0] != "verify"))
        {
            Console.Error.WriteLine("usage: symdump dump|verify <ManagedDir> <out.json|XmlDir> <Assembly>...");
            Console.Error.WriteLine("       symdump annotate <ManagedDir> <Assembly.xml> <SourceDir>");
            return 2;
        }
        string managed = args[1];
        var targets = args.Skip(3).ToHashSet();
        bool verify = args[0] == "verify";

        var refs = new List<MetadataReference>();
        foreach (string dll in Directory.GetFiles(managed, "*.dll"))
        {
            string xml = Path.Combine(args[2], Path.GetFileNameWithoutExtension(dll) + ".xml");
            DocumentationProvider docs = verify && File.Exists(xml)
                ? XmlDocumentationProvider.CreateFromFile(xml)
                : null;
            try { refs.Add(MetadataReference.CreateFromFile(dll, documentation: docs)); }
            catch (Exception) { /* native or otherwise unreadable dll */ }
        }
        var options = new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary,
            metadataImportOptions: MetadataImportOptions.All);
        var comp = CSharpCompilation.Create("symdump", references: refs, options: options);

        var symbols = new List<ISymbol>();
        foreach (var r in comp.References)
            if (comp.GetAssemblyOrModuleSymbol(r) is IAssemblySymbol a && targets.Contains(a.Name))
                Walk(a.GlobalNamespace, a.Name, symbols);

        return verify ? Verify(symbols) : Dump(symbols, args[2]);
    }

    static void Walk(INamespaceOrTypeSymbol scope, string asm, List<ISymbol> into)
    {
        foreach (var m in scope.GetMembers())
        {
            if (m is INamespaceSymbol ns) { Walk(ns, asm, into); continue; }
            if (m.ContainingAssembly?.Name != asm) continue;
            into.Add(m);
            if (m is INamedTypeSymbol t) Walk(t, asm, into);
        }
    }

    static int Dump(List<ISymbol> symbols, string outPath)
    {
        var rows = new List<object>();
        foreach (var m in symbols)
        {
            string id = m.GetDocumentationCommentId();
            if (id == null) continue;
            var ps = (m as IMethodSymbol)?.Parameters ?? (m as IPropertySymbol)?.Parameters;
            rows.Add(new
            {
                id,
                asm = m.ContainingAssembly.Name,
                kind = m.Kind.ToString(),
                mkind = (m as IMethodSymbol)?.MethodKind.ToString(),
                name = m.Name,
                type = m.ContainingType?.ToDisplayString(Full) ?? "",
                full = m.ToDisplayString(Full),
                ptypes = ps?.Select(p => p.Type.ToDisplayString(Short)).ToArray(),
                pnames = ps?.Select(p => p.Name).ToArray(),
                prefs = ps?.Select(p => p.RefKind.ToString()).ToArray(),
                tparams = (m as IMethodSymbol)?.TypeParameters.Length,
                acc = m.DeclaredAccessibility.ToString(),
                loc = LocalizationKeys(m),
            });
        }
        File.WriteAllText(outPath, JsonSerializer.Serialize(rows));
        Console.WriteLine($"{rows.Count} symbols");
        return 0;
    }

    // Attribute string arguments that are localization keys, such as
    // [KSPField(guiName = "#autoLOC_123")], as [attribute, argument, key].
    static string[][] LocalizationKeys(ISymbol m)
    {
        var found = new List<string[]>();
        foreach (var attr in m.GetAttributes())
        {
            string name = attr.AttributeClass?.Name ?? "";
            var ctor = attr.AttributeConstructor;
            for (int i = 0; i < attr.ConstructorArguments.Length; i++)
                if (IsKey(attr.ConstructorArguments[i]))
                    found.Add(new[] { name, ctor != null && i < ctor.Parameters.Length ? ctor.Parameters[i].Name : "", (string)attr.ConstructorArguments[i].Value });
            foreach (var named in attr.NamedArguments)
                if (IsKey(named.Value))
                    found.Add(new[] { name, named.Key, (string)named.Value.Value });
        }
        return found.Count > 0 ? found.ToArray() : null;
    }

    static bool IsKey(TypedConstant c) =>
        c.Kind == TypedConstantKind.Primitive && c.Value is string s
        && s.StartsWith("#autoLOC", StringComparison.OrdinalIgnoreCase);

    static int Verify(List<ISymbol> symbols)
    {
        foreach (var g in symbols.GroupBy(s => s.ContainingAssembly.Name))
        {
            int documented = g.Count(s => !string.IsNullOrEmpty(s.GetDocumentationCommentXml()));
            Console.WriteLine($"{g.Key}: {documented} of {g.Count()} symbols resolve to documentation");
        }
        return 0;
    }
}
