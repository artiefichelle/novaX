"""File-based, explicit module imports with public definitions and source spans."""
from pathlib import Path
from dataclasses import dataclass, fields
from frontend import (Program, Node, Expr, StructType, Call, StructLiteral,
                      CompileError, Analyzer, parse_source, BUILTINS)

MAX_MODULES = 128
MAX_DEPTH = 32
MAX_TOTAL_BYTES = 4 * 1024 * 1024


@dataclass
class Unit:
    program: Program
    prefix: str
    imports: dict


class Loader:
    def __init__(self):
        self.units = {}
        self.active = set()
        self.total_bytes = 0

    def read(self, path, span=None, depth=0):
        path = Path(path).resolve()
        if path in self.active: raise CompileError('Circular import: '+str(path), span)
        if path in self.units: return self.units[path]
        if depth > MAX_DEPTH: raise CompileError('Import nesting exceeds 32 levels', span)
        if len(self.units) >= MAX_MODULES: raise CompileError('Program exceeds 128 source modules', span)
        try:
            with path.open('rb') as handle: raw = handle.read(MAX_TOTAL_BYTES+1)
            self.total_bytes += len(raw)
            if self.total_bytes > MAX_TOTAL_BYTES: raise CompileError('Program source exceeds 4 MiB', span)
            text = raw.decode('utf-8')
        except (OSError, UnicodeError) as exc:
            raise CompileError('Cannot read source module '+str(path)+': '+str(exc), span) from None
        program = parse_source(text, str(path))
        unit = Unit(program, '' if not self.units else 'module'+str(len(self.units)), {})
        if unit.prefix and any(fn.name == 'main' for fn in program.functions):
            raise CompileError('Imported modules cannot define main', program.span)
        for fn in program.functions:
            if fn.name in BUILTINS: raise CompileError('Reserved name: '+fn.name, fn.span)
        local_types = {definition.name: definition for definition in program.structs}
        for definition in [*program.functions, *program.structs]:
            if not definition.public: continue
            signatures = ([definition.returns]+[arg.typ for arg in definition.args]
                          if hasattr(definition, 'returns') else [member.typ for member in definition.fields])
            for typ in signatures:
                if isinstance(typ, StructType) and typ.name in local_types and not local_types[typ.name].public:
                    raise CompileError('Public API exposes private struct: '+typ.name, definition.span)

        self.units[path] = unit
        self.active.add(path)
        for imported in program.imports:
            if imported.alias in unit.imports: raise CompileError('Duplicate import alias: '+imported.alias, imported.span)
            target = Path(imported.path)
            if target.is_absolute(): raise CompileError('Import paths must be relative', imported.span)
            if target.suffix != '.nx': raise CompileError('Import paths must name .nx files', imported.span)
            unit.imports[imported.alias] = self.read(path.parent/target, imported.span, depth+1)
        self.active.remove(path)
        return unit

    def canonical(self, unit, name):
        return unit.prefix+'::'+name if unit.prefix else name

    def reference(self, unit, name, kind, span):
        if '::' not in name:
            if kind == 'function' and name in BUILTINS: return name
            return self.canonical(unit, name)
        pieces = name.split('::')
        if len(pieces) != 2: raise CompileError('Use a direct import alias for each module', span)
        alias, member = pieces
        target = unit.imports.get(alias)
        if target is None: raise CompileError('Unknown import alias: '+alias, span)
        definitions = target.program.functions if kind == 'function' else target.program.structs
        definition = next((node for node in definitions if node.name == member), None)
        if definition is None: raise CompileError('Unknown exported '+kind+': '+name, span)
        if not definition.public: raise CompileError('Definition is private: '+name, span)
        return self.canonical(target, member)

    def rewrite(self, value, unit):
        if isinstance(value, StructType):
            return StructType(self.reference(unit, value.name, 'type', unit.program.span))
        if isinstance(value, list):
            return [self.rewrite(item, unit) for item in value]
        if isinstance(value, tuple):
            return tuple(self.rewrite(item, unit) for item in value)
        if isinstance(value, Node):
            if isinstance(value, Call): value.name = self.reference(unit, value.name, 'function', value.span)
            if isinstance(value, StructLiteral): value.name = self.reference(unit, value.name, 'type', value.span)
            for member in fields(value):
                if member.name not in ('span', 'name', 'public', 'typ'):
                    setattr(value, member.name, self.rewrite(getattr(value, member.name), unit))
            # Parameter types are declarations; expression types are filled by analysis.
            if not isinstance(value, Expr) and hasattr(value, 'typ'):
                value.typ = self.rewrite(value.typ, unit)
            return value
        return value

    def load(self, path):
        root = self.read(path)
        heights = {}
        def height(unit):
            key = id(unit)
            if key not in heights: heights[key] = max((height(child)+1 for child in unit.imports.values()), default=0)
            return heights[key]
        if height(root) > MAX_DEPTH: raise CompileError('Import nesting exceeds 32 levels', root.program.span)
        functions = []
        structs = []
        # Resolve references before changing any declared names.
        for unit in self.units.values():
            for fn in unit.program.functions: self.rewrite(fn, unit)
            for definition in unit.program.structs: self.rewrite(definition, unit)
        for unit in self.units.values():
            for fn in unit.program.functions:
                fn.name = self.canonical(unit, fn.name); functions.append(fn)
            for definition in unit.program.structs:
                definition.name = self.canonical(unit, definition.name); structs.append(definition)
        combined = Program(root.program.span, functions, structs)
        return Analyzer().analyze(combined), set(self.units)


def load_program(path):
    return Loader().load(path)
