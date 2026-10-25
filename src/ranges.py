"""Conservative interval facts for successful evaluations of checked i32 code.

Only straight-line while bodies receive inductive loop facts. Complex loop
control falls back to unknown values. No runtime safety check is removed here.
"""
from dataclasses import dataclass
from frontend import (Literal, Name, Binary, Unary, Call, Index, ArrayLiteral,
                      ArrayType, StructType, StructLiteral, Field, FieldAssign, Decl, Assign, IndexAssign, While, If, Print,
                      Return, ExprStmt)

LOW, HIGH = -2147483648, 2147483647
TOP = (LOW, HIGH)
BOTTOM = (1, 0)


def bottom(fact):
    return isinstance(fact, tuple) and fact[0] > fact[1]


@dataclass(frozen=True)
class ArrayFact:
    elements: tuple = TOP


def join(a, b):
    if bottom(a): return b
    if bottom(b): return a
    if isinstance(a, ArrayFact) and isinstance(b, ArrayFact):
        return ArrayFact(join(a.elements, b.elements))
    if a is None or b is None:
        return None
    return min(a[0], b[0]), max(a[1], b[1])


def widen(a, b):
    if bottom(a): return b
    if bottom(b): return a
    if isinstance(a, ArrayFact) and isinstance(b, ArrayFact):
        return ArrayFact(widen(a.elements, b.elements))
    if a is None or b is None:
        return None
    return (LOW if b[0] < a[0] else a[0], HIGH if b[1] > a[1] else a[1])


def unknown(fact):
    return ArrayFact() if isinstance(fact, ArrayFact) else (TOP if fact is not None else None)


def clone(state):
    return [dict(scope) for scope in state]


class RangeAnalysis:
    def __init__(self):
        self.facts = {}

    def lookup(self, state, name):
        for scope in reversed(state):
            if name in scope:
                return scope[name]
        return None

    def store(self, state, name, fact):
        for scope in reversed(state):
            if name in scope:
                scope[name] = fact
                return

    def expression(self, expr, state, record):
        fact = None
        if isinstance(expr, Literal):
            if expr.typ == 'int': fact = (expr.value, expr.value)
        elif isinstance(expr, Name):
            fact = self.lookup(state, expr.name)
        elif isinstance(expr, StructLiteral):
            for _,value in expr.fields: self.expression(value,state,record)
        elif isinstance(expr, Field):
            self.expression(expr.base,state,record)
            fact=TOP if expr.typ=='int' else None
        elif isinstance(expr, ArrayLiteral):
            values = [self.expression(e, state, record) for e in expr.elements]
            fact = ArrayFact((min(v[0] for v in values), max(v[1] for v in values)) if values else TOP)
        elif isinstance(expr, Index):
            base = self.expression(expr.base, state, record)
            self.expression(expr.index, state, record)
            fact = base.elements if isinstance(base, ArrayFact) else TOP
        elif isinstance(expr, Call):
            for arg in expr.args: self.expression(arg, state, record)
            fact = ArrayFact() if isinstance(expr.typ,ArrayType) else (TOP if expr.typ == 'int' else None)
        elif isinstance(expr, Unary):
            value = self.expression(expr.operand, state, record)
            if bottom(value): fact = BOTTOM
            elif expr.op == '-' and value is not None:
                fact = (max(LOW, -value[1]), min(HIGH, -value[0]))
        elif isinstance(expr, Binary):
            a = self.expression(expr.left, state, record)
            b = self.expression(expr.right, state, record)
            if expr.typ == 'int':
                fact = TOP
                if bottom(a) or bottom(b): fact = BOTTOM
                elif a is not None and b is not None:
                    if expr.op == '+': fact = (max(LOW, a[0]+b[0]), min(HIGH, a[1]+b[1]))
                    elif expr.op == '-': fact = (max(LOW, a[0]-b[1]), min(HIGH, a[1]-b[0]))
                    elif expr.op == '*':
                        products = [x*y for x in a for y in b]
                        fact = (max(LOW, min(products)), min(HIGH, max(products)))
                    elif expr.op == '%' and b[0] == b[1] and b[0] > 0:
                        limit = b[0]-1
                        fact = (0 if a[0] >= 0 else -limit, 0 if a[1] <= 0 else limit)
        # Empty successful result sets stay bottom, preserving monotonic transfer.
        if bottom(fact): fact = BOTTOM
        if record: self.facts[id(expr)] = fact
        return fact

    def merge(self, a, b, operation=join):
        return [{name: operation(value, b[i][name]) for name, value in scope.items()}
                for i, scope in enumerate(a)]

    def simple(self, body):
        return all(isinstance(stmt, (Decl, Assign, IndexAssign, Print, ExprStmt)) for stmt in body)

    def block(self, statements, state, record):
        state = clone(state) + [{}]
        for stmt in statements:
            if isinstance(stmt, Decl):
                state[-1][stmt.name] = self.expression(stmt.value, state, record)
            elif isinstance(stmt, Assign):
                self.store(state, stmt.name, self.expression(stmt.value, state, record))
            elif isinstance(stmt, FieldAssign):
                self.expression(stmt.target,state,record)
                self.expression(stmt.value,state,record)
            elif isinstance(stmt, IndexAssign):
                self.expression(stmt.target, state, record)
                value = self.expression(stmt.value, state, record)
                name = stmt.target.base.name
                previous = self.lookup(state, name)
                self.store(state, name, ArrayFact(join(previous.elements, value)))
            elif isinstance(stmt, (Print, Return, ExprStmt)):
                self.expression(stmt.value, state, record)
            elif isinstance(stmt, If):
                self.expression(stmt.condition, state, record)
                yes = self.block(stmt.yes, state, record)
                no = self.block(stmt.no, state, record)
                state = self.merge(yes, no)
            elif isinstance(stmt, While):
                entry = clone(state)
                if self.simple(stmt.body):
                    invariant = clone(entry)
                    for _ in range(8):
                        following = self.merge(entry, self.block(stmt.body, invariant, False))
                        following = self.merge(invariant, following, widen)
                        if following == invariant: break
                        invariant = following
                    else:
                        invariant = [{n: unknown(v) for n,v in scope.items()} for scope in entry]
                    # Narrowing preserves an invariant: F(I) is a subset of I.
                    for _ in range(3):
                        invariant = self.merge(entry, self.block(stmt.body, invariant, False))
                else:
                    # Includes all locals, to avoid assumptions about branches,
                    # break/continue paths, or shadowing in complex loops.
                    invariant = [{n: unknown(v) for n,v in scope.items()} for scope in entry]
                self.expression(stmt.condition, invariant, record)
                self.block(stmt.body, invariant, record)
                state = invariant
        return state[:-1]

    def analyze(self, program):
        for fn in program.functions:
            args = {arg.name: ArrayFact() if isinstance(arg.typ,ArrayType) else (TOP if arg.typ == 'int' else None) for arg in fn.args}
            self.block(fn.body, [args], True)
        return self.facts
