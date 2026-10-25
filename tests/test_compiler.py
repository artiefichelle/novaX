import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMPILER=ROOT/'src'/'novax.py'

class CompilerTests(unittest.TestCase):
    def compile_source(self, source, emit=True, optimization="2", extra=()):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.nx';path.write_text(source)
            cmd=[sys.executable,str(COMPILER),str(path),'-o',str(Path(d)/('test.ll' if emit else 'test'))]
            cmd.append("-O"+optimization)
            cmd.extend(extra)
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
        self.native('fn noisy() -> bool { print(99); return true; }\nfn main() -> int {\nprint(false && noisy()); print(true || noisy());\nprint(true && noisy()); print(false || noisy());\nprint((false || true) && (true || noisy())); return 0;\n}', 'false\ntrue\n99\ntrue\n99\ntrue\ntrue\n')

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
        self.native('fn choose(n: bool, text: str) -> str {\nif n { return text; } else { return "fallback"; }\n}\nfn main() -> int {\nlet message: str = "Hallo NOVA-X";\nvar selected = choose(true, message);\nprint(selected); selected = choose(false, message); print(selected);\nprint(42); return 0;\n}', 'Hallo NOVA-X\nfallback\n42\n')

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
        self.native('fn main() -> int {print(false && (1 / 0 == 0)); '
                    'print(true || (2147483647 + 1 == 0)); return 0;}','false\ntrue\n')

    def test_string_comparison_and_length(self):
        self.native('fn id(s: str) -> str {return s;} fn main() -> int {'
                    'print("same" == id("same")); print("a" != "b"); '
                    'print("a" < "b"); print("b" >= "a"); '
                    'print("same" <= "same"); print("b" > "a"); '
                    'print(len("")); print(len("Grüße")); return 0;}',
                    'true\ntrue\ntrue\ntrue\ntrue\ntrue\n0\n7\n')

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
        self.assertIn('0.10.0',version.stdout)
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

class ArchitectureRegressionTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_generated_integer_expressions_against_reference(self):
        import random
        rng=random.Random(501)
        def expression(depth):
            if not depth:
                n=rng.randint(-12,12)
                return str(n),n
            left,a=expression(depth-1)
            right,b=expression(depth-1)
            op=rng.choice(['+','-','*'])
            value={'+':lambda:a+b,'-':lambda:a-b,'*':lambda:a*b}[op]()
            return '('+left+op+right+')',value
        cases=[expression(3) for _ in range(40)]
        program='fn main() -> int {'+''.join('print('+text+');' for text,_ in cases)+'return 0;}'
        self.native(program,''.join(str(value)+'\n' for _,value in cases))

    def test_cli_source_diagnostic(self):
        p,_,_=self.compile_source('fn main() -> int {\n  let n: int = "oops";\n  return 0;\n}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('test.nx:2:16: error:',p.stderr)
        self.assertIn('^^^^^^',p.stderr)
        self.assertNotIn('Traceback',p.stderr)

class BooleanTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_boolean_functions_bindings_and_print(self):
        self.native('fn both(a: bool,b: bool) -> bool {return a && b;} '
                    'fn main() -> int {let ready: bool = 2<3; var ok=both(ready,true); '
                    'print(ok); ok=!ok; print(ok); print(ok==false); return 0;}',
                    'true\nfalse\ntrue\n')

    def test_boolean_short_circuit_and_casts(self):
        self.native('fn noisy() -> bool {print(99);return true;} fn main() -> int {'
                    'print(false && noisy()); print(true || noisy());'
                    'print(to_bool(-7));print(to_bool(0));print(to_int(true));'
                    'print(to_int(false)); return 0;}', 'false\ntrue\ntrue\nfalse\n1\n0\n')

    def test_boolean_abi_is_i1(self):
        p,llvm,_=self.compile_source('fn negate(x: bool) -> bool {return !x;} '
                                     'fn main() -> int {print(negate(false));return 0;}')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('define i1 @"nx_user_negate"(i1',llvm)

    def test_no_implicit_boolean_integer_conversion(self):
        cases=[
            'let x: int=true;', 'let x: bool=1;', 'var x=true;x=0;',
            'print(true+1);', 'print(-true);', 'print(!1);',
            'print(1 && true);', 'print(false || 0);', 'print(true==1);',
            'if 1 {print(0);}', 'while 1 {break;}', 'print(true < false);',
            'print(to_int(1));', 'print(to_bool(true));', 'print(to_bool("x"));',
            'print(to_bool());', 'print(to_int(true,false));',
        ]
        for body in cases:
            with self.subTest(body=body):
                p,_,_=self.compile_source('fn main() -> int {'+body+'return 0;}')
                self.assertNotEqual(p.returncode,0)
                self.assertIn('test.nx:1:',p.stderr)
                self.assertNotIn('Traceback',p.stderr)

    def test_boolean_function_type_errors(self):
        sources=[
            'fn flag() -> bool {return 1;} fn main() -> int {return 0;}',
            'fn f(x:bool) -> int {return 0;} fn main() -> int {return f(1);}',
            'fn main() -> bool {return true;}',
            'fn to_int(x:bool) -> int {return 0;} fn main() -> int {return 0;}',
        ]
        for source in sources:
            p,_,_=self.compile_source(source)
            self.assertNotEqual(p.returncode,0)
            self.assertNotIn('Traceback',p.stderr)

class ArrayTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_array_copy_mutation_and_assignment(self):
        self.native('fn main() -> int {var a:int[3]=[1,2,3];let copy=a;'
                    'a[0]=10;print(copy[0]);print(a[0]);a=[4,5,6];'
                    'print(a[2]);print(len(a));return 0;}', '1\n10\n6\n3\n')

    def test_array_sum_and_loop_initialization(self):
        self.native('fn main() -> int {let a=[10,20,30,];var i=0;var sum=0;'
                    'while i<len(a) {let local=[i,2];sum+=a[i]+local[0];i+=1;}'
                    'print(sum);return 0;}', '63\n')

    def test_empty_array_length(self):
        self.native('fn main() -> int {let a:int[0]=[];print(len(a));print(len([]));return 0;}', '0\n0\n')

    def test_array_side_effect_order(self):
        self.native('fn index() -> int {print(1);return 0;} '
                    'fn value() -> int {print(2);return 7;} '
                    'fn main() -> int {var a=[0];a[index()]=value();'
                    'print(a[0]);print(len([value(),value()]));return 0;}', '1\n2\n7\n2\n2\n2\n')

    def test_bounds_failures(self):
        for level in ('0','3'):
            for body in ('let a=[1];print(a[-1]);','let a=[1];print(a[1]);',
                         'var a=[1];a[-1]=0;','var a=[1];a[1]=0;',
                         'let a=[];print(a[0]);'):
                with self.subTest(level=level,body=body):
                    p,_,exe=self.compile_source('fn main() -> int {'+body+'return 0;}',False,level)
                    self.assertEqual(p.returncode,0,p.stderr)
                    self.assertEqual(exe.returncode,1)
                    self.assertIn('array index out of bounds',exe.stderr)

    def test_short_circuit_skips_index_error(self):
        self.native('fn main() -> int {let a=[];print(false && a[0]==1);'
                    'print(true || a[-1]==1);return 0;}', 'false\ntrue\n')

    def test_array_type_and_mutability_errors(self):
        bodies=['let a=[1];a[0]=2;', 'let a=[true];', 'let a=["x"];',
                'let a=[[1]];', 'let a:int[2]=[1];', 'var a=[1];a=[1,2];',
                'let a=[1];print(a[true]);', 'let a="x";print(a[0]);',
                'var a=[1];a[0]=false;', 'var a=[1];a[0]+=1;',
                'let a=[1];print(a);', 'let a=[1];print(a==a);',
                'let a=[1];print(a+1);','let a:bool[1]=[true];',
                'let a=[1];print([1][0]);']
        for body in bodies:
            with self.subTest(body=body):
                p,_,_=self.compile_source('fn main() -> int {'+body+'return 0;}')
                self.assertNotEqual(p.returncode,0)
                self.assertIn('test.nx:1:',p.stderr)
                self.assertNotIn('Traceback',p.stderr)

    def test_array_parameters_and_returns(self):
        self.native('fn echo(a:int[2]) -> int[2] {var copy=a;copy[0]=99;return copy;}fn main() -> int {let a=[1,2];let b=echo(a);print(a[0]);print(b[0]);return 0;}', '1\n99\n')

    def test_array_size_limit(self):
        for declaration in ('let a:int[4097]=[];','let a:int[-1]=[];',
                            'let a=['+','.join('0' for _ in range(4097))+'];'):
            p,_,_=self.compile_source('fn main() -> int {'+declaration+'return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('4096',p.stderr)

class RangeOptimizationTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source

    def compare_modes(self, source, expected=None, error=None):
        for extra in ((),('--no-range-opt',)):
            p,_,exe=self.compile_source(source,False,'3',extra)
            self.assertEqual(p.returncode,0,p.stderr)
            if error:
                self.assertEqual(exe.returncode,1)
                self.assertIn(error,exe.stderr)
            else:
                self.assertEqual(exe.returncode,0,exe.stderr)
                self.assertEqual(exe.stdout,expected)

    def test_inductive_modular_loop(self):
        source='fn main() -> int {let a=[1,3,5,7];var i=0;var sum=0;while i<10000 {sum=(sum+a[i%4])%97;i+=1;}print(sum);return 0;}'
        self.compare_modes(source,str((2500*16)%97)+'\n')
        p,_,_=self.compile_source(source,True,'3',('--opt-report',))
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('"modulo_reductions": 1',p.stderr)

    def test_negative_modulo_not_rewritten(self):
        self.compare_modes('fn main() -> int {var x=-3;var i=0;while i<10 {x=(x-2)%7;i+=1;}print(x);return 0;}', '-2\n')

    def test_array_mutation_and_shadowing(self):
        self.compare_modes('fn main() -> int {var a=[1];var x=0;var i=0;while i<3 {a[0]=-10;x=(x+a[0])%7;i+=1;}print(x);return 0;}', '-2\n')
        self.compare_modes('fn main() -> int {var x=3;var i=0;while i<3 {var x=-2;x=(x-1)%5;i+=1;}print(x);return 0;}', '3\n')

    def test_complex_loop_fallback(self):
        self.compare_modes('fn main() -> int {var x=0;var i=0;while i<8 {i+=1;if i==2 {continue;}else if i==6 {break;}x=(x-3)%7;}print(x);return 0;}', '-5\n')

    def test_checks_and_side_effects_preserved(self):
        self.compare_modes('fn main() -> int {var x=2147483647;x=(x+1)%7;print(x);return 0;}',error='integer overflow')
        self.compare_modes('fn main() -> int {var a=[1];var x=0;var i=0;while i<2 {x=(x+a[i])%7;i+=1;}print(x);return 0;}',error='array index out of bounds')
        self.compare_modes('fn step() -> int {print(9);return 3;}fn main() -> int {var x=0;var i=0;while i<2 {x=(x+step())%7;i+=1;}print(x);return 0;}', '9\n9\n6\n')

    def test_seeded_modular_loops_against_reference(self):
        import random
        rng=random.Random(808)
        for _ in range(10):
            values=[rng.randint(-20,20) for _ in range(4)]
            modulus=rng.randint(1,31)
            iterations=rng.randint(0,50)
            initial=rng.randint(-50,50)
            result=initial
            for i in range(iterations):
                value=result+values[i%4]
                quotient=(abs(value)//modulus)*(-1 if value<0 else 1)
                result=value-quotient*modulus
            source=('fn main() -> int {let a=['+','.join(map(str,values))+'];var x='+str(initial)+';var i=0;while i<'+str(iterations)+' {x=(x+a[i%4])%'+str(modulus)+';i+=1;}print(x);return 0;}')
            self.compare_modes(source,str(result)+'\n')

    def test_modulo_threshold_and_zero_iterations(self):
        self.compare_modes('fn main() -> int {var x=199;print(x%100);x=200;print(x%100);x=-1;print(x%100);print(2147483647%2147483647);return 0;}', '99\n0\n-1\n0\n')
        self.compare_modes('fn main() -> int {var x=100;var i=0;while i<0 {x=(x+1)%7;i+=1;}print(x%7);return 0;}', '2\n')

class AggregateFunctionTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_struct_construction_copy_and_functions(self):
        self.native('struct Point {x:int,y:int} '
                    'fn move(p:Point,dx:int) -> Point {var copy=p;copy.x=copy.x+dx;return copy;} '
                    'fn main() -> int {let p=new Point {y:20,x:10};var q=move(p,5);'
                    'print(p.x);print(q.x);q.y=99;print(p.y);print(q.y);print(move(p,2).x);return 0;}',
                    '10\n15\n20\n99\n12\n')

    def test_struct_primitive_fields_and_order(self):
        self.native('struct Item {enabled:bool,label:str,count:int,} '
                    'fn first() -> int {print(1);return 4;} '
                    'fn second() -> bool {print(2);return true;} '
                    'fn main() -> int {var item=new Item {count:first(),enabled:second(),label:"text"};'
                    'print(item.enabled);print(item.label);item.label="new";print(item.label);print(item.count);return 0;}',
                    '1\n2\ntrue\ntext\nnew\n4\n')

    def test_array_function_return_and_local_mutability(self):
        self.native('fn make() -> int[3] {return [4,5,6];} '
                    'fn sum(a:int[3]) -> int {var i=0;var total=0;while i<len(a) {total+=a[i];i+=1;}return total;} '
                    'fn main() -> int {let a=make();print(sum(a));print(len(make()));return 0;}', '15\n3\n')

    def test_aggregate_parameter_mutation_is_rejected(self):
        for source in [
            'fn f(a:int[1]) -> int {a[0]=1;return 0;}fn main() -> int {return 0;}',
            'struct P {x:int}fn f(p:P) -> int {p.x=1;return 0;}fn main() -> int {return 0;}',
        ]:
            p,_,_=self.compile_source(source)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('immutable',p.stderr)

    def test_invalid_structs(self):
        sources=[
            'struct P {x:int,x:int}fn main() -> int {return 0;}',
            'struct P {x:int}struct P {y:int}fn main() -> int {return 0;}',
            'struct P {x:Missing}fn main() -> int {return 0;}',
            'struct P {x:int[2]}fn main() -> int {return 0;}',
            'fn f(p:Missing) -> int {return 0;}fn main() -> int {return 0;}',
        ]
        for source in sources:
            p,_,_=self.compile_source(source)
            self.assertNotEqual(p.returncode,0)
            self.assertNotIn('Traceback',p.stderr)

    def test_struct_initializer_and_field_errors(self):
        bodies=['let p=new P {};','let p=new P {x:1,x:2};','let p=new P {y:1};',
                'let p=new P {x:true};','let p=new P {x:1};p.x=2;',
                'var p=new P {x:1};p.x=false;','let p=new P {x:1};print(p.y);',
                'let p=new P {x:1};print(p);','let p=new P {x:1};print(p==p);',
                'let p:Missing=new P {x:1};','new P {x:1}.x=2;']
        for body in bodies:
            p,_,_=self.compile_source('struct P {x:int}fn main() -> int {'+body+'return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('test.nx:1:',p.stderr)
            self.assertNotIn('Traceback',p.stderr)

    def test_aggregate_function_type_errors(self):
        for source in [
            'fn f(a:int[2]) -> int {return 0;}fn main() -> int {return f([1]);}',
            'fn f() -> int[2] {return [1];}fn main() -> int {return 0;}',
            'struct A {x:int}struct B {x:int}fn f(p:A) -> int {return 0;}fn main() -> int {return f(new B {x:1});}',
        ]:
            p,_,_=self.compile_source(source)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('expected',p.stderr)

    def test_array_return_bounds_are_checked(self):
        for level in ('0','3'):
            p,_,exe=self.compile_source('fn make() -> int[1] {return [42];}fn main() -> int {let a=make();print(a[1]);return 0;}',False,level)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(exe.returncode,1)
            self.assertIn('array index out of bounds',exe.stderr)

    def test_empty_aggregates_and_forward_type(self):
        self.native('fn echo(e:Empty,a:int[0]) -> Empty {return e;} '
                    'struct Empty {} fn main() -> int {let e=echo(new Empty {},[]);print(len([]));return 0;}', '0\n')

class NestedStructTests(unittest.TestCase):
    compile_source=CompilerTests.compile_source
    native=LanguageV02Tests.native

    def test_nested_copy_write_and_return(self):
        self.native('struct Point {x:int,y:int} struct Box {start:Point,end:Point} '
                    'fn moved(b:Box) -> Box {var copy=b;copy.start.x=copy.start.x+5;return copy;}'
                    'fn main() -> int {let p=new Point {x:1,y:2};let b=new Box {start:p,end:p};'
                    'var c=moved(b);c.end=new Point {x:9,y:8};print(b.start.x);print(c.start.x);'
                    'print(c.end.y);print(moved(b).start.x);return 0;}', '1\n6\n8\n6\n')

    def test_forward_nested_definition(self):
        self.native('struct Outer {inner:Inner} struct Inner {flag:bool,text:str}'
                    'fn main() -> int {var o=new Outer {inner:new Inner {flag:true,text:"hi"}};'
                    'o.inner.flag=false;o.inner.text="new";print(o.inner.flag);print(o.inner.text);return 0;}',
                    'false\nnew\n')

    def test_recursive_types_rejected(self):
        for declarations in ('struct A {self:A}', 'struct A {b:B}struct B {a:A}'):
            p,_,_=self.compile_source(declarations+'fn main() -> int {return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('Recursive by-value',p.stderr)
            self.assertNotIn('Traceback',p.stderr)

    def test_nested_errors(self):
        prefix='struct P {x:int}struct Box {p:P}'
        for body in ('let b=new Box {p:new P {x:1}};b.p.x=2;',
                     'var b=new Box {p:new P {x:1}};b.p=false;',
                     'let b=new Box {p:1};','let b=new Box {p:new P {x:1}};print(b.p.missing);'):
            p,_,_=self.compile_source(prefix+'fn main() -> int {'+body+'return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('test.nx:1:',p.stderr)
            self.assertNotIn('Traceback',p.stderr)

    def test_struct_storage_limit(self):
        declarations='struct S0 {x:int}'
        for i in range(1,15): declarations+='struct S'+str(i)+' {a:S'+str(i-1)+',b:S'+str(i-1)+'}'
        p,_,_=self.compile_source(declarations+'fn main() -> int {return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('64 KiB',p.stderr)
        declarations='struct D0 {}'
        for i in range(1,67): declarations+='struct D'+str(i)+' {child:D'+str(i-1)+'}'
        p,_,_=self.compile_source(declarations+'fn main() -> int {return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('64 levels',p.stderr)

if __name__=='__main__':unittest.main()

