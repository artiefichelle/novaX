#!/usr/bin/env python3
"""NOVA-X prototype compiler: experimental typed integers, booleans and strings -> LLVM IR -> clang executable."""
import argparse
import subprocess
import sys
from pathlib import Path
from llvmlite import binding
import json
import tempfile

VERSION="0.15.0"

from frontend import CompileError, analyze_source, optimize_program
from backend import Compiler
from ranges import RangeAnalysis
from modules import load_program

def main():
    ap=argparse.ArgumentParser(description='NOVA-X experimental systems-language compiler')
    ap.add_argument('--version',action='version',version='NOVA-X '+VERSION)
    ap.add_argument('source')
    ap.add_argument('-o','--output',default='a.out')
    ap.add_argument('--emit-llvm',action='store_true')
    ap.add_argument('--check',action='store_true',help='Type-check and verify LLVM IR without writing output')
    ap.add_argument('--no-range-opt',action='store_true',help='Disable interval-proven modulo reduction')
    ap.add_argument('--opt-report',action='store_true',help='Print deterministic AST optimization counts')
    ap.add_argument('-O',choices=['0','1','2','3'],default='2')
    args=ap.parse_args()
    try:
        source=Path(args.source).resolve(); output=Path(args.output).resolve()
        if not args.check and source == output: raise CompileError('Output must not overwrite source')
        ast,dependencies=load_program(source)
        if not args.check and output in dependencies: raise CompileError('Output must not overwrite any source module')
        ast,report=optimize_program(ast)
        report['source_modules']=len(dependencies)
        facts=RangeAnalysis().analyze(ast) if args.O in ('2','3') and not args.no_range_opt else {}
        c=Compiler(ast,facts); llvm=str(c.module)
        report['modulo_reductions']=c.modulo_reductions
        try: binding.parse_assembly(llvm).verify()
        except RuntimeError as exc: raise CompileError('LLVM verification failed: '+str(exc))
        if args.opt_report: print(json.dumps(report,indent=2),file=sys.stderr)
        if args.check:
            print('NOVA-X check passed: '+str(source)); return 0
        if args.emit_llvm: output.write_text(llvm,encoding='utf8'); return 0
        runtime=Path(__file__).resolve().with_name('runtime.c')
        if not runtime.is_file(): raise CompileError('Missing runtime.c beside compiler')
        with tempfile.TemporaryDirectory(prefix='novax-') as temp:
            irfile=Path(temp)/'module.ll'; irfile.write_text(llvm,encoding='utf8')
            native=Path(temp)/'program'
            try:
                subprocess.run(['clang',f'-O{args.O}',str(irfile),str(runtime),'-o',str(native)],check=True,capture_output=True,text=True)
            except FileNotFoundError: raise CompileError('clang not found; install clang or use --emit-llvm')
            except subprocess.CalledProcessError as exc: raise CompileError('LLVM backend failed:\n'+exc.stderr)
            # A failed compilation preserves any previous output file.
            import shutil
            shutil.copy2(native,output)
        print(f'NOVA-X compiled {source} -> {output}'); return 0
    except CompileError as exc:
        print(exc.render(),file=sys.stderr); return 1
    except (OSError,UnicodeError,RecursionError) as exc:
        print(f'nova error: {exc}',file=sys.stderr); return 1
if __name__=='__main__': sys.exit(main())
