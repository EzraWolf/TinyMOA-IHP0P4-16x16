# SPDX-FileCopyrightText: © 2026 Ezra Wolf
# SPDX-License-Identifier: Apache-2.0
#
# System integration tests for TinyMOA 8x8 DCIM.
# Tests only touch TT pins to simulate external FPGA.
#
# Pin mapping:
#   ui_in[7:0]   data_in
#   uo_out[7:0]  result (zero-padded)
#   uio[0]       IN   wen
#   uio[1]       IN   execute
#   uio[2]       IN   read_next
#   uio[3]       IN   acc_clear
#   uio[4]       OUT  col_sel[0]
#   uio[5]       OUT  col_sel[1]
#   uio[6]       OUT  col_sel[2]
#   uio[7]       OUT  done
#   uio_oe = 8'b11110000

import numpy as np
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

ARRAY_DIM = 8
ACC_WIDTH = 6


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


def read_col_sel(dut):
    return (int(dut.uio_out.value) >> 4) & 0x07


def read_done(dut):
    return (int(dut.uio_out.value) >> 7) & 1


async def load_weights(dut, rows):
    for row in rows:
        dut.ui_in.value = row & 0xFF
        dut.uio_in.value = 0b0001  # wen
        await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0
    dut.uio_in.value = 0


async def do_execute(dut, *activations):
    for act in activations:
        dut.ui_in.value = act & 0xFF
        dut.uio_in.value = 0b0010  # execute
        await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0
    dut.uio_in.value = 0


async def read_results(dut):
    results = []
    for _ in range(ARRAY_DIM):
        dut.uio_in.value = 0b0100  # read_next
        await ClockCycles(dut.clk, 1)
        results.append(read_uo(dut))
    dut.uio_in.value = 0
    return results


async def clear_acc(dut):
    dut.uio_in.value = 0b1000  # acc_clear
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0


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
    """Load 8x 0xFF, execute act=0xFF. All results equal and nonzero."""
    await setup(dut)
    await load_weights(dut, [0xFF] * ARRAY_DIM)
    await do_execute(dut, 0xFF)
    results = await read_results(dut)
    expected = results[0]
    assert expected > 0, f"expected nonzero, got {expected}"
    for c, val in enumerate(results):
        assert val == expected, f"col {c}: got {val}, expected {expected}"


@cocotb.test()
async def test_all_zeros(dut):
    """Load 8x 0x00, execute act=0xFF. All results = 0."""
    await setup(dut)
    await load_weights(dut, [0x00] * ARRAY_DIM)
    await do_execute(dut, 0xFF)
    results = await read_results(dut)
    for c, val in enumerate(results):
        assert val == 0, f"col {c}: expected 0, got {val}"


@cocotb.test()
async def test_weight_reuse(dut):
    """Execute, clear acc, execute again with different activation. Weights stay."""
    await setup(dut)
    await load_weights(dut, [0xFF] * ARRAY_DIM)
    await do_execute(dut, 0xFF)
    r1 = await read_results(dut)

    await clear_acc(dut)
    await do_execute(dut, 0x00)
    r2 = await read_results(dut)

    assert r1[0] > 0, f"first result should be nonzero, got {r1[0]}"
    for c, val in enumerate(r2):
        assert val == 0, f"col {c}: expected 0 for act=0x00, got {val}"


@cocotb.test()
async def test_multibit(dut):
    """precision=2. Two activation planes. Result should exceed single plane."""
    await setup(dut)
    await load_weights(dut, [0xFF] * ARRAY_DIM)
    await do_execute(dut, 0xFF, 0xFF)
    r2 = await read_results(dut)

    await clear_acc(dut)
    await do_execute(dut, 0xFF)
    r1 = await read_results(dut)

    for c in range(ARRAY_DIM):
        assert r2[c] > r1[c], f"col {c}: 2-bit {r2[c]} should exceed 1-bit {r1[c]}"


@cocotb.test()
async def test_done_flag(dut):
    """done pulses after execute."""
    await setup(dut)
    await load_weights(dut, [0xFF] * ARRAY_DIM)
    assert read_done(dut) == 0, "done should be 0 before execute"
    dut.ui_in.value = 0xFF
    dut.uio_in.value = 0b0010  # execute
    for cycle in range(4):
        await ClockCycles(dut.clk, 1)
        uio_val = int(dut.uio_out.value)
        dut._log.info(f"cycle {cycle}: uio_out=0b{uio_val:08b} done={read_done(dut)}")
    dut.uio_in.value = 0
    dut.ui_in.value = 0


# === Numpy DCIM-S reference model ===


def dcim_s_popcount(xnor_byte):
    """DCIM-S approximate popcount of an 8-bit value.
    Pairs: in[0]&in[1], in[2]|in[3], in[4]&in[5], in[6]|in[7]."""
    b = [(xnor_byte >> i) & 1 for i in range(8)]
    return (b[0] & b[1]) + (b[2] | b[3]) + (b[4] & b[5]) + (b[6] | b[7])


def dcim_s_mvm(weight_rows, activations):
    """Reference DCIM-S matrix-vector multiply.
    weight_rows: list of 8 ints (8-bit), row-major.
    activations: list of P ints (8-bit), bit-planes.
    Returns: list of 8 raw accumulator values."""
    N = len(weight_rows)
    weight_reg = []
    for col in range(N):
        val = 0
        for row in range(N):
            if weight_rows[row] & (1 << col):
                val |= 1 << row
        weight_reg.append(val)

    shift_acc = [0] * N
    for act in activations:
        for col in range(N):
            xnor = (~(weight_reg[col] ^ act)) & 0xFF
            pc = dcim_s_popcount(xnor)
            shift_acc[col] = (shift_acc[col] << 1) + pc
    return shift_acc


@cocotb.test()
async def test_mvm_random(dut):
    """Random 8x8 binary MVM through TT pins. Compare against numpy DCIM-S."""
    rng = np.random.RandomState(42)
    await setup(dut)

    weight_rows = [int(rng.randint(0, 256)) for _ in range(ARRAY_DIM)]
    activation = int(rng.randint(0, 256))
    expected = dcim_s_mvm(weight_rows, [activation])

    dut._log.info(f"weights: {[f'0x{w:02X}' for w in weight_rows]}")
    dut._log.info(f"activation: 0x{activation:02X}")
    dut._log.info(f"expected: {expected}")

    await load_weights(dut, weight_rows)
    await do_execute(dut, activation)
    results = await read_results(dut)

    dut._log.info(f"results:  {results}")
    for c in range(ARRAY_DIM):
        assert results[c] == expected[c], (
            f"col {c}: got {results[c]}, expected {expected[c]}"
        )


@cocotb.test()
async def test_mvm_multibit_random(dut):
    """Random 8x8 binary MVM with 2-bit precision through TT pins."""
    rng = np.random.RandomState(99)
    await setup(dut)

    weight_rows = [int(rng.randint(0, 256)) for _ in range(ARRAY_DIM)]
    act_plane0 = int(rng.randint(0, 256))
    act_plane1 = int(rng.randint(0, 256))
    expected = dcim_s_mvm(weight_rows, [act_plane0, act_plane1])

    dut._log.info(f"weights: {[f'0x{w:02X}' for w in weight_rows]}")
    dut._log.info(f"act planes: 0x{act_plane0:02X}, 0x{act_plane1:02X}")
    dut._log.info(f"expected: {expected}")

    await load_weights(dut, weight_rows)
    await do_execute(dut, act_plane0, act_plane1)
    results = await read_results(dut)

    dut._log.info(f"results:  {results}")
    for c in range(ARRAY_DIM):
        assert results[c] == expected[c], (
            f"col {c}: got {results[c]}, expected {expected[c]}"
        )
