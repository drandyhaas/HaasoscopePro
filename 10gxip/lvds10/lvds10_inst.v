	lvds10 u0 (
		.rx_in         (_connected_to_rx_in_),         //   input,   width = 12,         rx_in.export
		.rx_out        (_connected_to_rx_out_),        //  output,  width = 120,        rx_out.export
		.rx_coreclock  (_connected_to_rx_coreclock_),  //  output,    width = 1,  rx_coreclock.export
		.inclock       (_connected_to_inclock_),       //   input,    width = 1,       inclock.export
		.pll_areset    (_connected_to_pll_areset_),    //   input,    width = 1,    pll_areset.export
		.rx_dpa_locked (_connected_to_rx_dpa_locked_), //  output,   width = 12, rx_dpa_locked.export
		.pll_locked    (_connected_to_pll_locked_)     //  output,    width = 1,    pll_locked.export
	);

