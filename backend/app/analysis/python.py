"""Python analyzer (Tree-sitter grammar `tree-sitter-python`)."""

import tree_sitter_python
from tree_sitter import Language, Node

from app.analysis.base import (
    MAX_SYMBOLS_PER_FILE,
    TreeSitterAnalyzer,
    clean_docstring,
    compact,
    count_comment_lines,
    count_errors,
    end_line,
    node_text,
    preceding_comments,
    start_line,
)
from app.analysis.results import (
    ExportedName,
    ExtractedCall,
    ExtractedImport,
    ExtractedSymbol,
    FileAnalysis,
    ImportedName,
    Parameter,
    SymbolKind,
)

_FUNCTION_KINDS = (SymbolKind.FUNCTION, SymbolKind.METHOD)
_METHOD_DECORATORS = {"staticmethod": "static", "classmethod": "class", "property": "property"}
_CONDITIONAL_ANCESTORS = {
    "if_statement",
    "try_statement",
    "with_statement",
    "elif_clause",
    "else_clause",
}
_SCOPE_BOUNDARIES = {"module", "function_definition", "class_definition"}


class PythonAnalyzer(TreeSitterAnalyzer):
    language = "python"
    extensions = (".py", ".pyi")

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_python.language()))

    def analyze(self, source: bytes, path: str) -> FileAnalysis:
        return _PythonExtractor(source).run(self.parse(source).root_node)


class _PythonExtractor:
    def __init__(self, source: bytes) -> None:
        self.source = source
        self.result = FileAnalysis(language="python")

    # -- entry point -------------------------------------------------------

    def run(self, root: Node) -> FileAnalysis:
        self.result.docstring = self._docstring(root)
        self.result.syntax_error_count = count_errors(root)
        self.result.comment_lines = count_comment_lines(root)
        self._walk(root)
        self._summarise_calls()
        self._apply_exports(root)
        return self.result

    def _text(self, node: Node | None) -> str:
        return node_text(node, self.source)

    # -- traversal ---------------------------------------------------------

    def _walk(self, root: Node) -> None:
        # Each entry: (node, key of the enclosing symbol, decorated_definition wrapper)
        stack: list[tuple[Node, int | None, Node | None]] = [(root, None, None)]
        while stack:
            node, owner, decorated = stack.pop()
            kind = node.type

            if kind == "decorated_definition":
                definition = node.child_by_field_name("definition")
                if definition is not None:
                    stack.append((definition, owner, node))
                # Decorator expressions run in the enclosing scope.
                stack.extend(
                    (child, owner, None) for child in node.children if child.type == "decorator"
                )
                continue

            if kind in ("function_definition", "class_definition"):
                key = self._add_symbol(node, owner, decorated)
                if key is None:
                    continue
                for child in reversed(node.children):
                    if child.type == "block":
                        stack.append((child, key, None))
                    elif child.type in ("parameters", "argument_list"):
                        # Default values and base classes are evaluated in the outer scope.
                        stack.append((child, owner, None))
                continue

            if kind == "import_statement":
                self._add_plain_import(node, owner)
                continue
            if kind in ("import_from_statement", "future_import_statement"):
                self._add_from_import(node, owner)
                continue

            if kind == "call":
                self._add_call(node, owner)
            elif kind == "return_statement" and node.named_child_count and owner is not None:
                self._mark_function(owner, "returns_value")
            elif kind == "yield" and owner is not None:
                self._mark_function(owner, "is_generator")

            stack.extend((child, owner, None) for child in reversed(node.children))

    # -- symbols -----------------------------------------------------------

    def _add_symbol(self, node: Node, owner: int | None, decorated: Node | None) -> int | None:
        symbols = self.result.symbols
        if len(symbols) >= MAX_SYMBOLS_PER_FILE:
            self.result.truncated = True
            return None

        name_node = node.child_by_field_name("name")
        name = self._text(name_node)
        outer = decorated or node
        parent = symbols[owner] if owner is not None else None
        is_class = node.type == "class_definition"
        if is_class:
            kind = SymbolKind.CLASS
        elif parent is not None and parent.kind is SymbolKind.CLASS:
            kind = SymbolKind.METHOD
        else:
            kind = SymbolKind.FUNCTION

        symbol = ExtractedSymbol(
            key=len(symbols),
            name=name,
            kind=kind,
            start_line=start_line(outer),
            end_line=end_line(outer),
            parent_key=owner,
            qualified_name=f"{parent.qualified_name}.{name}" if parent else name,
            decorators=[
                compact(self._text(child).lstrip("@"))
                for child in (decorated.children if decorated else [])
                if child.type == "decorator"
            ],
            docstring=self._docstring(node.child_by_field_name("body")),
        )
        if decorated is not None and name_node is not None:
            symbol.metadata["definition_line"] = start_line(name_node)
        if comment := self._comment_text(outer):
            symbol.metadata["comment"] = comment

        if is_class:
            self._describe_class(node, symbol)
        else:
            self._describe_function(node, symbol)
        symbols.append(symbol)
        return symbol.key

    def _describe_class(self, node: Node, symbol: ExtractedSymbol) -> None:
        superclasses = node.child_by_field_name("superclasses")
        bases: list[str] = []
        if superclasses is not None:
            for argument in superclasses.named_children:
                if argument.type == "keyword_argument":
                    keyword = self._text(argument.child_by_field_name("name"))
                    symbol.metadata.setdefault("keywords", {})[keyword] = compact(
                        self._text(argument.child_by_field_name("value")), 120
                    )
                elif argument.type != "comment":
                    bases.append(compact(self._text(argument), 120))
        if bases:
            symbol.metadata["bases"] = bases
        arguments = compact(self._text(superclasses)) if superclasses is not None else ""
        symbol.signature = f"class {symbol.name}{arguments}"

    def _describe_function(self, node: Node, symbol: ExtractedSymbol) -> None:
        symbol.is_async = bool(node.children) and node.children[0].type == "async"
        parameters_node = node.child_by_field_name("parameters")
        symbol.parameters = self._parameters(parameters_node)
        return_node = node.child_by_field_name("return_type")
        symbol.return_type = compact(self._text(return_node)) if return_node else None

        signature = f"def {symbol.name}{compact(self._text(parameters_node))}"
        if symbol.return_type:
            signature += f" -> {symbol.return_type}"
        symbol.signature = f"async {signature}" if symbol.is_async else signature

        if symbol.kind is SymbolKind.METHOD:
            for decorator in symbol.decorators:
                if decorator in _METHOD_DECORATORS:
                    symbol.metadata["method_type"] = _METHOD_DECORATORS[decorator]
                elif decorator.endswith((".setter", ".deleter")):
                    symbol.metadata["method_type"] = "property"

    def _parameters(self, node: Node | None) -> list[Parameter]:
        if node is None:
            return []
        parameters: list[Parameter] = []
        keyword_only = False
        for child in node.named_children:
            if child.type == "positional_separator":
                for parameter in parameters:
                    if parameter.kind == "positional":
                        parameter.kind = "positional_only"
                continue
            if child.type == "keyword_separator":
                keyword_only = True
                continue
            parameter = self._parameter(child)
            if parameter is None:
                continue
            if parameter.kind == "var_positional":
                keyword_only = True
            elif keyword_only and parameter.kind == "positional":
                parameter.kind = "keyword_only"
            parameters.append(parameter)
        return parameters

    def _parameter(self, node: Node) -> Parameter | None:
        kind = node.type
        if kind == "identifier":
            return Parameter(name=self._text(node))
        if kind == "list_splat_pattern":
            return Parameter(name=self._text(node).lstrip("*"), kind="var_positional")
        if kind == "dictionary_splat_pattern":
            return Parameter(name=self._text(node).lstrip("*"), kind="var_keyword")
        if kind == "typed_parameter":
            inner = node.named_children[0] if node.named_children else None
            parameter = self._parameter(inner) if inner is not None else None
            if parameter is not None:
                parameter.type = compact(self._text(node.child_by_field_name("type")), 120) or None
            return parameter
        if kind in ("default_parameter", "typed_default_parameter"):
            type_node = node.child_by_field_name("type")
            return Parameter(
                name=self._text(node.child_by_field_name("name")),
                type=compact(self._text(type_node), 120) if type_node else None,
                default=compact(self._text(node.child_by_field_name("value")), 120),
            )
        if kind == "comment":
            return None
        return Parameter(name=compact(self._text(node), 120))

    def _mark_function(self, key: int, flag: str) -> None:
        symbol = self.result.symbols[key]
        if symbol.kind in _FUNCTION_KINDS:
            symbol.metadata[flag] = True

    def _docstring(self, block: Node | None) -> str | None:
        if block is None:
            return None
        first = next((child for child in block.named_children if child.type != "comment"), None)
        if first is None or first.type != "expression_statement" or first.named_child_count != 1:
            return None
        string = first.named_children[0]
        if string.type != "string":
            return None
        content = "".join(
            self._text(part) for part in string.named_children if part.type == "string_content"
        )
        return clean_docstring(content)

    def _comment_text(self, node: Node) -> str | None:
        lines = [self._text(comment).lstrip("#").strip() for comment in preceding_comments(node)]
        text = "\n".join(line for line in lines if line)
        return text[:1000] or None

    # -- imports -----------------------------------------------------------

    def _add_plain_import(self, node: Node, owner: int | None) -> None:
        # `import a.b as c, d` — one import per module.
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                module = self._text(child.child_by_field_name("name"))
                alias = self._text(child.child_by_field_name("alias")) or None
            else:
                module, alias = self._text(child), None
            imported = ExtractedImport(
                module=module,
                kind="import",
                start_line=start_line(node),
                end_line=end_line(node),
                names=[ImportedName(name=module, alias=alias)],
            )
            self._add_import_context(imported, node, owner)
            self.result.imports.append(imported)

    def _add_from_import(self, node: Node, owner: int | None) -> None:
        module_node = node.child_by_field_name("module_name")
        level, module = 0, "__future__" if node.type == "future_import_statement" else ""
        if module_node is not None and module_node.type == "relative_import":
            for part in module_node.named_children:
                if part.type == "import_prefix":
                    level = len(self._text(part).strip())
                elif part.type == "dotted_name":
                    module = self._text(part)
        elif module_node is not None:
            module = self._text(module_node)

        names: list[ImportedName] = []
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                names.append(
                    ImportedName(
                        name=self._text(child.child_by_field_name("name")),
                        alias=self._text(child.child_by_field_name("alias")) or None,
                    )
                )
            else:
                names.append(ImportedName(name=self._text(child)))
        if any(child.type == "wildcard_import" for child in node.children):
            names = [ImportedName(name="*")]

        imported = ExtractedImport(
            module="." * level + module,
            kind="from",
            level=level,
            start_line=start_line(node),
            end_line=end_line(node),
            names=names,
        )
        self._add_import_context(imported, node, owner)
        self.result.imports.append(imported)

    def _add_import_context(self, imported: ExtractedImport, node: Node, owner: int | None) -> None:
        if owner is not None:
            imported.metadata["scope"] = self.result.symbols[owner].kind.value
        ancestor = node.parent
        while ancestor is not None and ancestor.type not in _SCOPE_BOUNDARIES:
            if ancestor.type in _CONDITIONAL_ANCESTORS:
                imported.metadata["conditional"] = True
                condition = ancestor.child_by_field_name("condition")
                if ancestor.type == "if_statement" and "TYPE_CHECKING" in self._text(condition):
                    imported.is_type_only = True
            ancestor = ancestor.parent

    # -- calls -------------------------------------------------------------

    def _add_call(self, node: Node, owner: int | None) -> None:
        function = node.child_by_field_name("function")
        if function is None or function.type not in ("identifier", "attribute"):
            return
        callee = self._text(function)
        if "(" in callee or "[" in callee or len(callee) > 200:
            return
        self.result.calls.append(
            ExtractedCall(callee="".join(callee.split()), line=start_line(node), caller_key=owner)
        )

    def _summarise_calls(self) -> None:
        by_symbol: dict[int, list[str]] = {}
        for call in self.result.calls:
            if call.caller_key is not None:
                names = by_symbol.setdefault(call.caller_key, [])
                if call.callee not in names and len(names) < 50:
                    names.append(call.callee)
        for key, names in by_symbol.items():
            self.result.symbols[key].metadata["calls"] = names

    # -- exports -----------------------------------------------------------

    def _apply_exports(self, root: Node) -> None:
        top_level = [symbol for symbol in self.result.symbols if symbol.parent_key is None]
        declared = self._dunder_all(root)
        if declared is not None:
            names, line = declared
            local = {symbol.name for symbol in top_level}
            for symbol in top_level:
                symbol.is_exported = symbol.name in names
            self.result.exports = [
                ExportedName(
                    name=name, local_name=name if name in local else None, kind="all", line=line
                )
                for name in names
            ]
            return
        for symbol in top_level:
            symbol.is_exported = not symbol.name.startswith("_")
        self.result.exports = [
            ExportedName(
                name=symbol.name, local_name=symbol.name, kind="implicit", line=symbol.start_line
            )
            for symbol in top_level
            if symbol.is_exported
        ]

    def _dunder_all(self, root: Node) -> tuple[list[str], int] | None:
        """Names listed in a module-level `__all__ = [...]` (plus `+=` extensions)."""
        names: list[str] | None = None
        line = 0
        for statement in root.named_children:
            if statement.type != "expression_statement" or not statement.named_children:
                continue
            assignment = statement.named_children[0]
            if assignment.type not in ("assignment", "augmented_assignment"):
                continue
            if self._text(assignment.child_by_field_name("left")) != "__all__":
                continue
            value = assignment.child_by_field_name("right")
            if value is None or value.type not in ("list", "tuple"):
                continue
            items = [
                "".join(
                    self._text(part)
                    for part in item.named_children
                    if part.type == "string_content"
                )
                for item in value.named_children
                if item.type == "string"
            ]
            if assignment.type == "assignment" or names is None:
                names, line = items, start_line(statement)
            else:
                names.extend(items)
        return (names, line) if names is not None else None
