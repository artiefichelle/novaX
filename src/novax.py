#!/usr/bin/env python3
"""NOVA-X prototype compiler: experimental typed integers and strings -> LLVM IR -> clang executable."""
import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from llvmlite import ir, binding
import json
import tempfile

VERSION="0.4.0"

TOKEN = re.compile(r'(?P<WS>\s+)|(?P<COMMENT>//[^\n]*|/\*[\s\S]*?\*/)|(?P<STRING>"(?:[^"\\\n]|\\.)*")|(?P<NUM>\d+)|(?P<ID>[A-Za-z_][A-Za-z_0-9]*)|(?P<OP>\+=|-=|\*=|/=|%=|->|==|!=|<=|>=|&&|\|\||[@+*/%(){};,:=<>!-])|(?P<BAD>.)')
class CompileError(Exception): pass
@dataclass
class Tok:
    value: str
    pos: int

def lex(text):
    output=[]
    pos=0
    while pos < len(text):
        m=TOKEN.match(text,pos)
        if text.startswith('/*',pos) and m.lastgroup != 'COMMENT':
            raise CompileError(f'Unterminated block comment at offset {pos}')
        if m.lastgroup == 'BAD': raise CompileError(f'Unexpected character {m.group()!r} at offset {m.start()}')
        if m.lastgroup not in ('WS','COMMENT'): output.append(Tok(m.group(),m.start()))
        pos=m.end()
    output.append(Tok('<eof>',len(text)))
    return output

class Parser:
    def __init__(self, tokens): self.t=tokens; self.i=0
    def peek(self): return self.t[self.i].value
    def eat(self, v=None):
        t=self.t[self.i]
        if v is not None and t.value != v: raise CompileError(f'Expected {v!r}, got {t.value!r} at offset {t.pos}')
        self.i+=1; return t.value
    def ident(self):
        t=self.t[self.i]
        if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',t.value) or t.value in ('fn','let','var','return','if','else','while','break','continue','true','false','str','int'):
            raise CompileError(f'Expected identifier at offset {t.pos}')
        return self.eat()
    def parse(self):
        functions=[]
        while self.peek()!='<eof>':
            if self.peek()=='@':
                self.eat('@'); self.eat('optimize'); self.eat('('); self.eat('speed'); self.eat(')')
            self.eat('fn'); name=self.ident(); self.eat('('); args=[]
            if self.peek()!=')':
                while True:
                    arg=self.ident(); self.eat(':'); typ=self.eat()
                    if typ not in ('int','str'): raise CompileError('Expected parameter type int or str')
                    args.append((arg,typ))
                    if self.peek()!=',': break
                    self.eat(',')
            self.eat(')'); self.eat('->'); ret=self.eat()
            if ret not in ('int','str'): raise CompileError('Expected return type int or str')
            body=self.block(); functions.append((name,args,ret,body))
        return functions
    def block(self):
        self.eat('{'); statements=[]
        while self.peek()!='}':
            if self.peek()=='<eof>': raise CompileError('Unterminated block')
            statements.append(self.stmt())
        self.eat('}'); return statements
    def stmt(self):
        k=self.peek()
        if k in ('let','var'):
            self.eat(); name=self.ident()
            annotation=None
            if self.peek()==':':
                self.eat(':'); annotation=self.eat()
                if annotation not in ('int','str'): raise CompileError('Expected variable type int or str')
            self.eat('='); e=self.expr(); self.eat(';'); return ('decl',k,name,e,annotation)
        if k=='return': self.eat(); e=self.expr(); self.eat(';'); return ('return',e)
        if k=='if':
            self.eat(); cond=self.expr(); yes=self.block(); no=[]
            if self.peek()=='else':
                self.eat(); no=[self.stmt()] if self.peek()=='if' else self.block()
            return ('if',cond,yes,no)
        if k=='while': self.eat(); cond=self.expr(); return ('while',cond,self.block())
        if k in ('break','continue'):
            self.eat(); self.eat(';'); return (k,)
        if k=='print': self.eat(); self.eat('('); e=self.expr(); self.eat(')'); self.eat(';'); return ('print',e)
        if self.i+1 < len(self.t) and self.t[self.i+1].value in ('=','+=','-=','*=','/=','%='):
            name=self.ident(); op=self.eat(); expr=self.expr(); self.eat(';')
            if op!='=': expr=('binary',op[0],('name',name),expr)
            return ('assign',name,expr)
        e=self.expr(); self.eat(';')
        if e[0]!='call': raise CompileError('Only function calls may be used as expression statements')
        return ('expr',e)
    def expr(self, minprec=0):
        if self.peek() in ('-','!'):
            op=self.eat(); lhs=('unary',op,self.expr(7))
        elif self.peek()=='(':
            self.eat('('); lhs=self.expr(); self.eat(')')
        elif self.peek().startswith(chr(34)):
            literal=self.eat()
            try: value=json.loads(literal)
            except ValueError: raise CompileError('Invalid string escape or literal')
            if '\x00' in value: raise CompileError('Strings cannot contain NUL characters')
            try: value.encode('utf-8')
            except UnicodeEncodeError: raise CompileError('Invalid Unicode string')
            lhs=('string',value)
        elif self.peek() in ('true','false'): lhs=('num',int(self.eat()=='true'))
        elif self.peek().isdigit(): lhs=('num',int(self.eat()))
        else:
            name=self.ident()
            if self.peek()=='(':
                self.eat('('); args=[]
                if self.peek()!=')':
                    while True:
                        args.append(self.expr())
                        if self.peek()!=',': break
                        self.eat(',')
                self.eat(')'); lhs=('call',name,args)
            else: lhs=('name',name)
        precedence={'||':1,'&&':2,'==':3,'!=':3,'<':4,'>':4,'<=':4,'>=':4,'+':5,'-':5,'*':6,'/':6,'%':6}
        while precedence.get(self.peek(),-1)>=minprec:
            op=self.eat(); rhs=self.expr(precedence[op]+1); lhs=('binary',op,lhs,rhs)
        return lhs

I32=ir.IntType(32)
STR=ir.IntType(8).as_pointer()
TYPES={'int':I32,'str':STR}
class Compiler:
    def __init__(self, funcs):
        self.module=ir.Module(name='nova_x'); self.module.triple=binding.get_default_triple(); self.funcs={}
        if len({n for n,_,_,_ in funcs})!=len(funcs): raise CompileError('Duplicate function name')
        if 'main' not in {n for n,_,_,_ in funcs}: raise CompileError('Missing main function')
        for name,args,ret,_ in funcs:
            if name in ('print','printf','len'): raise CompileError('Reserved name: '+name)
            self.funcs[name]=ir.Function(self.module,ir.FunctionType(TYPES[ret],[TYPES[t] for _,t in args]),name=name if name=='main' else 'nx_user_'+name)
        if funcs[[n for n,_,_,_ in funcs].index('main')][1]: raise CompileError('main cannot have parameters')
        if self.funcs['main'].function_type.return_type != I32: raise CompileError('main must return int')
        self.printf=ir.Function(self.module,ir.FunctionType(I32,[ir.IntType(8).as_pointer()],var_arg=True),name='printf')
        self.fail=ir.Function(self.module,ir.FunctionType(ir.VoidType(),[STR]),name='nx_rt_fail')
        self.fail.attributes.add('noreturn')
        self.strlen=ir.Function(self.module,ir.FunctionType(I32,[STR]),name='nx_rt_len')
        self.strcmp=ir.Function(self.module,ir.FunctionType(I32,[STR,STR]),name='nx_rt_compare')
        self.checked={}
        for op in ('add','sub','mul'):
            typ=ir.FunctionType(ir.LiteralStructType([I32,ir.IntType(1)]),[I32,I32])
            self.checked[op]=ir.Function(self.module,typ,name=f'llvm.s{op}.with.overflow.i32')
        for name,args,ret,body in funcs: self.generate(name,args,body)
    def generate(self,name,args,body):
        fun=self.funcs[name]; allocations=fun.append_basic_block('allocations'); entry=fun.append_basic_block('entry'); self.allocations=ir.IRBuilder(allocations); self.builder=ir.IRBuilder(entry); self.scopes=[{}]; self.loops=[]
        for (arg_name,_),arg in zip(args,fun.args):
            if arg_name in self.scopes[-1]: raise CompileError('Duplicate argument: '+arg_name)
            slot=self.allocations.alloca(arg.type,name=arg_name); self.builder.store(arg,slot); self.scopes[-1][arg_name]=(slot,False)
        self.statements(body)
        if not self.builder.block.is_terminated: raise CompileError(f'Function {name} may exit without returning a value')
        self.allocations.branch(entry)
    def lookup(self,name):
        for scope in reversed(self.scopes):
            if name in scope:return scope[name]
        raise CompileError('Unknown variable: '+name)
    def require_type(self,value,expected,context):
        if value.type != expected:
            actual='str' if value.type == STR else 'int'
            wanted='str' if expected == STR else 'int'
            raise CompileError(f'{context}: expected {wanted}, got {actual}')
        return value
    def string_constant(self,text):
        data=text.encode('utf-8')+b'\x00'
        typ=ir.ArrayType(ir.IntType(8),len(data))
        glob=ir.GlobalVariable(self.module,typ,name=self.module.get_unique_name('.str'))
        glob.linkage='internal'; glob.global_constant=True
        glob.initializer=ir.Constant(typ,bytearray(data))
        zero=ir.Constant(I32,0)
        return glob.gep((zero,zero))
    def guard(self,bad,message):
        b=self.builder; f=b.function
        fail=f.append_basic_block('runtime.error'); ok=f.append_basic_block('runtime.ok')
        b.cbranch(bad,fail,ok); b.position_at_end(fail)
        b.call(self.fail,[self.string_constant(message)]); b.unreachable()
        b.position_at_end(ok)
    def arithmetic(self,op,a,c):
        b=self.builder
        if op in ('+','-','*'):
            result=b.call(self.checked[{'+':'add','-':'sub','*':'mul'}[op]],[a,c])
            value=b.extract_value(result,0); overflow=b.extract_value(result,1)
            self.guard(overflow,'integer overflow')
            return value
        zero=b.icmp_signed('==',c,ir.Constant(I32,0))
        self.guard(zero,'division by zero')
        minimum=b.icmp_signed('==',a,ir.Constant(I32,-2147483648))
        negative_one=b.icmp_signed('==',c,ir.Constant(I32,-1))
        self.guard(b.and_(minimum,negative_one),'integer overflow in division')
        return b.sdiv(a,c) if op=='/' else b.srem(a,c)
    def value(self,e):
        kind=e[0]; b=self.builder
        if kind=='string': return self.string_constant(e[1])
        if kind=='num':
            if e[1]>2147483647: raise CompileError('Integer literal exceeds i32 range')
            return ir.Constant(I32,e[1])
        if kind=='name': return b.load(self.lookup(e[1])[0])
        if kind=='call':
            if e[1]=='len':
                if len(e[2])!=1: raise CompileError('Wrong number of arguments to len')
                arg=self.require_type(self.value(e[2][0]),STR,'Argument to len')
                return b.call(self.strlen,[arg])
            if e[1] not in self.funcs: raise CompileError('Unknown function: '+e[1])
            fn=self.funcs[e[1]]
            if len(e[2])!=len(fn.args): raise CompileError('Wrong number of arguments to '+e[1])
            values=[self.require_type(self.value(x),arg.type,'Argument to '+e[1]) for x,arg in zip(e[2],fn.args)]
            return b.call(fn,values)
        if kind=='unary':
            if e[1]=='-' and e[2]==('num',2147483648): return ir.Constant(I32,-2147483648)
            v=self.require_type(self.value(e[2]),I32,'Unary '+e[1]); return self.arithmetic('-',ir.Constant(I32,0),v) if e[1]=='-' else b.zext(b.icmp_signed('==',v,ir.Constant(I32,0)),I32)
        if kind=='binary':
            op=e[1]; a=self.value(e[2])
            if op not in ('==','!=','<','>','<=','>='): self.require_type(a,I32,'Operator '+op)
            if op in ('&&','||'):
                # Evaluate the RHS only when the LHS cannot determine the result.
                origin=b.block; f=b.function
                rhs=f.append_basic_block('logic.rhs'); end=f.append_basic_block('logic.end')
                test=b.icmp_signed('!=',a,ir.Constant(I32,0))
                b.cbranch(test,rhs,end) if op=='&&' else b.cbranch(test,end,rhs)
                b.position_at_end(rhs)
                c=self.require_type(self.value(e[3]),I32,'Operator '+op); truth=b.zext(b.icmp_signed('!=',c,ir.Constant(I32,0)),I32)
                rhs_end=b.block; b.branch(end); b.position_at_end(end)
                result=b.phi(I32,'logic.result')
                result.add_incoming(ir.Constant(I32,0 if op=='&&' else 1),origin)
                result.add_incoming(truth,rhs_end)
                return result
            c=self.value(e[3]); self.require_type(c,a.type,'Operator '+op)
            if op in ('<','>','<=','>=','==','!='):
                if a.type==STR:
                    compared=b.call(self.strcmp,[a,c])
                    return b.zext(b.icmp_signed(op,compared,ir.Constant(I32,0)),I32)
                return b.zext(b.icmp_signed(op,a,c),I32)
            return self.arithmetic(op,a,c)
        raise CompileError('Invalid expression')
    def statements(self,items):
        self.scopes.append({})
        for s in items:
            if self.builder.block.is_terminated: raise CompileError('Unreachable statement after control transfer')
            k=s[0]; b=self.builder
            if k=='decl':
                _, mut,name,e,annotation=s
                if name in self.scopes[-1]: raise CompileError('Duplicate local: '+name)
                v=self.value(e)
                if annotation: self.require_type(v,TYPES[annotation],'Declaration '+name)
                slot=self.allocations.alloca(v.type,name=name); b.store(v,slot); self.scopes[-1][name]=(slot,mut=='var')
            elif k=='assign':
                slot,mutable=self.lookup(s[1]);
                if not mutable: raise CompileError('Cannot assign to immutable value: '+s[1])
                b.store(self.require_type(self.value(s[2]),slot.type.pointee,'Assignment '+s[1]),slot)
            elif k=='expr': self.value(s[1])
            elif k in ('break','continue'):
                if not self.loops: raise CompileError(k+' is only allowed inside a loop')
                b.branch(self.loops[-1][0 if k=='continue' else 1])
            elif k=='return': b.ret(self.require_type(self.value(s[1]),b.function.function_type.return_type,'Return'))
            elif k=='print':
                v=self.value(s[1]); fmt=self.string_constant('%s\n' if v.type==STR else '%d\n')
                b.call(self.printf,[fmt,v])
            elif k=='if':
                cond=self.require_type(self.value(s[1]),I32,'if condition'); test=b.icmp_signed('!=',cond,ir.Constant(I32,0)); f=b.function
                yes=f.append_basic_block('if.yes'); no=f.append_basic_block('if.no'); end=f.append_basic_block('if.end')
                b.cbranch(test,yes,no); b.position_at_end(yes); self.statements(s[2]); yt=b.block.is_terminated
                if not yt:b.branch(end)
                b.position_at_end(no); self.statements(s[3]); nt=b.block.is_terminated
                if not nt:b.branch(end)
                b.position_at_end(end)
                if yt and nt:b.unreachable()
            elif k=='while':
                f=b.function; cond_block=f.append_basic_block('while.cond'); body=f.append_basic_block('while.body'); end=f.append_basic_block('while.end')
                b.branch(cond_block); b.position_at_end(cond_block)
                test=b.icmp_signed('!=',self.require_type(self.value(s[1]),I32,'while condition'),ir.Constant(I32,0)); b.cbranch(test,body,end)
                b.position_at_end(body); self.loops.append((cond_block,end)); self.statements(s[2]); self.loops.pop();
                if not b.block.is_terminated:b.branch(cond_block)
                b.position_at_end(end)
        self.scopes.pop()

def optimize_program(funcs):
    """Deterministic optimization stage. No LLM/network access; do not claim AI.

    Performs semantics-preserving constant folding for operations where
    intermediate results fit i32. Excludes division, remainder and Boolean
    operators to preserve backend corner-case behavior.
    """
    report={'constant_folds': 0, 'ai_plugin_executed': False,
            'note': 'Deterministic optimization only; AI plugin interface is experimental.'}
    def expr(e):
        if e[0]=='binary':
            _,op,left,right=e
            left,right=expr(left),expr(right)
            if (left[0]=='num' and right[0]=='num' and op in ('+','-','*')
                    and 0<=left[1]<=2147483647 and 0<=right[1]<=2147483647):
                x,y=left[1],right[1]
                z={'+':lambda:x+y,'-':lambda:x-y,'*':lambda:x*y}[op]()
                if 0<=z<=2147483647:
                    report['constant_folds']+=1
                    return ('num',z)
            return ('binary',op,left,right)
        if e[0]=='unary':return ('unary',e[1],expr(e[2]))
        if e[0]=='call':return ('call',e[1],[expr(x) for x in e[2]])
        return e
    def statements(ss):
        out=[]
        for s in ss:
            k=s[0]
            if k=='decl':out.append((k,s[1],s[2],expr(s[3]),s[4]))
            elif k in ('assign',):out.append((k,s[1],expr(s[2])))
            elif k in ('return','print','expr'):out.append((k,expr(s[1])))
            elif k=='if':out.append((k,expr(s[1]),statements(s[2]),statements(s[3])))
            elif k=='while':out.append((k,expr(s[1]),statements(s[2])))
            elif k in ('break','continue'):out.append(s)
            else: raise CompileError('Unknown statement in optimizer: '+k)
        return out
    return [(name,args,ret,statements(body)) for name,args,ret,body in funcs],report

def main():
    ap=argparse.ArgumentParser(description='NOVA-X experimental systems-language compiler')
    ap.add_argument('--version',action='version',version='NOVA-X '+VERSION)
    ap.add_argument('source')
    ap.add_argument('-o','--output',default='a.out')
    ap.add_argument('--emit-llvm',action='store_true')
    ap.add_argument('--check',action='store_true',help='Type-check and verify LLVM IR without writing output')
    ap.add_argument('--opt-report',action='store_true',help='Print deterministic AST optimization counts')
    ap.add_argument('-O',choices=['0','1','2','3'],default='2')
    args=ap.parse_args()
    try:
        source=Path(args.source).resolve(); output=Path(args.output).resolve()
        if not args.check and source == output: raise CompileError('Output must not overwrite source')
        src=source.read_text(encoding='utf8')
        ast=Parser(lex(src)).parse(); ast,report=optimize_program(ast)
        c=Compiler(ast); llvm=str(c.module)
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
    except (CompileError,OSError,UnicodeError,RecursionError) as exc:
        print(f'nova error: {exc}',file=sys.stderr); return 1
if __name__=='__main__': sys.exit(main())
