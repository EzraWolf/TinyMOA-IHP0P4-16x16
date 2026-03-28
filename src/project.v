/*
 * Copyright (c) 2026 Ezra Wolf
 * SPDX-License-Identifier: Apache-2.0
 *
 * TinyMOA top level for TinyTapeout IHP0P4 experimental tapeout.
 * Passthrough wrapper for 8x8 DCIM core.
 *
 * Pin mapping:
 *   ui_in[7:0]   data_in (weights or activations)
 *   uo_out[7:0]  result (zero-padded from ACC_WIDTH)
 * 
 *   uio[0]       IN   wen
 *   uio[1]       IN   execute
 *   uio[2]       IN   read_next (increments col_sel)
 *   uio[3]       IN   acc_clear
 *   uio[4]       OUT  col_sel[0]
 *   uio[5]       OUT  col_sel[1]
 *   uio[6]       OUT  col_sel[2]
 *   uio[7]       OUT  done
 *   uio_oe       8'b11110000
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

    reg [2:0] col_sel;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            col_sel <= 0;
        else if (uio_in[2])
            col_sel <= col_sel + 1;
    end

    wire [ACC-1:0] result;
    wire           done;

    tinymoa_dcim #(.ARRAY_DIM(DIM), .ACC_WIDTH(ACC)) u_dcim (
        .clk       (clk),
        .nrst      (rst_n),
        .data_in   (ui_in),
        .wen       (uio_in[0]),
        .execute   (uio_in[1]),
        .acc_clear (uio_in[3]),
        .col_sel   (col_sel),
        .result    (result),
        .dbg_done  (done)
    );

    assign uo_out  = {{(8-ACC){1'b0}}, result};
    assign uio_out = {done, col_sel, 4'b0};
    assign uio_oe  = 8'b11110000;

    wire _unused = ena;

endmodule
