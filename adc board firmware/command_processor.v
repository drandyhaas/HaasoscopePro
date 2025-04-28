// the main module
// gets commands from USB, and takes actions
module command_processor (
   input  wire        rstn,
   input  wire        clk, // the main 50 MHz clock
   
   // to talk to data I/O FT232H USB2
   output wire        i_tready, // AXI-stream slave
   input  wire        i_tvalid, // ...
   input  wire [ 7:0] i_tdata,
   input  wire        o_tready, // AXI-stream master
   output wire        o_tvalid, // ...
   output wire [31:0] o_tdata,
   output wire [ 3:0] o_tkeep,
   output wire        o_tlast,

   output reg pllreset, // to reset pll's

   // to talk over SPI
   output reg  [7:0] spitx,
   input  reg  [7:0] spirx,
   input  reg        spitxready,
   output reg        spitxdv,
   input  reg        spirxdv,
   output reg  [7:0] spics, // which chip to talk to

   input wire  [3:0] lockinfo, // clock info

   // reading from RAM
   output reg  [9:0]    ram_rd_address=0,
   input wire  [559:0]  lvdsbitsin, // input bits from fifo

   // to adjust pll phases
   output reg  [2:0] phasecounterselect, // Dynamic phase shift counter Select. 000:all 001:M 010:C0 011:C1 100:C2 101:C3 110:C4. Registered in the rising edge of scanclk.
   output reg        phaseupdown=1, // Dynamic phase shift direction; 1:UP, 0:DOWN. Registered in the PLL on the rising edge of scanclk.
   output reg  [3:0] phasestep,
   output reg        scanclk=0,

   output reg  [2:0] spimisossel=0, //which spimiso to listen to
   output reg [11:0] debugout, 
   input wire  [3:0] overrange,  //ORA0,A1,B0,B1
   output reg  [1:0] spi_mode=0,
   input wire  [7:0] boardin,
   output wire [7:0] boardout=0,
   output reg        spireset_L=1'b1,
   output reg        clkswitch=0, // to switch between external clock and internal oscillator
   input wire        lvdsin_spare,
   output reg        lvdsout_spare=0,
   input wire        clk50, // needed while doing pllreset
   output reg        clk_over_4, // clock output for flash and RGB LEDs

   // for flash firmware updating
   output reg [23:0] flash_addr,
   output reg        flash_bulk_erase,
   output reg [7:0]  flash_datain,
   output reg        flash_rden,
   output reg        flash_read,
   output reg        flash_write,
   output reg        flash_reset,
   input             flash_busy,
   input             flash_data_valid,
   input [7:0]       flash_dataout,
   
   // to turn control LVDS clk off
   output reg clkout_ena=1,
   
   // to RGB LEDs
   output reg [23:0] neo_color[2],
   output reg send_color,
   
   // outputs to triggerer
   output reg signed [11:0]  lowerthresh,
   output reg signed [11:0]  upperthresh,
   output reg [15:0] lengthtotake,
   output reg [15:0] prelengthtotake,
   output reg        triggerlive,
   output reg        didreadout,
   output reg [7:0]  triggertype,
   output reg [7:0]  triggerToT,
   output reg        triggerchan,
   output reg        dorolling,
   output reg        auxoutselector,
   output reg [7:0]  channeltype,
   output reg [7:0]  downsamplemerging,
   output reg        highres,
   output reg [4:0]  downsample,
   
   // inputs from triggerer
   input [7:0]    acqstate,
   input [31:0]   eventcounter,
   input [9:0]    ram_address_triggered,
   input [19:0]   sample_triggered,
   input [7:0]    downsamplemergingcounter_triggered,
   input [8:0]    triggerphase
);

integer version = 25; // firmware version

// these first 10 debugout's go to LEDs on the board
assign debugout[0] = clkswitch;
assign debugout[1] = clkout_ena;
assign debugout[2] = send_color;
assign debugout[3] = lvdsin_spare;
assign debugout[4] = lockinfo[0]; //locked
assign debugout[5] = lockinfo[1]; //activeclock
assign debugout[6] = lockinfo[2]; //clkbad0
assign debugout[7] = lockinfo[3]; //clkbad1
assign debugout[8] = boardin[0]; // extra inputs on PCB, mirrored to LEDs for now
assign debugout[9] = boardin[1];

assign debugout[10]= flash_busy; // doesn't actually go to a pin or LED anymore, it's used for auxout
assign debugout[11]= fanon; // the cooling fan (could be PWM'ed for finer control)
// boardin[2] is 12Vconnected
// boardin[3] is PG12V
// boardin[5] is Lockdetect (from ADF4350)
// boardin[6] is Muxout (from ADF4350)
// boardin[7] is Calstat (from ADC)

// boardout[3] is the 1kHz square wave going to the front panel
// other 7 boardout's are for controlling relays

// variables in clk domain, reading out of the RAM buffer
localparam [3:0] INIT=4'd0, RX=4'd1, PROCESS=4'd2, TX_DATA_CONST=4'd3, TX_DATA1=4'd4, TX_DATA2=4'd5, TX_DATA3=4'd6, TX_DATA4=4'd7, PLLCLOCK=4'd8, BOOTUP=4'd9;
reg [ 3:0]  state = INIT;
reg         didbootup = 0;
reg [ 3:0]  rx_counter = 0;
reg [ 7:0]  rx_data[7:0];
integer     length = 0;
reg [ 3:0]  spistate = 0;
reg [5:0]   channel = 0;
reg [5:0]   channel2 = 0; // the "channel" we are sending out for two-channel mode, to reorder samples
reg [5:0]   spicscounter = 0;
reg [7:0]   pllclock_counter = 0; // for clock phase
reg [7:0]   scanclk_cycles = 0;
reg [9:0]   ram_preoffset = 0;
integer     overrange_counter[4];
reg [15:0]  probecompcounter = 0;
reg [3:0]   flashstate=0, flashbusycounter=0;
reg         fanon = 0; 
reg [31:0]  o_tdatatemp = 0;
reg         clkstrprob = 0;
reg [3:0]   numones=0, numones2=0;

// synced inputs from other clocks
reg [ 7:0]  acqstate_sync = 0;
integer     eventcounter_sync = 0;
reg [ 9:0]  ram_address_triggered_sync = 0;
reg [19:0]  sample_triggered_sync = 0;
reg [7:0]   downsamplemergingcounter_triggered_sync = 0;
reg [8:0]   triggerphase_sync = 0;
reg [7:0]   boardin_sync = 0;

// Sequence of register writes that triggers sending 4 bytes usb response.
`define SEND_STD_USB_RESPONSE \
    length <= 4; \
    o_tvalid <= 1'b1; \
    state <= TX_DATA_CONST;

integer i;
always @ (posedge clk or negedge rstn) begin
    if (~rstn) begin
        didbootup <= 1'b0;
        state  <= INIT;
    end else begin
        if (probecompcounter==16'd25000) begin
            boardout[3] <= ~boardout[3]; // for probe compensation, 1kHz
            probecompcounter <= 0;
        end
        else probecompcounter <= probecompcounter + 16'd1;

        case (state)
        INIT : begin
            spireset_L <= 1'b1;
            pllreset2 <= 1'b0;
            rx_counter <= 0;
            length <= 0;
            spistate <= 0;
            spitxdv <= 1'b0;
            spics <= 8'hff;
            channel <= 6'd0;
            channel2 <= 6'd0;
            triggerlive <= 1'b0;
            didreadout <= 1'b0;
            if (didbootup) state <= RX;
            else state <= BOOTUP;
        end

        RX : begin
            if (i_tvalid) begin // get 8 bytes
                rx_data[rx_counter] <= i_tdata;
                if (rx_counter==7) begin
                    state <= PROCESS;
                    rx_counter <= 0;
                end
                else rx_counter <= rx_counter + 4'd1;
            end
        end

        PROCESS : begin // do something, based on the command in the first byte
            case (rx_data[0])
            0 : begin // send a length of bytes from the RAM buffer
                length <= {rx_data[7],rx_data[6],rx_data[5],rx_data[4]};
                ram_rd_address <= ram_address_triggered_sync - ram_preoffset; // set the address to read from at the triggered point - an offset, to see what happened before the trigger
                state <= TX_DATA1;
            end

            1 : begin // sets length of data to take, activates trigger for new event if we don't already have one
                triggertype <= rx_data[1]; // while we're at it, set the trigger type
                channeltype <= rx_data[2]; // and the channel type (bit0: single or dual, bit1: oversampling (swapped inputs))
                lengthtotake <= {rx_data[5],rx_data[4]};
                if (acqstate_sync == 0) triggerlive <= 1'b1; // gets reset in INIT state
                o_tdata <= {4'd0,sample_triggered_sync,acqstate_sync}; // return acqstate, so we can see if we have an event ready to be read out, and which samples triggered (to prevent jitter)
                `SEND_STD_USB_RESPONSE
            end

            2 : begin // reads version or does other stuff
                case (rx_data[1]) 
                0: o_tdata <= version;
                1: o_tdata <= {24'd0,boardin_sync};
                2: o_tdata <= overrange_counter[rx_data[2][1:0]];
                3: o_tdata <= eventcounter_sync;
                4: o_tdata <= {16'd0,triggerphase_sync[7:0],downsamplemergingcounter_triggered_sync};
                5: begin
                    lvdsout_spare <= rx_data[2][0]; // used for telling order of devices
                    o_tdata <= {8'd0, 7'd0,lvdsin_spare, 4'd0,lockinfo, 7'd0,~clkswitch};
                end
                6: begin
                    fanon <= rx_data[2][0];
                    o_tdata <= fanon;
                end
                7: begin
                    prelengthtotake <= {rx_data[3],rx_data[2]};
                    o_tdata <= prelengthtotake;
                end
                8: begin
                    dorolling <= rx_data[2][0];
                    o_tdata <= dorolling;
                end
                9: begin
                    clkout_ena <= rx_data[2][0];
                    o_tdata <= {31'd0,clkout_ena};
                end
                10: begin
                    auxoutselector <= rx_data[2][0];
                    o_tdata <= {31'd0,auxoutselector};
                end
                endcase
                `SEND_STD_USB_RESPONSE
            end

            3 : begin // SPI command
                case (spistate)
                0 : begin
                    spimisossel <= rx_data[1][2:0]; // select requested data from chip
                    spics[rx_data[1][2:0]] <= 1'b0; //select requested chip
                    spitx <= rx_data[2]; //first byte to send
                    if (spicscounter==6'd10) begin // wait a bit for cs to go low
                        spicscounter <= 6'd0;
                        spistate <= 4'd1;
                    end
                    else spicscounter <= spicscounter + 6'd1;
                end
                1 : begin
                    if (spitxready) begin
                        spitxdv <= 1'b1;
                        if (rx_data[7]==2) spistate <= 4'd4; //sending 2 bytes
                        else spistate <= 4'd2; // sending more than 2 bytes
                    end
                end
                2 : begin
                    spitxdv <= 1'b0;
                    spitx <= rx_data[3];//second byte to send
                    spistate <= 4'd3;
                end
                3 : begin
                    if (spitxready) begin
                        spitxdv <= 1'b1;
                        spistate <= 4'd4;
                    end
                end
                4 : begin
                    spitxdv <= 1'b0;
                    spitx <= rx_data[4];//third byte to send (ignored during read)
                    if (spirxdv) begin
                        spistate <= 4'd5;
                        o_tdata[15:8] <= spirx; // send back the SPI data read during byte 1 (used for slowadc)
                    end
                end
                5 : begin
                    if (spitxready) begin
                        spitxdv <= 1'b1;
                        if (rx_data[7]==4) spistate <= 4'd6; // send the 4th byte
                        else spistate <= 4'd8; // skip the 4th byte
                    end
                end
                6 : begin
                    spitxdv <= 1'b0;
                    spitx <= rx_data[5];//fourth byte to send
                    spistate <= 4'd7;
                end
                7 : begin
                    if (spitxready) begin
                        spitxdv <= 1'b1;
                        spistate <= 4'd8;
                    end
                end
                8 : begin
                    spitxdv <= 1'b0;
                    if (spirxdv) begin
                        spistate <= 4'd9;
                        o_tdata[7:0] <= spirx; // send back the SPI data read
                    end
                end
                9 : begin
                    if (spicscounter==6'd35) begin // wait a bit before setting cs high
                        spicscounter<=6'd0;
                        spistate <= 4'd0;
                        `SEND_STD_USB_RESPONSE
                    end
                    else spicscounter <= spicscounter + 6'd1;
                end
                default : spistate <= 4'd0;
                endcase
            end

            4 : begin // set SPI_MODE (see SPI_Master.v)
                spireset_L <= 1'b0;
                spi_mode <= rx_data[1][1:0];
                o_tdata <= rx_data[1];
                `SEND_STD_USB_RESPONSE
            end

            5 : begin // reset plls
                pllreset2 <= 1'b1;
                o_tdata <= 5;
                `SEND_STD_USB_RESPONSE
            end

            6 : begin // for clock phase adjustment
                phasecounterselect <= rx_data[2][2:0];// 000:all 001:M 010:C0 011:C1 100:C2 101:C3 110:C4.
                phaseupdown <= rx_data[3][0]; // up or down
                scanclk <= 1'b0; // start low
                phasestep[rx_data[1]] <= 1'b1; // assert - the index here selects which pll to adjust
                pllclock_counter <= 0;
                scanclk_cycles <= 0;
                state <= PLLCLOCK;
            end

            7 : begin // try to switch clocks
                clkswitch <= ~clkswitch;
                o_tdata <= {8'd0,8'd0,4'd0,lockinfo,7'd0,~clkswitch};
                `SEND_STD_USB_RESPONSE
            end

            8 : begin // trigger settings
                lowerthresh <= ((rx_data[1] - rx_data[2] - 12'd128)<<4) + 12'd8;
                upperthresh <= ((rx_data[1] + rx_data[2] - 12'd128)<<4) + 12'd8;
                ram_preoffset <= (rx_data[3][1:0]<<8) + rx_data[4];
                triggerToT <= rx_data[5];
                triggerchan <= rx_data[6][0];
                o_tdata <= 8;
                `SEND_STD_USB_RESPONSE
            end

            9 : begin // downsample and highres settings
                downsample <= rx_data[1][4:0];
                highres <= rx_data[2][0];
                downsamplemerging <= rx_data[3];
                o_tdata <= 9;
                `SEND_STD_USB_RESPONSE
            end

            10 : begin // boardout controls
                boardout[rx_data[1][2:0]] <= rx_data[2][0]; // set bit given by rx_data1 to value in rx_data2
                o_tdata <= boardout;
                `SEND_STD_USB_RESPONSE
            end

            11 : begin // LED controls
                neo_color[0] <= {rx_data[4],rx_data[3],rx_data[2]};
                neo_color[1] <= {rx_data[7],rx_data[6],rx_data[5]};
                send_color <= rx_data[1][0];
                o_tdata <= 123;
                `SEND_STD_USB_RESPONSE
            end

            12 : begin
                // Return acqstate, so we can see if we have an event ready to be read out,
                // and which samples triggered (to prevent jitter)
                o_tdata <= {4'd0,sample_triggered_sync,acqstate_sync};
                `SEND_STD_USB_RESPONSE
            end

            13 : begin // force-arm-trigger function
                triggertype <= rx_data[1]; // set the trigger type
                channeltype <= rx_data[2]; // the channel type (bit0: single or dual, bit1: oversampling (swapped inputs))
                lengthtotake <= {rx_data[5],rx_data[4]};

                // we might not have actually read out data yet; however, since we are force arming the trigger we are going to pretend that we did so
                // in the separate "loop" over clklvds that should move acqstate to 0
                length <= 0;
                didreadout <= 1'b1;
                triggerlive <= 1'b1; // gets reset in INIT state
                
                if (flashbusycounter==4) begin // wait for didreadout to allow trigger to get back to state 0 before lowering triggerlive in INIT state
                   flashbusycounter<=0;        //(reusing flashbusycounter since it can't conflict)

                   // Assuming that trigger type is changed, trigger will always be re-armed;
                   // For debuging current acqstate in the first byte
                   o_tdata <= {8'd0, 8'd0, 8'd0, acqstate_sync};
                   `SEND_STD_USB_RESPONSE
                end
                else flashbusycounter <= flashbusycounter+4'd1;
            end

            14 : begin // read-register function
                // Returns "register" (some are wires) value indentified by a number in rx_data[1]
                case (rx_data[1])
                    0 : o_tdata <= {22'd0, ram_preoffset};
                    1 : o_tdata <= {22'd0, ram_address_triggered_sync};
                    2 : o_tdata <= {28'd0, spistate};
                    3 : o_tdata <= version;
                    4 : o_tdata <= {24'd0, boardin_sync};
                    5 : o_tdata <= {24'd0, acqstate_sync};
                    6 : o_tdata <= eventcounter_sync;
                    7 : o_tdata <= {12'd0, sample_triggered_sync};
                    8 : o_tdata <= {24'd0, downsamplemergingcounter_triggered_sync};
                    9 : o_tdata <= {24'd0, downsamplemerging};
                    10: o_tdata <= {27'd0, downsample};
                    11: o_tdata <= {31'd0, highres};
                    12: o_tdata <= {20'd0, upperthresh};
                    13: o_tdata <= {31'd0, flash_busy};
                    default:
                        o_tdata <= {32'd0};
                endcase
                `SEND_STD_USB_RESPONSE
            end

            15 : begin // read from flash
               case (flashstate)
               0 : begin
                  if (!flash_busy) begin
                     flash_addr <= {rx_data[1],rx_data[2],rx_data[3]};
                     if (flashbusycounter==8) begin // wait for flash to not be busy, then start (need extra 2 clk_over_4 cycles according to note in datasheet)
                        flashbusycounter<=0;
                        flash_rden <= 1'b1;
                        flash_read <= 1'b1;
                        flashstate <= 4'd1;
                     end
                     else flashbusycounter <= flashbusycounter+4'd1;
                  end
               end
               1 : begin
                  if (flash_busy) begin // once busy, read has started
                     if (flashbusycounter==4) begin // wait for addr to register
                        flashbusycounter<=0;
                        flash_rden <= 1'b0;
                        flash_read <= 1'b0;
                        flashstate <= 4'd2;
                     end
                     else flashbusycounter <= flashbusycounter+4'd1;
                  end
               end
               2 : begin
                  if (flash_data_valid) begin // once we got data, we're done
                     flashstate <= 4'd0;
                     o_tdata <= {8'd0, 8'd0, 8'd0, flash_dataout};
                     `SEND_STD_USB_RESPONSE
                  end
               end
               default : flashstate <= 4'd0;
               endcase
            end

            16 : begin // write to flash
               case (flashstate)
               0 : begin
                  if (!flash_busy) begin
                     flash_addr <= {rx_data[1],rx_data[2],rx_data[3]};
                     flash_datain <= rx_data[4];
                     if (flashbusycounter==8) begin // wait for flash to not be busy, then start (need extra 2 clk_over_4 cycles according to note in datasheet)
                        flashbusycounter<=0;
                        flashstate <= 4'd1;
                     end
                     else flashbusycounter <= flashbusycounter+4'd1;
                  end
               end
               1 : begin
                  if (flashbusycounter==4) begin // wait for data and addr to register
                     flashbusycounter<=0;
                     if (rx_data[5]==100 && rx_data[6]==101 && rx_data[7]==102) begin
                        flash_write <= 1'b1;
                        flashstate <= 4'd2;
                     end
                     else flashstate <= 4'd3;
                  end
                  else flashbusycounter <= flashbusycounter+4'd1;
               end
               2 : begin
                  if (flash_busy) begin // once busy
                     if (flashbusycounter==4) begin // wait for write to start
                        flashbusycounter<=0;
                        flash_write <= 1'b0;
                        flashstate <= 4'd3;
                     end
                     else flashbusycounter <= flashbusycounter+4'd1;
                  end
               end
               3 : begin // we'll return immediately, future operations will wait for busy to be deasserted
                  flashstate <= 4'd0;
                  o_tdata <= {8'd0, 8'd0, 8'd0, 8'd200};
                  `SEND_STD_USB_RESPONSE
               end
               default : flashstate <= 4'd0;
               endcase
            end

            17 : begin // erase flash
               case (flashstate)
               0 : begin
                  if (!flash_busy) begin
                     if (flashbusycounter==12) begin // wait for flash to not be busy, then start (need extra 2 clk_over_4 cycles according to note in datasheet)
                        flashbusycounter<=0;
                        if (rx_data[5]==100 && rx_data[6]==101 && rx_data[7]==102) begin
                           flash_bulk_erase <= 1'b1;
                           flashstate <= 4'd1;
                        end
                        else flashstate <= 4'd2;
                     end
                     else flashbusycounter <= flashbusycounter+4'd1;
                  end
               end
               1 : begin
                  if (flash_busy) begin // once busy, erase has started
                     if (flashbusycounter==12) begin // wait for erase to start
                        flashbusycounter<=0;
                        flash_bulk_erase <= 1'b0;
                        flashstate <= 4'd2;
                     end
                     else flashbusycounter <= flashbusycounter+4'd1;
                  end
               end
               2 : begin // we'll return immediately, future operations will wait for busy to be deasserted
                  flashstate <= 4'd0;
                  o_tdata <= {8'd0, 8'd0, 8'd0, 8'd222};
                  `SEND_STD_USB_RESPONSE
               end
               default : flashstate <= 4'd0;
               endcase
            end

            default: // some command we didn't know
            state <= RX;

            endcase
        end

        TX_DATA_CONST : begin
            if (o_tready) begin
                if (length >= 4) begin
                    length <= length - 16'd4;
                end else begin
                    length <= 0;
                    o_tvalid <= 1'b0;
                    state <= INIT;
                end
            end
        end

        TX_DATA1 : begin
            o_tvalid <= 1'b0;
            if (o_tready) begin
                state <= TX_DATA2; // wait for data
            end
        end

        TX_DATA2 : begin
            o_tvalid <= 1'b0;
            if (o_tready) begin
                channel <= 6'd0;
                channel2 <= 6'd0;
                state <= TX_DATA3; // wait for data
            end
        end

        TX_DATA3 : begin
            if (o_tready) begin
                o_tvalid <= 1'b1;
                if (channel==48) begin
                  if (clkstrprob) o_tdata <= {16'hbeef,16'h01}; // marker, clkstr problem
                  else o_tdata <= {16'hbeef,16'h00}; // marker, no problems
                end
                else if (channel==44 || channel==46) begin
                   numones=0;
                   numones2=0;
                   for (i=0; i<10; i++) begin
                     if (channel==44) begin
                     o_tdatatemp[i] = lvdsbitsin[14*(0+i)+13]; //samplestr 0-9
                     o_tdatatemp[i+16] = lvdsbitsin[14*(10+i)+13]; //samplestr 10-19
                     end
                     else begin
                     o_tdatatemp[i] = lvdsbitsin[14*(20+i)+13]; //samplestr 20-29
                     o_tdatatemp[i+16] = lvdsbitsin[14*(30+i)+13]; //samplestr 30-39
                     end
                     if (o_tdatatemp[i]) numones=numones+4'd1;
                     if (o_tdatatemp[i+16]) numones2=numones2+4'd1;
                   end
                   for (i=0; i<6; i++) begin
                     o_tdatatemp[i+10] = 0; //padding
                     o_tdatatemp[i+26] = 0; //padding
                   end
                   if (numones>1 || numones2>1) clkstrprob<=1'b1; // issue with str
                   o_tdata <= o_tdatatemp;
                end
                else if (channel==40 || channel==42) begin
                   for (i=0; i<10; i++) begin
                     if (channel==40) begin
                     o_tdatatemp[i] = lvdsbitsin[14*(0+i)+12]; //sampleclk 0-9
                     o_tdatatemp[i+16] = lvdsbitsin[14*(10+i)+12]; //sampleclk 10-19
                     end
                     else begin
                     o_tdatatemp[i] = lvdsbitsin[14*(20+i)+12]; //sampleclk 20-29
                     o_tdatatemp[i+16] = lvdsbitsin[14*(30+i)+12]; //sampleclk 30-39
                     end
                   end
                   for (i=0; i<6; i++) begin
                     o_tdatatemp[i+10] = 0; //padding
                     o_tdatatemp[i+26] = 0; //padding
                   end
                   if ( (o_tdatatemp[9:0]!=10'd341 && o_tdatatemp[9:0]!=10'd682) ||
                        (o_tdatatemp[25:16]!=10'd341 && o_tdatatemp[25:16]!=10'd682) ) clkstrprob<=1'b1; // issue with clk
                   o_tdata <= o_tdatatemp;
                end
                else begin // data
                   if (channeltype[0]==1'b0) begin // single channel mode
                     o_tdata  <= {lvdsbitsin[14*(38-channel) +: 12], 4'd0, lvdsbitsin[14*(39-channel) +: 12], 4'd0};
                   end
                   else begin // two channel mode
                     o_tdata  <= {lvdsbitsin[14*(38-channel2) +: 12], 4'd0, lvdsbitsin[14*(39-channel2) +: 12], 4'd0};
                   end
                   clkstrprob <= 1'b0; // assume no clkstr problems, will check in next steps
                end
                channel <= channel + 6'd2;
                channel2 <= channel2 + 6'd2;
                state <= TX_DATA4;
            end
        end

        TX_DATA4 : begin
            if (o_tready) begin
                o_tvalid <= 1'b0;
                if (length >= 4) begin
                    length <= length - 16'd4;

                    if (channel==10) channel2 <= 6'd20;
                    if (channel==20) channel2 <= 6'd10;
                    if (channel==30) channel2 <= 6'd30;

                    if (channel==50) begin
                        channel <= 0;
                        ram_rd_address <= ram_rd_address + 10'd1;
                        state <= TX_DATA1;
                    end
                    else state <= TX_DATA3;
                end
                else begin
                    length <= 0;
                    channel <= 0;
                    channel2 <= 0;
                    didreadout <= 1'b1; // tell it we have read out this event (could be moved earlier?)
                    state <= RX;
                end
            end
        end

        PLLCLOCK : begin // to step the clock phase, you have to toggle scanclk a few times
            pllclock_counter <= pllclock_counter+8'd1;
            if (pllclock_counter[4]) begin
                scanclk <= ~scanclk;
                pllclock_counter <= 0;
                scanclk_cycles <= scanclk_cycles + 8'd1;
                if (scanclk_cycles>5) phasestep[rx_data[1]] <= 1'b0; // deassert!
                if (scanclk_cycles>7) state <= INIT;
            end
        end

        BOOTUP : begin // runs once at startup
            didbootup <= 1'b1;

            neo_color[0] <= 24'h0f0f0f; // B R G
            neo_color[1] <= 24'h0f0f0f;
            send_color <= 1'b1;

            rx_data[0] <= 8'd3; // SPI command
            rx_data[1] <= 8'd0; // talk to ADC
            rx_data[2] <= 8'h00; // ADC address 1
            rx_data[3] <= 8'h02; // ADC address 2
            rx_data[4] <= 8'h03; // power down ADC
            state <= PROCESS;
        end

        default : state <= INIT;
        endcase
    end
end

// sync inputs from other clocks
always @ (posedge clk) begin
   acqstate_sync <= acqstate;
   eventcounter_sync <= eventcounter;
   ram_address_triggered_sync <= ram_address_triggered;
   sample_triggered_sync <= sample_triggered;
   downsamplemergingcounter_triggered_sync <= downsamplemergingcounter_triggered;
   triggerphase_sync <= triggerphase;
   boardin_sync <= boardin;
   for (i=0;i<4;i=i+1) if (overrange[i]) overrange_counter[i] <= overrange_counter[i] + 1;
end

// make 12.5 MHz clock, for flash and RGB LEDs
reg clk_over_4_counter = 0;
always @ (posedge clk50) begin
   if (clk_over_4_counter) clk_over_4 <= ~clk_over_4;
   clk_over_4_counter <= clk_over_4_counter + 1'b1;
end

// for pll reset, need to run the logic on the crystal directly, not the pll output
reg [1:0] pllresetstate=0;
reg pllreset2=0;
always @ (posedge clk50) begin
   case (pllresetstate)
    0 : begin
      if (pllreset2) begin
         pllreset <= 1'b1;
         pllresetstate <= 2'd1;
      end
   end
   1 : begin
      pllreset<=1'b0;
      if (!pllreset2) pllresetstate <= 2'd0;
   end
   endcase
end

assign flash_reset = ~rstn; // active high flash controller reset signal
assign i_tready = (state == RX); // for FT232H data output
assign o_tkeep  = (length>=4) ? 4'b1111 : (length==3) ? 4'b0111 :(length==2) ? 4'b0011 : (length==1) ? 4'b0001 : /*length==0*/ 4'b0000;
assign o_tlast  = (length>=4) ? 1'b0 : 1'b1;

endmodule
