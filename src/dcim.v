/*
 * Copyright (c) 2026 Ezra Wolf
 * SPDX-License-Identifier: Apache-2.0
 *
 * TinyMOA 8x8 DCIM Core with stateless datapath
 *
 * Building block for larger arrays (16x16 = 2x2, 32x32 = 4x4).
 * No FSM. External controller (FPGA/wrapper) sequences all operations.
 *
 * Weight loading transposes row-major input into column registers:
 *   weight_reg[col][row] = data_in[col] when wen pulses for that row.
 *
 * Uses tinymoa_compressor_8 (DCIM-S by default via define).
 *
 * Reference: ISSCC 2022, Wang et al.
 * "DIMC: 2219TOPS/W 2569F2/b Digital In-Memory Computing Macro
 *  in 28nm Based on Approximate Arithmetic Hardware"
 */

`default_nettype none
`timescale 1ns / 1ps

module tinymoa_dcim #(
    parameter ARRAY_DIM = 8,
    parameter ACC_WIDTH = 6
)(
    input clk,
    input nrst,

    input [ARRAY_DIM-1:0]  data_in,
    input                  wen,
    input                  execute,
    input                  acc_clear,

    input  [$clog2(ARRAY_DIM)-1:0] col_sel,
    output [ACC_WIDTH-1:0]         result,
    output reg                     dbg_done
);
    reg [ARRAY_DIM-1:0] weight_reg [0:ARRAY_DIM-1]; // 2D array of column vectors
    reg [ACC_WIDTH-1:0] shift_acc [0:ARRAY_DIM-1];  // Shift-acc (one/column)
    reg [$clog2(ARRAY_DIM)-1:0] row_cnt;            // Weight transpose row counter

    // XNOR + compressor (one/column)
    wire [3:0] comp_out [0:ARRAY_DIM-1];
    wire [4:0] popcount [0:ARRAY_DIM-1];

    genvar col;
    generate
        for (col = 0; col < ARRAY_DIM; col = col + 1) begin : gen_col
            wire [ARRAY_DIM-1:0] xnor_bits = ~(weight_reg[col] ^ data_in);

            tinymoa_compressor_8 comp (
                .in  (xnor_bits),
                .out (comp_out[col])
            );

            assign popcount[col] = {1'b0, comp_out[col]};
        end
    endgenerate

    assign result = shift_acc[col_sel];

    integer i;
    always @(posedge clk or negedge nrst) begin
        if (!nrst) begin
            row_cnt   <= 0;
            dbg_done  <= 1'b0;
            for (i = 0; i < ARRAY_DIM; i = i + 1) begin
                weight_reg[i] <= 0;
                shift_acc[i]  <= 0;
            end
        end else begin
            dbg_done <= 1'b0;

            if (wen) begin
                // Transpose: distribute data_in bits across column registers
                for (i = 0; i < ARRAY_DIM; i = i + 1)
                    weight_reg[i][row_cnt] <= data_in[i];
                row_cnt <= row_cnt + 1;
            end

            if (acc_clear) begin
                for (i = 0; i < ARRAY_DIM; i = i + 1)
                    shift_acc[i] <= 0;
            end else if (execute) begin
                for (i = 0; i < ARRAY_DIM; i = i + 1)
                    shift_acc[i] <= (shift_acc[i] << 1) + {{(ACC_WIDTH-5){1'b0}}, popcount[i]};
                dbg_done <= 1'b1;
            end
        end
    end

endmodule
