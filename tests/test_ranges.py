import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from frontend import analyze_source, optimize_program, Binary
from ranges import RangeAnalysis, TOP, LOW, HIGH, join, widen, bottom


class IntervalTests(unittest.TestCase):
    def test_loop_invariant_and_array_bounds(self):
        source='fn main() -> int {let a=[1,19];var sum=0;var i=0;while i<100 {sum=(sum+a[i%2])%1000003;i+=1;}return 0;}'
        program,_=optimize_program(analyze_source(source))
        facts=RangeAnalysis().analyze(program)
        remainder=program.functions[0].body[3].body[0].value
        self.assertEqual(facts[id(remainder.left)],(1,1000021))

    def test_boundary_arithmetic_facts_cover_successful_results(self):
        intervals=[(LOW,LOW),(LOW,-1),(-10,10),(0,0),(0,HIGH),(HIGH,HIGH),TOP]
        for op in ('+','-','*','%'):
            program=analyze_source('fn f(a:int,b:int) -> int {return a'+op+'b;}fn main() -> int {return 0;}')
            expression=program.functions[0].body[0].value
            for a in intervals:
                for b in intervals:
                    analyzer=RangeAnalysis()
                    fact=analyzer.expression(expression,[{'a':a,'b':b}],True)
                    for x in set([a[0],a[1]]+[v for v in (-1,0,1) if a[0]<=v<=a[1]]):
                        for y in set([b[0],b[1]]+[v for v in (-1,0,1) if b[0]<=v<=b[1]]):
                            if op=='%':
                                if y==0 or (x==LOW and y==-1):continue
                                quotient=(abs(x)//abs(y))*(-1 if (x<0)!=(y<0) else 1)
                                result=x-quotient*y
                            else: result={'+':lambda:x+y,'-':lambda:x-y,'*':lambda:x*y}[op]()
                            if LOW<=result<=HIGH:
                                self.assertFalse(bottom(fact),(op,a,b,result))
                                self.assertLessEqual(fact[0],result,(op,a,b))
                                self.assertGreaterEqual(fact[1],result,(op,a,b))

    def test_bottom_join_and_widen(self):
        self.assertEqual(join((1,0),(2,3)),(2,3))
        self.assertEqual(widen((0,1),(-1,2)),TOP)

    def test_loop_with_unknown_call_does_not_prove_nonnegative_sum(self):
        program=analyze_source('fn value() -> int {return -3;}fn main() -> int {var x=0;var i=0;while i<4 {x=(x+value())%7;i+=1;}return 0;}')
        facts=RangeAnalysis().analyze(program)
        remainder=program.functions[1].body[2].body[0].value
        self.assertLess(facts[id(remainder.left)][0],0)


if __name__=='__main__':unittest.main()
