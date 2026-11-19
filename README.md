# Y86-64 顺序处理器模拟器

[![课程自动评测](https://github.com/realZillionX/PJ-Y86-Simulator/actions/workflows/grader.yml/badge.svg)](https://github.com/realZillionX/PJ-Y86-Simulator/actions/workflows/grader.yml)

复旦大学《计算机系统基础》课程项目。模拟器读取 Y86-64 的 `.yo` 机器码，依次执行取指、译码、执行、访存、写回和 PC 更新。从一条指令的机器码，到每个周期结束后的体系结构状态，都可以用仓库里的程序复现。[课程项目说明](https://ics-26fall-fdu.github.io/project/pj/) · [官方 Python 模板](https://github.com/ICS-26Fall-FDU/PJ-Y86-Simulator-py)

## 运行

在仓库根目录使用 Python 3，无第三方依赖。以下命令分别运行课程评测、边界测试，以及带有汇编注释的数组求和演示。

```bash
python3 test.py --bin "python3 cpu.py"
python3 -m unittest -v test_edges
python3 demo.py test/asum.yo
```

课程评测入口从标准输入读取机器码，向标准输出写一个 JSON 数组。每条指令对应一项快照，包含 `PC`、`REG`、`CC`、`MEM` 和 `STAT`。正常执行后的 `PC` 指向下一条指令；停机快照的 `PC` 保留在触发停机的指令上。寄存器与内存字以有符号十进制数输出，`MEM` 仅列出非零的 8 字节对齐字。

```bash
python3 cpu.py < test/asum.yo
```

## 一条指令如何通过六个阶段

以 `asum.yo` 的第一轮循环为例，`0x077` 处的 `mrmovq (%rdi), %r10` 长 10 字节。指令中的寄存器字节为 `a7`，高半字节指定目的寄存器 `%r10`，低半字节指定基址寄存器 `%rdi`。

| 阶段 | 源码入口 | 本周期发生的事 |
| --- | --- | --- |
| 取指 | `fetch` | 拆分 `50` 得到主操作码 5 和功能码 0；再读寄存器字节与 8 字节小端位移。得到 `valC = 0`、`valP = 0x081`。 |
| 译码 | `decode` | 选择 `rB` 作为地址基址，从 `%rdi` 读出 `valB = 0x018`。 |
| 执行 | `execute` | 计算有效地址 `valE = valB + valC = 0x018`。地址计算保留当前条件码。 |
| 访存 | `memory_stage` | 从 `0x018` 开始读 8 字节，小端拼成 `valM = 0x000d000d000d`。 |
| 写回 | `write_back` | 将 `valM` 写入 `%r10`。 |
| 更新 PC | `update_pc` | 选择顺序地址 `valP = 0x081`。下一条 `addq %r10, %rax` 将读到刚刚装入的值。 |

`Y86Simulator.step()` 执行一个周期。评分入口和终端演示都调用这个方法。[模拟器源码](cpu.py) · [演示入口](demo.py)

## 指令与数据通路

处理器有 15 个通用寄存器，`%rsp` 兼作栈指针。寄存器编号 `0xf` 表示此位置没有寄存器。内存默认为 8 KiB，按字节寻址。取指与数据访存共享同一个字节数组。

| 主操作码 | 指令 | 数据通路 |
| --- | --- | --- |
| `0 / 1` | `halt`、`nop` | 前者在取指阶段停机，后者顺序前进 1 字节。 |
| `2` | `rrmovq / cmovXX` | 从 `rA` 读数据；条件成立才写入 `rB`。功能码 0 表示无条件传送。 |
| `3` | `irmovq` | 将指令编码中的 8 字节常数写入 `rB`。 |
| `4 / 5` | `rmmovq`、`mrmovq` | 以 `R[rB] + D` 为地址，分别写入 `R[rA]` 或将读出的字写回 `rA`。 |
| `6` | `OPq` | 对 `R[rB]` 和 `R[rA]` 做加、减、与或异或。结果写回 `rB`，更新 `ZF / SF / OF`。 |
| `7` | `jXX` | 条件成立选择指令中的目标地址 `valC`，否则选择 `valP`。 |
| `8 / 9` | `call`、`ret` | 调用时将 `valP` 压栈并跳往 `valC`；返回时从旧栈顶读出下一条 PC。 |
| `a / b` | `pushq`、`popq` | 以 8 字节为单位调整 `%rsp`，在新栈顶写入或从旧栈顶读取。 |

### 算术、栈与异常

- **带符号溢出。** `subq rA, rB` 计算 `B − A`。先用 Python 整数求精确的带符号结果，再截取低 64 位。截断结果为零时置 `ZF`，最高位为 1 时置 `SF`，精确值与截断后的带符号值不等时置 `OF`。位运算的带符号结果始终可表示，因此清零 `OF`。有符号“小于”取 `SF xor OF`；跳转和条件传送共用这套判断。
- **同一个栈指针可以读写两次。** `pushq %rsp` 在译码时保存旧值，访存时将旧值写到新栈顶。`popq %rsp` 从旧栈顶读取数据，写回时先写递增后的栈指针，再写内存值，后者成为最终的 `%rsp`。
- **取指失败与访存失败具有不同的写回时序。** `STAT` 取 `AOK = 1`、`HLT = 2`、`ADR = 3`、`INS = 4`。取指越界、编码非法或遇到 `halt` 时直接停机。数据访存越界时，读返回 0，写不改变任何字节；按课程模型仍执行本条指令的写回，然后在更新 PC 之前停机。例如从 `%rsp = 0` 压栈，最终快照中 `%rsp = -8`。

## 现场演示：四个数组元素如何相加

`test/asum.yo` 以 `%rdi` 保存数组指针、`%rsi` 保存剩余元素数、`%rax` 保存累加和。启动代码将栈顶设为 `0x200`，在 `0x00a` 调用 `main`；`main` 在 `0x04c` 调用 `sum`。两个返回地址分别写到 `0x1f8` 和 `0x1f0`。

观察同一条条件跳转的五次执行：

```bash
python3 demo.py test/asum.yo --at 0x87 --watch rsi rax
```

| 执行步 | 剩余元素数 | 累加和（十六进制） | `jne` 选择的下一条 PC |
| ---: | ---: | ---: | --- |
| 11 | 4 | `0x000000000000` | `0x077`，进入循环体 |
| 16 | 3 | `0x000d000d000d` | `0x077` |
| 21 | 2 | `0x00cd00cd00cd` | `0x077` |
| 26 | 1 | `0x0bcd0bcd0bcd` | `0x077` |
| 31 | 0 | `0xabcdabcdabcd` | `0x090`，退出循环 |

第一次 `jne` 检查 `andq %rsi, %rsi` 留下的条件码。之后每轮由 `subq %r9, %rsi` 递减计数并更新条件码；最后一次产生 `ZF = 1`。两次 `ret` 依次返回 `0x055`、`0x013`。第 34 步执行 `halt`，此时 `%rsp` 恢复到 `0x200`。

```bash
python3 demo.py test/asum.yo --at 0xa 0x4c 0x90 0x55 0x13 --watch rsp
```

也可以对照 [程序清单](test/asum.yo)、[标准快照](answer/asum.json)和[边界测试](test_edges.py)，从任意一个周期追到对应的阶段实现。
