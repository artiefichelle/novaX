"""Unique ownership, conservative control-flow checking and native reclamation."""
import subprocess
import tempfile
from pathlib import Path
import test_compiler as helpers
ROOT=helpers.ROOT
import unittest

class OwnershipTests(unittest.TestCase):
    compile_source=helpers.CompilerTests.compile_source
    native=helpers.LanguageV02Tests.native

    def test_move_return_and_mutation(self):
        self.native('fn relay(x: BoxInt) -> BoxInt { return x; } fn main() -> int { let a=box(4); var b=relay(a); write_box(b,42); print(read_box(b)); b=b; print(read_box(b)); return 0; }','42\n42\n')

    def test_reinitialization(self):
        self.native('fn main() -> int { var a=box(1); let b=a; a=box(2); print(read_box(a)+read_box(b)); return 0; }','3\n')

    def test_rejected_ownership(self):
        cases=[
            ('let a=box(1); let b=a; print(read_box(a));','Use after move'),
            ('let a=box(1); write_box(a,2);','mutable'),
            ('let a=box(1); if true { let b=a; } print(read_box(a));','Use after move'),
            ('let a=box(1); while false { let b=a; }','reinitializing owner'),
            ('let a=box(1); print(a);','print'),
            ('let a=box(1); let b=box(1); print(a==b);','compared'),
            ('read_box(box(1));','named owner'),
            ('let a=box(1); let xs=[a];','expected int'),
        ]
        for body,error in cases:
            with self.subTest(body=body):
                p,_,_=self.compile_source('fn main() -> int {'+body+' return 0;}')
                self.assertNotEqual(p.returncode,0)
                self.assertIn(error,p.stderr)

    def test_struct_owner_rejected(self):
        p,_,_=self.compile_source('struct S { a: BoxInt } fn main() -> int {return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Struct fields',p.stderr)

    def test_short_circuit_move_rejected(self):
        p,_,_=self.compile_source('fn take(x:BoxInt)->bool{return true;} fn main()->int{let a=box(1); let b=false && take(a); print(read_box(a)); return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Use after move',p.stderr)

    def test_borrow_owner_cannot_move_in_write_value(self):
        p,_,_=self.compile_source('fn take(x:BoxInt)->int{return read_box(x);} fn main()->int{var a=box(1); write_box(a,take(a)); return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Use after move',p.stderr)

    def test_all_exit_paths_release_allocations(self):
        source='''fn relay(x:BoxInt)->BoxInt {let unused=box(9); return x;}
fn early(n:int)->int {let a=box(n); if n==1 {return read_box(a);} return 0;}
fn main()->int { var a=box(1); a=box(2); let b=relay(a); box(3); early(1); early(0);
var i=0; while i<5 {let local=box(i); i=i+1; if i==2 {continue;} if i==4 {break;} let another=box(i);}
if true {let nested=box(5);} print(read_box(b)); return 0;}'''
        self.assert_reclaimed(source,'2\n')

    def assert_reclaimed(self, source, expected):
        p,ir,_=self.compile_source(source)
        self.assertEqual(p.returncode,0,p.stderr)
        runtime=(ROOT/'src/runtime.c').read_text()
        runtime=runtime.replace('/* A BoxInt', 'static int live_boxes=0;\nstatic void report_boxes(void) { fprintf(stderr,"live=%d\\n",live_boxes); }\n/* A BoxInt')
        runtime=runtime.replace('int32_t *p = malloc(sizeof(*p));','static int registered=0; if (!registered) {atexit(report_boxes); registered=1;}\n    int32_t *p = malloc(sizeof(*p)); if(p) live_boxes++;')
        runtime=runtime.replace('free(p);','if(p) live_boxes--; free(p);')
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d); (folder/'test.ll').write_text(ir); (folder/'runtime.c').write_text(runtime)
            for level in ('0','3'):
                build=subprocess.run(['clang','-O'+level,'-fsanitize=address',str(folder/'test.ll'),str(folder/'runtime.c'),'-o',str(folder/'run')],capture_output=True,text=True)
                self.assertEqual(build.returncode,0,build.stderr)
                run=subprocess.run([str(folder/'run')],capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertEqual(run.stdout,expected)
                self.assertEqual(run.stderr,'live=0\n')

    def test_loop_reinitialization_is_not_definite(self):
        p,_,_=self.compile_source('fn main()->int{var a=box(1); let b=a; while false {a=box(2);} print(read_box(a)); return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Use after move',p.stderr)

    def test_branch_exclusivity(self):
        self.native('fn take(x:BoxInt)->int{return read_box(x);} fn main()->int{let a=box(7); if true {print(take(a));} else {print(take(a));} return 0;}','7\n')

    def test_repeated_call_argument_rejected(self):
        p,_,_=self.compile_source('fn take(x:BoxInt,y:BoxInt)->int{return 0;} fn main()->int{let a=box(1); return take(a,a);}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Use after move',p.stderr)

    def test_loop_condition_move_rejected(self):
        p,_,_=self.compile_source('fn take(x:BoxInt)->bool{return false;} fn main()->int{let a=box(1); while take(a) {} return 0;}')
        self.assertNotEqual(p.returncode,0)
        self.assertIn('outer owner',p.stderr)
