module pll10_1 (
		input  wire       refclk,           //           refclk.clk
		output wire       locked,           //           locked.export
		input  wire       rst,              //            reset.reset
		input  wire       scanclk,          //          scanclk.clk
		input  wire       phase_en,         //         phase_en.phase_en
		input  wire       updn,             //             updn.updn
		input  wire [4:0] cntsel,           //           cntsel.cntsel
		output wire       phase_done,       //       phase_done.phase_done
		input  wire [2:0] num_phase_shifts, // num_phase_shifts.num_phase_shifts
		input  wire       refclk1,          //          refclk1.clk
		input  wire       extswitch,        //        extswitch.extswitch
		output wire       activeclk,        //        activeclk.activeclk
		output wire [1:0] clkbad,           //           clkbad.clkbad
		output wire       outclk_0,         //          outclk0.clk
		output wire       outclk_1,         //          outclk1.clk
		output wire       outclk_2,         //          outclk2.clk
		output wire       outclk_3          //          outclk3.clk
	);
endmodule

