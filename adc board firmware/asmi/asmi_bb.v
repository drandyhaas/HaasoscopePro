
module asmi (
	clkin,
	read,
	rden,
	addr,
	reset,
	dataout,
	busy,
	data_valid,
	bulk_erase,
	illegal_erase,
	write,
	datain,
	illegal_write);	

	input		clkin;
	input		read;
	input		rden;
	input	[23:0]	addr;
	input		reset;
	output	[7:0]	dataout;
	output		busy;
	output		data_valid;
	input		bulk_erase;
	output		illegal_erase;
	input		write;
	input	[7:0]	datain;
	output		illegal_write;
endmodule
