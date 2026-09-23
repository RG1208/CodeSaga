# Source-Code Analysis (Phase 3)

CodeSage parses repositories into a **structural representation** — files, symbols,
imports and a dependency graph — instead of treating code as plain text. Later phases
(retrieval, RAG, code review) build on these tables.

Not in this phase: embeddings, BM25/search indexes, RAG, LLM features, code review.

## Where it runs

Analysis is the **PARSING** stage of the existing indexing job:

```
queued → cloning → analyzing → indexing → parsing → completed
```

It runs on the temporary checkout, and its results are written in the same final
transaction as the file index. A failed re-index therefore keeps the previous
symbols and graph. Repositories indexed before Phase 3 have no analysis until they
are re-indexed.

## Pipeline (`backend/app/analysis/`)

```
indexed text files ──▶ registry: which analyzer?  (.py → Python, .ts → TypeScript, .tsx → TSX, .js/.jsx/.mjs/.cjs → JavaScript)
                          │
                          ▼
                 Tree-sitter parse → syntax tree ──▶ language analyzer ──▶ FileAnalysis
                                                    (symbols, imports, calls, exports, API calls)
                          │
                          ▼
                 ImportResolver: specifier → repository file (confirmed / inferred / external / unresolved)
                          │
                          ▼
                 DependencyGraphBuilder: imports, calls, renders, inherits edges
                          │
                          ▼
                 rows for code_files, code_symbols, code_imports, code_relationships (+ summary)
```

| Module | Responsibility |
| --- | --- |
| `results.py` | Plain dataclasses: `ExtractedSymbol`, `ExtractedImport`, `ExtractedCall`, `ExportedName`, `ApiCall`, `FileAnalysis`; enums `SymbolKind`, `RelationshipType`, `Confidence`, `ParseStatus`. No Tree-sitter or database types. |
| `base.py` | `LanguageAnalyzer` interface, `TreeSitterAnalyzer` base, helpers (text, line numbers, non-recursive tree walk, comments). |
| `python.py` | `PythonAnalyzer`. |
| `ecmascript.py` | `JavaScriptAnalyzer`, `TypeScriptAnalyzer`, `TsxAnalyzer` — one shared extractor, three grammars. |
| `registry.py` | Extension → analyzer. **Adding a language = one analyzer class + one `register()` line.** |
| `resolver.py` | Import resolution for Python and JS/TS, incl. tsconfig/jsconfig `paths`, `baseUrl`, `extends`. |
| `graph.py` | Relationship building and repository summary statistics. |
| `repository.py` | Orchestrates a whole checkout; returns database-ready rows with pre-assigned UUIDs. |

### Why Tree-sitter

Tree-sitter is an incremental parser with grammars for most languages. It is fast
(FastAPI's 1,142 Python files parse in a few seconds), **tolerates syntax errors**
(it still returns a tree with `ERROR` nodes), gives exact line ranges, and — unlike
Python's `ast` module — handles every language with one API. It only builds a
syntax tree: no code is imported, compiled or executed.

## What is extracted

Every parsed file records its **path, language, size, line count, content hash, parse
status**, docstring/top comment, exports, API calls and comment-line count.

| Item | Python | JavaScript / TypeScript / TSX |
| --- | --- | --- |
| Functions | `def`, `async def`, nested functions | declarations, arrow functions and function expressions assigned to a name, generators, `exports.x = () => …` |
| Classes | `class` with bases and keywords (e.g. `metaclass`) | classes, abstract classes, `extends` / `implements` |
| Methods | functions in a class body; `@staticmethod` / `@classmethod` / `@property` noted | methods, getters/setters, static, constructors, arrow-function class fields |
| Types | — | `interface`, `type` aliases, `enum` |
| Constants | — | exported top-level `const`/`let`/`var` |
| Parameters | name, type, default, kind (positional-only, keyword-only, `*args`, `**kwargs`) | name, type, default, optional (`?`), rest (`...`), destructured patterns |
| Return information | return annotation; whether it returns a value; generator | return type annotation; returns a value; generator |
| Decorators | `@decorator(...)` text | `@Decorator(...)` on classes, methods, fields |
| Docstrings / comments | docstrings; `#` comments directly above a definition | `/** JSDoc */` blocks; `//` comments directly above |
| Locations | start/end line (1-based, inclusive, **including decorators**); `definition_line` of the `def` | start/end line (including decorators and `export`) |
| Parent symbol | methods → class; nested functions → enclosing function | methods/fields → class; nested named functions → enclosing function |
| Imports | `import a.b as c`, `from .x import y as z`, `from x import *`, relative levels, imports inside functions, `if TYPE_CHECKING:` (type-only) | default, named, namespace, `import type`, side-effect, `require()` (incl. destructuring), dynamic `import()`, re-exports |
| Exports | `__all__`, otherwise public top-level names | `export` declarations, `export default`, `export { a as b }`, re-exports, CommonJS `module.exports` / `exports.x` |
| React | — | **components** (functions returning JSX, `memo`/`forwardRef`/`observer` wrappers, `React.Component` classes), **hooks used** (`useX` calls), custom hooks (`useX` functions), **components rendered** (`<Card />`) |
| API calls | — | `fetch`, `axios` (and `.get/.post/…`), `ky`, `got`, `useSWR`, and `<client>.<method>("/path")` — **only when the URL is a literal or template literal** (`/api/users/{id}`) |

Files with syntax errors are stored with `parse_status = "partial"`: everything
Tree-sitter could understand is still extracted. Very large files
(`MAX_PARSED_FILE_SIZE_KB`, default 512 KB), binary files and minified bundles
(`*.min.js`) are not parsed.

## Import resolution

| Import | Rule | Confidence |
| --- | --- | --- |
| Python relative (`from ..models import User`) | Walk up from the importing file's package; `models.py` or `models/__init__.py` | confirmed |
| Python absolute (`from app.core import config`) | Match against every importable dotted name. A directory is a possible source root if it is the repo root or has no `__init__.py` (so `backend/app/core/config.py` is `app.core.config`). Submodules named in `from pkg import sub` resolve to `pkg/sub.py`. | confirmed if exactly one file matches; **inferred** (closest to the importer) if several do |
| Python stdlib / third-party | No repository match | external (package name recorded) |
| JS/TS relative (`./api`, `../components/Card`) | Try the path, then `.ts .tsx .d.ts .js .jsx .mjs .cjs .mts .cts`, then `index.*`; `./util.js` also finds `util.ts` | confirmed |
| JS/TS aliases (`@/lib/api`, `src/util`) | Nearest `tsconfig.json`/`jsconfig.json`: `compilerOptions.paths`, `baseUrl`, relative `extends` (JSON with comments supported) | confirmed |
| Bare specifiers (`react`, `@scope/pkg/sub`) | No alias match | external (`react`, `@scope/pkg`) |
| Paths escaping the repository | `../../../etc/passwd` | unresolved |

Imports of files that exist but are not parsed (e.g. `import logo from "./logo.png"`)
resolve to their path but create no graph edge.

## Dependency graph: confirmed vs inferred

| Relationship | From → to | How it is found | Confidence |
| --- | --- | --- | --- |
| `imports` | file → file | An import resolved to exactly one repository file | **confirmed** (inferred only for ambiguous Python module paths) |
| `calls` | symbol → symbol | A call inside a function/method matched by name | **inferred** |
| `renders` | component → component | A JSX element `<Name />` matched by name | **inferred** |
| `inherits` | class → class | A base class name matched by name | **inferred** |

Symbol-level edges are **always inferred**: static analysis cannot prove which
function runs at run time (shadowed names, dynamic dispatch, dependency injection,
values passed as arguments). CodeSage resolves a call only through these strategies
and records which one was used (`metadata.resolution`):

| Strategy | Example |
| --- | --- |
| `same_file` | `helper()` where `helper` is defined at the top of the same file; `LocalClass.method()` |
| `import` | `slugify()` after `from shop.utils import slugify` (aliases and TS barrel re-exports followed) |
| `namespace` | `utils.slugify()` after `from shop import utils`; `api.getUsers()` after `import * as api` |
| `self` | `self.check()` / `this.log()` → a method of the enclosing class |
| `self_inherited` | `self.validate()` found on a base class that itself resolves |

Everything else is **left out, never guessed** — for example `service.save()` where
`service` is a parameter. Edges are aggregated: one row per (source, target, type)
with `weight` = number of occurrences and example lines/expressions in metadata.

## Database

```
repositories 1 ── * code_files 1 ── * code_symbols ─┐ parent_symbol_id (tree)
                               │                     └─┘
                               └── * code_imports ── resolved_file_id → code_files
code_relationships: source/target file → code_files, source/target symbol → code_symbols
```

| Table | Key columns |
| --- | --- |
| `code_files` | `repository_id`, `path` (unique per repository), `language`, `size_bytes`, `line_count`, `content_sha256`, `parse_status`, `symbol_count`, `import_count`, `metadata` (docstring, exports, API calls, syntax error count) |
| `code_symbols` | `repository_id`, `file_id`, `parent_symbol_id`, `name`, `qualified_name` (`ProductService.save`), `kind`, `start_line`, `end_line`, `signature`, `docstring`, `return_type`, `is_exported`, `is_async`, `parameters` (JSON), `decorators` (JSON), `metadata` (calls, renders, hooks, API calls, bases, comment…) |
| `code_imports` | `repository_id`, `file_id`, `module` (as written), `kind`, `names` (JSON), `start_line`, `end_line`, `is_type_only`, `resolution_status`, `resolved_path`, `resolved_file_id`, `metadata` (confidence, strategy, candidates, package, name targets) |
| `code_relationships` | `repository_id`, `relationship_type`, `confidence`, `source_file_id`, `target_file_id`, `source_symbol_id`, `target_symbol_id`, `weight`, `metadata` |

Repository-level statistics (symbols by kind, relationships by type and confidence,
most-imported files, external packages) are stored in `repositories.repo_metadata.analysis`.

## API

All under `/api/v1/repositories/{repository_id}`:

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/files?analyzed=&path_prefix=&limit=&offset=` | Every indexed file with `analyzed`, `parser`, `parse_status`, `symbol_count` (limit up to 20,000 for file trees) |
| GET | `/files/content?path=` | File text from the checkout (only indexed paths; `..`, absolute and backslash paths rejected with 422) |
| GET | `/files/detail?path=` | Symbols, imports (with resolution), exports, API calls, `depends_on` and `imported_by` files |
| GET | `/files/symbols?path=` | Symbols of one file, in line order (build the tree with `parent_symbol_id`) |
| GET | `/symbols?q=&kind=&path_prefix=&exported=` | Repository-wide symbol search (exact name matches first) |
| GET | `/dependencies?type=&confidence=&path=&symbol_id=&direction=` | Relationships with file paths and symbol references |

## Frontend: code explorer (`/repositories/{id}/code`)

| Area | What it shows |
| --- | --- |
| File tree | All indexed files; filter box; "parsed source files only"; symbol counts |
| Source viewer | Line-numbered source; the selected symbol's line range is highlighted and scrolled into view |
| Symbols tab | Outline tree (classes → methods) with kind, export marker and line range; details: signature, docstring, parameters, return type, decorators, bases, hooks, API calls, **uses / used by** |
| Imports & exports tab | Each import with its kind, names, resolved file (clickable) or package, and confidence; exports; API calls |
| Dependencies view | Two diagrams: files that import this file → file → files it imports, and callers → selected symbol → callees. **Solid lines are confirmed, dashed lines inferred** (not colour alone). Nodes are clickable. |
| Symbol search | Search across the repository; selecting a result opens its file at the symbol |
| Overview | Files parsed, symbols by kind, confirmed imports, inferred calls, most-imported files, external packages |

The selected file and symbol live in the URL (`?path=…&symbol=…`), so views can be
bookmarked and the browser back button works.

## Adding a language

1. `pip install tree-sitter-<language>` and add it to `backend/requirements.txt`.
2. Create `app/analysis/<language>.py` with a `TreeSitterAnalyzer` subclass that fills a
   `FileAnalysis` (symbols, imports, calls, exports). Use `python.py` as a template.
3. Register it in `registry.default_registry()`.
4. Optional: teach `resolver.py` the language's import rules to get file-level edges.
5. Add a small fixture project under `backend/tests/fixtures/code/` and tests.

No database, API or frontend changes are required.

## Known limitations

- **Name-based call resolution.** Calls through parameters, attributes of objects, return
  values, callbacks, `getattr`, dependency injection or dynamic imports are not linked.
- **No type inference.** `user.save()` is not resolved even if `user: User` is annotated.
- **Grammar gaps.** Some newer TypeScript syntax is not supported by the current
  `tree-sitter-typescript` grammar (e.g. call signatures in type literals without a
  separator, `typeof import("x")` as a type argument); such files are marked `partial`.
- **Monorepo resolution** follows the nearest tsconfig/jsconfig only; `package.json`
  workspaces, Node `exports` maps and Python `sys.path` manipulation are not modelled.
- **Parsing runs inside the API process** (thread-pool jobs). A native crash in a parser
  would stop the backend; `tree-sitter` is pinned to 0.25.2 because 0.26.0 crashed while
  parsing larger files. A separate worker process (planned with a real job queue) would
  isolate this.
- The dependency diagram shows up to 12 neighbours per side (`+N more`); there is no
  whole-repository graph view yet.
- No syntax highlighting in the source viewer; files over 5,000 lines show the first 5,000.
