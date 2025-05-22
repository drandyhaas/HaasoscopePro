	pll10_1 u0 (
		.refclk           (_connected_to_refclk_),           //   input,  width = 1,           refclk.clk
		.locked           (_connected_to_locked_),           //  output,  width = 1,           locked.export
		.rst              (_connected_to_rst_),              //   input,  width = 1,            reset.reset
		.scanclk          (_connected_to_scanclk_),          //   input,  width = 1,          scanclk.clk
		.phase_en         (_connected_to_phase_en_),         //   input,  width = 1,         phase_en.phase_en
		.updn             (_connected_to_updn_),             //   input,  width = 1,             updn.updn
		.cntsel           (_connected_to_cntsel_),           //   input,  width = 5,           cntsel.cntsel
		.phase_done       (_connected_to_phase_done_),       //  output,  width = 1,       phase_done.phase_done
		.num_phase_shifts (_connected_to_num_phase_shifts_), //   input,  width = 3, num_phase_shifts.num_phase_shifts
		.refclk1          (_connected_to_refclk1_),          //   input,  width = 1,          refclk1.clk
		.extswitch        (_connected_to_extswitch_),        //   input,  width = 1,        extswitch.extswitch
		.activeclk        (_connected_to_activeclk_),        //  output,  width = 1,        activeclk.activeclk
		.clkbad           (_connected_to_clkbad_),           //  output,  width = 2,           clkbad.clkbad
		.outclk_0         (_connected_to_outclk_0_),         //  output,  width = 1,          outclk0.clk
		.outclk_1         (_connected_to_outclk_1_),         //  output,  width = 1,          outclk1.clk
		.outclk_2         (_connected_to_outclk_2_),         //  output,  width = 1,          outclk2.clk
		.outclk_3         (_connected_to_outclk_3_)          //  output,  width = 1,          outclk3.clk
	);

