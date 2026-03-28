/*
 * Copyright (c) 2026 Ezra Wolf
 * SPDX-License-Identifier: Apache-2.0
 *
 * 32x32 unsigned multiplier macro for space testing.
*/

`default_nettype none
`timescale 1ns / 1ps

module multiply #(parameter DATA_WIDTH = 32) (
    input  wire        clk,
    input  wire        nrst,
    input  wire [DATA_WIDTH-1:0] a,
    input  wire [DATA_WIDTH-1:0] b,
    output reg  [2*DATA_WIDTH-1:0] result
);
    always @(posedge clk or negedge nrst) begin
        if (!nrst)
            result <= {2 * DATA_WIDTH {1'b0}};
        else
            result <= a * b;
    end

endmodule
