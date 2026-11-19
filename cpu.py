"""Y86-64 sequential processor and the course JSON trace interface."""

import json
import sys

AOK, HLT, ADR, INS = 1, 2, 3, 4
RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, RNONE = range(8, 16)
REG_NAMES = (
    "rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
    "r8", "r9", "r10", "r11", "r12", "r13", "r14",
)

I_HALT, I_NOP, I_RRMOVQ, I_IRMOVQ = range(4)
I_RMMOVQ, I_MRMOVQ, I_ALU, I_JMP = range(4, 8)
I_CALL, I_RET, I_PUSHQ, I_POPQ = range(8, 12)
MAX_IFUN = {I_RRMOVQ: 6, I_ALU: 3, I_JMP: 6}
WITH_REG = (I_RRMOVQ, I_IRMOVQ, I_RMMOVQ, I_MRMOVQ, I_ALU, I_PUSHQ, I_POPQ)
WITH_CONST = (I_IRMOVQ, I_RMMOVQ, I_MRMOVQ, I_JMP, I_CALL)
WORD_BYTES = 8
MASK64 = (1 << 64) - 1


def signed64(value):
    """Interpret the low 64 bits as a two's complement integer."""
    bits = value & MASK64
    return bits - (1 << 64) if bits >= 1 << 63 else bits


class Y86Simulator:
    def __init__(self, mem_size=8192):
        self.memory = bytearray(mem_size)
        self.REG = [0] * (RNONE + 1)  # RNONE is a zero source, never a destination.
        self.CC = {"ZF": 1, "SF": 0, "OF": 0}
        self.PC = 0
        self.STAT = AOK
        self.trace = []

        # Combinational signals for the current instruction.
        self.icode = I_NOP
        self.ifun = 0
        self.rA = self.rB = RNONE
        self.valC = self.valP = self.valA = self.valB = self.valE = self.valM = 0
        self.Cnd = False

    def read_mem(self, addr, size):
        if addr < 0 or addr + size > len(self.memory):
            self.STAT = ADR
            return 0
        return int.from_bytes(self.memory[addr:addr + size], "little")

    def write_mem(self, addr, size, value):
        if addr < 0 or addr + size > len(self.memory):
            self.STAT = ADR
            return
        mask = (1 << (8 * size)) - 1
        self.memory[addr:addr + size] = (value & mask).to_bytes(size, "little")

    def check_cond(self, ifun):
        zero = bool(self.CC["ZF"])
        less = self.CC["SF"] != self.CC["OF"]
        # Function codes 0..6: always, le, l, e, ne, ge, g.
        return (True, less or zero, less, zero, not zero, not less, not less and not zero)[ifun]

    def fetch(self):
        first = self.read_mem(self.PC, 1)
        if self.STAT != AOK:
            return
        self.icode, self.ifun = first >> 4, first & 0xF
        op = self.icode
        if op > I_POPQ or self.ifun > MAX_IFUN.get(op, 0):
            self.STAT = INS
            return
        if op == I_HALT:
            self.STAT = HLT
            return

        cursor = self.PC + 1
        self.rA = self.rB = RNONE
        self.valC = 0
        if op in WITH_REG:
            pair = self.read_mem(cursor, 1)
            if self.STAT != AOK:
                return
            self.rA, self.rB = pair >> 4, pair & 0xF
            # The unused nibble is F in irmovq and in pushq/popq.
            needs_a = op != I_IRMOVQ
            needs_b = op not in (I_PUSHQ, I_POPQ)
            if (self.rA != RNONE, self.rB != RNONE) != (needs_a, needs_b):
                self.STAT = INS
                return
            cursor += 1
        if op in WITH_CONST:
            self.valC = self.read_mem(cursor, WORD_BYTES)
            if self.STAT != AOK:
                return
            cursor += WORD_BYTES
        self.valP = cursor

    def decode(self):
        op = self.icode
        srcA = srcB = RNONE
        if op in (I_RRMOVQ, I_RMMOVQ, I_ALU, I_PUSHQ):
            srcA = self.rA
        elif op in (I_POPQ, I_RET):
            srcA = RSP
        if op in (I_RMMOVQ, I_MRMOVQ, I_ALU):
            srcB = self.rB
        elif op in (I_CALL, I_RET, I_PUSHQ, I_POPQ):
            srcB = RSP
        self.valA, self.valB = self.REG[srcA], self.REG[srcB]

    def execute(self):
        op = self.icode
        self.valE = 0
        self.Cnd = op in (I_RRMOVQ, I_JMP) and self.check_cond(self.ifun)
        if op == I_ALU:
            a, b = signed64(self.valA), signed64(self.valB)
            if self.ifun == 0:
                result = b + a
            elif self.ifun == 1:
                result = b - a
            elif self.ifun == 2:
                result = b & a
            else:
                result = b ^ a
            self.valE = result & MASK64
            wrapped = signed64(self.valE)
            # Python preserves the exact signed result before 64-bit wraparound.
            self.CC.update(ZF=int(wrapped == 0), SF=int(wrapped < 0), OF=int(wrapped != result))
        elif op == I_RRMOVQ:
            self.valE = self.valA
        elif op == I_IRMOVQ:
            self.valE = self.valC
        elif op in (I_RMMOVQ, I_MRMOVQ):
            self.valE = (self.valB + self.valC) & MASK64
        elif op in (I_PUSHQ, I_CALL):
            self.valE = (self.valB - WORD_BYTES) & MASK64
        elif op in (I_POPQ, I_RET):
            self.valE = (self.valB + WORD_BYTES) & MASK64

    def memory_stage(self):
        op = self.icode
        self.valM = 0
        if op in (I_PUSHQ, I_RMMOVQ):
            self.write_mem(self.valE, WORD_BYTES, self.valA)
        elif op == I_CALL:
            self.write_mem(self.valE, WORD_BYTES, self.valP)
        elif op == I_MRMOVQ:
            self.valM = self.read_mem(self.valE, WORD_BYTES)
        elif op in (I_POPQ, I_RET):
            self.valM = self.read_mem(self.valA, WORD_BYTES)

    def write_back(self):
        op = self.icode
        if op in (I_CALL, I_RET, I_PUSHQ, I_POPQ):
            self.REG[RSP] = self.valE
        elif op in (I_IRMOVQ, I_ALU) or (op == I_RRMOVQ and self.Cnd):
            self.REG[self.rB] = self.valE
        # The memory port wins when popq %rsp writes both results to %rsp.
        if op in (I_MRMOVQ, I_POPQ):
            self.REG[self.rA] = self.valM

    def update_pc(self):
        if self.icode == I_CALL or (self.icode == I_JMP and self.Cnd):
            self.PC = self.valC
        elif self.icode == I_RET:
            self.PC = self.valM
        else:
            self.PC = self.valP

    def step(self):
        """Execute one instruction, leaving PC on a faulting or halting instruction."""
        if self.STAT != AOK:
            return
        self.fetch()
        if self.STAT != AOK:
            return
        self.decode()
        self.execute()
        self.memory_stage()
        self.write_back()  # The course model commits write-back even on a data ADR.
        if self.STAT == AOK:
            self.update_pc()

    def dump_state(self):
        words = {}
        for addr in range(0, len(self.memory), WORD_BYTES):
            value = int.from_bytes(self.memory[addr:addr + WORD_BYTES], "little")
            if value:
                words[str(addr)] = signed64(value)
        self.trace.append({
            "CC": self.CC.copy(),
            "MEM": words,
            "PC": self.PC,
            "REG": {name: signed64(self.REG[i]) for i, name in enumerate(REG_NAMES)},
            "STAT": self.STAT,
        })

    def load_program(self, file_obj):
        """Load .yo bytes. Return their optional source annotations for the demo."""
        listing = {}
        for line in file_obj:
            record, _, source = line.partition("|")
            address, sep, data = record.partition(":")
            if not sep or not data.strip():
                continue
            addr = int(address.strip(), 16)
            raw = bytes.fromhex(data)
            # Intersect the record with physical memory, without resizing the bytearray.
            start, stop = max(0, addr), min(len(self.memory), addr + len(raw))
            if start < stop:
                self.memory[start:stop] = raw[start - addr:stop - addr]
            listing[addr] = raw, source.partition("#")[0].strip()
        return listing

    def run(self):
        while self.STAT == AOK:
            self.step()
            self.dump_state()
        print(json.dumps(self.trace, indent=4))


if __name__ == "__main__":
    sim = Y86Simulator()
    sim.load_program(sys.stdin)
    sim.run()
