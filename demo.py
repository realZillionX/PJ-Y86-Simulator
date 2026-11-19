"""Print an instruction trace from the same CPU used by the autograder."""

import argparse
from pathlib import Path

from cpu import ADR, AOK, HLT, INS, I_JMP, RAX, REG_NAMES, Y86Simulator


def source_at(cpu, listing):
    pc = cpu.PC
    if not 0 <= pc < len(cpu.memory):
        return "(fetch outside memory)"
    if pc in listing:
        raw, source = listing[pc]
        if source and cpu.memory[pc:pc + len(raw)] == raw:
            return " ".join(source.split())
    return f".byte 0x{cpu.memory[pc]:02x}"


def show_trace(program, at, watch):
    cpu = Y86Simulator()
    with program.open(encoding="utf-8") as stream:
        listing = cpu.load_program(stream)
    status = {AOK: "AOK", HLT: "HLT", ADR: "ADR", INS: "INS"}
    print("Step  PC      Next    Instruction                       Result")
    step = 0
    while cpu.STAT == AOK:
        pc = cpu.PC
        source = source_at(cpu, listing)
        previous = cpu.REG.copy()
        cpu.step()
        step += 1
        if at and pc not in at:
            continue
        details = []
        if cpu.icode == I_JMP and cpu.STAT == AOK:
            details.append("taken" if cpu.Cnd else "fall-through")
            details.append(f"ZF={cpu.CC['ZF']}")
        for i, name in enumerate(REG_NAMES):
            if name in watch or previous[i] != cpu.REG[i]:
                details.append(f"%{name}={cpu.REG[i]:#x}")
        if cpu.STAT != AOK:
            details.append(status[cpu.STAT])
        print(f"{step:>4}  {pc:#05x}   {cpu.PC:#05x}   {source:<32}  {'  '.join(details)}")
    print(f"\n{step} steps   {status[cpu.STAT]}   PC={cpu.PC:#x}   %rax={cpu.REG[RAX]:#x}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path, help="Y86 object listing (.yo)")
    parser.add_argument("--at", type=lambda s: int(s, 0), nargs="+", metavar="PC",
                        help="display only instructions executed at these addresses")
    parser.add_argument("--watch", choices=REG_NAMES, nargs="+", default=(),
                        help="also display these registers after each selected step")
    args = parser.parse_args()
    show_trace(args.program, args.at, args.watch)
