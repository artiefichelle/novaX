"""Unique owned texts, UTF-8 byte operations and automatic reclamation."""
import unittest
import sys
import subprocess
import tempfile
from pathlib import Path
import test_compiler as helpers

class TextTests(unittest.TestCase):
    compile_source=helpers.CompilerTests.compile_source
    native=helpers.LanguageV02Tests.native

    def reject(self, source, error):
        p,_,_=self.compile_source(source)
        self.assertNotEqual(p.returncode,0)
        self.assertIn(error,p.stderr)

    def test_utf8_and_static_string_coexist(self):
        self.native('fn main()->int{let literal="static"; let a=text("Hallo 🌍"); print_text(a);print(text_len(a));print(text_byte(a,6)); print(literal);return 0;}','Hallo 🌍\n10\n240\nstatic\n')

    def test_concat_borrows_both_owners(self):
        self.native('fn main()->int{let a=text("ab");let b=text("cd");let c=text_concat(a,b); print_text(c);print_text(a);print_text(b);let d=text_concat(a,a);print_text(d);return 0;}','abcd\nab\ncd\nabab\n')

    def test_clone_remains_after_source_drop(self):
        self.native('fn clone()->Text{let a=text("independent");return text_clone(a);} fn main()->int{let a=clone();print_text(a);return 0;}','independent\n')

    def test_moves_and_self_assignment(self):
        self.native('fn relay(a:Text)->Text{return a;}fn main()->int{let a=text("ok");var b=relay(a);b=b;print_text(b);return 0;}','ok\n')

    def test_overwrite_with_concat_of_self(self):
        self.native('fn main()->int{var a=text("x");a=text_concat(a,a);print_text(a);return 0;}','xx\n')

    def test_equal_and_empty(self):
        self.native('fn main()->int{let a=text("");let b=text("");let c=text("z");print(text_equal(a,b));print(text_equal(a,c));print(text_len(a));print(print_text(a));return 0;}','true\nfalse\n0\n\n0\n')

    def test_loop_replacement(self):
        self.native('fn relay(a:Text)->Text{return a;}fn main()->int{var a=text("x");let suffix=text("!");var i=0;while i<3{let b=relay(a);a=text_concat(b,suffix);i=i+1;}print_text(a);return 0;}','x!!!\n')

    def test_use_after_move(self):
        for access in ('text_len(a)','print_text(a)','text_clone(a)','text_equal(a,b)','text_concat(b,a)'):
            self.reject('fn main()->int{let a=text("x");let b=a;'+access+';return 0;}','Use after move')

    def test_text_not_implicitly_copyable_or_comparable(self):
        self.reject('fn main()->int{let a=text("x");let b=text("x");print(a==b);return 0;}','compared')
        self.reject('fn main()->int{let a=text("x");print(a);return 0;}','print')

    def test_owned_aggregate_fields_rejected(self):
        self.reject('struct S {value:Text}fn main()->int{return 0;}','Struct fields')
        self.reject('fn main()->int{let a=[text("x")];return 0;}','expected int')

    def test_borrows_require_named_typed_owner(self):
        self.reject('fn main()->int{text_len(text("x"));return 0;}','named owner')
        self.reject('fn main()->int{let a="x";text_len(a);return 0;}','Expected Text owner')
        self.reject('fn main()->int{let a=text("x");read_box(a);return 0;}','Expected BoxInt owner')

    def test_index_cannot_move_owner(self):
        self.reject('fn consume(a:Text)->int{return 0;}fn main()->int{let a=text("x");text_byte(a,consume(a));return 0;}','Use after move')

    def test_bounds_errors(self):
        for index in (-1,0,1):
            source='fn main()->int{let a=text("");print(text_byte(a,'+str(index)+'));return 0;}'
            for level in ('0','3'):
                p,_,exe=self.compile_source(source,False,level)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(exe.returncode,1)
                self.assertIn('text byte index out of bounds',exe.stderr)

    def test_loop_missing_replacement_rejected(self):
        self.reject('fn main()->int{let a=text("x");while true{let b=a;}return 0;}','reinitializing owner')

    def test_loop_condition_move_rejected(self):
        self.reject('fn consume(a:Text)->bool{return false;}fn main()->int{let a=text("x");while consume(a){}return 0;}','loop condition')

    def test_builtin_arity_and_return_types(self):
        for expr in ('text()','text_len()','text_byte()','text_concat()','text_clone()','text_equal()','print_text()'):
            self.reject('fn main()->int{'+expr+';return 0;}','Wrong number')
        self.reject('fn main()->int{let a:Text="x";return 0;}','expected Text')
        self.reject('fn main()->int{let a=text("x");let n:int=text_equal(a,a);return 0;}','expected int')

    def test_all_text_allocations_released(self):
        source='''fn relay(a:Text)->Text{let unused=text("unused");return a;}
fn maybe(flag:bool)->Text{let a=text("return");if flag{return a;}return text_clone(a);}
fn main()->int{let literal="static";let number=box(2);var a=text("a");a=text_concat(a,a);let b=relay(a);text_clone(b);text("discard");
var acc=text("x");let suffix=text("!");var i=0;while i<5{let old=acc;acc=text_concat(old,suffix);let temp=text("temp");i=i+1;if i==2{continue;}if i==4{break;}}print(text_len(acc));
let yes=maybe(true);let no=maybe(false);print_text(b);print_text(yes);print_text(no);print(literal);print(read_box(number));return 0;}'''
        p,ir,_=self.compile_source(source)
        self.assertEqual(p.returncode,0,p.stderr)
        runtime=(helpers.ROOT/'src/runtime.c').read_text()
        instrumentation='''static int allocations=0;
static void report_allocations(void){fprintf(stderr,"live=%d\\n",allocations);}
static void *tracked_malloc(size_t n){static int registered=0;if(!registered){atexit(report_allocations);registered=1;}void *p=malloc(n);if(p)allocations++;return p;}
static void tracked_free(void *p){if(p)allocations--;free(p);}
#define malloc tracked_malloc
#define free tracked_free
'''
        runtime=runtime.replace('_Noreturn void nx_rt_fail',instrumentation+'\n_Noreturn void nx_rt_fail')
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'main.ll').write_text(ir);(folder/'runtime.c').write_text(runtime)
            for level in ('0','3'):
                p=subprocess.run(['clang','-O'+level,'-fsanitize=address,undefined','-fno-sanitize-recover=all',str(folder/'main.ll'),str(folder/'runtime.c'),'-o',str(folder/'run')],capture_output=True,text=True,timeout=20)
                self.assertEqual(p.returncode,0,p.stderr)
                exe=subprocess.run([str(folder/'run')],capture_output=True,text=True,timeout=5)
                self.assertEqual(exe.returncode,0,exe.stderr)
                self.assertEqual(exe.stdout,'5\naa\nreturn\nreturn\nstatic\n2\n')
                self.assertEqual(exe.stderr,'live=0\n')

    def test_owned_text_in_module_api(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            (folder/'words.nx').write_text('pub fn greeting()->Text{return text("Hello");} pub fn add(a:Text)->Text{let suffix=text("!");return text_concat(a,suffix);}')
            (folder/'main.nx').write_text('import "words.nx" as words;fn main()->int{let a=words::greeting();let b=words::add(a);print_text(b);return 0;}')
            for level in ('0','3'):
                p=subprocess.run([sys.executable,str(helpers.COMPILER),str(folder/'main.nx'),'-O'+level,'-o',str(folder/'run')],capture_output=True,text=True,timeout=20)
                self.assertEqual(p.returncode,0,p.stderr)
                exe=subprocess.run([str(folder/'run')],capture_output=True,text=True,timeout=5)
                self.assertEqual(exe.returncode,0,exe.stderr)
                self.assertEqual(exe.stdout,'Hello!\n')
