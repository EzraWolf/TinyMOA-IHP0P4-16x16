/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 *
 * Top level file for TinyTapeout.
 */

`default_nettype none
`timescale 1ns / 1ps

module tt_um_tinymoa_ihp0p4 (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,   // IO in  path
    output wire [7:0] uio_out,  // IO out path
    output wire [7:0] uio_oe,   // IO enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1, keep but ignore
    input  wire       clk,
    input  wire       rst_n 
);

    wire [7:0] a_in = ui_in;
    wire [7:0] b_in = uio_in;
    wire [15:0] mul_result;

    multiply #(.DATA_WIDTH(8)) u_mul (
        .clk    (clk),
        .nrst   (rst_n),
        .a      (a_in),
        .b      (b_in),
        .result (mul_result)
    );

    assign uo_out  = mul_result[7:0];
    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    wire _unused = &{ena, mul_result[15:8], 1'b0};

endmodule
