"""JavaScript, TypeScript and TSX analyzers (Tree-sitter grammars `tree-sitter-javascript`
and `tree-sitter-typescript`). The three grammars share almost all node types, so one
extractor handles them all.
"""

import re
from dataclasses import dataclass, replace

import tree_sitter_javascript
import tree_sitter_typescript
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
    ApiCall,
    ExportedName,
    ExtractedCall,
    ExtractedImport,
    ExtractedSymbol,
    FileAnalysis,
    ImportedName,
    Parameter,
    SymbolKind,
)

_FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
_CLASS_NODES = {"class_declaration", "abstract_class_declaration", "class"}
_TYPE_NODES = {
    "interface_declaration": SymbolKind.INTERFACE,
    "type_alias_declaration": SymbolKind.TYPE_ALIAS,
    "enum_declaration": SymbolKind.ENUM,
}
_FIELD_NODES = {"public_field_definition", "field_definition"}
_COMPONENT_WRAPPERS = {"memo", "forwardRef", "observer", "React.memo", "React.forwardRef"}
_REACT_BASES = re.compile(r"^(React\.)?(Pure)?Component\b")
_HOOK_NAME = re.compile(r"^use[A-Z0-9]")
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_FETCH_CALLEES = {
    "fetch",
    "window.fetch",
    "globalThis.fetch",
    "$fetch",
    "ofetch",
    "useFetch",
    "useSWR",
}
_HTTP_CLIENTS = {
    "axios", "ky", "got", "superagent", "request", "$http", "http", "https", "api",
    "apiClient", "client", "httpClient", "instance",
}  # fmt: skip


@dataclass(frozen=True)
class _Context:
    """Information a parent node passes down to the declaration it wraps."""

    exported: bool = False
    default: bool = False
    decorators: tuple[str, ...] = ()
    outer: Node | None = None  # node whose line range/comments describe the declaration
    name: str | None = None  # binding name for function/class expressions
    wrapper: str | None = None  # memo / forwardRef / observer


_NO_CONTEXT = _Context()


class EcmaScriptAnalyzer(TreeSitterAnalyzer):
    def analyze(self, source: bytes, path: str) -> FileAnalysis:
        return _EcmaScriptExtractor(source, self.language).run(self.parse(source).root_node)


class JavaScriptAnalyzer(EcmaScriptAnalyzer):
    language = "javascript"
    extensions = (".js", ".jsx", ".mjs", ".cjs")

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_javascript.language()))


class TypeScriptAnalyzer(EcmaScriptAnalyzer):
    language = "typescript"
    extensions = (".ts", ".mts", ".cts")

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_typescript.language_typescript()))


class TsxAnalyzer(EcmaScriptAnalyzer):
    language = "tsx"
    extensions = (".tsx",)

    def __init__(self) -> None:
        super().__init__(Language(tree_sitter_typescript.language_tsx()))


class _EcmaScriptExtractor:
    def __init__(self, source: bytes, language: str) -> None:
        self.source = source
        self.result = FileAnalysis(language=language)
        self._stack: list[tuple[Node, int | None, _Context]] = []

    # -- entry point -------------------------------------------------------

    def run(self, root: Node) -> FileAnalysis:
        self.result.syntax_error_count = count_errors(root)
        self.result.comment_lines = count_comment_lines(root)
        self.result.docstring = self._file_comment(root)
        self._walk(root)
        self._finalize()
        return self.result

    def _text(self, node: Node | None) -> str:
        return node_text(node, self.source)

    def _push_children(self, node: Node, owner: int | None) -> None:
        self._stack.extend((child, owner, _NO_CONTEXT) for child in reversed(node.children))

    # -- traversal ---------------------------------------------------------

    def _walk(self, root: Node) -> None:
        self._stack = [(root, None, _NO_CONTEXT)]
        while self._stack:
            node, owner, context = self._stack.pop()
            kind = node.type

            if kind == "export_statement":
                self._export_statement(node, owner)
            elif kind == "import_statement":
                self._import_statement(node)
            elif kind in ("function_declaration", "generator_function_declaration"):
                self._function(node, owner, context, self._text(node.child_by_field_name("name")))
            elif kind in _FUNCTION_VALUES:
                if context.name is not None:
                    self._function(node, owner, context, context.name)
                else:
                    self._push_children(node, owner)  # anonymous callback: part of its owner
            elif kind in _CLASS_NODES:
                self._class(node, owner, context)
            elif kind == "method_definition":
                if node.parent is not None and node.parent.type == "class_body":
                    self._method(node, owner)
                else:
                    self._push_children(node, owner)  # object-literal method
            elif kind in _FIELD_NODES:
                self._field(node, owner)
            elif kind in ("lexical_declaration", "variable_declaration"):
                outer = context.outer or node
                for child in reversed(node.named_children):
                    if child.type == "variable_declarator":
                        self._declarator(child, owner, replace(context, outer=outer))
            elif kind in _TYPE_NODES:
                self._type_declaration(node, owner, context)
            elif kind == "call_expression":
                self._call(node, owner)
                self._push_children(node, owner)
            elif kind == "new_expression":
                constructor = node.child_by_field_name("constructor")
                self._record_call(constructor, node, owner)
                self._push_children(node, owner)
            elif kind in ("jsx_opening_element", "jsx_self_closing_element"):
                self._jsx(node, owner)
                self._push_children(node, owner)
            elif kind == "expression_statement":
                self._commonjs_export(node, owner)
            else:
                if owner is not None:
                    if kind == "return_statement" and self._has_value(node):
                        self.result.symbols[owner].metadata["returns_value"] = True
                    elif kind == "yield_expression":
                        self.result.symbols[owner].metadata["is_generator"] = True
                self._push_children(node, owner)

    # -- declarations --------------------------------------------------------

    def _new_symbol(
        self, name: str, kind: SymbolKind, node: Node, owner: int | None, context: _Context
    ) -> ExtractedSymbol | None:
        symbols = self.result.symbols
        if len(symbols) >= MAX_SYMBOLS_PER_FILE:
            self.result.truncated = True
            return None
        outer = context.outer or node
        parent = symbols[owner] if owner is not None else None
        symbol = ExtractedSymbol(
            key=len(symbols),
            name=name or "default",
            kind=kind,
            start_line=start_line(outer),
            end_line=end_line(outer),
            parent_key=owner,
            qualified_name=f"{parent.qualified_name}.{name}" if parent else name,
            is_exported=context.exported and owner is None,
            decorators=list(context.decorators) + self._decorators(node),
        )
        if context.default:
            symbol.metadata["default_export"] = True
        docstring, comment = self._doc_comments(outer)
        symbol.docstring = docstring
        if comment:
            symbol.metadata["comment"] = comment
        symbols.append(symbol)
        return symbol

    def _function(self, node: Node, owner: int | None, context: _Context, name: str) -> None:
        symbol = self._new_symbol(
            name or context.name or "default", SymbolKind.FUNCTION, node, owner, context
        )
        if symbol is None:
            return
        self._describe_callable(
            node, symbol, prefix="" if node.type == "arrow_function" else "function "
        )
        if context.wrapper:
            symbol.metadata["wrapper"] = context.wrapper
        if "generator" in node.type:
            symbol.metadata["is_generator"] = True
        body = node.child_by_field_name("body")
        if body is not None and body.type != "statement_block":
            symbol.metadata["returns_value"] = True  # arrow function with an expression body
        self._push_children(node, symbol.key)

    def _method(self, node: Node, owner: int | None) -> None:
        name = self._text(node.child_by_field_name("name"))
        # In a class body, a method's decorators are the sibling nodes just before it.
        decorator_nodes: list[Node] = []
        sibling = node.prev_sibling
        while sibling is not None and sibling.type == "decorator":
            decorator_nodes.insert(0, sibling)
            sibling = sibling.prev_sibling
        decorators = tuple(compact(self._text(d).lstrip("@"), 120) for d in decorator_nodes)
        context = _Context(decorators=decorators)
        symbol = self._new_symbol(name, SymbolKind.METHOD, node, owner, context)
        if symbol is None:
            return
        if decorator_nodes:
            symbol.start_line = start_line(decorator_nodes[0])
            symbol.docstring, comment = self._doc_comments(decorator_nodes[0])
            if comment:
                symbol.metadata["comment"] = comment
        modifiers = {child.type for child in node.children if not child.is_named}
        self._describe_callable(node, symbol, prefix="")
        if "static" in modifiers:
            symbol.metadata["static"] = True
        if modifiers & {"get", "set"}:
            symbol.metadata["accessor"] = "get" if "get" in modifiers else "set"
        if name == "constructor":
            symbol.metadata["constructor"] = True
        self._push_children(node, symbol.key)

    def _field(self, node: Node, owner: int | None) -> None:
        value = node.child_by_field_name("value")
        if value is None or value.type not in _FUNCTION_VALUES:
            self._push_children(node, owner)
            return
        name_node = node.child_by_field_name("name") or node.child_by_field_name("property")
        context = _Context(outer=node, decorators=tuple(self._decorators(node)))
        symbol = self._new_symbol(self._text(name_node), SymbolKind.METHOD, value, owner, context)
        if symbol is None:
            return
        self._describe_callable(value, symbol, prefix="")
        symbol.metadata["field"] = True
        if any(child.type == "static" for child in node.children):
            symbol.metadata["static"] = True
        if (
            value.child_by_field_name("body") is not None
            and value.child_by_field_name("body").type != "statement_block"
        ):
            symbol.metadata["returns_value"] = True
        self._push_children(value, symbol.key)

    def _class(self, node: Node, owner: int | None, context: _Context) -> None:
        name = self._text(node.child_by_field_name("name")) or context.name or "default"
        symbol = self._new_symbol(name, SymbolKind.CLASS, node, owner, context)
        if symbol is None:
            return
        heritage = next(
            (child for child in node.named_children if child.type == "class_heritage"), None
        )
        if heritage is not None:
            extends, implements = self._heritage(heritage)
            if extends:
                symbol.metadata["bases"] = [extends]
                if _REACT_BASES.match(extends):
                    symbol.kind = SymbolKind.COMPONENT
            if implements:
                symbol.metadata["implements"] = implements
        body = node.child_by_field_name("body")
        header_end = body.start_byte if body is not None else node.end_byte
        header = self.source[node.start_byte : header_end].decode("utf-8", errors="replace")
        symbol.signature = compact(header.split("{")[0] if "{" in header else header)
        if body is not None:
            self._stack.append((body, symbol.key, _NO_CONTEXT))

    def _heritage(self, heritage: Node) -> tuple[str | None, list[str]]:
        extends: str | None = None
        implements: list[str] = []
        for child in heritage.named_children:
            if child.type == "extends_clause":  # TypeScript grammar
                value = child.child_by_field_name("value")
                extends = compact(self._text(value), 120) if value is not None else None
            elif child.type == "implements_clause":
                implements = [compact(self._text(item), 120) for item in child.named_children]
            elif child.type != "comment" and extends is None:  # JavaScript grammar
                extends = compact(self._text(child), 120)
        return extends, implements

    def _declarator(self, node: Node, owner: int | None, context: _Context) -> None:
        name_node = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if value is None:
            return
        if name_node is None or name_node.type != "identifier":
            self._stack.append((value, owner, _NO_CONTEXT))  # destructuring (e.g. require)
            return
        name = self._text(name_node)
        target, wrapper = value, None
        if value.type == "call_expression":
            callee = self._text(value.child_by_field_name("function"))
            arguments = value.child_by_field_name("arguments")
            first = self._first_argument(arguments)
            if (
                callee in _COMPONENT_WRAPPERS
                and first is not None
                and first.type in _FUNCTION_VALUES
            ):
                target, wrapper = first, callee.split(".")[-1]
        if target.type in _FUNCTION_VALUES or target.type == "class":
            self._stack.append((target, owner, replace(context, name=name, wrapper=wrapper)))
            return
        if context.exported and owner is None:
            symbol = self._new_symbol(name, SymbolKind.VARIABLE, node, owner, context)
            if symbol is not None:
                type_node = node.child_by_field_name("type")
                annotation = f": {self._type_text(type_node)}" if type_node is not None else ""
                symbol.signature = compact(f"const {name}{annotation}")
                self._stack.append((value, symbol.key, _NO_CONTEXT))
                return
        self._stack.append((value, owner, _NO_CONTEXT))

    def _type_declaration(self, node: Node, owner: int | None, context: _Context) -> None:
        name = self._text(node.child_by_field_name("name"))
        symbol = self._new_symbol(name, _TYPE_NODES[node.type], node, owner, context)
        if symbol is None:
            return
        body = node.child_by_field_name("body") or node.child_by_field_name("value")
        header_end = body.start_byte if body is not None else node.end_byte
        header = self.source[node.start_byte : header_end].decode("utf-8", errors="replace")
        symbol.signature = compact(header.rstrip("= ").rstrip())
        extends = next((c for c in node.named_children if c.type == "extends_type_clause"), None)
        if extends is not None:
            symbol.metadata["extends"] = [
                compact(self._text(item), 120) for item in extends.named_children
            ]

    def _describe_callable(self, node: Node, symbol: ExtractedSymbol, prefix: str) -> None:
        symbol.is_async = any(child.type == "async" for child in node.children)
        parameters_node = node.child_by_field_name("parameters") or node.child_by_field_name(
            "parameter"
        )
        symbol.parameters = self._parameters(parameters_node)
        return_node = node.child_by_field_name("return_type")
        symbol.return_type = self._type_text(return_node) if return_node is not None else None
        parameters_text = (
            compact(self._text(parameters_node)) if parameters_node is not None else "()"
        )
        if not parameters_text.startswith("("):
            parameters_text = f"({parameters_text})"
        type_parameters = node.child_by_field_name("type_parameters")
        generics = compact(self._text(type_parameters), 120) if type_parameters is not None else ""
        signature = f"{prefix}{symbol.name}{generics}{parameters_text}"
        if symbol.return_type:
            signature += f": {symbol.return_type}"
        symbol.signature = f"async {signature}" if symbol.is_async else signature

    def _parameters(self, node: Node | None) -> list[Parameter]:
        if node is None:
            return []
        if node.type == "identifier":  # `x => …`
            return [Parameter(name=self._text(node))]
        parameters: list[Parameter] = []
        for child in node.named_children:
            if child.type == "comment":
                continue
            if child.type in ("required_parameter", "optional_parameter"):
                pattern = child.child_by_field_name("pattern")
                if pattern is None or self._text(pattern) == "this":
                    continue
                parameter = self._pattern_parameter(pattern)
                type_node = child.child_by_field_name("type")
                value = child.child_by_field_name("value")
                if type_node is not None:
                    parameter.type = self._type_text(type_node)
                if value is not None:
                    parameter.default = compact(self._text(value), 120)
                parameter.optional = child.type == "optional_parameter"
            else:
                parameter = self._pattern_parameter(child)
            parameters.append(parameter)
        return parameters

    def _pattern_parameter(self, node: Node) -> Parameter:
        if node.type == "identifier":
            return Parameter(name=self._text(node))
        if node.type == "assignment_pattern":
            left = node.child_by_field_name("left")
            parameter = self._pattern_parameter(left) if left is not None else Parameter(name="")
            parameter.default = compact(self._text(node.child_by_field_name("right")), 120)
            return parameter
        if node.type == "rest_pattern":
            return Parameter(name=self._text(node).lstrip("."), kind="rest")
        if node.type in ("object_pattern", "array_pattern"):
            return Parameter(name=compact(self._text(node), 120), kind="destructured")
        return Parameter(name=compact(self._text(node), 120))

    def _type_text(self, node: Node) -> str:
        return compact(self._text(node).lstrip().removeprefix(":").strip(), 200)

    def _decorators(self, node: Node) -> list[str]:
        return [
            compact(self._text(child).lstrip("@"), 120)
            for child in node.children
            if child.type == "decorator"
        ]

    # -- imports and exports -------------------------------------------------

    def _import_statement(self, node: Node) -> None:
        module = self._string_value(node.child_by_field_name("source"))
        if module is None:
            return
        imported = ExtractedImport(
            module=module,
            kind="side_effect",
            start_line=start_line(node),
            end_line=end_line(node),
            is_type_only=any(child.type == "type" for child in node.children),
        )
        clause = next(
            (child for child in node.named_children if child.type == "import_clause"), None
        )
        if clause is not None:
            imported.kind = "import"
            for part in clause.named_children:
                if part.type == "identifier":
                    imported.names.append(ImportedName(name="default", alias=self._text(part)))
                elif part.type == "namespace_import":
                    alias = next((c for c in part.named_children if c.type == "identifier"), None)
                    imported.names.append(ImportedName(name="*", alias=self._text(alias) or None))
                elif part.type == "named_imports":
                    for specifier in part.named_children:
                        if specifier.type != "import_specifier":
                            continue
                        imported.names.append(
                            ImportedName(
                                name=self._text(specifier.child_by_field_name("name")),
                                alias=self._text(specifier.child_by_field_name("alias")) or None,
                            )
                        )
        self.result.imports.append(imported)

    def _export_statement(self, node: Node, owner: int | None) -> None:
        is_default = any(child.type == "default" for child in node.children)
        decorators = tuple(
            compact(self._text(child).lstrip("@"), 120)
            for child in node.children
            if child.type == "decorator"
        )
        line = start_line(node)
        source = node.child_by_field_name("source")
        clause = next(
            (child for child in node.named_children if child.type == "export_clause"), None
        )

        if source is not None:  # re-export: export … from "module"
            module = self._string_value(source) or ""
            imported = ExtractedImport(
                module=module,
                kind="re_export",
                start_line=line,
                end_line=end_line(node),
                is_type_only=any(child.type == "type" for child in node.children),
            )
            namespace = next((c for c in node.named_children if c.type == "namespace_export"), None)
            if clause is not None:
                for name, alias in self._export_specifiers(clause):
                    imported.names.append(ImportedName(name=name, alias=alias))
                    self.result.exports.append(
                        ExportedName(name=alias or name, kind="re_export", source=module, line=line)
                    )
            elif namespace is not None:
                alias = (
                    self._text(namespace.named_children[-1]) if namespace.named_children else None
                )
                imported.names.append(ImportedName(name="*", alias=alias))
                self.result.exports.append(
                    ExportedName(name=alias or "*", kind="namespace", source=module, line=line)
                )
            else:
                imported.names.append(ImportedName(name="*"))
                self.result.exports.append(
                    ExportedName(name="*", kind="re_export", source=module, line=line)
                )
            self.result.imports.append(imported)
            return

        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            context = _Context(exported=True, default=is_default, decorators=decorators, outer=node)
            self._stack.append((declaration, owner, context))
            self._record_declaration_exports(declaration, is_default, line)
            return

        value = node.child_by_field_name("value")
        if value is not None and is_default:
            if value.type == "identifier":
                local = self._text(value)
                self.result.exports.append(
                    ExportedName(name="default", local_name=local, kind="default", line=line)
                )
            elif value.type in _FUNCTION_VALUES or value.type in _CLASS_NODES:
                local = self._text(value.child_by_field_name("name")) or "default"
                self.result.exports.append(
                    ExportedName(name="default", local_name=local, kind="default", line=line)
                )
                context = _Context(exported=True, default=True, outer=node, name=local)
                self._stack.append((value, owner, context))
            else:
                self.result.exports.append(ExportedName(name="default", kind="default", line=line))
                self._stack.append((value, owner, _NO_CONTEXT))
            return

        if clause is not None:  # export { a, b as c }
            for name, alias in self._export_specifiers(clause):
                self.result.exports.append(
                    ExportedName(name=alias or name, local_name=name, kind="named", line=line)
                )

    def _record_declaration_exports(self, declaration: Node, is_default: bool, line: int) -> None:
        names: list[str] = []
        if declaration.type in ("lexical_declaration", "variable_declaration"):
            for child in declaration.named_children:
                name_node = (
                    child.child_by_field_name("name")
                    if child.type == "variable_declarator"
                    else None
                )
                if name_node is not None and name_node.type == "identifier":
                    names.append(self._text(name_node))
        else:
            name = self._text(declaration.child_by_field_name("name"))
            names.append(name or "default")
        for name in names:
            exported = ExportedName(
                name="default" if is_default else name,
                local_name=name,
                kind="default" if is_default else "named",
                line=line,
            )
            # TypeScript overloads declare the same export several times.
            if not any(
                (e.name, e.local_name, e.kind)
                == (exported.name, exported.local_name, exported.kind)
                for e in self.result.exports
            ):
                self.result.exports.append(exported)

    def _export_specifiers(self, clause: Node) -> list[tuple[str, str | None]]:
        return [
            (
                self._text(specifier.child_by_field_name("name")),
                self._text(specifier.child_by_field_name("alias")) or None,
            )
            for specifier in clause.named_children
            if specifier.type == "export_specifier"
        ]

    def _commonjs_export(self, node: Node, owner: int | None) -> None:
        assignment = node.named_children[0] if node.named_children else None
        if assignment is None or assignment.type != "assignment_expression" or owner is not None:
            self._push_children(node, owner)
            return
        left = "".join(self._text(assignment.child_by_field_name("left")).split())
        right = assignment.child_by_field_name("right")
        line = start_line(node)
        if right is None or not (
            left == "module.exports" or left.startswith(("exports.", "module.exports."))
        ):
            self._push_children(node, owner)
            return

        if left == "module.exports":
            if right.type == "identifier":
                self.result.exports.append(
                    ExportedName(
                        name="default", local_name=self._text(right), kind="commonjs", line=line
                    )
                )
            elif right.type == "object":
                for item in right.named_children:
                    if item.type == "shorthand_property_identifier":
                        name = self._text(item)
                        self.result.exports.append(
                            ExportedName(name=name, local_name=name, kind="commonjs", line=line)
                        )
                    elif item.type == "pair":
                        value = item.child_by_field_name("value")
                        self.result.exports.append(
                            ExportedName(
                                name=self._text(item.child_by_field_name("key")),
                                local_name=self._text(value)
                                if value is not None and value.type == "identifier"
                                else None,
                                kind="commonjs",
                                line=line,
                            )
                        )
            self._stack.append((right, owner, _NO_CONTEXT))
            return

        name = left.rsplit(".", 1)[-1]
        if right.type in _FUNCTION_VALUES or right.type == "class":
            self.result.exports.append(
                ExportedName(name=name, local_name=name, kind="commonjs", line=line)
            )
            self._stack.append((right, owner, _Context(exported=True, outer=node, name=name)))
            return
        local = self._text(right) if right.type == "identifier" else None
        self.result.exports.append(
            ExportedName(name=name, local_name=local, kind="commonjs", line=line)
        )
        self._stack.append((right, owner, _NO_CONTEXT))

    # -- calls, JSX, API calls ---------------------------------------------------

    def _call(self, node: Node, owner: int | None) -> None:
        function = node.child_by_field_name("function")
        arguments = node.child_by_field_name("arguments")
        if function is None:
            return
        first = self._first_argument(arguments)

        if function.type == "import":  # import("./module")
            module = self._string_value(first)
            if module is not None:
                self.result.imports.append(
                    ExtractedImport(
                        module=module,
                        kind="dynamic",
                        start_line=start_line(node),
                        end_line=end_line(node),
                    )
                )
            return

        callee = self._record_call(function, node, owner)
        if callee is None:
            return
        if callee == "require":
            module = self._string_value(first)
            if module is not None:
                self._require(node, module)
            return
        if owner is not None and _HOOK_NAME.match(callee.rsplit(".", 1)[-1]):
            hooks = self.result.symbols[owner].metadata.setdefault("hooks", [])
            hook = callee.rsplit(".", 1)[-1]
            if hook not in hooks:
                hooks.append(hook)
        self._api_call(callee, arguments, node, owner)

    def _record_call(self, function: Node | None, node: Node, owner: int | None) -> str | None:
        if function is None or function.type not in ("identifier", "member_expression"):
            return None
        callee = "".join(self._text(function).split()).replace("?.", ".")
        if "(" in callee or "[" in callee or len(callee) > 200:
            return None
        if callee != "require":
            self.result.calls.append(
                ExtractedCall(callee=callee, line=start_line(node), caller_key=owner)
            )
        return callee

    def _require(self, node: Node, module: str) -> None:
        imported = ExtractedImport(
            module=module, kind="require", start_line=start_line(node), end_line=end_line(node)
        )
        parent = node.parent
        if parent is not None and parent.type == "variable_declarator":
            pattern = parent.child_by_field_name("name")
            if pattern is not None and pattern.type == "identifier":
                imported.names.append(ImportedName(name="*", alias=self._text(pattern)))
            elif pattern is not None and pattern.type == "object_pattern":
                for item in pattern.named_children:
                    if item.type == "shorthand_property_identifier_pattern":
                        imported.names.append(ImportedName(name=self._text(item)))
                    elif item.type == "pair_pattern":
                        imported.names.append(
                            ImportedName(
                                name=self._text(item.child_by_field_name("key")),
                                alias=self._text(item.child_by_field_name("value")) or None,
                            )
                        )
        self.result.imports.append(imported)

    def _api_call(self, callee: str, arguments: Node | None, node: Node, owner: int | None) -> None:
        """Record HTTP calls whose URL is a literal (or template literal) in the source."""
        first = self._first_argument(arguments)
        url = self._url_literal(first)
        method: str | None = None
        client: str

        if callee in _FETCH_CALLEES:
            client = callee.rsplit(".", 1)[-1]
            method = self._option(self._nth_argument(arguments, 1), "method") or "GET"
        elif callee in ("axios", "ky", "got") and first is not None and first.type == "object":
            client = callee
            url = self._url_literal(self._pair_value(first, "url"))
            method = self._option(first, "method") or "GET"
        elif "." in callee:
            obj, _, prop = callee.rpartition(".")
            client = obj.rsplit(".", 1)[-1]
            if prop.lower() not in _HTTP_METHODS:
                return
            if client not in _HTTP_CLIENTS and not (url or "").startswith(
                ("/", "http://", "https://")
            ):
                return
            method = prop.upper()
        else:
            return
        if url is None:
            return
        self.result.api_calls.append(
            ApiCall(
                client=client,
                method=method.upper(),
                url=url,
                line=start_line(node),
                caller_key=owner,
            )
        )

    def _jsx(self, node: Node, owner: int | None) -> None:
        if owner is not None:
            self.result.symbols[owner].metadata["has_jsx"] = True
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return  # fragment <>
        name = self._text(name_node)
        if name[:1].isupper():  # lower-case names are HTML elements
            self.result.calls.append(
                ExtractedCall(callee=name, line=start_line(node), caller_key=owner, kind="render")
            )

    # -- literal helpers ---------------------------------------------------------

    def _string_value(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type == "string":
            return self._text(node)[1:-1]
        if node.type == "template_string" and not any(
            c.type == "template_substitution" for c in node.named_children
        ):
            return self._text(node)[1:-1]
        return None

    def _url_literal(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type == "string":
            return self._text(node)[1:-1] or None
        if node.type == "template_string":
            parts: list[str] = []
            for child in node.named_children:
                if child.type == "template_substitution":
                    inner = compact(self._text(child)[2:-1], 40)
                    parts.append("{" + inner + "}")
                else:
                    parts.append(self._text(child))
            return "".join(parts) or None
        return None

    def _first_argument(self, arguments: Node | None) -> Node | None:
        return self._nth_argument(arguments, 0)

    def _nth_argument(self, arguments: Node | None, index: int) -> Node | None:
        if arguments is None:
            return None
        values = [child for child in arguments.named_children if child.type != "comment"]
        return values[index] if len(values) > index else None

    def _pair_value(self, obj: Node | None, key: str) -> Node | None:
        if obj is None or obj.type != "object":
            return None
        for item in obj.named_children:
            if (
                item.type == "pair"
                and self._text(item.child_by_field_name("key")).strip("'\"") == key
            ):
                return item.child_by_field_name("value")
        return None

    def _option(self, obj: Node | None, key: str) -> str | None:
        return self._string_value(self._pair_value(obj, key))

    def _has_value(self, node: Node) -> bool:
        return any(child.type != "comment" for child in node.named_children)

    # -- comments ------------------------------------------------------------------

    def _doc_comments(self, node: Node) -> tuple[str | None, str | None]:
        comments = preceding_comments(node)
        if not comments:
            return None, None
        last = self._text(comments[-1])
        if last.startswith("/**"):
            return self._clean_block_comment(last), None
        lines = [self._text(comment).lstrip("/").strip() for comment in comments]
        return None, "\n".join(line for line in lines if line)[:1000] or None

    def _clean_block_comment(self, text: str) -> str | None:
        body = text.removeprefix("/**").removeprefix("/*").removesuffix("*/")
        lines = [line.strip().removeprefix("*").removeprefix(" ") for line in body.splitlines()]
        return clean_docstring("\n".join(lines))

    def _file_comment(self, root: Node) -> str | None:
        """A comment block at the top of the file, separated from the code below by a blank line."""
        children = root.children
        if not children or children[0].type != "comment":
            return None
        block = [children[0]]
        for child in children[1:]:
            if child.type == "comment" and child.start_point.row <= block[-1].end_point.row + 1:
                block.append(child)
            else:
                if child.start_point.row <= block[-1].end_point.row + 1:
                    return None  # attached to the first declaration: that symbol's doc
                break
        texts = [self._text(comment) for comment in block]
        if texts[0].startswith("/*"):
            return self._clean_block_comment(texts[0])
        return clean_docstring("\n".join(text.lstrip("/").strip() for text in texts))

    # -- post-processing --------------------------------------------------------

    def _finalize(self) -> None:
        symbols = self.result.symbols
        top_level = {symbol.name: symbol for symbol in symbols if symbol.parent_key is None}

        for exported in self.result.exports:
            symbol = top_level.get(exported.local_name or "")
            if symbol is None:
                continue
            symbol.is_exported = True
            if exported.kind == "default" or exported.name == "default":
                symbol.metadata["default_export"] = True
            elif exported.name != symbol.name:
                aliases = symbol.metadata.setdefault("export_names", [])
                if exported.name not in aliases:
                    aliases.append(exported.name)

        calls: dict[int, list[str]] = {}
        renders: dict[int, list[str]] = {}
        for call in self.result.calls:
            if call.caller_key is None:
                continue
            bucket = renders if call.kind == "render" else calls
            names = bucket.setdefault(call.caller_key, [])
            if call.callee not in names and len(names) < 50:
                names.append(call.callee)
        for api_call in self.result.api_calls:
            if api_call.caller_key is not None:
                symbols[api_call.caller_key].metadata.setdefault("api_calls", []).append(
                    api_call.to_dict()
                )

        for symbol in symbols:
            if symbol.key in calls:
                symbol.metadata["calls"] = calls[symbol.key]
            if symbol.key in renders:
                symbol.metadata["renders"] = renders[symbol.key]
            is_function = symbol.kind is SymbolKind.FUNCTION
            capitalised = symbol.name[:1].isupper() or symbol.name == "default"
            if (
                is_function
                and capitalised
                and (symbol.metadata.get("has_jsx") or symbol.metadata.get("wrapper"))
            ):
                symbol.kind = SymbolKind.COMPONENT
            if is_function and _HOOK_NAME.match(symbol.name):
                symbol.metadata["react_hook"] = True
