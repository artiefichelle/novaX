"""Native console parsing, EOF and ownership checks."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import test_compiler as helpers

class InputTests(unittest.TestCase):
    compile_source=helpers.CompilerTests.compile_source

    def run_cases(self, source, cases):
        for level in ('0','3'):
            with tempfile.TemporaryDirectory() as d:
                folder=Path(d); path=folder/'input.nx'; path.write_text(source)
                executable=folder/'run'
                build=subprocess.run([sys.executable,str(helpers.COMPILER),str(path),'-O'+level,'-o',str(executable)],capture_output=True,text=True,timeout=20)
                self.assertEqual(build.returncode,0,build.stderr)
                for data,stdout,error in cases:
                    with self.subTest(optimization=level,input=data):
                        run=subprocess.run([str(executable)],input=data,capture_output=True,timeout=5)
                        self.assertEqual(run.stdout.decode(),stdout)
                        if error:
                            self.assertEqual(run.returncode,1,run.stderr)
                            self.assertIn(error,run.stderr.decode())
                        else:
                            self.assertEqual(run.returncode,0,run.stderr)
                            self.assertEqual(run.stderr,b'')

    def test_integer_boundaries_and_signs(self):
        tokens=[b'0',b'-0',b'+0',b'2147483647',b'-2147483648',b'+00042',b'-00042']
        self.run_cases('fn main()->int{print(read_int());return 0;}',[(x,str(int(x))+'\n',None) for x in tokens])

    def test_ascii_whitespace_and_multiple_values(self):
        self.run_cases('fn main()->int{print(read_int());print(read_int());print(read_int());return 0;}',[(b' \t\r\n\v\f1\r\n-2\t+3  ','1\n-2\n3\n',None)])

    def test_overflow(self):
        self.run_cases('fn main()->int{print(read_int());return 0;}',[(x,'','exceeds i32 range') for x in [b'2147483648',b'-2147483649',b'99999999999999999999999']])

    def test_invalid_tokens(self):
        tokens=[b'+',b'-',b'--1',b'1.0',b'12x',b'0x10',b'1_000',b'1\x002',b'\xff',b'+ 1', '１２'.encode()]
        self.run_cases('fn main()->int{print(read_int());return 0;}',[(x,'','invalid integer input') for x in tokens])

    def test_required_input_eof(self):
        self.run_cases('fn main()->int{print(read_int());return 0;}',[(b'','','end of input'),(b' \t\n','','end of input')])

    def test_try_input_eof_preserves_value(self):
        self.run_cases('fn main()->int{var value=box(99);print(try_read_int(value));print(read_box(value));return 0;}',[(b'','false\n99\n',None),(b'\r\n','false\n99\n',None),(b'-2147483648','true\n-2147483648\n',None)])

    def test_try_input_loop(self):
        source='fn main()->int{var value=box(0);var sum=0;while try_read_int(value){sum=sum+read_box(value);}print(sum);print(read_box(value));return 0;}'
        self.run_cases(source,[(b'1 2 3','6\n3\n',None),(b'','0\n0\n',None)])

    def test_try_input_invalid_is_error(self):
        self.run_cases('fn main()->int{var value=box(99);print(try_read_int(value));return 0;}',[(b'x','','invalid integer input'),(b'2147483648','','exceeds i32 range')])

    def test_long_leading_zeros(self):
        self.run_cases('fn main()->int{print(read_int());return 0;}',[(b'0'*10000+b'42','42\n',None)])

    def test_reject_invalid_builtin_calls(self):
        cases=[('read_int(1);','Wrong number'),('try_read_int();','Wrong number'),('try_read_int(box(1));','named owner'),('let v=box(1);try_read_int(v);','mutable'),('var v=1;try_read_int(v);','Expected BoxInt'),('var v=box(1);let moved=v;try_read_int(v);','Use after move')]
        for body,error in cases:
            p,_,_=self.compile_source('fn main()->int{'+body+'return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn(error,p.stderr)

    def test_read_int_returns_int_and_try_returns_bool(self):
        for body in ['let flag:bool=read_int();','var value=box(0);let n:int=try_read_int(value);']:
            p,_,_=self.compile_source('fn main()->int{'+body+'return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('expected',p.stderr)

    def test_reserved_builtin_names(self):
        for name in ('read_int','try_read_int'):
            p,_,_=self.compile_source('fn '+name+'()->int{return 0;} fn main()->int{return 0;}')
            self.assertNotEqual(p.returncode,0)
            self.assertIn('Reserved name',p.stderr)

    def test_sanitized_stream(self):
        source='fn main()->int{var value=box(0);while try_read_int(value){print(read_box(value));}return 0;}'
        p,ir,_=self.compile_source(source)
        self.assertEqual(p.returncode,0,p.stderr)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d); (folder/'input.ll').write_text(ir)
            for level in ('0','3'):
                build=subprocess.run(['clang','-O'+level,'-fsanitize=address,undefined','-fno-sanitize-recover=all',str(folder/'input.ll'),str(helpers.ROOT/'src/runtime.c'),'-o',str(folder/'run')],capture_output=True,text=True,timeout=20)
                self.assertEqual(build.returncode,0,build.stderr)
                run=subprocess.run([str(folder/'run')],input=b'-2147483648 2147483647 -0 +1',capture_output=True,timeout=5)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertEqual(run.stdout,b'-2147483648\n2147483647\n0\n1\n')
                self.assertEqual(run.stderr,b'')

    def test_input_from_imported_module(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            (folder/'reader.nx').write_text('pub fn next()->int{return read_int();} pub fn next_into(value:BoxInt)->BoxInt{var local=value;try_read_int(local);return local;}')
            (folder/'main.nx').write_text('import "reader.nx" as reader;fn main()->int{print(reader::next());let b=reader::next_into(box(0));print(read_box(b));return 0;}')
            for level in ('0','3'):
                build=subprocess.run([sys.executable,str(helpers.COMPILER),str(folder/'main.nx'),'-O'+level,'-o',str(folder/'run')],capture_output=True,text=True,timeout=20)
                self.assertEqual(build.returncode,0,build.stderr)
                run=subprocess.run([str(folder/'run')],input=b'7 8',capture_output=True,timeout=5)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertEqual(run.stdout,b'7\n8\n')
