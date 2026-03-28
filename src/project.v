/*
 * Copyright (c) 2026 Ezra Wolf
 * SPDX-License-Identifier: Apache-2.0
 *
 * TinyMOA top level for TinyTapeout IHP0P4 experimental tapeout.
 * 2x2 grid of 8x8 DCIM cores = 16x16 array.
 *
 * Pin mapping:
 *   ui_in[7:0]   data_in (weights or activations)
 *   uo_out[7:0]  result (column sum of two row-cores)
 *
 *   uio[0]       IN   wen
 *   uio[1]       IN   execute
 *   uio[2]       IN   read_next
 *   uio[3]       IN   acc_clear
 *   uio[4]       OUT  col_sel[0]
 *   uio[5]       OUT  col_sel[1]
 *   uio[6]       OUT  col_sel[2]
 *   uio[7]       OUT  done
 *   uio_oe       8'b11110000
 *
 * Data ordering (FPGA sends):
 *   Weight load: row0_lo, row0_hi, row1_lo, row1_hi, ... row15_lo, row15_hi
 *     (32 wen pulses total, toggle routes lo->core[*,0], hi->core[*,1])
 *     (first 16 pulses = core row 0, next 16 = core row 1)
 *   Execute: act_lo, act_hi per bit-plane
 *     (toggle routes lo->row 0 cores, hi->row 1 cores)
 *   Readout: 16 read_next pulses
 *     (first 8 = columns 0-7 from core col 0, next 8 = columns 8-15 from core col 1)
 *     (each result = core[0,c].result + core[1,c].result)
 */

`default_nettype none
`timescale 1ns / 1ps

module tt_um_tinymoa_ihp0p4_16x16 (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    localparam DIM = 8;
    localparam ACC = 6;

    // Toggle bit: flips on each wen, execute, or read_next
    // Selects core column during wen/readout, core row during execute
    reg toggle;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            toggle <= 0;
        else if (uio_in[0] | uio_in[1] | uio_in[2])
            toggle <= ~toggle;
        else if (uio_in[3])
            toggle <= 0;
    end

    // Row counter: counts which weight row we're on (0-7 per core row)
    // Increments every 2 wen pulses (after both lo and hi bytes)
    // Bit 3 selects core row (0 = first 8 rows, 1 = last 8 rows)
    reg [4:0] wen_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            wen_cnt <= 0;
        else if (uio_in[0])
            wen_cnt <= wen_cnt + 1;
    end

    wire core_row_sel = wen_cnt[4];  // core row during weight load
    wire exec_row_sel = toggle;       // core row during execute

    // Column readout counter
    reg [3:0] read_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            read_cnt <= 0;
        else if (uio_in[2])
            read_cnt <= read_cnt + 1;
        else if (uio_in[3])
            read_cnt <= 0;
    end

    wire       read_core_col = read_cnt[3]; // 0 for first 8, 1 for next 8
    wire [2:0] read_col_sel  = read_cnt[2:0];

    // Per-core signals
    wire [ACC-1:0] result [0:1][0:1]; // result[row][col]
    wire           done   [0:1][0:1];

    // 2x2 Core instantiation
    genvar r, c;
    generate
        for (r = 0; r < 2; r = r + 1) begin : gen_row
            for (c = 0; c < 2; c = c + 1) begin : gen_col

                wire core_wen = uio_in[0] & (toggle == c[0]) & (core_row_sel == r[0]);
                wire core_exec = uio_in[1] & (exec_row_sel == r[0]);
                wire core_acc_clear = uio_in[3];
                wire [2:0] core_col_sel = read_col_sel;

                tinymoa_dcim #(.ARRAY_DIM(DIM), .ACC_WIDTH(ACC)) u_dcim (
                    .clk       (clk),
                    .nrst      (rst_n),
                    .data_in   (ui_in),
                    .wen       (core_wen),
                    .execute   (core_exec),
                    .acc_clear (core_acc_clear),
                    .col_sel   (core_col_sel),
                    .result    (result[r][c]),
                    .dbg_done  (done[r][c])
                );
            end
        end
    endgenerate

    // Result: sum of both row-cores for the selected column pair
    wire [ACC:0] col_sum = {1'b0, result[0][read_core_col]} + {1'b0, result[1][read_core_col]};

    assign uo_out  = {{(8-ACC-1){1'b0}}, col_sum};
    assign uio_out = {done[0][0], read_col_sel, 4'b0};
    assign uio_oe  = 8'b11110000;

    wire _unused = ena;

endmodule
