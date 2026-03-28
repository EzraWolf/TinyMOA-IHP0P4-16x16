# SPDX-FileCopyrightText: © 2026 Ezra Wolf
# SPDX-License-Identifier: Apache-2.0
#
# System integration tests for TinyMOA 2x2 grid of 8x8 DCIM cores.
# Tests only touch TT pins to simulate external FPGA.
#
# Pin mapping:
#   ui_in[7:0]   data_in
#   uo_out[7:0]  result (column sum of row-core pair)
#   uio[0]       IN   wen
#   uio[1]       IN   execute
#   uio[2]       IN   read_next
#   uio[3]       IN   acc_clear
#   uio[4]       OUT  col_sel[0]
#   uio[5]       OUT  col_sel[1]
#   uio[6]       OUT  col_sel[2]
#   uio[7]       OUT  done
#   uio_oe = 8'b11110000
#
# Data ordering:
#   Weight load (GRID*GRID * CORE_DIM*2 = 32 wen pulses):
#     row0_lo, row0_hi, row1_lo, row1_hi, ... (core row 0)
#     row8_lo, row8_hi, ... (core row 1)
#   Execute (GRID pulses per bit-plane):
#     act_lo (row 0 cores), act_hi (row 1 cores)
#   Readout (GRID*CORE_DIM = 16 read_next pulses):
#     cols 0-7 from core col 0, cols 8-15 from core col 1

import numpy as np
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

GRID = 2  # 2x2 grid of cores
CORE_DIM = 8  # each core is 8x8
ACC_WIDTH = 6
TOTAL_DIM = GRID * CORE_DIM  # 16


async def setup(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 1)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 1)


def read_uo(dut):
    return int(dut.uo_out.value)


def read_done(dut):
    return (int(dut.uio_out.value) >> 7) & 1


async def load_weights(dut, weight_rows):
    """Load TOTAL_DIM rows of TOTAL_DIM-bit weights.
    Each row sent as GRID bytes (lo, hi, ...).
    TOTAL_DIM * GRID = 32 wen pulses."""
    for row in weight_rows:
        for g in range(GRID):
            byte_val = (row >> (g * 8)) & 0xFF
            dut.ui_in.value = byte_val
            dut.uio_in.value = 0b0001  # wen
            await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0
    dut.uio_in.value = 0


async def do_execute(dut, *activations):
    """Execute with TOTAL_DIM-bit activations.
    Each sent as GRID bytes. GRID execute pulses per bit-plane."""
    for act in activations:
        for g in range(GRID):
            byte_val = (act >> (g * 8)) & 0xFF
            dut.ui_in.value = byte_val
            dut.uio_in.value = 0b0010  # execute
            await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0
    dut.uio_in.value = 0


async def read_results(dut):
    """Read TOTAL_DIM results. GRID*CORE_DIM read_next pulses."""
    results = []
    for _ in range(TOTAL_DIM):
        dut.uio_in.value = 0b0100  # read_next
        await ClockCycles(dut.clk, 1)
        results.append(read_uo(dut))
    dut.uio_in.value = 0
    return results


async def clear_acc(dut):
    dut.uio_in.value = 0b1000  # acc_clear
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0


# === Numpy DCIM-S reference model ===


def dcim_s_popcount(xnor_byte):
    """DCIM-S approximate popcount of an 8-bit value."""
    b = [(xnor_byte >> i) & 1 for i in range(8)]
    return (b[0] & b[1]) + (b[2] | b[3]) + (b[4] & b[5]) + (b[6] | b[7])


def dcim_s_mvm(weight_rows, activations):
    """Reference DCIM-S MVM for a GRID x GRID array of CORE_DIM x CORE_DIM cores.

    weight_rows: list of TOTAL_DIM ints (TOTAL_DIM-bit each)
    activations: list of P ints (TOTAL_DIM-bit each)
    Returns: list of TOTAL_DIM raw accumulator sums."""

    # Split weights into core quadrants
    core_weights = [[[] for _ in range(GRID)] for _ in range(GRID)]
    for r in range(GRID):
        for c in range(GRID):
            for row_idx in range(CORE_DIM):
                full_row = weight_rows[r * CORE_DIM + row_idx]
                core_weights[r][c].append((full_row >> (c * 8)) & 0xFF)

    # Transpose each core
    core_wreg = [[[] for _ in range(GRID)] for _ in range(GRID)]
    for r in range(GRID):
        for c in range(GRID):
            wreg = []
            for col in range(CORE_DIM):
                val = 0
                for row in range(CORE_DIM):
                    if core_weights[r][c][row] & (1 << col):
                        val |= 1 << row
                wreg.append(val)
            core_wreg[r][c] = wreg

    # Shift-accumulate per core
    core_acc = [[[0] * CORE_DIM for _ in range(GRID)] for _ in range(GRID)]
    for act_full in activations:
        for r in range(GRID):
            act_byte = (act_full >> (r * 8)) & 0xFF
            for c in range(GRID):
                for col in range(CORE_DIM):
                    xnor = (~(core_wreg[r][c][col] ^ act_byte)) & 0xFF
                    pc = dcim_s_popcount(xnor)
                    core_acc[r][c][col] = (core_acc[r][c][col] << 1) + pc

    # Sum row-cores per column
    results = []
    for c in range(GRID):
        for col in range(CORE_DIM):
            total = sum(core_acc[r][c][col] for r in range(GRID))
            results.append(total)
    return results


# === Tests ===


@cocotb.test()
async def test_reset_state(dut):
    """After reset, uo_out = 0, uio_oe = 0xF0."""
    await setup(dut)
    assert read_uo(dut) == 0, f"expected uo_out=0, got {read_uo(dut)}"
    assert int(dut.uio_oe.value) == 0xF0, (
        f"expected uio_oe=0xF0, got 0x{int(dut.uio_oe.value):02X}"
    )


@cocotb.test()
async def test_all_ones(dut):
    """All-ones weights and activation. All results equal and nonzero."""
    await setup(dut)
    all_ones = (1 << TOTAL_DIM) - 1
    await load_weights(dut, [all_ones] * TOTAL_DIM)
    await do_execute(dut, all_ones)
    results = await read_results(dut)
    expected = results[0]
    assert expected > 0, f"expected nonzero, got {expected}"
    for c, val in enumerate(results):
        assert val == expected, f"col {c}: got {val}, expected {expected}"


@cocotb.test()
async def test_all_zeros(dut):
    """All-zeros weights, all-ones activation. All results = 0."""
    await setup(dut)
    all_ones = (1 << TOTAL_DIM) - 1
    await load_weights(dut, [0] * TOTAL_DIM)
    await do_execute(dut, all_ones)
    results = await read_results(dut)
    for c, val in enumerate(results):
        assert val == 0, f"col {c}: expected 0, got {val}"


@cocotb.test()
async def test_weight_reuse(dut):
    """Execute, clear acc, execute with different activation."""
    await setup(dut)
    all_ones = (1 << TOTAL_DIM) - 1
    await load_weights(dut, [all_ones] * TOTAL_DIM)
    await do_execute(dut, all_ones)
    r1 = await read_results(dut)

    await clear_acc(dut)
    await do_execute(dut, 0)
    r2 = await read_results(dut)

    assert r1[0] > 0, f"first result should be nonzero, got {r1[0]}"
    for c, val in enumerate(r2):
        assert val == 0, f"col {c}: expected 0, got {val}"


@cocotb.test()
async def test_multibit(dut):
    """2-bit precision. Result should exceed single plane."""
    await setup(dut)
    all_ones = (1 << TOTAL_DIM) - 1
    await load_weights(dut, [all_ones] * TOTAL_DIM)
    await do_execute(dut, all_ones, all_ones)
    r2 = await read_results(dut)

    await clear_acc(dut)
    await do_execute(dut, all_ones)
    r1 = await read_results(dut)

    for c in range(TOTAL_DIM):
        assert r2[c] > r1[c], f"col {c}: 2-bit {r2[c]} should exceed 1-bit {r1[c]}"


@cocotb.test()
async def test_mvm_random(dut):
    """Random 16x16 binary MVM through TT pins."""
    rng = np.random.RandomState(42)
    await setup(dut)

    weight_rows = [int(rng.randint(0, 1 << TOTAL_DIM)) for _ in range(TOTAL_DIM)]
    activation = int(rng.randint(0, 1 << TOTAL_DIM))
    expected = dcim_s_mvm(weight_rows, [activation])

    dut._log.info(f"weights: {[f'0x{w:04X}' for w in weight_rows]}")
    dut._log.info(f"activation: 0x{activation:04X}")
    dut._log.info(f"expected: {expected}")

    await load_weights(dut, weight_rows)
    await do_execute(dut, activation)
    results = await read_results(dut)

    dut._log.info(f"results:  {results}")
    for c in range(TOTAL_DIM):
        assert results[c] == expected[c], (
            f"col {c}: got {results[c]}, expected {expected[c]}"
        )


@cocotb.test()
async def test_mvm_multibit_random(dut):
    """Random 16x16 binary MVM with 2-bit precision through TT pins."""
    rng = np.random.RandomState(99)
    await setup(dut)

    weight_rows = [int(rng.randint(0, 1 << TOTAL_DIM)) for _ in range(TOTAL_DIM)]
    act0 = int(rng.randint(0, 1 << TOTAL_DIM))
    act1 = int(rng.randint(0, 1 << TOTAL_DIM))
    expected = dcim_s_mvm(weight_rows, [act0, act1])

    dut._log.info(f"weights: {[f'0x{w:04X}' for w in weight_rows]}")
    dut._log.info(f"act planes: 0x{act0:04X}, 0x{act1:04X}")
    dut._log.info(f"expected: {expected}")

    await load_weights(dut, weight_rows)
    await do_execute(dut, act0, act1)
    results = await read_results(dut)

    dut._log.info(f"results:  {results}")
    for c in range(TOTAL_DIM):
        assert results[c] == expected[c], (
            f"col {c}: got {results[c]}, expected {expected[c]}"
        )
