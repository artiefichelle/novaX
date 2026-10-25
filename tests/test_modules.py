import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMPILER=ROOT/'src/novax.py'
sys.path.insert(0,str(ROOT/'src'))
from modules import load_program
from frontend import CompileError


class ModuleTests(unittest.TestCase):
    def compile_tree(self, files, level='3', output='program'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,text in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            before={name:(root/name).read_bytes() for name in files}
            p=subprocess.run([sys.executable,str(COMPILER),str(root/'main.nx'),'-O'+level,'-o',str(root/output),'--opt-report'],capture_output=True,text=True,timeout=20)
            executable=subprocess.run([str(root/output)],capture_output=True,text=True,timeout=10) if p.returncode==0 else None
            after={name:(root/name).read_bytes() for name in files}
            return p,executable,before==after

    def test_public_struct_function_and_private_helper(self):
        files={'main.nx':'import "lib.nx" as lib;fn main() -> int {let p:lib::P=new lib::P {x:10};print(lib::moved(p).x);return 0;}',
               'lib.nx':'pub struct P {x:int}fn helper(x:int) -> int {return x+5;}pub fn moved(p:P) -> P {var q=p;q.x=helper(q.x);return q;}'}
        for level in ('0','3'):
            p,exe,_=self.compile_tree(files,level)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(exe.stdout,'15\n')

    def test_private_function_rejected(self):
        p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {return lib::hidden();}', 'lib.nx':'fn hidden() -> int {return 0;}'})
        self.assertNotEqual(p.returncode,0);self.assertIn('private',p.stderr)

    def test_private_struct_rejected(self):
        p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {let p=new lib::P {x:1};return 0;}', 'lib.nx':'struct P {x:int}'})
        self.assertNotEqual(p.returncode,0);self.assertIn('private',p.stderr)

    def test_transitive_diamond_imports_and_namespaces(self):
        files={'main.nx':'import "left.nx" as a;import "right.nx" as b;fn same() -> int {return 9;}fn main() -> int {print(a::same());print(b::same());print(same());return 0;}',
               'left.nx':'import "common.nx" as c;pub fn same() -> int {return c::value()+1;}',
               'right.nx':'import "common.nx" as c;pub fn same() -> int {return c::value()+2;}',
               'common.nx':'pub fn value() -> int {return 40;}'}
        p,exe,_=self.compile_tree(files)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(exe.stdout,'41\n42\n9\n')
        self.assertIn('"source_modules": 4',p.stderr)

    def test_duplicate_alias_missing_file_and_cycle(self):
        cases=[({'main.nx':'import "x.nx" as x;import "x.nx" as x;fn main() -> int {return 0;}','x.nx':''},'Duplicate import alias'),
               ({'main.nx':'import "missing.nx" as x;fn main() -> int {return 0;}'},'Cannot read source module'),
               ({'main.nx':'import "x.nx" as x;fn main() -> int {return 0;}','x.nx':'import "main.nx" as root;'},'Circular import')]
        for files,message in cases:
            p,_,_=self.compile_tree(files)
            self.assertNotEqual(p.returncode,0);self.assertIn(message,p.stderr)
            self.assertNotIn('Traceback',p.stderr)

    def test_imported_main_rejected(self):
        p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {return 0;}', 'lib.nx':'fn main() -> int {return 0;}'})
        self.assertNotEqual(p.returncode,0);self.assertIn('cannot define main',p.stderr)

    def test_diagnostic_points_to_imported_file(self):
        p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {return lib::f();}', 'lib.nx':'pub fn f() -> int {\nreturn "wrong";\n}'})
        self.assertNotEqual(p.returncode,0);self.assertIn('lib.nx:2:8: error:',p.stderr)

    def test_output_cannot_overwrite_dependency(self):
        p,_,preserved=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {return 0;}', 'lib.nx':'pub fn f() -> int {return 1;}'},output='lib.nx')
        self.assertNotEqual(p.returncode,0);self.assertTrue(preserved)
        self.assertIn('must not overwrite any source module',p.stderr)

    def test_import_resolution_errors(self):
        for body in ('return missing::f();','return lib::missing();'):
            p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {'+body+'}', 'lib.nx':'pub fn f() -> int {return 0;}'})
            self.assertNotEqual(p.returncode,0);self.assertIn('Unknown',p.stderr)

    def test_reserved_function_in_library(self):
        p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {return 0;}', 'lib.nx':'pub fn len() -> int {return 0;}'})
        self.assertNotEqual(p.returncode,0);self.assertIn('Reserved name',p.stderr)

    def test_loader_preserves_source_spans(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'main.nx').write_text('import "lib.nx" as lib;fn main() -> int {return lib::f();}')
            (root/'lib.nx').write_text('pub fn f() -> int {return 7;}')
            program,dependencies=load_program(root/'main.nx')
            self.assertEqual(len(dependencies),2)
            self.assertEqual(len(program.functions),2)
            self.assertTrue(program.functions[1].name.endswith('::f'))
            self.assertEqual(program.functions[1].span.source.filename,str((root/'lib.nx').resolve()))

    def test_public_api_cannot_expose_private_struct(self):
        p,_,_=self.compile_tree({'main.nx':'import "lib.nx" as lib;fn main() -> int {return 0;}',
                                'lib.nx':'struct Hidden {x:int}pub fn f() -> Hidden {return new Hidden {x:1};}'})
        self.assertNotEqual(p.returncode,0);self.assertIn('Public API exposes private struct',p.stderr)

    def test_two_aliases_refer_to_same_nominal_type(self):
        p,exe,_=self.compile_tree({'main.nx':'import "lib.nx" as a;import "lib.nx" as b;fn main() -> int {let p:a::P=new b::P {x:7};print(p.x);return 0;}',
                                  'lib.nx':'pub struct P {x:int}'})
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(exe.stdout,'7\n')
        self.assertIn('"source_modules": 2',p.stderr)

    def test_invalid_paths_and_import_depth(self):
        for path in ('/absolute.nx','wrong.txt'):
            p,_,_=self.compile_tree({'main.nx':'import '+json.dumps(path)+' as lib;fn main() -> int {return 0;}'})
            self.assertNotEqual(p.returncode,0)
        files={'main.nx':'import "m0.nx" as lib;fn main() -> int {return 0;}'}
        for i in range(34): files['m'+str(i)+'.nx']='import "m'+str(i+1)+'.nx" as next;'
        p,_,_=self.compile_tree(files)
        self.assertNotEqual(p.returncode,0);self.assertIn('32 levels',p.stderr)


if __name__=='__main__':unittest.main()
