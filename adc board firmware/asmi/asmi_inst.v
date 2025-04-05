	asmi u0 (
		.clkin         (<connected-to-clkin>),         //         clkin.clk
		.read          (<connected-to-read>),          //          read.read
		.rden          (<connected-to-rden>),          //          rden.rden
		.addr          (<connected-to-addr>),          //          addr.addr
		.reset         (<connected-to-reset>),         //         reset.reset
		.dataout       (<connected-to-dataout>),       //       dataout.dataout
		.busy          (<connected-to-busy>),          //          busy.busy
		.data_valid    (<connected-to-data_valid>),    //    data_valid.data_valid
		.bulk_erase    (<connected-to-bulk_erase>),    //    bulk_erase.bulk_erase
		.illegal_erase (<connected-to-illegal_erase>), // illegal_erase.illegal_erase
		.write         (<connected-to-write>),         //         write.write
		.datain        (<connected-to-datain>),        //        datain.datain
		.illegal_write (<connected-to-illegal_write>)  // illegal_write.illegal_write
	);

