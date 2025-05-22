//altclkctrl CBX_SINGLE_OUTPUT_FILE="ON" CLOCK_TYPE="Global Clock" DEVICE_FAMILY="Cyclone 10 GX" ENA_REGISTER_MODE="falling edge" USE_GLITCH_FREE_SWITCH_OVER_IMPLEMENTATION="OFF" ena inclk outclk
//VERSION_BEGIN 22.4 cbx_altclkbuf 2022:11:21:17:09:32:SC cbx_lpm_add_sub 2022:11:21:17:09:33:SC cbx_lpm_compare 2022:11:21:17:09:33:SC cbx_lpm_decode 2022:11:21:17:09:33:SC cbx_lpm_mux 2022:11:21:17:09:33:SC cbx_mgl 2022:11:23:20:35:14:SC cbx_nadder 2022:11:21:17:09:32:SC cbx_stratix 2022:11:21:17:09:33:SC cbx_stratixii 2022:11:21:17:09:33:SC cbx_stratixiii 2022:11:21:17:09:33:SC cbx_stratixv 2022:11:23:20:35:14:SC  VERSION_END
// synthesis VERILOG_INPUT_VERSION VERILOG_2001
// altera message_off 10463



// Copyright (C) 2022  Intel Corporation. All rights reserved.
//  Your use of Intel Corporation's design tools, logic functions 
//  and other software and tools, and any partner logic 
//  functions, and any output files from any of the foregoing 
//  (including device programming or simulation files), and any 
//  associated documentation or information are expressly subject 
//  to the terms and conditions of the Intel Program License 
//  Subscription Agreement, the Intel Quartus Prime License Agreement,
//  the Intel FPGA IP License Agreement, or other applicable license
//  agreement, including, without limitation, that your use is for
//  the sole purpose of programming logic devices manufactured by
//  Intel and sold by Intel or its authorized distributors.  Please
//  refer to the applicable agreement for further details, at
//  https://fpgasoftware.intel.com/eula.



//synthesis_resources = cyclone10gx_clkena 1 
//synopsys translate_off
`timescale 1 ps / 1 ps
//synopsys translate_on
module  clkctrl10_altclkctrl_2000_flawdga_sub
	( 
	ena,
	inclk,
	outclk) /* synthesis synthesis_clearbox=1 */;
	input   ena;
	input   [3:0]  inclk;
	output   outclk;
`ifndef ALTERA_RESERVED_QIS
// synopsys translate_off
`endif
	tri1   ena;
	tri0   [3:0]  inclk;
`ifndef ALTERA_RESERVED_QIS
// synopsys translate_on
`endif

	wire  wire_sd1_outclk;
	wire [1:0]  clkselect;

	cyclone10gx_clkena   sd1
	( 
	.ena(ena),
	.enaout(),
	.inclk(inclk[0]),
	.outclk(wire_sd1_outclk));
	defparam
		sd1.clock_type = "Global Clock",
		sd1.ena_register_mode = "falling edge",
		sd1.lpm_type = "cyclone10gx_clkena";
	assign
		clkselect = {2{1'b0}},
		outclk = wire_sd1_outclk;
endmodule //clkctrl10_altclkctrl_2000_flawdga_sub
//VALID FILE // (C) 2001-2022 Intel Corporation. All rights reserved.
// Your use of Intel Corporation's design tools, logic functions and other 
// software and tools, and its AMPP partner logic functions, and any output 
// files from any of the foregoing (including device programming or simulation 
// files), and any associated documentation or information are expressly subject 
// to the terms and conditions of the Intel Program License Subscription 
// Agreement, Intel FPGA IP License Agreement, or other applicable 
// license agreement, including, without limitation, that your use is for the 
// sole purpose of programming logic devices manufactured by Intel and sold by 
// Intel or its authorized distributors.  Please refer to the applicable 
// agreement for further details.



// synopsys translate_off
`timescale 1 ps / 1 ps
// synopsys translate_on
module  clkctrl10_altclkctrl_2000_flawdga  (
    ena,
    inclk,
    outclk);

    input    ena;
    input    inclk;
    output   outclk;
`ifndef ALTERA_RESERVED_QIS
// synopsys translate_off
`endif
    tri1     ena;
`ifndef ALTERA_RESERVED_QIS
// synopsys translate_on
`endif

    wire  sub_wire0;
    wire  outclk;
    wire  sub_wire1;
    wire [3:0] sub_wire2;
    wire [2:0] sub_wire3;

    assign  outclk = sub_wire0;
    assign  sub_wire1 = inclk;
    assign sub_wire2[3:0] = {sub_wire3, sub_wire1};
    assign sub_wire3[2:0] = 3'h0;

    clkctrl10_altclkctrl_2000_flawdga_sub  clkctrl10_altclkctrl_2000_flawdga_sub_component (
                .ena (ena),
                .inclk (sub_wire2),
                .outclk (sub_wire0));

endmodule