"""Boundary cases beyond the course's whole-program traces."""

import unittest

from cpu import ADR, AOK, HLT, INS, MASK64, RAX, RBX, RSP, Y86Simulator


def machine(code):
    raw = bytes.fromhex(code)
    cpu = Y86Simulator(len(raw))
    cpu.memory[:] = raw
    return cpu


class EdgeCases(unittest.TestCase):
    def test_malformed_instruction_stops_at_fetch(self):
        for code in ("ff", "01", "67 03", "77", "30 00", "20 f0", "a0 40"):
            with self.subTest(code=code):
                cpu = machine(code)
                cpu.step()
                self.assertEqual((cpu.STAT, cpu.PC, cpu.REG), (INS, 0, [0] * 16))

    def test_truncated_fetch_and_outside_pc(self):
        for code in ("", "20", "30 f0 00 00", "80 01 00"):
            with self.subTest(code=code):
                cpu = machine(code)
                cpu.step()
                self.assertEqual((cpu.STAT, cpu.PC, cpu.REG[RSP]), (ADR, 0, 0))

    def test_fetch_of_jump_target_occurs_next_cycle(self):
        cpu = machine("70 ff ff ff ff ff ff ff ff")
        cpu.step()
        self.assertEqual((cpu.STAT, cpu.PC), (AOK, MASK64))
        cpu.step()
        self.assertEqual((cpu.STAT, cpu.PC), (ADR, MASK64))

    def test_overflow_and_signed_conditions(self):
        minimum = 1 << 63
        for op, b, result, sf in (("60", minimum - 1, minimum, 1),
                                  ("61", minimum, minimum - 1, 0)):
            with self.subTest(op=op):
                cpu = machine(f"{op} 03")
                cpu.REG[RAX], cpu.REG[RBX] = 1, b
                cpu.step()
                self.assertEqual(cpu.REG[RBX], result)
                self.assertEqual(cpu.CC, {"ZF": 0, "SF": sf, "OF": 1})
                self.assertEqual(cpu.check_cond(2), sf == 0)  # jl uses SF xor OF.

    def test_logic_clears_overflow(self):
        for op in ("62", "63"):
            with self.subTest(op=op):
                cpu = machine(f"{op} 03")
                cpu.CC["OF"] = 1
                cpu.step()
                self.assertEqual(cpu.CC, {"ZF": 1, "SF": 0, "OF": 0})

    def test_conditional_move_matches_jump(self):
        # Compare signed b-a. In the final case, overflow reverses SF.
        for a, b in ((2, 1), (7, 7), (2, 3), (1, -(1 << 63))):
            predicates = (True, b <= a, b < a, b == a, b != a, b >= a, b > a)
            for fun, expected in enumerate(predicates):
                with self.subTest(a=a, b=b, fun=fun):
                    cpu = machine(f"61 03 2{fun} 01 7{fun} 00 00 00 00 00 00 00 00")
                    cpu.REG[RAX], cpu.REG[RBX] = a, b & MASK64
                    cpu.step()
                    cpu.step()
                    self.assertEqual(cpu.REG[1], a if expected else 0)
                    cpu.step()
                    self.assertEqual(cpu.PC, 0 if expected else len(cpu.memory))

    def test_data_fault_still_writes_back(self):
        cpu = machine("b0 4f")  # popq %rsp: failed read supplies zero to the last port.
        cpu.REG[RSP] = 1
        cpu.step()
        self.assertEqual((cpu.STAT, cpu.PC, cpu.REG[RSP]), (ADR, 0, 0))
        cpu = machine("a0 4f 00 00 00 00 00 00")
        cpu.REG[RSP] = 10  # New RSP = 2. Only six of the eight bytes would fit.
        before = bytes(cpu.memory)
        cpu.step()
        self.assertEqual((cpu.STAT, cpu.PC, cpu.REG[RSP]), (ADR, 0, 2))
        self.assertEqual(cpu.memory, before)

    def test_unaligned_word_at_last_legal_address(self):
        cpu = machine("00 " * 11)
        cpu.write_mem(3, 8, 0x8877665544332211)
        self.assertEqual(cpu.memory[3:], bytes.fromhex("11 22 33 44 55 66 77 88"))
        self.assertEqual(cpu.read_mem(3, 8), 0x8877665544332211)
        cpu.step()
        self.assertEqual(cpu.STAT, HLT)
        cpu.dump_state()
        self.assertEqual(cpu.trace[0]["MEM"]["8"], 0x887766)


if __name__ == "__main__":
    unittest.main()
