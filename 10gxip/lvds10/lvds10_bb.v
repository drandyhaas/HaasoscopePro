module lvds10 (
		input  wire [13:0]  rx_in,         //         rx_in.export
		output wire [139:0] rx_out,        //        rx_out.export
		output wire         rx_coreclock,  //  rx_coreclock.export
		input  wire         inclock,       //       inclock.export
		input  wire         pll_areset,    //    pll_areset.export
		output wire [13:0]  rx_dpa_locked, // rx_dpa_locked.export
		output wire         pll_locked     //    pll_locked.export
	);
endmodule

