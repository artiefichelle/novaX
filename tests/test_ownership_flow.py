"""Ownership joins follow reachable continuations and validate loop backedges."""
import unittest
import test_compiler as helpers
import test_ownership as ownership

class OwnershipFlowTests(unittest.TestCase):
    compile_source=helpers.CompilerTests.compile_source
    native=helpers.LanguageV02Tests.native

    def reject(self, body, error='reinitializing owner'):
        p,_,_=self.compile_source('fn main()->int{'+body+' return 0;}')
        self.assertNotEqual(p.returncode,0,p.stderr)
        self.assertIn(error,p.stderr)

    def test_returning_branch_does_not_poison_continuation(self):
        self.native('fn take(flag:bool)->int{let a=box(7); if flag {let b=a; return read_box(b);} return read_box(a);} fn main()->int{print(take(true));print(take(false));return 0;}','7\n7\n')

    def test_else_return_does_not_poison_continuation(self):
        self.native('fn take(flag:bool)->int{let a=box(8); if flag {} else {let b=a; return read_box(b);} return read_box(a);} fn main()->int{print(take(true)); print(take(false)); return 0;}','8\n8\n')

    def test_loop_move_reinitialized(self):
        self.native('fn main()->int{var a=box(0); var i=0; while i<4 {let b=a; a=box(read_box(b)+1); i=i+1;} print(read_box(a)); return 0;}','4\n')

    def test_continue_reinitialized(self):
        self.native('fn main()->int{var a=box(0);var i=0;while i<4{let b=a;a=box(read_box(b)+1);i=i+1;if i==2 {continue;} write_box(a,read_box(a)+1);}print(read_box(a));return 0;}','7\n')

    def test_break_move_is_allowed_when_not_reused(self):
        self.native('fn main()->int{let a=box(9);while true{let b=a; print(read_box(b));break;}return 0;}','9\n')

    def test_return_from_loop_may_move_outer_owner(self):
        self.native('fn take(flag:bool)->BoxInt{let a=box(10);while flag{return a;}return a;} fn main()->int{let a=take(true);let b=take(false);print(read_box(a)+read_box(b));return 0;}','20\n')

    def test_shadow_does_not_replace_outer_binding(self):
        self.reject('var a=box(1);while true{let b=a;var a=box(2);}', 'reinitializing owner: a')

    def test_conditional_reinitialization_is_not_enough(self):
        self.reject('var a=box(1);while true{let b=a;if true{a=box(2);}}')

    def test_continue_requires_reinitialization_before_transfer(self):
        self.reject('var a=box(1);while true{let b=a;if true{continue;}a=box(2);}')

    def test_break_paths_join_at_loop_exit(self):
        self.reject('let a=box(1);while true{if true{let b=a;break;}break;}print(read_box(a));','Use after move')

    def test_nested_break_targets_nearest_loop(self):
        self.reject('let a=box(1);while true{while true{let b=a;break;}}')

    def test_nested_loop_reinitialization(self):
        self.native('fn main()->int{var a=box(0);var i=0;while i<2{var j=0;while j<3{let b=a;a=box(read_box(b)+1);j=j+1;}i=i+1;}print(read_box(a));return 0;}','6\n')

    def test_break_reinitialized_preserves_owner(self):
        self.native('fn main()->int{var a=box(0);while true{let b=a;a=box(read_box(b)+5);break;}print(read_box(a));return 0;}','5\n')

    def test_continue_branch_does_not_poison_fallthrough(self):
        self.native('fn main()->int{var a=box(1);var i=0;while i<3{i=i+1;if i==2{let b=a;a=box(read_box(b)+3);continue;}write_box(a,read_box(a)+1);}print(read_box(a));return 0;}','6\n')

    def test_break_branch_does_not_poison_other_iteration_path(self):
        self.native('fn main()->int{let a=box(11);var i=0;while i<3{i=i+1;if i==2{let b=a;print(read_box(b));break;}print(read_box(a));}return 0;}','11\n11\n')

    def test_loop_memory_paths(self):
        source='''fn take(flag:bool)->BoxInt{let a=box(10);while flag{return a;}return a;}
fn main()->int{var a=box(0);var i=0;while i<5{let b=a;a=box(read_box(b)+1);i=i+1;if i==2{continue;}if i==4{let c=a;break;}}
let first=take(true);let second=take(false);print(read_box(first)+read_box(second));return 0;}'''
        self.assert_reclaimed(source,'20\n')

    assert_reclaimed=ownership.OwnershipTests.assert_reclaimed
