//--------------------------------------------------------------------------------------------------------
// Module  : fpga_top_ft232h_tx_mass
// Type    : synthesizable, FPGA's top, IP's example design
// Standard: Verilog 2001 (IEEE1364-2001)
// Function: an example of ftdi_245fifo_top
//           the pins of this module should connect to FT600 chip
//           This design will receive 4 bytes from FTDI chip,
//           and then regard the 4 bytes as a length, send length of bytes to FTDI chip
//--------------------------------------------------------------------------------------------------------

module fpga_top_ft232h_tx_mass (
    input  wire         rstn,
    input  wire         clk,            // main clock, connect to on-board crystal oscillator
    output wire  [ 1:0] LED,
    
    // USB2.0 HS (FT232H chip) ------------------------------------------------------------
    output wire         ftdi_resetn,    // to FT232H's pin34 (RESET#) , !!!!!! UnComment this line if this signal is connected to FPGA !!!!!!
    output wire         ftdi_pwrsav,    // to FT232H's pin31 (PWRSAV#), !!!!!! UnComment this line if this signal is connected to FPGA !!!!!!
    output wire         ftdi_siwu,      // to FT232H's pin28 (SIWU#)  , !!!!!! UnComment this line if this signal is connected to FPGA !!!!!!
    input  wire         ftdi_clk,       // to FT232H's pin29 (CLKOUT)
    input  wire         ftdi_rxf_n,     // to FT232H's pin21 (RXF#)
    input  wire         ftdi_txe_n,     // to FT232H's pin25 (TXE#)
    output wire         ftdi_oe_n,      // to FT232H's pin30 (OE#)
    output wire         ftdi_rd_n,      // to FT232H's pin26 (RD#)
    output wire         ftdi_wr_n,      // to FT232H's pin27 (WR#)
    inout        [ 7:0] ftdi_data,      // to FT232H's pin20~13 (ADBUS7~ADBUS0)
    
   // user AXI-stream signals
   input  wire        rx_tready,
   output wire        rx_tvalid,
   output wire [ 7:0] rx_tdata,

   output wire        tx_tready,
   input  wire        tx_tvalid,
   input  wire [31:0] tx_tdata,
   input  wire [ 3:0] tx_tkeep,
   input  wire        tx_tlast
);

assign ftdi_resetn = 1'b1;  // 1=normal operation , !!!!!! UnComment this line if this signal is connected to FPGA !!!!!!
assign ftdi_pwrsav = 1'b1;  // 1=normal operation , !!!!!! UnComment this line if this signal is connected to FPGA !!!!!!
assign ftdi_siwu   = 1'b1;  // 1=send immidiently , !!!!!! UnComment this line if this signal is connected to FPGA !!!!!!

// FTDI USB chip's 245fifo mode controller
ftdi_245fifo_top #(
    .TX_EW                 ( 2                  ),   // TX data stream width,  0=8bit, 1=16bit, 2=32bit, 3=64bit, 4=128bit ...
    .TX_EA                 ( 8                 ),   // TX FIFO depth = 2^TX_AEXP = 2^10 = 1024
    .RX_EW                 ( 0                  ),   // RX data stream width,  0=8bit, 1=16bit, 2=32bit, 3=64bit, 4=128bit ...
    .RX_EA                 ( 4                  ),   // RX FIFO depth = 2^RX_AEXP = 2^10 = 1024
    .CHIP_TYPE             ( "FTx232H"          )
) u_ftdi_245fifo_top (
    .rstn_async            ( rstn               ),
    .tx_clk                ( clk                ),
    .tx_tready             ( tx_tready          ),
    .tx_tvalid             ( tx_tvalid          ),
    .tx_tdata              ( tx_tdata           ),
    .tx_tkeep              ( tx_tkeep           ),
    .tx_tlast              ( tx_tlast           ),
    .rx_clk                ( clk                ),
    .rx_tready             ( rx_tready          ),
    .rx_tvalid             ( rx_tvalid          ),
    .rx_tdata              ( rx_tdata           ),
    .rx_tkeep              (                    ),
    .rx_tlast              (                    ),
    .ftdi_clk              ( ftdi_clk           ),
    .ftdi_rxf_n            ( ftdi_rxf_n         ),
    .ftdi_txe_n            ( ftdi_txe_n         ),
    .ftdi_oe_n             ( ftdi_oe_n          ),
    .ftdi_rd_n             ( ftdi_rd_n          ),
    .ftdi_wr_n             ( ftdi_wr_n          ),
    .ftdi_data             ( ftdi_data          ),
    .ftdi_be               (                    )    // FT232H do not have BE signals
);


// if ftdi_clk continuous run, then beat will blink. The function of this module is to observe whether ftdi_clk is running
clock_beat # (
    .CLK_FREQ              ( 60000000           ),
    .BEAT_FREQ             ( 5                  )
) u_ftdi_clk_beat (
    .clk                   ( ftdi_clk           ),
    .beat                  ( LED[1]             )
);

//if clk continuous run, then beat will blink. The function of this module is to observe whether clk is running
clock_beat # (
    .CLK_FREQ              ( 50000000           ),
    .BEAT_FREQ             ( 5                  )
) u_clk_beat (
    .clk                   ( clk           ),
    .beat                  ( LED[0]             )
);

endmodule
