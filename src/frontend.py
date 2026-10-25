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
    r'(?P<OP>\+=|-=|\*=|/=|%=|->|==|!=|<=|>=|&&|\|\||[@+*/%(){};,:=<>!-])|(?P<BAD>.)'
)
KEYWORDS = {'fn', 'let', 'var', 'return', 'if', 'else', 'while', 'break',
            'continue', 'true', 'false', 'int', 'str'}
TYPES = {'int', 'str'}
BUILTINS = {'print', 'printf', 'len'}


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


@dataclass
class Node:
    span: Span


@dataclass
class Expr(Node):
    typ: str | None = field(init=False, default=None)


@dataclass
class Literal(Expr):
    value: int | str


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
class Decl(Node):
    mutable: bool
    name: str
    value: Expr
    annotation: str | None


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
    typ: str


@dataclass
class Function(Node):
    name: str
    args: list[Parameter]
    returns: str
    body: list[Node]


@dataclass
class Program(Node):
    functions: list[Function]


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

    def type_name(self):
        token = self.eat()
        if token.value not in TYPES:
            raise CompileError('Expected type int or str', token.span)
        return token.value

    def parse(self):
        start = self.peek().span
        functions = []
        try:
            while self.peek().kind != 'EOF':
                functions.append(self.function())
        except RecursionError:
            raise CompileError('Program exceeds nesting limit', self.peek().span) from None
        return Program(self.span(start), functions)

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
        if self.index + 1 < len(self.tokens) and self.tokens[self.index + 1].value in ('=', '+=', '-=', '*=', '/=', '%='):
            name = self.ident()
            op = self.eat().value
            value = self.expression()
            self.eat(';')
            if op != '=':
                value = Binary(self.span(start), op[0], Name(name.span, name.value), value)
            return Assign(self.span(start), name.value, value)
        value = self.expression()
        self.eat(';')
        if not isinstance(value, Call):
            raise CompileError('Only function calls may be used as expression statements', value.span)
        return ExprStmt(self.span(start), value)

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
            left = Literal(token.span, int(token.value == 'true'))
        else:
            name = self.ident()
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
                left = Call(self.span(start), name.value, args)
            else:
                left = Name(name.span, name.value)
        while self.precedence.get(self.peek().value, -1) >= minimum:
            op = self.eat().value
            right = self.expression(self.precedence[op] + 1)
            left = Binary(Span(start.source, left.span.start, right.span.end), op, left, right)
        self.depth -= 1
        return left


@dataclass(frozen=True)
class Symbol:
    typ: str
    mutable: bool


class Analyzer:
    """Resolve names, annotate expression types and validate control flow."""
    def analyze(self, program):
        self.functions = {}
        for fn in program.functions:
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

    def lookup(self, name, span):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise CompileError('Unknown variable: ' + name, span)

    def expect(self, expression, wanted, context):
        actual = self.expression(expression)
        if actual != wanted:
            raise CompileError(f'{context}: expected {wanted}, got {actual}', expression.span)

    def expression(self, expr):
        if isinstance(expr, Literal):
            if isinstance(expr.value, int):
                if not -2147483648 <= expr.value <= 2147483647:
                    raise CompileError('Integer literal exceeds i32 range', expr.span)
                expr.typ = 'int'
            else:
                expr.typ = 'str'
        elif isinstance(expr, Name):
            expr.typ = self.lookup(expr.name, expr.span).typ
        elif isinstance(expr, Call):
            if expr.name == 'len':
                if len(expr.args) != 1:
                    raise CompileError('Wrong number of arguments to len', expr.span)
                self.expect(expr.args[0], 'str', 'Argument to len')
                expr.typ = 'int'
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
                self.expect(expr.operand, 'int', 'Unary ' + expr.op)
            expr.typ = 'int'
        elif isinstance(expr, Binary):
            left = self.expression(expr.left)
            if expr.op not in ('==', '!=', '<', '>', '<=', '>=') and left != 'int':
                raise CompileError('Operator ' + expr.op + ': expected int, got ' + left, expr.left.span)
            self.expect(expr.right, left, 'Operator ' + expr.op)
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
            elif isinstance(stmt, Return):
                self.expect(stmt.value, self.returns, 'Return')
                terminated = True
            elif isinstance(stmt, (Print, ExprStmt)):
                self.expression(stmt.value)
            elif isinstance(stmt, Transfer):
                if not self.loops:
                    raise CompileError(stmt.kind + ' is only allowed inside a loop', stmt.span)
                terminated = True
            elif isinstance(stmt, If):
                self.expect(stmt.condition, 'int', 'if condition')
                yes, no = self.block(stmt.yes), self.block(stmt.no)
                terminated = yes and no
            elif isinstance(stmt, While):
                self.expect(stmt.condition, 'int', 'while condition')
                self.loops += 1
                self.block(stmt.body)
                self.loops -= 1
            else:
                raise TypeError('Unknown statement node: ' + type(stmt).__name__)
        self.scopes.pop()
        return terminated


def parse_source(text, filename='<input>'):
    return Parser(lex(Source(text, filename))).parse()


def analyze_source(text, filename='<input>'):
    return Analyzer().analyze(parse_source(text, filename))


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
        elif isinstance(expr, Unary):
            expr.operand = expression(expr.operand)
        elif isinstance(expr, Call):
            expr.args = [expression(arg) for arg in expr.args]
        return expr

    def block(statements):
        for stmt in statements:
            if isinstance(stmt, (Decl, Assign, Return, Print, ExprStmt)):
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
