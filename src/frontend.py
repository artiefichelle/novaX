"""NOVA-X syntax and semantic analysis; independent of LLVM and Clang."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import json
import re

MAX_SOURCE_BYTES = 1_048_576
MAX_TOKENS = 100_000
MAX_NESTING = 128


@dataclass(frozen=True)
class Source:
    text: str
    filename: str = '<input>'
    line_starts: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'line_starts', (0,) + tuple(m.end() for m in re.finditer('\n', self.text)))

    def location(self, offset):
        offset = min(max(0, offset), len(self.text))
        line = bisect_right(self.line_starts, offset) - 1
        return line + 1, offset - self.line_starts[line] + 1


@dataclass(frozen=True)
class Span:
    source: Source
    start: int
    end: int


class CompileError(Exception):
    def __init__(self, message, span=None):
        super().__init__(message)
        self.span = span

    def render(self):
        if self.span is None:
            return 'nova error: ' + str(self)
        span = self.span
        line, column = span.source.location(span.start)
        start = span.source.line_starts[line - 1]
        end = span.source.text.find('\n', start)
        if end < 0:
            end = len(span.source.text)
        text = span.source.text[start:end].rstrip('\r')
        # Align a tab-containing source excerpt without altering logical columns.
        prefix = text[:column - 1].expandtabs(4)
        width = max(1, min(span.end - span.start, end - span.start))
        return (f'{span.source.filename}:{line}:{column}: error: {self}\n'
                f'  {text.expandtabs(4)}\n  {" " * len(prefix)}{"^" * width}')


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    span: Span


TOKEN = re.compile(
    r'(?P<WS>\s+)|(?P<COMMENT>//[^\n]*|/\*[\s\S]*?\*/)|'
    r'(?P<STRING>"(?:[^"\\\n]|\\.)*")|(?P<NUM>[0-9]+)|'
    r'(?P<ID>[A-Za-z_][A-Za-z_0-9]*)|'
    r'(?P<OP>::|\+=|-=|\*=|/=|%=|->|==|!=|<=|>=|&&|\|\||[@+*/%(){}\[\];,.:=<>!-])|(?P<BAD>.)'
)
KEYWORDS = {'fn', 'let', 'var', 'return', 'if', 'else', 'while', 'break',
            'continue', 'true', 'false', 'int', 'str', 'bool', 'struct', 'new', 'import', 'as', 'pub'}
TYPES = {'int', 'str', 'bool', 'BoxInt'}
BUILTINS = {'print', 'printf', 'len', 'to_bool', 'to_int', 'box', 'read_box', 'write_box'}


def lex(source):
    if isinstance(source, str):
        source = Source(source)
    if len(source.text.encode('utf-8')) > MAX_SOURCE_BYTES:
        raise CompileError('Source exceeds 1 MiB limit', Span(source, 0, 0))
    tokens = []
    pos = 0
    while pos < len(source.text):
        match = TOKEN.match(source.text, pos)
        span = Span(source, pos, match.end())
        if source.text.startswith('/*', pos) and match.lastgroup != 'COMMENT':
            raise CompileError('Unterminated block comment', span)
        if match.lastgroup == 'BAD':
            message = 'Unterminated string literal' if match.group() == '"' else f'Unexpected character {match.group()!r}'
            raise CompileError(message, span)
        if match.lastgroup not in ('WS', 'COMMENT'):
            tokens.append(Token(match.lastgroup, match.group(), span))
            if len(tokens) > MAX_TOKENS:
                raise CompileError('Source exceeds token limit', span)
        pos = match.end()
    tokens.append(Token('EOF', '<eof>', Span(source, pos, pos)))
    return tokens


MAX_ARRAY_SIZE = 4096


@dataclass(frozen=True)
class ArrayType:
    size: int

    def __str__(self):
        return f'int[{self.size}]'


@dataclass(frozen=True)
class StructType:
    name: str

    def __str__(self):
        return self.name


@dataclass
class Node:
    span: Span


@dataclass
class Expr(Node):
    typ: str | ArrayType | StructType | None = field(init=False, default=None)


@dataclass
class Literal(Expr):
    value: int | str | bool


@dataclass
class Name(Expr):
    name: str


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]


@dataclass
class Unary(Expr):
    op: str
    operand: Expr


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class ArrayLiteral(Expr):
    elements: list[Expr]


@dataclass
class Index(Expr):
    base: Expr
    index: Expr


@dataclass
class IndexAssign(Node):
    target: Index
    value: Expr


@dataclass
class StructLiteral(Expr):
    name: str
    fields: list[tuple[str, Expr]]


@dataclass
class Field(Expr):
    base: Expr
    name: str


@dataclass
class FieldAssign(Node):
    target: Field
    value: Expr


@dataclass
class StructDef(Node):
    name: str
    fields: list[Parameter]
    public: bool = False


@dataclass
class Decl(Node):
    mutable: bool
    name: str
    value: Expr
    annotation: str | ArrayType | StructType | None


@dataclass
class Assign(Node):
    name: str
    value: Expr


@dataclass
class Return(Node):
    value: Expr


@dataclass
class Print(Node):
    value: Expr


@dataclass
class ExprStmt(Node):
    value: Call


@dataclass
class If(Node):
    condition: Expr
    yes: list[Node]
    no: list[Node]


@dataclass
class While(Node):
    condition: Expr
    body: list[Node]


@dataclass
class Transfer(Node):
    kind: str


@dataclass
class Parameter(Node):
    name: str
    typ: str | ArrayType | StructType


@dataclass
class Function(Node):
    name: str
    args: list[Parameter]
    returns: str | ArrayType | StructType
    body: list[Node]
    public: bool = False


@dataclass
class Import(Node):
    path: str
    alias: str


@dataclass
class Program(Node):
    functions: list[Function]
    structs: list[StructDef] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)


class Parser:
    precedence = {'||': 1, '&&': 2, '==': 3, '!=': 3, '<': 4, '>': 4,
                  '<=': 4, '>=': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6}

    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.index]

    def eat(self, expected=None):
        token = self.peek()
        if expected is not None and token.value != expected:
            raise CompileError(f'Expected {expected!r}, got {token.value!r}', token.span)
        if token.kind == 'EOF':
            raise CompileError('Unexpected end of file', token.span)
        self.index += 1
        return token

    def span(self, start):
        return Span(start.source, start.start, self.tokens[max(0, self.index - 1)].span.end)

    def ident(self):
        token = self.peek()
        if token.kind != 'ID' or token.value in KEYWORDS:
            raise CompileError('Expected identifier', token.span)
        return self.eat()

    def qualified_name(self):
        name = self.ident().value
        while self.peek().value == '::':
            self.eat('::')
            name += '::' + self.ident().value
        return name

    def type_name(self):
        token = self.eat()
        if token.value not in TYPES:
            if token.kind == 'ID' and token.value not in KEYWORDS:
                name = token.value
                while self.peek().value == '::':
                    self.eat('::')
                    name += '::' + self.ident().value
                return StructType(name)
            raise CompileError('Expected type int, str, bool, array or struct name', token.span)
        if self.peek().value == '[':
            self.eat('[')
            size = self.eat()
            digits = size.value.lstrip('0') or '0'
            if size.kind != 'NUM' or len(digits) > 4 or int(digits) > MAX_ARRAY_SIZE:
                raise CompileError('Array size must be between 0 and 4096', size.span)
            self.eat(']')
            if token.value != 'int':
                raise CompileError('Only int arrays are supported', token.span)
            return ArrayType(int(digits))
        return token.value

    def parse(self):
        start = self.peek().span
        functions = []
        structs = []
        imports = []
        try:
            while self.peek().kind != 'EOF':
                exported = False
                if self.peek().value == 'pub':
                    self.eat('pub')
                    exported = True
                if self.peek().value == 'import':
                    if exported: raise CompileError('Imports cannot be pub', self.peek().span)
                    start_import = self.eat('import').span
                    token = self.eat()
                    if token.kind != 'STRING': raise CompileError('Expected quoted import path', token.span)
                    try: path = json.loads(token.value)
                    except ValueError: raise CompileError('Invalid import path', token.span) from None
                    if not path or '\x00' in path: raise CompileError('Invalid import path', token.span)
                    self.eat('as')
                    alias = self.ident().value
                    self.eat(';')
                    imports.append(Import(self.span(start_import), path, alias))
                elif self.peek().value == 'struct':
                    definition = self.struct_definition(); definition.public = exported
                    structs.append(definition)
                else:
                    definition = self.function(); definition.public = exported
                    functions.append(definition)
        except RecursionError:
            raise CompileError('Program exceeds nesting limit', self.peek().span) from None
        return Program(self.span(start), functions, structs, imports)

    def struct_definition(self):
        start = self.eat('struct').span
        name = self.ident().value
        self.eat('{')
        fields = []
        while self.peek().value != '}':
            token = self.ident()
            self.eat(':')
            typ = self.type_name()
            fields.append(Parameter(self.span(token.span), token.value, typ))
            if self.peek().value != ',': break
            self.eat(',')
        self.eat('}')
        return StructDef(self.span(start), name, fields)

    def function(self):
        start = self.peek().span
        if self.peek().value == '@':
            for token in ('@', 'optimize', '(', 'speed', ')'):
                self.eat(token)
        self.eat('fn')
        name = self.ident().value
        self.eat('(')
        args = []
        if self.peek().value != ')':
            while True:
                arg = self.ident()
                self.eat(':')
                typ = self.type_name()
                args.append(Parameter(self.span(arg.span), arg.value, typ))
                if self.peek().value != ',':
                    break
                self.eat(',')
        self.eat(')')
        self.eat('->')
        returns = self.type_name()
        body = self.block()
        return Function(self.span(start), name, args, returns, body)

    def block(self):
        self.eat('{')
        self.depth += 1
        if self.depth > MAX_NESTING:
            raise CompileError('Program exceeds nesting limit', self.peek().span)
        statements = []
        while self.peek().value != '}':
            if self.peek().kind == 'EOF':
                raise CompileError('Unterminated block', self.peek().span)
            statements.append(self.statement())
        self.eat('}')
        self.depth -= 1
        return statements

    def statement(self):
        start = self.peek().span
        kind = self.peek().value
        if kind in ('let', 'var'):
            self.eat()
            name = self.ident().value
            annotation = None
            if self.peek().value == ':':
                self.eat(':')
                annotation = self.type_name()
            self.eat('=')
            value = self.expression()
            self.eat(';')
            return Decl(self.span(start), kind == 'var', name, value, annotation)
        if kind == 'return':
            self.eat()
            value = self.expression()
            self.eat(';')
            return Return(self.span(start), value)
        if kind == 'print':
            self.eat()
            self.eat('(')
            value = self.expression()
            self.eat(')')
            self.eat(';')
            return Print(self.span(start), value)
        if kind == 'if':
            self.eat()
            condition = self.expression()
            yes = self.block()
            no = []
            if self.peek().value == 'else':
                self.eat()
                no = [self.statement()] if self.peek().value == 'if' else self.block()
            return If(self.span(start), condition, yes, no)
        if kind == 'while':
            self.eat()
            condition = self.expression()
            body = self.block()
            return While(self.span(start), condition, body)
        if kind in ('break', 'continue'):
            self.eat()
            self.eat(';')
            return Transfer(self.span(start), kind)
        target = self.expression()
        if self.peek().value in ('=', '+=', '-=', '*=', '/=', '%='):
            op = self.eat().value
            value = self.expression()
            self.eat(';')
            if isinstance(target, Name):
                if op != '=':
                    value = Binary(self.span(start), op[0], target, value)
                return Assign(self.span(start), target.name, value)
            if isinstance(target, Field):
                if op != '=': raise CompileError('Struct fields currently support plain assignment only', target.span)
                return FieldAssign(self.span(start), target, value)
            if isinstance(target, Index):
                if op != '=':
                    raise CompileError('Array elements currently support plain assignment only', target.span)
                return IndexAssign(self.span(start), target, value)
            raise CompileError('Invalid assignment target', target.span)
        self.eat(';')
        if not isinstance(target, Call):
            raise CompileError('Only function calls may be used as expression statements', target.span)
        return ExprStmt(self.span(start), target)

    def expression(self, minimum=0):
        self.depth += 1
        if self.depth > MAX_NESTING:
            raise CompileError('Program exceeds nesting limit', self.peek().span)
        start = self.peek().span
        token = self.peek()
        if token.value in ('-', '!'):
            op = self.eat().value
            left = Unary(start, op, self.expression(7))
            left.span = self.span(start)
        elif token.value == '(':
            self.eat()
            left = self.expression()
            self.eat(')')
        elif token.value == 'new':
            self.eat()
            name = self.qualified_name()
            self.eat('{')
            fields = []
            while self.peek().value != '}':
                field_name = self.ident().value
                self.eat(':')
                fields.append((field_name, self.expression()))
                if self.peek().value != ',': break
                self.eat(',')
            self.eat('}')
            left = StructLiteral(self.span(start), name, fields)
        elif token.value == '[':
            self.eat()
            elements = []
            if self.peek().value != ']':
                while True:
                    elements.append(self.expression())
                    if len(elements) > MAX_ARRAY_SIZE:
                        raise CompileError('Array exceeds 4096 elements', self.peek().span)
                    if self.peek().value != ',':
                        break
                    self.eat(',')
                    if self.peek().value == ']':
                        break
            self.eat(']')
            left = ArrayLiteral(self.span(start), elements)
        elif token.kind == 'STRING':
            self.eat()
            try:
                value = json.loads(token.value)
                value.encode('utf-8')
            except (ValueError, UnicodeError):
                raise CompileError('Invalid string escape or Unicode literal', token.span) from None
            if '\x00' in value:
                raise CompileError('Strings cannot contain NUL characters', token.span)
            left = Literal(token.span, value)
        elif token.kind == 'NUM':
            self.eat()
            digits = token.value.lstrip('0') or '0'
            if len(digits) > 10 or int(digits) > 2147483648:
                raise CompileError('Integer literal exceeds i32 range', token.span)
            left = Literal(token.span, int(digits))
        elif token.value in ('true', 'false'):
            self.eat()
            left = Literal(token.span, token.value == 'true')
        else:
            name_token = self.peek()
            name = self.qualified_name()
            if self.peek().value == '(':
                self.eat()
                args = []
                if self.peek().value != ')':
                    while True:
                        args.append(self.expression())
                        if self.peek().value != ',':
                            break
                        self.eat(',')
                self.eat(')')
                left = Call(self.span(start), name, args)
            else:
                left = Name(name_token.span, name)
        while self.peek().value in ('[', '.'):
            if self.peek().value == '.':
                self.eat('.')
                name = self.ident().value
                left = Field(self.span(left.span), left, name)
            else:
                self.eat('[')
                index = self.expression()
                self.eat(']')
                left = Index(Span(start.source, left.span.start, self.tokens[self.index - 1].span.end), left, index)
        while self.precedence.get(self.peek().value, -1) >= minimum:
            op = self.eat().value
            right = self.expression(self.precedence[op] + 1)
            left = Binary(Span(start.source, left.span.start, right.span.end), op, left, right)
        self.depth -= 1
        return left


@dataclass(frozen=True)
class Symbol:
    typ: str | ArrayType | StructType
    mutable: bool
    available: bool = True


@dataclass
class LoopState:
    entry: list[dict[str, Symbol]]
    breaks: list[list[dict[str, Symbol]]] = field(default_factory=list)


class Analyzer:
    """Resolve names, annotate expression types and validate control flow."""
    def analyze(self, program):
        self.functions = {}
        self.structs = {}
        for definition in program.structs:
            if definition.name in self.structs:
                raise CompileError('Duplicate struct: ' + definition.name, definition.span)
            fields = {}
            for member in definition.fields:
                if member.name in fields: raise CompileError('Duplicate field: ' + member.name, member.span)
                if member.typ == 'BoxInt' or (member.typ not in TYPES and not isinstance(member.typ, StructType)):
                    raise CompileError('Struct fields require primitive or struct types', member.span)
                fields[member.name] = member.typ
            self.structs[definition.name] = fields
        definitions = {definition.name: definition for definition in program.structs}
        sizes = {}
        heights = {}
        visiting = set()
        def layout(name, depth=0):
            if name in visiting: raise CompileError('Recursive by-value struct: ' + name, definitions[name].span)
            if name in sizes:
                if depth + heights[name] > 64: raise CompileError('Struct nesting exceeds 64 levels', definitions[name].span)
                return sizes[name]
            if depth > 64: raise CompileError('Struct nesting exceeds 64 levels', definitions[name].span)
            visiting.add(name)
            size = 0
            height = 0
            for member in definitions[name].fields:
                self.validate_type(member.typ, member.span)
                size += layout(member.typ.name, depth+1) if isinstance(member.typ, StructType) else 8
                if isinstance(member.typ, StructType): height = max(height, heights[member.typ.name]+1)
                if size > 65536: raise CompileError('Struct storage estimate exceeds 64 KiB', definitions[name].span)
            visiting.remove(name)
            if height > 64: raise CompileError('Struct nesting exceeds 64 levels', definitions[name].span)
            sizes[name] = size
            heights[name] = height
            return size
        for name in self.structs: layout(name)
        for fn in program.functions:
            self.validate_type(fn.returns, fn.span)
            for arg in fn.args: self.validate_type(arg.typ, arg.span)
            if fn.name in self.functions:
                raise CompileError('Duplicate function name: ' + fn.name, fn.span)
            if fn.name in BUILTINS:
                raise CompileError('Reserved name: ' + fn.name, fn.span)
            self.functions[fn.name] = fn
        if 'main' not in self.functions:
            raise CompileError('Missing main function', program.span)
        main = self.functions['main']
        if main.args:
            raise CompileError('main cannot have parameters', main.span)
        if main.returns != 'int':
            raise CompileError('main must return int', main.span)
        try:
            for fn in program.functions:
                self.scopes = [{}]
                self.loops = 0
                self.condition_depths = []
                self.loop_states = []
                self.returns = fn.returns
                for arg in fn.args:
                    if arg.name in self.scopes[0]:
                        raise CompileError('Duplicate argument: ' + arg.name, arg.span)
                    self.scopes[0][arg.name] = Symbol(arg.typ, False)
                if not self.block(fn.body):
                    raise CompileError(f'Function {fn.name} may exit without returning a value', fn.span)
        except RecursionError:
            raise CompileError('Program exceeds analysis nesting limit', program.span) from None
        return program

    def validate_type(self, typ, span):
        if isinstance(typ, StructType) and typ.name not in self.structs:
            raise CompileError('Unknown struct type: ' + typ.name, span)

    def lookup(self, name, span):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise CompileError('Unknown variable: ' + name, span)

    def owner(self, expr):
        if not isinstance(expr, Name):
            raise CompileError('Box borrow requires a named owner', expr.span)
        symbol = self.lookup(expr.name, expr.span)
        if symbol.typ != 'BoxInt': raise CompileError('Expected BoxInt owner', expr.span)
        if not symbol.available: raise CompileError('Use after move: ' + expr.name, expr.span)
        expr.typ = 'BoxInt'
        return symbol

    def set_available(self, name, available):
        for scope in reversed(self.scopes):
            if name in scope:
                old = scope[name]
                scope[name] = Symbol(old.typ, old.mutable, available)
                return

    def snapshot(self):
        # Symbols are immutable, so copying the scope dictionaries is sufficient.
        return [dict(scope) for scope in self.scopes]

    def merge(self, states):
        # Only states reaching the same continuation participate in its join.
        self.scopes = [dict(scope) for scope in states[0]]
        for i, scope in enumerate(self.scopes):
            for name, symbol in list(scope.items()):
                available = all(state[i][name].available for state in states)
                scope[name] = Symbol(symbol.typ, symbol.mutable, available)

    def check_backedge(self, loop, span):
        # Preserve the loop-header availability invariant before any next iteration.
        # Bindings created inside the loop are dropped rather than carried back.
        for i, scope in enumerate(loop.entry):
            for name, symbol in scope.items():
                if symbol.typ == 'BoxInt' and symbol.available and not self.scopes[i][name].available:
                    raise CompileError('Loop backedge requires reinitializing owner: ' + name, span)

    def expect(self, expression, wanted, context):
        actual = self.expression(expression)
        if actual != wanted:
            raise CompileError(f'{context}: expected {wanted}, got {actual}', expression.span)

    def expression(self, expr):
        if isinstance(expr, Literal):
            if isinstance(expr.value, bool):
                expr.typ = 'bool'
            elif isinstance(expr.value, int):
                if not -2147483648 <= expr.value <= 2147483647:
                    raise CompileError('Integer literal exceeds i32 range', expr.span)
                expr.typ = 'int'
            else:
                expr.typ = 'str'
        elif isinstance(expr, StructLiteral):
            fields = self.structs.get(expr.name)
            if fields is None: raise CompileError('Unknown struct type: ' + expr.name, expr.span)
            seen = set()
            for name, value in expr.fields:
                if name in seen: raise CompileError('Duplicate initializer field: ' + name, value.span)
                if name not in fields: raise CompileError('Unknown field: ' + name, value.span)
                seen.add(name)
                self.expect(value, fields[name], 'Field ' + name)
            missing = set(fields) - seen
            if missing: raise CompileError('Missing fields: ' + ', '.join(sorted(missing)), expr.span)
            expr.typ = StructType(expr.name)
        elif isinstance(expr, Field):
            base = self.expression(expr.base)
            if not isinstance(base, StructType): raise CompileError('Field access requires a struct', expr.base.span)
            fields = self.structs[base.name]
            if expr.name not in fields: raise CompileError('Unknown field: ' + expr.name, expr.span)
            expr.typ = fields[expr.name]
        elif isinstance(expr, ArrayLiteral):
            for element in expr.elements:
                self.expect(element, 'int', 'Array element')
            expr.typ = ArrayType(len(expr.elements))
        elif isinstance(expr, Index):
            base_type = self.expression(expr.base)
            if not isinstance(expr.base, Name) or not isinstance(base_type, ArrayType):
                raise CompileError('Indexing requires a named local int array', expr.base.span)
            self.expect(expr.index, 'int', 'Array index')
            expr.typ = 'int'
        elif isinstance(expr, Name):
            expr.typ = self.lookup(expr.name, expr.span).typ
            if expr.typ == 'BoxInt':
                self.owner(expr)
                index = next(i for i in range(len(self.scopes)-1, -1, -1) if expr.name in self.scopes[i])
                if self.condition_depths and index < self.condition_depths[-1]:
                    raise CompileError('Cannot move an outer owner in a loop condition', expr.span)
                self.set_available(expr.name, False)
        elif isinstance(expr, Call):
            if expr.name in ('box', 'read_box', 'write_box'):
                count = 2 if expr.name == 'write_box' else 1
                if len(expr.args) != count: raise CompileError('Wrong number of arguments to ' + expr.name, expr.span)
                if expr.name == 'box':
                    self.expect(expr.args[0], 'int', 'box value')
                    expr.typ = 'BoxInt'
                else:
                    symbol = self.owner(expr.args[0])
                    if expr.name == 'write_box':
                        if not symbol.mutable: raise CompileError('write_box requires a mutable owner', expr.span)
                        self.expect(expr.args[1], 'int', 'write_box value')
                        self.owner(expr.args[0])
                    expr.typ = 'int'
            elif expr.name in ('len', 'to_bool', 'to_int'):
                if len(expr.args) != 1:
                    raise CompileError('Wrong number of arguments to ' + expr.name, expr.span)
                arg_type = {'len': 'str', 'to_bool': 'int', 'to_int': 'bool'}[expr.name]
                if expr.name == 'len':
                    actual = self.expression(expr.args[0])
                    if actual != 'str' and not isinstance(actual, ArrayType):
                        raise CompileError('Argument to len: expected str or array, got ' + str(actual), expr.args[0].span)
                else:
                    self.expect(expr.args[0], arg_type, 'Argument to ' + expr.name)
                expr.typ = 'bool' if expr.name == 'to_bool' else 'int'
            else:
                fn = self.functions.get(expr.name)
                if fn is None:
                    raise CompileError('Unknown function: ' + expr.name, expr.span)
                if len(expr.args) != len(fn.args):
                    raise CompileError('Wrong number of arguments to ' + expr.name, expr.span)
                for value, arg in zip(expr.args, fn.args):
                    self.expect(value, arg.typ, 'Argument to ' + expr.name)
                expr.typ = fn.returns
        elif isinstance(expr, Unary):
            if expr.op == '-' and isinstance(expr.operand, Literal) and expr.operand.value == 2147483648:
                expr.operand.typ = 'int'
            else:
                self.expect(expr.operand, 'bool' if expr.op == '!' else 'int', 'Unary ' + expr.op)
            expr.typ = 'bool' if expr.op == '!' else 'int'
        elif isinstance(expr, Binary):
            left = self.expression(expr.left)
            if expr.op in ('&&', '||'):
                if left != 'bool':
                    raise CompileError('Operator ' + expr.op + ': expected bool, got ' + str(left), expr.left.span)
                self.expect(expr.right, 'bool', 'Operator ' + expr.op)
                expr.typ = 'bool'
            elif expr.op in ('==', '!=', '<', '>', '<=', '>='):
                if left == 'BoxInt' or isinstance(left, (ArrayType, StructType)):
                    raise CompileError('Aggregates cannot be compared directly', expr.left.span)
                if expr.op not in ('==', '!=') and left == 'bool':
                    raise CompileError('Ordering requires int or str, got bool', expr.left.span)
                self.expect(expr.right, left, 'Operator ' + expr.op)
                expr.typ = 'bool'
            else:
                if left != 'int':
                    raise CompileError('Operator ' + expr.op + ': expected int, got ' + str(left), expr.left.span)
                self.expect(expr.right, 'int', 'Operator ' + expr.op)
                expr.typ = 'int'
        else:
            raise TypeError('Unknown expression node: ' + type(expr).__name__)
        return expr.typ

    def block(self, statements):
        self.scopes.append({})
        terminated = False
        for stmt in statements:
            if terminated:
                raise CompileError('Unreachable statement after control transfer', stmt.span)
            if isinstance(stmt, Decl):
                if stmt.annotation: self.validate_type(stmt.annotation, stmt.span)
                if stmt.name in self.scopes[-1]:
                    raise CompileError('Duplicate local: ' + stmt.name, stmt.span)
                typ = self.expression(stmt.value)
                if stmt.annotation and stmt.annotation != typ:
                    raise CompileError(f'Declaration {stmt.name}: expected {stmt.annotation}, got {typ}', stmt.value.span)
                self.scopes[-1][stmt.name] = Symbol(typ, stmt.mutable)
            elif isinstance(stmt, Assign):
                symbol = self.lookup(stmt.name, stmt.span)
                if not symbol.mutable:
                    raise CompileError('Cannot assign to immutable value: ' + stmt.name, stmt.span)
                self.expect(stmt.value, symbol.typ, 'Assignment ' + stmt.name)
                self.set_available(stmt.name, True)
            elif isinstance(stmt, FieldAssign):
                self.expression(stmt.target)
                root = stmt.target.base
                while isinstance(root, Field): root = root.base
                if not isinstance(root, Name):
                    raise CompileError('Field assignment requires a named local struct', stmt.target.span)
                symbol = self.lookup(root.name, stmt.target.span)
                if not symbol.mutable:
                    raise CompileError('Cannot assign to immutable struct: ' + root.name, stmt.target.span)
                self.expect(stmt.value, stmt.target.typ, 'Field assignment')
            elif isinstance(stmt, IndexAssign):
                self.expression(stmt.target)
                symbol = self.lookup(stmt.target.base.name, stmt.target.span)
                if not symbol.mutable:
                    raise CompileError('Cannot assign to immutable array: ' + stmt.target.base.name, stmt.target.span)
                self.expect(stmt.value, 'int', 'Array assignment')
            elif isinstance(stmt, Return):
                self.expect(stmt.value, self.returns, 'Return')
                terminated = True
            elif isinstance(stmt, (Print, ExprStmt)):
                typ = self.expression(stmt.value)
                if isinstance(stmt, Print) and (typ == 'BoxInt' or isinstance(typ, (ArrayType, StructType))):
                    raise CompileError('print does not support aggregates; print individual elements or fields', stmt.value.span)
            elif isinstance(stmt, Transfer):
                if not self.loops:
                    raise CompileError(stmt.kind + ' is only allowed inside a loop', stmt.span)
                loop = self.loop_states[-1]
                if stmt.kind == 'continue':
                    self.check_backedge(loop, stmt.span)
                else:
                    loop.breaks.append(self.snapshot()[:len(loop.entry)])
                terminated = True
            elif isinstance(stmt, If):
                self.expect(stmt.condition, 'bool', 'if condition')
                before = self.snapshot()
                yes = self.block(stmt.yes)
                after_yes = self.snapshot()
                self.scopes = [dict(scope) for scope in before]
                no = self.block(stmt.no)
                after_no = self.snapshot()
                continuing = []
                if not yes: continuing.append(after_yes)
                if not no: continuing.append(after_no)
                self.merge(continuing or [before])
                terminated = yes and no
            elif isinstance(stmt, While):
                loop = LoopState(self.snapshot())
                self.condition_depths.append(len(self.scopes))
                self.expect(stmt.condition, 'bool', 'while condition')
                self.condition_depths.pop()
                self.loops += 1
                self.loop_states.append(loop)
                body_terminated = self.block(stmt.body)
                if not body_terminated: self.check_backedge(loop, stmt.span)
                self.loop_states.pop()
                self.loops -= 1
                # A false condition can exit before the first iteration. Backedges
                # preserve entry availability; breaks may additionally move owners.
                self.merge([loop.entry] + loop.breaks)
            else:
                raise TypeError('Unknown statement node: ' + type(stmt).__name__)
        self.scopes.pop()
        return terminated


def parse_source(text, filename='<input>'):
    return Parser(lex(Source(text, filename))).parse()


def analyze_source(text, filename='<input>'):
    program = parse_source(text, filename)
    if program.imports: raise CompileError('Imports require the file-based module loader', program.imports[0].span)
    return Analyzer().analyze(program)


def optimize_program(program):
    """Fold checked, typed integer expressions, retaining their source spans."""
    report = {'constant_folds': 0, 'ai_plugin_executed': False,
              'note': 'Deterministic optimization only; AI plugin interface is experimental.'}

    def expression(expr):
        if isinstance(expr, Binary):
            expr.left, expr.right = expression(expr.left), expression(expr.right)
            if (expr.op in ('+', '-', '*') and isinstance(expr.left, Literal)
                    and isinstance(expr.right, Literal) and expr.left.typ == expr.right.typ == 'int'):
                a, b = expr.left.value, expr.right.value
                result = {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b}[expr.op]()
                if -2147483648 <= result <= 2147483647:
                    folded = Literal(expr.span, result)
                    folded.typ = 'int'
                    report['constant_folds'] += 1
                    return folded
        elif isinstance(expr, StructLiteral):
            expr.fields = [(name, expression(value)) for name, value in expr.fields]
        elif isinstance(expr, Field):
            expr.base = expression(expr.base)
        elif isinstance(expr, ArrayLiteral):
            expr.elements = [expression(element) for element in expr.elements]
        elif isinstance(expr, Index):
            expr.base, expr.index = expression(expr.base), expression(expr.index)
        elif isinstance(expr, Unary):
            expr.operand = expression(expr.operand)
        elif isinstance(expr, Call):
            expr.args = [expression(arg) for arg in expr.args]
        return expr

    def block(statements):
        for stmt in statements:
            if isinstance(stmt, (Decl, Assign, Return, Print, ExprStmt)):
                stmt.value = expression(stmt.value)
            elif isinstance(stmt, (IndexAssign, FieldAssign)):
                stmt.target = expression(stmt.target)
                stmt.value = expression(stmt.value)
            elif isinstance(stmt, If):
                stmt.condition = expression(stmt.condition)
                block(stmt.yes)
                block(stmt.no)
            elif isinstance(stmt, While):
                stmt.condition = expression(stmt.condition)
                block(stmt.body)
    for fn in program.functions:
        block(fn.body)
    return program, report
