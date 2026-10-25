import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMPILER=ROOT/'src'/'novax.py'

class CompilerTests(unittest.TestCase):
    def compile_source(self, source, emit=True, optimization="2"):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.nx';path.write_text(source)
            cmd=[sys.executable,str(COMPILER),str(path),'-o',str(Path(d)/('test.ll' if emit else 'test'))]
            cmd.append("-O"+optimization)
            if emit:cmd.append('--emit-llvm')
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
            out=Path(d)/('test.ll' if emit else 'test')
            ir=out.read_text() if out.exists() and emit else ''
            exe=subprocess.run([str(out)],capture_output=True,text=True,timeout=20) if p.returncode==0 and not emit else None
            return p,ir,exe
    def test_constant_folding(self):
        p,ir,_=self.compile_source('fn main() -> int { let x = 6*7; print(x); return 0; }')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('i32 42',ir)
    def test_immutable(self):
        p,_,_=self.compile_source('fn main() -> int { let x = 5; x = 9; return x; }')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('immutable',p.stderr)
    def test_native(self):
        p,_,exe=self.compile_source('fn main() -> int { print(6*7); return 0; }',False)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(exe.stdout,'42\n')
    def test_wrong_arity(self):
        p,_,_=self.compile_source('fn sum(a: int) -> int {return a;} fn main() -> int {return sum();}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Wrong number',p.stderr)

class LanguageV02Tests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    def native(self, source, expected):
        for level in ('0','3'):
            with self.subTest(optimization=level):
                p,_,exe=self.compile_source(source,False,level)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(exe.returncode,0,exe.stderr)
                self.assertEqual(exe.stdout,expected)

    def test_short_circuit_side_effects(self):
        self.native('fn noisy() -> int { print(99); return 1; }\nfn main() -> int {\nprint(false && noisy()); print(true || noisy());\nprint(true && noisy()); print(false || noisy());\nprint((false || true) && (true || noisy())); return 0;\n}', '0\n1\n99\n1\n99\n1\n1\n')

    def test_nested_loops_and_else_if(self):
        self.native('fn main() -> int {\nvar i = 0; var total = 0;\nwhile i < 6 {\ni = i + 1;\nif i == 2 { continue; } else if i == 5 { break; }\nvar j = 0;\nwhile true { j = j + 1; if j == 2 { break; } total = total + i; }\n}\nprint(total); print(i); return 0;\n}', '8\n5\n')

    def test_calls_comments_and_minimum_integer(self):
        self.native('/* Multi-line\ncomment */\nfn hello() -> int { print(42); return 0; }\nfn main() -> int { hello(); print(-2147483648); return 0; }', '42\n-2147483648\n')

    def test_invalid_control_flow(self):
        for keyword in ('break','continue'):
            with self.subTest(keyword=keyword):
                p,_,_=self.compile_source('fn main() -> int { '+keyword+'; return 0; }')
                self.assertNotEqual(p.returncode,0)
                self.assertIn('only allowed inside a loop',p.stderr)

    def test_unterminated_comment(self):
        p,_,_=self.compile_source('fn main() -> int { return 0; } /* unfinished')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Unterminated block comment',p.stderr)

    def test_reserved_runtime_function(self):
        p,_,_=self.compile_source('fn printf() -> int {return 0;} fn main() -> int {return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Reserved name',p.stderr)

    def test_integer_range(self):
        for literal in ('2147483648','-2147483649'):
            p,_,_=self.compile_source('fn main() -> int { print('+literal+'); return 0; }')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('i32 range',p.stderr)

class StringTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_string_functions_and_variables(self):
        self.native('fn choose(n: int, text: str) -> str {\nif n { return text; } else { return "fallback"; }\n}\nfn main() -> int {\nlet message: str = "Hallo NOVA-X";\nvar selected = choose(1, message);\nprint(selected); selected = choose(0, message); print(selected);\nprint(42); return 0;\n}', 'Hallo NOVA-X\nfallback\n42\n')

    def test_unicode_escapes_and_format_safety(self):
        self.native('fn main() -> int {\nprint("Grüße 🌍"); print("Zeile 1\\nZeile 2\\t\\"ok\\"");\nprint("100% %s %n"); print(""); print("/* not a comment");\nprint("// not a comment"); print("\\u0041"); return 0;\n}', 'Grüße 🌍\nZeile 1\nZeile 2\t"ok"\n100% %s %n\n\n/* not a comment\n// not a comment\nA\n')

    def test_type_errors(self):
        cases = [
            ('let x: int = "text";', 'Declaration'),
            ('let x: str = 1;', 'Declaration'),
            ('var x = "text"; x = 2;', 'Assignment'),
            ('print("x" + 1);', 'Operator'),
            ('print(1 + "x");', 'Operator'),
            ('print(!"x");', 'Unary'),
            ('if "x" { print(1); }', 'if condition'),
            ('while "x" { break; }', 'while condition'),
            ('print(false && "x");', 'Operator'),
        ]
        for body, diagnostic in cases:
            with self.subTest(body=body):
                p,_,_=self.compile_source('fn main() -> int {'+body+' return 0;}')
                self.assertNotEqual(p.returncode,0)
                self.assertIn(diagnostic,p.stderr)
                self.assertNotIn('Traceback',p.stderr)

    def test_function_type_errors(self):
        for source,diagnostic in [
            ('fn f(x: str) -> int {return 0;} fn main() -> int {return f(1);}', 'Argument'),
            ('fn f() -> str {return 1;} fn main() -> int {return 0;}', 'Return'),
            ('fn main() -> str {return "text";}', 'main must return int'),
        ]:
            p,_,_=self.compile_source(source)
            self.assertNotEqual(p.returncode,0)
            self.assertIn(diagnostic,p.stderr)

    def test_invalid_string_literals(self):
        for literal in ['"unterminated', r'"bad\q"', r'"nul\u0000"', r'"\ud800"']:
            with self.subTest(literal=literal):
                p,_,_=self.compile_source('fn main() -> int {print('+literal+');return 0;}')
                self.assertNotEqual(p.returncode,0)
                self.assertNotIn('Traceback',p.stderr)

class SystemsFoundationTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_checked_arithmetic(self):
        expressions=['2147483647 + 1','-2147483648 - 1','50000 * 50000',
                     '-(-2147483648)','1 / 0','1 % 0',
                     '-2147483648 / -1','-2147483648 % -1']
        for level in ('0','3'):
            for expression in expressions:
                with self.subTest(level=level,expression=expression):
                    p,_,exe=self.compile_source('fn main() -> int {print('+expression+');return 0;}',False,level)
                    self.assertEqual(p.returncode,0,p.stderr)
                    self.assertEqual(exe.returncode,1)
                    self.assertIn('nova runtime error:',exe.stderr)
                    self.assertNotIn('Traceback',exe.stderr)

    def test_signed_division_and_boundaries(self):
        self.native('fn main() -> int { print(-7 / 3); print(-7 % 3); '
                    'print(2147483647); print(-2147483648); return 0; }','-2\n-1\n2147483647\n-2147483648\n')

    def test_short_circuit_skips_runtime_error(self):
        self.native('fn main() -> int {print(false && (1 / 0)); '
                    'print(true || (2147483647 + 1)); return 0;}','0\n1\n')

    def test_string_comparison_and_length(self):
        self.native('fn id(s: str) -> str {return s;} fn main() -> int {'
                    'print("same" == id("same")); print("a" != "b"); '
                    'print("a" < "b"); print("b" >= "a"); '
                    'print("same" <= "same"); print("b" > "a"); '
                    'print(len("")); print(len("Grüße")); return 0;}',
                    '1\n1\n1\n1\n1\n1\n0\n7\n')

    def test_compound_assignments(self):
        self.native('fn main() -> int {var x=10; x+=5; x-=3; x*=2; x/=4; x%=4; print(x); return 0;}','2\n')
        p,_,_=self.compile_source('fn main() -> int {let x=1; x+=1;return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('immutable',p.stderr)

    def test_invalid_builtins_and_mixed_comparison(self):
        for body in ('print(len(1));','print(len());','print("x" == 1);'):
            p,_,_=self.compile_source('fn main() -> int {'+body+'return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertNotIn('Traceback',p.stderr)

    def test_no_fold_of_out_of_range_literals(self):
        p,_,_=self.compile_source('fn main() -> int {print(2147483648 - 1);return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('i32 range',p.stderr)

    def test_loop_allocations_are_in_entry_block(self):
        p,llvm,_=self.compile_source('fn main() -> int {var i=0; while i<10 {let n=i; i+=1;}return 0;}')
        self.assertEqual(p.returncode,0,p.stderr)
        # No stack allocation is allowed inside the repeated loop body.
        self.assertEqual(llvm.count('alloca '),2)
        self.assertNotIn('alloca ',llvm.split('entry:')[1])

    def test_runtime_symbol_isolation(self):
        self.native('fn exit(x: int) -> int {return x;} '
                    'fn nx_rt_fail(x: int) -> int {return x;} '
                    'fn main() -> int {print(exit(nx_rt_fail(42)));return 0;}','42\n')

    def test_cli_check_and_version(self):
        version=subprocess.run([sys.executable,str(COMPILER),'--version'],capture_output=True,text=True,timeout=20)
        self.assertEqual(version.returncode,0,version.stderr)
        self.assertIn('0.4.0',version.stdout)
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'input.nx'; source.write_text('fn main() -> int {return 0;}')
            output=Path(d)/'absent'
            result=subprocess.run([sys.executable,str(COMPILER),str(source),'--check','-o',str(output)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(output.exists())

    def test_cli_preserves_inputs_and_existing_ir(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'input.nx'; original='fn main() -> int {return 0;}'
            source.write_text(original)
            result=subprocess.run([sys.executable,str(COMPILER),str(source),'-o',str(source)],capture_output=True,text=True,timeout=20)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(source.read_text(),original)
            sentinel=Path(d)/'program.ll'; sentinel.write_text('keep this')
            result=subprocess.run([sys.executable,str(COMPILER),str(source),'-o',str(Path(d)/'program')],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(sentinel.read_text(),'keep this')

if __name__=='__main__':unittest.main()

