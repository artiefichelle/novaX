"""Front-end tests run without importing LLVM or invoking a native compiler."""
import random
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from frontend import (Analyzer, Binary, Call, CompileError, Decl, Literal, Name,
                      Parser, Program, Source, Span, Unary, analyze_source, lex,
                      optimize_program, parse_source)


class LexerTests(unittest.TestCase):
    def test_tokens_preserve_offsets_and_source(self):
        source = Source('/* ignored */\nvar x += 2;', 'tokens.nx')
        tokens = lex(source)
        self.assertEqual([t.value for t in tokens], ['var', 'x', '+=', '2', ';', '<eof>'])
        for token in tokens[:-1]:
            self.assertEqual(source.text[token.span.start:token.span.end], token.value)
            self.assertIs(token.span.source, source)
        self.assertEqual(source.location(tokens[0].span.start), (2, 1))

    def test_comment_markers_inside_string(self):
        tokens = lex('"/* text // */" // comment\n42')
        self.assertEqual([t.kind for t in tokens], ['STRING', 'NUM', 'EOF'])

    def test_bad_character_diagnostic(self):
        with self.assertRaises(CompileError) as caught:
            lex(Source('fn main() -> int {\n  $\n}', 'bad.nx'))
        self.assertEqual(caught.exception.span.source.location(caught.exception.span.start), (2, 3))
        self.assertIn('bad.nx:2:3: error:', caught.exception.render())
        self.assertIn('  $\n    ^', caught.exception.render())

    def test_eof_location(self):
        source = Source('line\n', 'end.nx')
        self.assertEqual(source.location(5), (2, 1))

    def test_resource_limits(self):
        for text, diagnostic in [(' ' * 1_048_577, '1 MiB'), ('x;' * 50_001, 'token limit')]:
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaises(CompileError) as caught:
                    lex(text)
                self.assertIn(diagnostic, str(caught.exception))


class ParserTests(unittest.TestCase):
    def test_typed_nodes_and_precedence(self):
        program = parse_source('fn main() -> int {let n=1+2*3;return n;}')
        self.assertIsInstance(program, Program)
        declaration = program.functions[0].body[0]
        self.assertIsInstance(declaration, Decl)
        self.assertIsInstance(declaration.value, Binary)
        self.assertEqual(declaration.value.op, '+')
        self.assertEqual(declaration.value.right.op, '*')
        self.assertIsNone(declaration.value.typ)
        self.assertEqual(declaration.span.source.text[declaration.span.start:declaration.span.end], 'let n=1+2*3;')

    def test_missing_semicolon_points_at_next_token(self):
        with self.assertRaises(CompileError) as caught:
            parse_source('fn main() -> int {\nlet x=1\nreturn x;\n}', 'syntax.nx')
        error = caught.exception
        self.assertEqual(error.span.source.location(error.span.start), (3, 1))
        self.assertIn("Expected ';'", str(error))

    def test_large_integer_has_controlled_error(self):
        with self.assertRaises(CompileError) as caught:
            parse_source('fn main() -> int {return ' + '9' * 5000 + ';}')
        self.assertIn('i32 range', str(caught.exception))

    def test_unterminated_block(self):
        with self.assertRaises(CompileError) as caught:
            parse_source('fn main() -> int {')
        self.assertIn('Unterminated block', str(caught.exception))

    def test_deep_expression_is_rejected(self):
        with self.assertRaises(CompileError) as caught:
            parse_source('fn main() -> int {return ' + '(' * 150 + '1' + ')' * 150 + ';}')
        self.assertIn('nesting limit', str(caught.exception))


class AnalyzerTests(unittest.TestCase):
    def test_expression_types_are_recorded(self):
        program = analyze_source('fn echo(s: str) -> str {return s;} fn main() -> int {let s=echo("x");print(len(s));return 0;}')
        declaration = program.functions[1].body[0]
        self.assertEqual(declaration.value.typ, 'str')
        self.assertEqual(declaration.value.args[0].typ, 'str')
        length = program.functions[1].body[1].value
        self.assertEqual(length.typ, 'int')
        self.assertEqual(length.args[0].typ, 'str')

    def test_type_error_points_at_value(self):
        with self.assertRaises(CompileError) as caught:
            analyze_source('fn main() -> int {\n  let n: int = "oops";\n  return 0;\n}', 'types.nx')
        error = caught.exception
        self.assertIn('types.nx:2:16: error: Declaration n: expected int, got str', error.render())
        self.assertIn('^^^^^^', error.render())

    def test_undefined_name_and_immutable_parameter(self):
        for source, diagnostic in [
            ('fn main() -> int {return unknown;}', 'Unknown variable'),
            ('fn f(n:int) -> int {n=1;return n;} fn main() -> int {return 0;}', 'immutable'),
        ]:
            with self.assertRaises(CompileError) as caught:
                analyze_source(source)
            self.assertIn(diagnostic, str(caught.exception))
            self.assertIsNotNone(caught.exception.span)

    def test_all_paths_and_unreachable_code(self):
        for body, diagnostic in [('if true {return 0;}', 'may exit'), ('return 0;print(1);', 'Unreachable')]:
            with self.assertRaises(CompileError) as caught:
                analyze_source('fn main() -> int {' + body + '}')
            self.assertIn(diagnostic, str(caught.exception))
        analyze_source('fn main() -> int {if true {return 0;} else {return 1;}}')

    def test_shadowing(self):
        analyze_source('fn main() -> int {let n=1;if n != 0 {let n="inner";print(n);}return n;}')

    def test_minimum_integer_only_under_negation(self):
        analyze_source('fn main() -> int {return -2147483648;}')
        with self.assertRaises(CompileError):
            analyze_source('fn main() -> int {return 2147483648;}')

    def test_boolean_nodes_and_comparison_types(self):
        program = analyze_source('fn main() -> int {let flag: bool=true;print(1<2);return to_int(flag);}')
        fn = program.functions[0]
        self.assertIs(fn.body[0].value.value, True)
        self.assertEqual(fn.body[0].value.typ, 'bool')
        self.assertEqual(fn.body[1].value.typ, 'bool')
        self.assertEqual(fn.body[2].value.typ, 'int')
        self.assertEqual(fn.body[2].value.args[0].typ, 'bool')

    def test_boolean_arithmetic_rejected_before_optimization(self):
        for expression in ('true+false', 'true==1', '!1', 'to_int(1)'):
            with self.subTest(expression=expression):
                with self.assertRaises(CompileError):
                    analyze_source('fn main() -> int {print('+expression+');return 0;}')

    def test_validate_before_optimization(self):
        for expression in ('2147483648 - 1', 'false && missing()', 'true || "text"'):
            with self.assertRaises(CompileError):
                analyze_source('fn main() -> int {return ' + expression + ';}')

    def test_optimizer_preserves_types_and_spans(self):
        program = analyze_source('fn main() -> int {return 1-3;}')
        original = program.functions[0].body[0].value.span
        program, report = optimize_program(program)
        value = program.functions[0].body[0].value
        self.assertIsInstance(value, Literal)
        self.assertEqual(value.value, -2)
        self.assertEqual(value.typ, 'int')
        self.assertEqual(value.span, original)
        self.assertEqual(report['constant_folds'], 1)

    def test_frontend_import_without_site_packages(self):
        code = 'import sys;sys.path.insert(0,' + repr(str(ROOT / 'src')) + ');from frontend import analyze_source;analyze_source("fn main() -> int {return 0;}");assert "llvmlite" not in sys.modules'
        result = subprocess.run([sys.executable, '-S', '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_seeded_malformed_input_smoke(self):
        rng = random.Random(20261025)
        alphabet = 'fn main() -> int {}[];:123"/*\\=!?\n'
        for _ in range(400):
            source = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 150)))
            try:
                analyze_source(source)
            except CompileError as error:
                self.assertIsNotNone(error.span)


if __name__ == '__main__':
    unittest.main()
