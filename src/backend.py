"""LLVM lowering for an already analyzed NOVA-X Program."""
from llvmlite import ir, binding
from frontend import (CompileError, Literal, Name, Call, Unary, Binary, ArrayLiteral, Index, IndexAssign, ArrayType, StructType, StructLiteral, Field, FieldAssign,
                      Decl, Assign, Return, Print, ExprStmt, If, While, Transfer)

I32=ir.IntType(32)
STR=ir.IntType(8).as_pointer()
BOOL=ir.IntType(1)
BOX=I32.as_pointer()
TYPES={'int':I32,'str':STR,'bool':BOOL,'BoxInt':BOX}
class Compiler:
    def __init__(self, funcs, ranges=None):
        self.ranges=ranges or {}; self.modulo_reductions=0
        self.module=ir.Module(name='nova_x',context=ir.Context()); self.module.triple=binding.get_default_triple(); self.funcs={}
        self.struct_defs={definition.name:definition for definition in funcs.structs}
        self.struct_types={}
        for definition in funcs.structs:
            typ=self.module.context.get_identified_type('nx_struct_'+definition.name)
            self.struct_types[definition.name]=typ
        for definition in funcs.structs:
            self.struct_types[definition.name].set_body(*[self.llvm_type(field.typ) for field in definition.fields])
        for fn in funcs.functions:
            self.funcs[fn.name]=ir.Function(self.module,ir.FunctionType(self.llvm_type(fn.returns),[self.llvm_type(arg.typ) for arg in fn.args]),name=self.symbol_name(fn.name))
        self.printf=ir.Function(self.module,ir.FunctionType(I32,[ir.IntType(8).as_pointer()],var_arg=True),name='printf')
        self.fail=ir.Function(self.module,ir.FunctionType(ir.VoidType(),[STR]),name='nx_rt_fail')
        self.fail.attributes.add('noreturn')
        self.strlen=ir.Function(self.module,ir.FunctionType(I32,[STR]),name='nx_rt_len')
        self.strcmp=ir.Function(self.module,ir.FunctionType(I32,[STR,STR]),name='nx_rt_compare')
        self.box_new=ir.Function(self.module,ir.FunctionType(BOX,[I32]),name='nx_rt_box_new')
        self.box_get=ir.Function(self.module,ir.FunctionType(I32,[BOX]),name='nx_rt_box_get')
        self.box_set=ir.Function(self.module,ir.FunctionType(I32,[BOX,I32]),name='nx_rt_box_set')
        self.box_drop=ir.Function(self.module,ir.FunctionType(ir.VoidType(),[BOX]),name='nx_rt_box_drop')
        self.checked={}
        for op in ('add','sub','mul'):
            typ=ir.FunctionType(ir.LiteralStructType([I32,ir.IntType(1)]),[I32,I32])
            self.checked[op]=ir.Function(self.module,typ,name=f'llvm.s{op}.with.overflow.i32')
        for fn in funcs.functions: self.generate(fn.name,fn.args,fn.body)
    def symbol_name(self,name):
        if name=='main': return name
        if '::' not in name: return 'nx_user_'+name
        return 'nx_module_'+'_'.join(str(len(part))+part for part in name.split('::'))
    def llvm_type(self,typ):
        if isinstance(typ,ArrayType): return ir.ArrayType(I32,typ.size)
        if isinstance(typ,StructType): return self.struct_types[typ.name]
        return TYPES[typ]
    def field_index(self,base,name):
        return [field.name for field in self.struct_defs[base.typ.name].fields].index(name)
    def field_pointer(self,target):
        indices=[]
        node=target
        while isinstance(node,Field):
            indices.append(self.field_index(node.base,node.name))
            node=node.base
        slot,_=self.lookup(node.name)
        return self.builder.gep(slot,[ir.Constant(I32,0)]+[ir.Constant(I32,index) for index in reversed(indices)])
    def generate(self,name,args,body):
        fun=self.funcs[name]; allocations=fun.append_basic_block('allocations'); entry=fun.append_basic_block('entry'); self.allocations=ir.IRBuilder(allocations); self.builder=ir.IRBuilder(entry); self.scopes=[{}]; self.loops=[]
        for parameter,arg in zip(args,fun.args):
            arg_name=parameter.name
            if arg_name in self.scopes[-1]: raise CompileError('Duplicate argument: '+arg_name)
            slot=self.allocations.alloca(arg.type,name=arg_name); self.builder.store(arg,slot); self.scopes[-1][arg_name]=(slot,False)
        self.statements(body)
        if not self.builder.block.is_terminated: raise CompileError(f'Function {name} may exit without returning a value')
        self.allocations.branch(entry)
    def lookup(self,name):
        for scope in reversed(self.scopes):
            if name in scope:return scope[name]
        raise CompileError('Unknown variable: '+name)
    def cleanup(self,scopes):
        for scope in reversed(scopes):
            for slot,_ in reversed(list(scope.values())):
                if slot.type.pointee == BOX:
                    self.builder.call(self.box_drop,[self.builder.load(slot)])
                    self.builder.store(ir.Constant(BOX,None),slot)
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
    def index_pointer(self,target):
        b=self.builder
        slot,_=self.lookup(target.base.name)
        index=self.value(target.index)
        negative=b.icmp_signed('<',index,ir.Constant(I32,0))
        too_large=b.icmp_signed('>=',index,ir.Constant(I32,target.base.typ.size))
        self.guard(b.or_(negative,too_large),'array index out of bounds')
        return b.gep(slot,[ir.Constant(I32,0),index])
    def value(self,e):
        b=self.builder
        if isinstance(e,Literal):
            return self.string_constant(e.value) if e.typ=='str' else ir.Constant(TYPES[e.typ],e.value)
        if isinstance(e,StructLiteral):
            result=ir.Constant(self.llvm_type(e.typ),None)
            positions={field.name:index for index,field in enumerate(self.struct_defs[e.name].fields)}
            for name,value in e.fields: result=b.insert_value(result,self.value(value),positions[name])
            return result
        if isinstance(e,Field): return b.extract_value(self.value(e.base),self.field_index(e.base,e.name))
        if isinstance(e,ArrayLiteral):
            result=ir.Constant(ir.ArrayType(I32,len(e.elements)),None)
            for index,element in enumerate(e.elements): result=b.insert_value(result,self.value(element),index)
            return result
        if isinstance(e,Index): return b.load(self.index_pointer(e))
        if isinstance(e,Name):
            slot=self.lookup(e.name)[0]
            value=b.load(slot)
            if e.typ=='BoxInt': b.store(ir.Constant(BOX,None),slot)
            return value
        if isinstance(e,Call):
            if e.name=='box': return b.call(self.box_new,[self.value(e.args[0])])
            if e.name=='read_box': return b.call(self.box_get,[b.load(self.lookup(e.args[0].name)[0])])
            if e.name=='write_box':
                value=self.value(e.args[1])
                return b.call(self.box_set,[b.load(self.lookup(e.args[0].name)[0]),value])
            if e.name=='len':
                value=self.value(e.args[0])
                return ir.Constant(I32,e.args[0].typ.size) if isinstance(e.args[0].typ,ArrayType) else b.call(self.strlen,[value])
            if e.name=='to_bool': return b.icmp_signed('!=',self.value(e.args[0]),ir.Constant(I32,0))
            if e.name=='to_int': return b.zext(self.value(e.args[0]),I32)
            return b.call(self.funcs[e.name],[self.value(x) for x in e.args])
        if isinstance(e,Unary):
            if e.op=='-' and isinstance(e.operand,Literal) and e.operand.value==2147483648:
                return ir.Constant(I32,-2147483648)
            v=self.value(e.operand)
            return self.arithmetic('-',ir.Constant(I32,0),v) if e.op=='-' else b.not_(v)
        if isinstance(e,Binary):
            op=e.op; a=self.value(e.left)
            if op in ('&&','||'):
                origin=b.block; f=b.function
                rhs=f.append_basic_block('logic.rhs'); end=f.append_basic_block('logic.end')
                test=a
                b.cbranch(test,rhs,end) if op=='&&' else b.cbranch(test,end,rhs)
                b.position_at_end(rhs)
                truth=self.value(e.right)
                rhs_end=b.block; b.branch(end); b.position_at_end(end)
                result=b.phi(BOOL,'logic.result')
                result.add_incoming(ir.Constant(BOOL,0 if op=='&&' else 1),origin)
                result.add_incoming(truth,rhs_end)
                return result
            c=self.value(e.right)
            if op in ('<','>','<=','>=','==','!='):
                if e.left.typ=='str':
                    compared=b.call(self.strcmp,[a,c])
                    return b.icmp_signed(op,compared,ir.Constant(I32,0))
                return b.icmp_signed(op,a,c)
            bounds=self.ranges.get(id(e.left))
            if (op=='%' and isinstance(e.right,Literal) and e.right.typ=='int'
                    and e.right.value>0 and isinstance(bounds,tuple)
                    and 0<=bounds[0]<=bounds[1] and bounds[1]<2*e.right.value):
                self.modulo_reductions+=1
                return b.select(b.icmp_signed('>=',a,c),b.sub(a,c),a)
            return self.arithmetic(op,a,c)
        raise CompileError('Invalid expression')
    def statements(self,items):
        self.scopes.append({})
        for s in items:
            if self.builder.block.is_terminated: raise CompileError('Unreachable statement after control transfer')
            b=self.builder
            if isinstance(s,Decl):
                v=self.value(s.value)
                slot=self.allocations.alloca(v.type,name=s.name)
                if v.type==BOX: self.allocations.store(ir.Constant(BOX,None),slot)
                b.store(v,slot); self.scopes[-1][s.name]=(slot,s.mutable)
            elif isinstance(s,Assign):
                slot,_=self.lookup(s.name)
                value=self.value(s.value)
                if s.value.typ=='BoxInt': b.call(self.box_drop,[b.load(slot)])
                b.store(value,slot)
            elif isinstance(s,FieldAssign):
                pointer=self.field_pointer(s.target)
                b.store(self.value(s.value),pointer)
            elif isinstance(s,IndexAssign):
                pointer=self.index_pointer(s.target)
                b.store(self.value(s.value),pointer)
            elif isinstance(s,ExprStmt):
                value=self.value(s.value)
                if s.value.typ=='BoxInt': b.call(self.box_drop,[value])
            elif isinstance(s,Transfer):
                self.cleanup(self.scopes[self.loops[-1][2]:])
                b.branch(self.loops[-1][0 if s.kind=='continue' else 1])
            elif isinstance(s,Return):
                value=self.value(s.value)
                self.cleanup(self.scopes)
                b.ret(value)
            elif isinstance(s,Print):
                v=self.value(s.value)
                if s.value.typ=='bool': v=b.select(v,self.string_constant('true'),self.string_constant('false'))
                fmt=self.string_constant('%s\n' if v.type==STR else '%d\n')
                b.call(self.printf,[fmt,v])
            elif isinstance(s,If):
                test=self.value(s.condition); f=b.function
                yes=f.append_basic_block('if.yes'); no=f.append_basic_block('if.no'); end=f.append_basic_block('if.end')
                b.cbranch(test,yes,no); b.position_at_end(yes); self.statements(s.yes); yt=b.block.is_terminated
                if not yt:b.branch(end)
                b.position_at_end(no); self.statements(s.no); nt=b.block.is_terminated
                if not nt:b.branch(end)
                b.position_at_end(end)
                if yt and nt:b.unreachable()
            elif isinstance(s,While):
                f=b.function; cond_block=f.append_basic_block('while.cond'); body=f.append_basic_block('while.body'); end=f.append_basic_block('while.end')
                b.branch(cond_block); b.position_at_end(cond_block)
                test=self.value(s.condition); b.cbranch(test,body,end)
                b.position_at_end(body); self.loops.append((cond_block,end,len(self.scopes))); self.statements(s.body); self.loops.pop()
                if not b.block.is_terminated:b.branch(cond_block)
                b.position_at_end(end)
            else: raise TypeError('Unknown statement node: '+type(s).__name__)
        if not self.builder.block.is_terminated: self.cleanup([self.scopes[-1]])
        self.scopes.pop()

