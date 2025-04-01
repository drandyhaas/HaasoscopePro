// Sequence of register writes that triggers sending 4 bytes usb response.
`define SEND_STD_USB_RESPONSE \
    length <= 4; \
    o_tvalid <= 1'b1; \
    state <= TX_DATA_CONST;

module command_processor (
	input  wire        rstn,
	input  wire        clk,
	// AXI-stream slave
	output wire        i_tready,
	input  wire        i_tvalid,
	input  wire [ 7:0] i_tdata,
	// AXI-stream master
	input  wire        o_tready,
	output wire        o_tvalid,
	output wire [31:0] o_tdata,
	output wire [ 3:0] o_tkeep,
	output wire        o_tlast,

	output reg pllreset,

	output reg [7:0]	spitx,
	input  reg [7:0]	spirx,
	input  reg 			spitxready,
	output reg			spitxdv,
	input  reg			spirxdv,
	output reg [7:0]	spics, // which chip to talk to

	input wire [3:0]	lockinfo, // clock info

	input wire [139:0] lvds1bits, lvds2bits, lvds3bits, lvds4bits,// rx_in[0] drives data to rx_out[(J-1)..0], rx_in[1] drives data to the next J number of bits on rx_out
	input wire			clklvds, // clk1, runs at LVDS bit rate (ADC clk input rate) / 2
	output reg			ram_wr=0,
	output reg [9:0]	ram_wr_address=0, ram_rd_address=0,
	output reg [559:0] lvdsbitsout, //output bits to fifo
	input wire [559:0] lvdsbitsin, // input bits from fifo

	output reg[2:0] phasecounterselect, // Dynamic phase shift counter Select. 000:all 001:M 010:C0 011:C1 100:C2 101:C3 110:C4. Registered in the rising edge of scanclk.
	output reg phaseupdown=1, // Dynamic phase shift direction; 1:UP, 0:DOWN. Registered in the PLL on the rising edge of scanclk.
	output reg [3:0] phasestep,
	output reg scanclk=0,

	output reg [2:0] spimisossel=0, //which spimiso to listen to
	output reg [11:0]	debugout,  // for debugging
	input wire [3:0]	overrange,  //ORA0,A1,B0,B1

	output reg [1:0] spi_mode=0,

	input wire [7:0] boardin,
	output wire [7:0] boardout=0,
	output reg spireset_L=1'b1,
	input wire clk50, // needed while doing pllreset,
	input wire lvdsin_trig,
	output reg lvdsout_trig=0,
	input wire lvdsin_trig_b,
	output reg lvdsout_trig_b=0,
	output reg clkswitch=0,
	input wire lvdsin_spare,
	output reg lvdsout_spare=0,
	input wire [69:0] lvdsEbits, lvdsLbits,
	output reg [1:0] leds // controls LED 3..2
);
integer version = 22; // firmware version

assign debugout[0] = clkswitch;
assign debugout[1] = lvdsin_trig;
assign debugout[2] = lvdsin_trig_b;
assign debugout[3] = lvdsin_spare;
assign debugout[4] = lockinfo[0]; //locked
assign debugout[5] = lockinfo[1]; //activeclock
assign debugout[6] = lockinfo[2]; //clkbad0
assign debugout[7] = lockinfo[3]; //clkbad1

assign debugout[8] = boardin[0]; // inputs on PCB
assign debugout[9] = boardin[1];
assign debugout[10] = boardout[3]; //1kHz out 50 Ohm

reg fanon=0;
assign debugout[11] = fanon;

wire exttrigin;
assign exttrigin = boardin[4];
assign leds[0] = exttrigin; // LED2

// variables in clklvds domain, writing into the RAM buffer
integer		downsamplecounter = 1;
reg signed [5+11:0] highressamplevalue[20];
reg signed [11:0] samplevalue2[40];
reg signed [11:0] samplevalue[40], samplevaluereg[40];
reg signed [47:0]	highressamplevalueavg0 = 0, highressamplevalueavgtemp0 = 0;
reg signed [47:0]	highressamplevalueavg1 = 0, highressamplevalueavgtemp1 = 0;
reg [1:0] 	sampleclkstr[40];
reg [7:0]	tot_counter = 0;
reg [7:0]	downsamplemergingcounter = 1;
reg [15:0]	triggercounter = 0;
integer		rollingtriggercounter = 0;

// variables synced between domains
reg [ 7:0]	acqstate = 0, acqstate_sync = 0;
reg signed [11:0]  lowerthresh = 0, lowerthresh_sync = 0;
reg signed [11:0]  upperthresh = 0, upperthresh_sync = 0;
integer		eventcounter = 0, eventcounter_sync = 0;
reg [15:0]	lengthtotake = 0, lengthtotake_sync = 0;
reg [15:0]	prelengthtotake=1000, prelengthtotake_sync=1000;
reg 			triggerlive = 0, triggerlive_sync = 0;
reg			didreadout = 0, didreadout_sync = 0;
reg [ 7:0]	triggertype = 0, triggertype_sync = 0;
reg [ 7:0]	channeltype = 0, channeltype_sync = 0;
reg [ 9:0]	ram_address_triggered = 0, ram_address_triggered_sync = 0;
reg [ 7:0] 	triggerToT = 0, triggerToT_sync = 0;
reg [4:0] 	downsample = 0, downsample_sync = 0;
reg			highres = 0, highres_sync = 0;
reg [7:0]	downsamplemerging = 1, downsamplemerging_sync = 1;
reg [19:0] 	sample_triggered = 0, sample_triggered_sync = 0;
reg [7:0]	downsamplemergingcounter_triggered = 0, downsamplemergingcounter_triggered_sync = 0;
reg 			triggerchan = 0, triggerchan_sync = 0;
reg			dorolling = 0, dorolling_sync = 0;

// this drives the trigger
always @ (posedge clklvds or negedge rstn) begin
	if (~rstn) acqstate <= 8'd0;
	else begin
		triggerlive_sync       <= triggerlive;
		lengthtotake_sync      <= lengthtotake;
		prelengthtotake_sync   <= prelengthtotake;
		triggertype_sync       <= triggertype;
		channeltype_sync       <= channeltype;
		didreadout_sync        <= didreadout;
		lowerthresh_sync       <= lowerthresh;
		upperthresh_sync       <= upperthresh;
		triggerToT_sync        <= triggerToT;
		downsample_sync        <= downsample;
		downsamplemerging_sync <= downsamplemerging;
		highres_sync           <= highres;
		triggerchan_sync       <= triggerchan;
		dorolling_sync         <= dorolling;

		if (acqstate==251) begin // not writing, while waiting to be read out
			ram_wr <= 1'b0;
			downsamplecounter <= 1;
			downsamplemergingcounter <= 1;
		end
		else begin // always writing while waiting for a trigger, to see what happened before
			if (downsamplecounter[downsample_sync]) begin
				downsamplecounter <= 1;
				if (downsamplemergingcounter==downsamplemerging_sync) begin
					downsamplemergingcounter <= 8'd1;
					ram_wr_address <= ram_wr_address + 10'd1;
					ram_wr <= 1'b1;
				end
				else begin
				    downsamplemergingcounter <= downsamplemergingcounter + 8'd1;
				    ram_wr <= 1'b0;
				end
			end
			else begin
			    downsamplecounter <= downsamplecounter  +1;
			    ram_wr <= 1'b0;
			end
		end

		// rolling trigger
		if (dorolling_sync && acqstate>0 && acqstate<250) begin
			if (rollingtriggercounter==40000000) begin
				sample_triggered <= 0;
				downsamplemergingcounter_triggered <= downsamplemergingcounter;
				ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
				lvdsout_trig <= 1'b1; // tell the others (maybe want to do rolling trigger on just the first board?)
				//lvdsout_trig_b <= 1'b1; // no need, just going forwards?
				acqstate <= 8'd250; // trigger
			end
			else rollingtriggercounter <= rollingtriggercounter + 1;
		end

		case (acqstate)
		0 : begin // ready
			tot_counter <= 0;
			sample_triggered <= 0;
			downsamplemergingcounter_triggered <= -8'd1;
			lvdsout_trig <= 0;
			lvdsout_trig_b <= 0;

			// wait for pre-aquisition
			if (triggercounter<prelengthtotake_sync) begin
				if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) begin
					triggercounter <= triggercounter + 16'd1;
				end
			end
			else if (triggerlive_sync) begin
				triggercounter <= 0; // will also use this to keep recording enough samples after the trigger, so reset

				case(triggertype_sync)
					8'd0 : ; // disable conditional triggering
					8'd1 : acqstate <= 8'd1; // threshold trigger rising edge
					8'd2 : acqstate <= 8'd3; // threshold trigger falling edge
					8'd3 : acqstate <= 8'd5; // external trigger
					8'd4 : acqstate <= 8'd6; // auto trigger (forces waveform capture unconditionally)
					default: begin
						// Does this ever happen?
						ram_address_triggered <= ram_wr_address; // remember where the trigger happened
						//lvdsout_trig <= 1'b1; // tell the others
						//lvdsout_trig_b <= 1'b1; // tell the others
						acqstate <= 8'd250; // go straight to taking more data, no trigger, triggertype==0
					end
				endcase
			end
		end

		// rising edge trigger (1)
		1 : begin // ready for first part of trigger condition to be met
			if (triggertype_sync!=1) acqstate <= 0;
			else begin
				for (i=0;i<10;i=i+1) begin
					if (
					    (triggerchan_sync==1'b0 && samplevalue[i]<lowerthresh_sync) ||
					    (triggerchan_sync==1'b1 && samplevalue[10+i]<lowerthresh_sync)
					) acqstate <= 8'd2;
					if (
					    (triggerchan_sync==1'b0 && samplevalue[i]>upperthresh_sync) ||
					    (triggerchan_sync==1'b1 && samplevalue[10+i]>upperthresh_sync)
					)
					    sample_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
					else
					    sample_triggered[9-i] <= 1'b0;
				end
			end
		end

		2 : begin // ready for second part of trigger condition to be met
			if (triggertype_sync!=1) acqstate <= 0;
			else begin
                for (i=0;i<10;i=i+1) begin
                    if (
                        (triggerchan_sync==1'b0 && samplevalue[i]>upperthresh_sync) ||
                        (triggerchan_sync==1'b1 && samplevalue[10+i]>upperthresh_sync)
                    ) begin
                        if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
                            sample_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
                            downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
                        end

                        if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync)
                            tot_counter <= tot_counter + 8'd1;

                        if (tot_counter>=triggerToT_sync &&
                            (triggerToT_sync==0 || downsamplemergingcounter==downsamplemergingcounter_triggered) )
                        begin
                            ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
                            lvdsout_trig <= 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
                            lvdsout_trig_b <= 1'b1; // and backwards
                            acqstate <= 8'd250;
                        end
                    end
                end
			end
		end

		// falling edge trigger (2)
		3 : begin // ready for first part of trigger condition to be met
            if (triggertype_sync!=2) acqstate <= 0;
            else begin
                for (i=0;i<10;i=i+1) begin
                    if (
                        (triggerchan_sync==1'b0 && samplevalue[i]>upperthresh_sync) ||
                        (triggerchan_sync==1'b1 && samplevalue[10+i]>upperthresh_sync)
                    )
                        acqstate <= 8'd4;

                    if (
                        (triggerchan_sync==1'b0 && samplevalue[i]<lowerthresh_sync) ||
                        (triggerchan_sync==1'b1 && samplevalue[10+i]<lowerthresh_sync)
                    )
                        sample_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
                    else
                        sample_triggered[9-i] <= 1'b0;
                end
            end
		end
		4 : begin // ready for second part of trigger condition to be met
            if (triggertype_sync!=2) acqstate <= 0;
            else begin
                for (i=0;i<10;i=i+1) begin
                    if (
                        (triggerchan_sync==1'b0 && samplevalue[i]<lowerthresh_sync) ||
                        (triggerchan_sync==1'b1 && samplevalue[10+i]<lowerthresh_sync)
                    ) begin
                        if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
                            sample_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
                            downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
                        end

                        if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) begin
                            tot_counter <= tot_counter + 8'd1;
                        end

                        if (tot_counter>=triggerToT_sync &&
                            (triggerToT_sync==0 || downsamplemergingcounter==downsamplemergingcounter_triggered) )
                        begin
                            ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
                            lvdsout_trig <= 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
                            lvdsout_trig_b <= 1'b1; // and backwards
                            acqstate <= 8'd250;
                        end
                    end
                end
            end
		end

		5 : begin // external trigger, like from another board (3)
            if (triggertype_sync!=3) acqstate <= 0;
            else begin
                if (lvdsin_trig) begin
                    ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
                    lvdsout_trig <= 1'b1; // tell the others forwards
                    sample_triggered <= 0; // not used, since we didn't measure the trigger edge - will take it from the board that caused the trigger
                    downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that we were on when we got this trigger
                    acqstate <= 8'd250;
                end
                if (lvdsin_trig_b) begin
                    ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
                    lvdsout_trig_b <= 1'b1; // tell the others backwards
                    sample_triggered <= 0; // not used, since we didn't measure the trigger edge - will take it from the board that caused the trigger
                    downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that we were on when we got this trigger
                    acqstate <= 8'd250;
                end
            end
		end

		6: begin
			// We end up here when triggertype is set to 4 (auto trigger). When we enter here triggercounter is 0,
			// so we will accumlate pre-trigger samples, then record trigger position and move on to step 250 where
			// reminder of the data (after-trigger samples) will be accumlated. This to force waveform capture
			// call force-arm-trigger function with trigger type set to 4.
			if (triggercounter<prelengthtotake_sync) begin
				if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) begin
					triggercounter <= triggercounter + 16'd1;
				end
			end else begin
				ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
				lvdsout_trig <= 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
				lvdsout_trig_b <= 1'b1; // and backwards
				downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
				acqstate <= 8'd250;
			end
		end

		250 : begin // triggered, now taking more data
			lvdsout_trig <= 0; // stop telling the others forwards
			lvdsout_trig_b <= 0; // and backwards
			rollingtriggercounter <= 0; // reset after getting an event
			if (triggercounter<lengthtotake_sync) begin
				if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) begin
				    triggercounter <= triggercounter + 16'd1;
				end
			end
			else begin
				eventcounter <= eventcounter + 1;
				acqstate <= 8'd251;
			end
		end

		251 : begin // ready to be read out, not writing into RAM
			lvdsout_trig <= 0;
			lvdsout_trig_b <= 0;
			triggercounter <= 0;
			if (didreadout_sync) acqstate <= 8'd0;
		end

		default : begin
			acqstate <= 8'd0;
		end
		endcase
	end
end


// variables in clk domain, reading out of the RAM buffer
localparam [3:0] INIT=4'd0, RX=4'd1, PROCESS=4'd2, TX_DATA_CONST=4'd3, TX_DATA1=4'd4, TX_DATA2=4'd5, TX_DATA3=4'd6;
localparam [3:0] TX_DATA4=4'd7, PLLCLOCK=4'd8, BOOTUP=4'd9;

reg [ 3:0]	state = INIT;
reg			didbootup = 0;
reg [ 3:0]	rx_counter = 0;
reg [ 7:0]	rx_data[7:0];
integer		length = 0;
reg [ 3:0]	spistate = 0;
reg [5:0]	channel = 0;
reg [5:0]	spicscounter = 0;
reg [7:0] pllclock_counter = 0; // for clock phase
reg [7:0] scanclk_cycles = 0;
reg [9:0] ram_preoffset = 0;
integer overrange_counter[4];
reg [15:0]	probecompcounter = 0;
reg send_color = 1;

always @ (posedge clk) begin
	acqstate_sync <= acqstate;
	eventcounter_sync <= eventcounter;
	ram_address_triggered_sync <= ram_address_triggered;
	sample_triggered_sync <= sample_triggered;
	downsamplemergingcounter_triggered_sync <= downsamplemergingcounter_triggered;

	for (i=0;i<4;i=i+1)
	    if (overrange[i]) overrange_counter[i] <= overrange_counter[i] + 1;
end

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
                if (rx_data[1]==0) o_tdata <= version;
                if (rx_data[1]==1) o_tdata <= {boardin,boardin,boardin,boardin};
                if (rx_data[1]==2) o_tdata <= overrange_counter[rx_data[2][1:0]];
                if (rx_data[1]==3) o_tdata <= eventcounter_sync;
                if (rx_data[1]==4) o_tdata <= downsamplemergingcounter_triggered_sync;
                if (rx_data[1]==5) begin
                    lvdsout_spare <= rx_data[2][0]; // used for telling order of devices
                    o_tdata <= {8'd0, 7'd0,lvdsin_spare, 4'd0,lockinfo, 7'd0,~clkswitch};
                end
                if (rx_data[1]==6) begin
                    fanon <= rx_data[2][0];
                    o_tdata <= fanon;
                end
                if (rx_data[1]==7) begin
                    prelengthtotake <= {rx_data[3],rx_data[2]};
                    o_tdata <= prelengthtotake;
                end
                if (rx_data[1]==8) begin
                    dorolling <= rx_data[2][0];
                    o_tdata <= dorolling;
                end
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
                if (acqstate_sync == 0 || acqstate_sync == 251) begin
                    triggertype <= rx_data[1]; // set the trigger type
                    channeltype <= rx_data[2]; // the channel type (bit0: single or dual, bit1: oversampling (swapped inputs))
                    lengthtotake <= {rx_data[5],rx_data[4]};

                    // we might not have actually read out data yet; however, since we are force arming the trigger we
                    // are going to pretend that we did so. In the separate "loop" over clklvds that should move
                    // acqstate to 0
                    length <= 0;
                    channel <= 0;
                    didreadout <= 1'b1;

                    triggerlive <= 1'b1; // gets reset in INIT state

                    // return 1 in the first byte indicating that we were able to arm the trigger
                    // and for debuging current acqstate in the second.
                    o_tdata <= {8'd0, 8'd0, acqstate_sync, 8'd1};
                end else begin
                    // return 0 in the first byte indicating that we were not able to arm the trigger
                    // and for debuging current acqstate in the second.
                    o_tdata <= {8'd0, 8'd0, acqstate_sync, 8'd0};
                end
                `SEND_STD_USB_RESPONSE
            end

            14 : begin // read-register function.
                // Returns "register" (some are wires) value indentified by a number in rx_data[1].
                case (rx_data[1])
                    0 : o_tdata <= {22'd0, ram_preoffset};
                    1 : o_tdata <= {22'd0, ram_address_triggered_sync};
                    2 : o_tdata <= {28'd0, spistate};
                    3 : o_tdata <= version;
                    4 : o_tdata <= {24'd0, boardin};
                    5 : o_tdata <= {24'd0, acqstate_sync};
                    6 : o_tdata <= eventcounter_sync;
                    7 : o_tdata <= {12'd0, sample_triggered_sync};
                    8 : o_tdata <= {24'd0, downsamplemergingcounter_triggered_sync};
                    9 : o_tdata <= {24'd0, downsamplemerging};
                    10: o_tdata <= {27'd0, downsample};
                    11: o_tdata <= {31'd0, highres};
                    default:
                    	o_tdata <= {32'd0};
                endcase
                `SEND_STD_USB_RESPONSE
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

        TX_DATA1 : begin // channel==0
            o_tvalid <= 1'b0;
            if (o_tready) begin
                //wait for data
                state <= TX_DATA2;
            end
        end

        TX_DATA2 : begin
            o_tvalid <= 1'b0;
            if (o_tready) begin
                // wait for data
                state <= TX_DATA3;
            end
        end

        TX_DATA3 : begin
            if (o_tready) begin
                o_tvalid <= 1'b1;
                if (channel==48) o_tdata <= {16'hbeef,16'hdead};//marker
                else if (channel==46) o_tdata  <= {
                    12'd0,
                    lvdsbitsin[14*39+12 +: 2], //sampleclkstr39
                    lvdsbitsin[14*38+12 +: 2],lvdsbitsin[14*37+12 +: 2],lvdsbitsin[14*36+12 +: 2],lvdsbitsin[14*35+12 +: 2],lvdsbitsin[14*34+12 +: 2],lvdsbitsin[14*33+12 +: 2],lvdsbitsin[14*32+12 +: 2],lvdsbitsin[14*31+12 +: 2],
                    lvdsbitsin[14*30+12 +: 2], //sampleclkstr30
                    };
                else if (channel==44) o_tdata  <= {
                    12'd0,
                    lvdsbitsin[14*29+12 +: 2], //sampleclkstr29
                    lvdsbitsin[14*28+12 +: 2],lvdsbitsin[14*27+12 +: 2],lvdsbitsin[14*26+12 +: 2],lvdsbitsin[14*25+12 +: 2],lvdsbitsin[14*24+12 +: 2],lvdsbitsin[14*23+12 +: 2],lvdsbitsin[14*22+12 +: 2],lvdsbitsin[14*21+12 +: 2],
                    lvdsbitsin[14*20+12 +: 2], //sampleclkstr20
                    };
                else if (channel==42) o_tdata  <= {
                    12'd0,
                    lvdsbitsin[14*19+12 +: 2], //sampleclkstr19
                    lvdsbitsin[14*18+12 +: 2],lvdsbitsin[14*17+12 +: 2],lvdsbitsin[14*16+12 +: 2],lvdsbitsin[14*15+12 +: 2],lvdsbitsin[14*14+12 +: 2],lvdsbitsin[14*13+12 +: 2],lvdsbitsin[14*12+12 +: 2],lvdsbitsin[14*11+12 +: 2],
                    lvdsbitsin[14*10+12 +: 2], //sampleclkstr10
                    };
                else if (channel==40) o_tdata  <= {
                    12'd0,
                    lvdsbitsin[14*9+12 +: 2], //sampleclkstr9
                    lvdsbitsin[14*8+12 +: 2],lvdsbitsin[14*7+12 +: 2],lvdsbitsin[14*6+12 +: 2],lvdsbitsin[14*5+12 +: 2],lvdsbitsin[14*4+12 +: 2],lvdsbitsin[14*3+12 +: 2],lvdsbitsin[14*2+12 +: 2],lvdsbitsin[14*1+12 +: 2],
                    lvdsbitsin[14*0+12 +: 2], //sampleclkstr0
                    };
                else o_tdata  <= {4'd0, lvdsbitsin[14*(channel+1) +: 12], 4'd0, lvdsbitsin[14*channel +: 12]};
                channel <= channel + 6'd2;
                state <= TX_DATA4;
            end
        end

        TX_DATA4 : begin
            if (o_tready) begin
                o_tvalid <= 1'b0;
                if (length >= 4) begin
                    length <= length - 16'd4;
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

        default :
            state <= INIT;

        endcase
    end
end

// this is all for downsample merging, since 40 samples come in each clklvds tick
integer i, j;
always @ (posedge clklvds) begin

//	for (i=0;i<10;i=i+2) begin // account for switching of bits from DDR in lvds reciever?
//		samplevalue[i]  <= {lvds1bits[110+i+1],lvds1bits[100+i+1],lvds1bits[90+i+1],lvds1bits[80+i+1],lvds1bits[70+i+1],lvds1bits[60+i+1],lvds1bits[50+i+1],lvds1bits[40+i+1],lvds1bits[30+i+1],lvds1bits[20+i+1],lvds1bits[10+i+1],lvds1bits[0+i+1]};
//		samplevalue[i+1]  <= {lvds1bits[110+i],lvds1bits[100+i],lvds1bits[90+i],lvds1bits[80+i],lvds1bits[70+i],lvds1bits[60+i],lvds1bits[50+i],lvds1bits[40+i],lvds1bits[30+i],lvds1bits[20+i],lvds1bits[10+i],lvds1bits[0+i]};
//		samplevalue[10+i]  <= {lvds2bits[110+i+1],lvds2bits[100+i+1],lvds2bits[90+i+1],lvds2bits[80+i+1],lvds2bits[70+i+1],lvds2bits[60+i+1],lvds2bits[50+i+1],lvds2bits[40+i+1],lvds2bits[30+i+1],lvds2bits[20+i+1],lvds2bits[10+i+1],lvds2bits[0+i+1]};
//		samplevalue[10+i+1]  <= {lvds2bits[110+i],lvds2bits[100+i],lvds2bits[90+i],lvds2bits[80+i],lvds2bits[70+i],lvds2bits[60+i],lvds2bits[50+i],lvds2bits[40+i],lvds2bits[30+i],lvds2bits[20+i],lvds2bits[10+i],lvds2bits[0+i]};
//		samplevalue[20+i]  <= {lvds3bits[110+i+1],lvds3bits[100+i+1],lvds3bits[90+i+1],lvds3bits[80+i+1],lvds3bits[70+i+1],lvds3bits[60+i+1],lvds3bits[50+i+1],lvds3bits[40+i+1],lvds3bits[30+i+1],lvds3bits[20+i+1],lvds3bits[10+i+1],lvds3bits[0+i+1]};
//		samplevalue[20+i+1]  <= {lvds3bits[110+i],lvds3bits[100+i],lvds3bits[90+i],lvds3bits[80+i],lvds3bits[70+i],lvds3bits[60+i],lvds3bits[50+i],lvds3bits[40+i],lvds3bits[30+i],lvds3bits[20+i],lvds3bits[10+i],lvds3bits[0+i]};
//		samplevalue[30+i]  <= {lvds4bits[110+i+1],lvds4bits[100+i+1],lvds4bits[90+i+1],lvds4bits[80+i+1],lvds4bits[70+i+1],lvds4bits[60+i+1],lvds4bits[50+i+1],lvds4bits[40+i+1],lvds4bits[30+i+1],lvds4bits[20+i+1],lvds4bits[10+i+1],lvds4bits[0+i+1]};
//		samplevalue[30+i+1]  <= {lvds4bits[110+i],lvds4bits[100+i],lvds4bits[90+i],lvds4bits[80+i],lvds4bits[70+i],lvds4bits[60+i],lvds4bits[50+i],lvds4bits[40+i],lvds4bits[30+i],lvds4bits[20+i],lvds4bits[10+i],lvds4bits[0+i]};
//
//		sampleclkstr[i] <= {lvds1bits[130+i],lvds1bits[120+i]};
//		sampleclkstr[i+1] <= {lvds1bits[130+i+1],lvds1bits[120+i+1]};
//		sampleclkstr[10+i] <= {lvds2bits[130+i],lvds2bits[120+i]};
//		sampleclkstr[10+i+1] <= {lvds2bits[130+i+1],lvds2bits[120+i+1]};
//		sampleclkstr[20+i] <= {lvds3bits[130+i],lvds3bits[120+i]};
//		sampleclkstr[20+i+1] <= {lvds3bits[130+i+1],lvds3bits[120+i+1]};
//		sampleclkstr[30+i] <= {lvds4bits[130+i],lvds4bits[120+i]};
//		sampleclkstr[30+i+1] <= {lvds4bits[130+i+1],lvds4bits[120+i+1]};
//	end

	for (i=0;i<10;i=i+1) begin
		samplevaluereg[0 +i]  <= {lvds1bits[110+i],lvds1bits[100+i],lvds1bits[90+i],lvds1bits[80+i],lvds1bits[70+i],lvds1bits[60+i],lvds1bits[50+i],lvds1bits[40+i],lvds1bits[30+i],lvds1bits[20+i],lvds1bits[10+i],lvds1bits[0+i]};
		samplevaluereg[10+i]  <= {lvds2bits[110+i],lvds2bits[100+i],lvds2bits[90+i],lvds2bits[80+i],lvds2bits[70+i],lvds2bits[60+i],lvds2bits[50+i],lvds2bits[40+i],lvds2bits[30+i],lvds2bits[20+i],lvds2bits[10+i],lvds2bits[0+i]};
		samplevaluereg[20+i]  <= {lvds3bits[110+i],lvds3bits[100+i],lvds3bits[90+i],lvds3bits[80+i],lvds3bits[70+i],lvds3bits[60+i],lvds3bits[50+i],lvds3bits[40+i],lvds3bits[30+i],lvds3bits[20+i],lvds3bits[10+i],lvds3bits[0+i]};
		samplevaluereg[30+i]  <= {lvds4bits[110+i],lvds4bits[100+i],lvds4bits[90+i],lvds4bits[80+i],lvds4bits[70+i],lvds4bits[60+i],lvds4bits[50+i],lvds4bits[40+i],lvds4bits[30+i],lvds4bits[20+i],lvds4bits[10+i],lvds4bits[0+i]};

		if (channeltype_sync[1] == 1'b0) begin // normal, not swapped
			// don't invert input 0
			samplevalue[0 +i] <= samplevaluereg[0 +i];
			samplevalue[20+i] <= samplevaluereg[20+i];
			if (channeltype_sync[0] == 1'b0) begin // single, also don't invert these on input 0
				samplevalue[10+i] <= samplevaluereg[10+i];
				samplevalue[30+i] <= samplevaluereg[30+i];
			end
			else begin // dual, inverted on input 1
				samplevalue[10+i] <= (samplevaluereg[10+i]== -12'd2048) ? 12'd2047: -samplevaluereg[10+i]; // careful when inverting - there is no inverse of -2^12!
				samplevalue[30+i] <= (samplevaluereg[30+i]== -12'd2048) ? 12'd2047: -samplevaluereg[30+i];
			end
		end
		else begin // doing oversampling, swapped
			// invert input 1
			samplevalue[0 +i] <= (samplevaluereg[0 +i]== -12'd2048) ? 12'd2047: -samplevaluereg[0 +i];
			samplevalue[20+i] <= (samplevaluereg[20+i]== -12'd2048) ? 12'd2047: -samplevaluereg[20+i];
			// always in single mode while oversampling, also invert these on input 1
			samplevalue[10+i] <= (samplevaluereg[10+i]== -12'd2048) ? 12'd2047: -samplevaluereg[10+i];
			samplevalue[30+i] <= (samplevaluereg[30+i]== -12'd2048) ? 12'd2047: -samplevaluereg[30+i];
		end

		sampleclkstr[i]    <= {lvds1bits[130+i],lvds1bits[120+i]};
		sampleclkstr[10+i] <= {lvds2bits[130+i],lvds2bits[120+i]};
		sampleclkstr[20+i] <= {lvds3bits[130+i],lvds3bits[120+i]};
		sampleclkstr[30+i] <= {lvds4bits[130+i],lvds4bits[120+i]};
	end

	for (i=0;i<40;i=i+1) begin
		lvdsbitsout[14*i+12 +:2] <= sampleclkstr[i]; // always use the same clk and str bits
		samplevalue2[i] <= samplevalue[i]; // pipeline just so the delay is the same for this and higher downsample rates - also helps with timing closure
	end

	if (channeltype_sync[0]==1'b0) begin // single channel mode

			if (downsamplemerging_sync==1) begin // this is highest rate
				for (i=0;i<10;i=i+1) begin // straighten the samples out
					lvdsbitsout[14*(i*4+0) +:12] <= samplevalue2[30+1*i];
					lvdsbitsout[14*(i*4+1) +:12] <= samplevalue2[20+1*i];
					lvdsbitsout[14*(i*4+2) +:12] <= samplevalue2[10+1*i];
					lvdsbitsout[14*(i*4+3) +:12] <= samplevalue2[ 0+1*i];
				end
			end

        if (downsamplemerging_sync==2) begin
            for (i=0;i<10;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[0*10+i] <= samplevalue[20+1*i] + samplevalue[30+1*i]; // every bit from chan 2 into bit 0,2,4...18, and add in the other bits
                    lvdsbitsout[14*(i*2+0) +:12] <= highressamplevalue[0*10+i][1+:12]; // shift left 1 bit, thus dividing by 2
                    highressamplevalue[1*10+i] <= samplevalue[0+1*i] + samplevalue[10+1*i]; // every bit from chan 0 into bit 1,3,5...19, add in the other bits
                    lvdsbitsout[14*(i*2+1) +:12] <= highressamplevalue[1*10+i][1+:12]; // shift left 1 bit, thus dividing by 2
                end
                else begin
                    lvdsbitsout[14*(i*2+0) +:12] <= samplevalue[20+1*i]; // every bit from chan 2 into bit 0,2,4...18
                    lvdsbitsout[14*(i*2+1) +:12] <= samplevalue[0+1*i]; // every bit from chan 0 into bit 1,3,5...19
                end
                lvdsbitsout[14*(i*2+20) +:12] <= lvdsbitsout[14*(i*2+0) +:12]; // move what was in first 20 into second 20
                lvdsbitsout[14*(i*2+21) +:12] <= lvdsbitsout[14*(i*2+1) +:12];
            end
        end

        if (downsamplemerging_sync==4) begin
            for (i=0;i<10;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[i] <= samplevalue[0+1*i] + samplevalue[10+1*i] + samplevalue[20+1*i] + samplevalue[30+1*i]; // every bit of chan 0, and add in the other bits
                    lvdsbitsout[14*i +:12] <= highressamplevalue[i][2+:12]; // shift left 2 bits, thus dividing by 4
                end
                else begin
                    lvdsbitsout[14*i +:12] <= samplevalue[0+1*i]; // every bit of chan 0
                end
                for (j=0;j<30;j=j+10) begin
                    lvdsbitsout[14*(i+10+j) +:12] <= lvdsbitsout[14*(i+j) +:12]; // move what was in first 10 into second 10
                end
            end
        end

        if (downsamplemerging_sync==8) begin
            for (i=0;i<5;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[i] <= samplevalue[0+2*i] + samplevalue[1+2*i] + samplevalue[10+2*i] + samplevalue[11+2*i] + samplevalue[20+2*i] + samplevalue[21+2*i] + samplevalue[30+2*i] + samplevalue[31+2*i]; // every other bit of chan 0, and add in the other bits
                    lvdsbitsout[14*i +:12] <= highressamplevalue[i][3+:12]; // shift left 3 bits, thus dividing by 8
                end
                else begin
                    lvdsbitsout[14*i +:12] <= samplevalue[0+2*i]; // every other bit of chan 0
                end
                for (j=0;j<35;j=j+5) begin
                    lvdsbitsout[14*(i+5+j) +:12] <= lvdsbitsout[14*(i+j) +:12]; // move what was in first 5 into second 5
                end
            end
        end

        if (downsamplemerging_sync==20) begin
            for (i=0;i<2;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[i] <= samplevalue[0+5*i] + samplevalue[1+5*i] + samplevalue[3+5*i] + samplevalue[4+5*i] +
                                                    samplevalue[10+5*i] + samplevalue[11+5*i] + samplevalue[13+5*i] + samplevalue[14+5*i] +
                                                    samplevalue[20+5*i] + samplevalue[21+5*i] + samplevalue[23+5*i] + samplevalue[24+5*i] +
                                                    samplevalue[30+5*i] + samplevalue[31+5*i] + samplevalue[33+5*i] + samplevalue[34+5*i]; // every first and fifth bit of chan 0, and add in the other bits
                    lvdsbitsout[14*i +:12] <= highressamplevalue[i][4+:12]; // would like to have divided by 20, but instead skip every 5th bit, and divide by 16
                end
                else begin
                    lvdsbitsout[14*i +:12] <= samplevalue[0+5*i]; // every first and fifth bit of chan 0
                end
                for (j=0;j<38;j=j+2) begin
                    lvdsbitsout[14*(i+2+j) +:12] <= lvdsbitsout[14*(i+j) +:12]; // move what was in first 2 into second 2
                end
            end
        end

        if (downsamplemerging_sync==40) begin
            if (highres_sync) begin
                highressamplevalue[0] <= samplevalue[0] + samplevalue[1] + samplevalue[3] + samplevalue[4] + samplevalue[5] + samplevalue[6] + samplevalue[8] + samplevalue[9] +
                                                samplevalue[10] + samplevalue[11] + samplevalue[13] + samplevalue[14] + samplevalue[15] + samplevalue[16] + samplevalue[18] + samplevalue[19] +
                                                samplevalue[20] + samplevalue[21] + samplevalue[23] + samplevalue[24] + samplevalue[25] + samplevalue[26] + samplevalue[28] + samplevalue[29] +
                                                samplevalue[30] + samplevalue[31] + samplevalue[33] + samplevalue[34] + samplevalue[35] + samplevalue[36] + samplevalue[38] + samplevalue[39]; // every bit of chan 0, and add in the other bits
                if (downsamplecounter[downsample_sync]) begin
                    highressamplevalueavgtemp0 = highressamplevalueavg0+highressamplevalue[0];
                    lvdsbitsout[0 +:12] <= highressamplevalueavgtemp0[(5+downsample_sync)+:12]; // would like to have divided by 40, but instead skip every 5th bit, and divide by 32 * 2^downsample
                    highressamplevalueavg0 <= 0;
                end
                else begin
                    highressamplevalueavg0 <= highressamplevalueavg0+highressamplevalue[0];
                end
            end
            else begin
                lvdsbitsout[0 +:12] <= samplevalue[0]; // every first bit of chan 0
            end
            if (downsamplecounter[downsample_sync]) begin
                for (j=0;j<39;j=j+1) begin
                    lvdsbitsout[14*(1+j) +:12] <= lvdsbitsout[14*(j) +:12]; // move what was in first 1 into second 1
                end
            end
        end
	end
	else begin // two channel mode

			if (downsamplemerging_sync==1) begin // this is highest rate
				for (i=0;i<5;i=i+1) begin // straighten the samples out
					lvdsbitsout[14*(i*2+0 ) +:12] <= samplevalue2[20+1*i];
					lvdsbitsout[14*(i*2+1 ) +:12] <= samplevalue2[ 0+1*i];
					lvdsbitsout[14*(i*2+10) +:12] <= samplevalue2[30+1*i];
					lvdsbitsout[14*(i*2+11) +:12] <= samplevalue2[10+1*i];
					lvdsbitsout[14*(i*2+20) +:12] <= samplevalue2[25+1*i];
					lvdsbitsout[14*(i*2+21) +:12] <= samplevalue2[ 5+1*i];
					lvdsbitsout[14*(i*2+30) +:12] <= samplevalue2[35+1*i];
					lvdsbitsout[14*(i*2+31) +:12] <= samplevalue2[15+1*i];
				end
			end

        if (downsamplemerging_sync==2) begin
            for (i=0;i<10;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[0 +i] <= samplevalue[0 +i] + samplevalue[20+i]; // add 1 bit of chan 0 + 1 bit of chan 2, into bit 0, 1, 2, 3, ... 8, 9
                    lvdsbitsout[14*(i+ 0) +:12] <= highressamplevalue[ 0+i][1+:12]; // shift left 1 bit, thus dividing by 2
                    highressamplevalue[10+i] <= samplevalue[10+i] + samplevalue[30+i]; // add 1 bit of chan 1 + 1 bit of chan 3, into bit 10, 11, 12, 13, ... 18, 19
                    lvdsbitsout[14*(i+10) +:12] <= highressamplevalue[10+i][1+:12]; // shift left 1 bit, thus dividing by 2
                end
                else begin
                    lvdsbitsout[14*(i+ 0) +:12] <= samplevalue[0 +i]; // just chan 0
                    lvdsbitsout[14*(i+10) +:12] <= samplevalue[10+i]; // just chan 1
                end
                lvdsbitsout[14*(i*2+20) +:12] <= lvdsbitsout[14*(i*2+0) +:12]; // move what was in first 10 into second 10, for each channel
                lvdsbitsout[14*(i*2+21) +:12] <= lvdsbitsout[14*(i*2+1) +:12];
            end
        end

        if (downsamplemerging_sync==4) begin
            for (i=0;i<5;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[i] <= samplevalue[0+2*i] + samplevalue[1+2*i] + samplevalue[20+2*i] + samplevalue[21+2*i]; // 2 bits of chan 0 and 2, into bit 0, 1, 2, 3, 4
                    lvdsbitsout[14*(i +0) +:12] <= highressamplevalue[i][2+:12]; // shift left 2 bits, thus dividing by 4
                    highressamplevalue[5+i] <= samplevalue[10+2*i] + samplevalue[11+2*i] + samplevalue[30+2*i] + samplevalue[31+2*i]; // 2 bits of chan 1 and 3, into bit 10, 11, 12, 13, 14
                    lvdsbitsout[14*(i+10) +:12] <= highressamplevalue[5+i][2+:12]; // shift left 2 bits, thus dividing by 4
                end
                else begin
                    lvdsbitsout[14*(i+ 0) +:12] <= samplevalue[ 0+2*i]; // every other bit of chan 0
                    lvdsbitsout[14*(i+10) +:12] <= samplevalue[10+2*i]; // every other bit of chan 1
                end
                lvdsbitsout[14*(i+5 ) +:12] <= lvdsbitsout[14*(i+0 ) +:12]; // move what was in first 5 into second 5, for each channel
                lvdsbitsout[14*(i+20) +:12] <= lvdsbitsout[14*(i+5 ) +:12];
                lvdsbitsout[14*(i+25) +:12] <= lvdsbitsout[14*(i+20) +:12];
                lvdsbitsout[14*(i+15) +:12] <= lvdsbitsout[14*(i+10) +:12];
                lvdsbitsout[14*(i+30) +:12] <= lvdsbitsout[14*(i+15) +:12];
                lvdsbitsout[14*(i+35) +:12] <= lvdsbitsout[14*(i+30) +:12];
            end
        end

        if (downsamplemerging_sync==10) begin
            for (i=0;i<2;i=i+1) begin
                if (highres_sync) begin
                    highressamplevalue[i] <= samplevalue[0+5*i] + samplevalue[1+5*i] + samplevalue[3+5*i] + samplevalue[4+5*i] +
                                                    samplevalue[20+5*i] + samplevalue[21+5*i] + samplevalue[23+5*i] + samplevalue[24+5*i]; // 5 bits of chan 0 and 2, into bit 0, 1 (but skip every 5th bit)
                    lvdsbitsout[14*(i +0) +:12] <= highressamplevalue[i][3+:12]; // would like to have divided by 10, but instead skip every 5th bit, and divide by 8
                    highressamplevalue[2+i] <= samplevalue[10+5*i] + samplevalue[11+5*i] + samplevalue[13+5*i] + samplevalue[14+5*i] +
                                                      samplevalue[30+5*i] + samplevalue[31+5*i] + samplevalue[33+5*i] + samplevalue[34+5*i]; // 5 bits of chan 1 and 3, into bit 10, 11 (but skip every 5th bit)
                    lvdsbitsout[14*(i+10) +:12] <= highressamplevalue[2+i][3+:12]; // would like to have divided by 10, but instead skip every 5th bit, and divide by 8
                end
                else begin
                    lvdsbitsout[14*(i+ 0) +:12] <= samplevalue[ 0+5*i]; // every fifth bit of chan 0
                    lvdsbitsout[14*(i+10) +:12] <= samplevalue[10+5*i]; // every fifth bit of chan 1
                end
                lvdsbitsout[14*(i+2 ) +:12] <= lvdsbitsout[14*(i+0 ) +:12]; // move what was in first 2 into second 2, for each channel
                lvdsbitsout[14*(i+4 ) +:12] <= lvdsbitsout[14*(i+2 ) +:12];
                lvdsbitsout[14*(i+6 ) +:12] <= lvdsbitsout[14*(i+4 ) +:12];
                lvdsbitsout[14*(i+8 ) +:12] <= lvdsbitsout[14*(i+6 ) +:12];
                lvdsbitsout[14*(i+20) +:12] <= lvdsbitsout[14*(i+8 ) +:12];
                lvdsbitsout[14*(i+22) +:12] <= lvdsbitsout[14*(i+20) +:12];
                lvdsbitsout[14*(i+24) +:12] <= lvdsbitsout[14*(i+22) +:12];
                lvdsbitsout[14*(i+26) +:12] <= lvdsbitsout[14*(i+24) +:12];
                lvdsbitsout[14*(i+28) +:12] <= lvdsbitsout[14*(i+26) +:12];

                lvdsbitsout[14*(i+12) +:12] <= lvdsbitsout[14*(i+10) +:12];
                lvdsbitsout[14*(i+14) +:12] <= lvdsbitsout[14*(i+12) +:12];
                lvdsbitsout[14*(i+16) +:12] <= lvdsbitsout[14*(i+14) +:12];
                lvdsbitsout[14*(i+18) +:12] <= lvdsbitsout[14*(i+16) +:12];
                lvdsbitsout[14*(i+30) +:12] <= lvdsbitsout[14*(i+18) +:12];
                lvdsbitsout[14*(i+32) +:12] <= lvdsbitsout[14*(i+30) +:12];
                lvdsbitsout[14*(i+34) +:12] <= lvdsbitsout[14*(i+32) +:12];
                lvdsbitsout[14*(i+36) +:12] <= lvdsbitsout[14*(i+34) +:12];
                lvdsbitsout[14*(i+38) +:12] <= lvdsbitsout[14*(i+36) +:12];
            end
        end

        if (downsamplemerging_sync==20) begin
            if (highres_sync) begin
                highressamplevalue[0] <= samplevalue[0] + samplevalue[1] + samplevalue[3] + samplevalue[4] + samplevalue[5] + samplevalue[6] + samplevalue[8] + samplevalue[9] +
                                                samplevalue[20] + samplevalue[21] + samplevalue[23] + samplevalue[24] + samplevalue[25] + samplevalue[26] + samplevalue[28] + samplevalue[29]; // 10 bits of chan 0 and 2, into bit 0 (but skip every 5th bit)
                highressamplevalue[1] <= samplevalue[10] + samplevalue[11] + samplevalue[13] + samplevalue[14] + samplevalue[15] + samplevalue[16] + samplevalue[18] + samplevalue[19] +
                                                samplevalue[30] + samplevalue[31] + samplevalue[33] + samplevalue[34] + samplevalue[35] + samplevalue[36] + samplevalue[38] + samplevalue[39]; // 10 bits of chan 1 and 3, into bit 10 (but skip every 5th bit)
                if (downsamplecounter[downsample_sync]) begin
                    highressamplevalueavgtemp0 = highressamplevalueavg0 + highressamplevalue[0];
                    highressamplevalueavgtemp1 = highressamplevalueavg1 + highressamplevalue[1];
                    lvdsbitsout[14*0  +:12] <= highressamplevalueavgtemp0[(4+downsample_sync)+:12]; // would like to have divided by 20, but instead skip every 5th bit, and divide by 16
                    lvdsbitsout[14*10 +:12] <= highressamplevalueavgtemp1[(4+downsample_sync)+:12]; // would like to have divided by 20, but instead skip every 5th bit, and divide by 16
                    highressamplevalueavg0 <= 0;
                    highressamplevalueavg1 <= 0;
                end
                else begin
                    highressamplevalueavg0 <= highressamplevalueavg0 + highressamplevalue[0];
                    highressamplevalueavg1 <= highressamplevalueavg1 + highressamplevalue[1];
                end
            end
            else begin
                lvdsbitsout[14*0  +:12] <= samplevalue[ 0]; // every first bit of chan 0
                lvdsbitsout[14*10 +:12] <= samplevalue[10]; // every first bit of chan 1
            end
            if (downsamplecounter[downsample_sync]) begin
                for (j=0;j<9;j=j+1) begin
                    lvdsbitsout[14*(1+ j) +:12] <= lvdsbitsout[14*(0+ j) +:12]; // move what was in first 1 into second 1
                    lvdsbitsout[14*(11+j) +:12] <= lvdsbitsout[14*(10+j) +:12];
                    lvdsbitsout[14*(21+j) +:12] <= lvdsbitsout[14*(20+j) +:12];
                    lvdsbitsout[14*(31+j) +:12] <= lvdsbitsout[14*(30+j) +:12];
                end
                lvdsbitsout[14*(20) +:12] <= lvdsbitsout[14*(9) +:12];
                lvdsbitsout[14*(30) +:12] <= lvdsbitsout[14*(19) +:12];
            end
        end
	end

end


// Neopixel LED state control
// Adapted from https://vivonomicon.com/2018/12/24/learning-how-to-fpga-with-neopixel-leds/
reg [2:0] neostate;
reg [1:0] npxc;
reg [12:0] lpxc;
reg [7:0] neobits;
reg [1:0] neo_led_num;
parameter neo_led_num_max = 2;
reg [23:0] neo_color[neo_led_num_max];
reg clk_over_4 = 0;
reg clk_over_4_counter = 0;

always @ (posedge clk50) begin // Make 12.5 MHz clock
	if (clk_over_4_counter) clk_over_4 <= ~clk_over_4;
	clk_over_4_counter <= clk_over_4_counter + 1'b1;
end
always @ (posedge clk_over_4) begin // Process the state machine at each 12.5 MHz clock edge
	// Process the state machine; states 0-3 are the four WS2812B 'ticks',
	// each consisting of 80 * 4 = 320 nanoseconds. Four of those
	// periods are then 1280 nanoseconds long, and we can get close to
	// the ideal 1250ns period (and the minimum is 1200ns).
	// A '1' is 3 high periods followed by 1 low period (960/320 ns)
	// A '0' is 1 high period followed by 3 low periods (320/960 ns)
	if (neostate == 0 || neostate == 1 || neostate == 2 || neostate == 3) begin
		 npxc = npxc + 2'd1;
		 if (npxc == 0) neostate = neostate + 3'd1;
	end
	if (neostate == 4) begin
		 neobits = neobits + 8'd1;
		 if (neobits == 24) begin
			  neobits = 0;
			  neostate = neostate + 3'd1;
		 end
		 else neostate = 0;
	end
	if (neostate == 5) begin
		 neo_led_num = neo_led_num + 2'd1;
		 if (neo_led_num == neo_led_num_max) begin
			  neo_led_num = 0;
			  neostate = neostate + 3'd1;
		 end
		 else neostate = 0;
	end
	if (neostate == 6) begin
		 lpxc = lpxc + 13'd1;
		 if (lpxc == 0 && send_color) neostate = 0;
	end

	if (neo_color[neo_led_num] & (1 << neobits)) begin // Set the correct pin state
	  if (neostate == 0 || neostate == 1 || neostate == 2) leds[1] = 1;
	  else if (neostate == 3 || neostate == 6) leds[1] = 0;
	end
	else begin
	  if (neostate == 0) leds[1] = 1;
	  else if (neostate == 1 || neostate == 2 || neostate == 3 || neostate == 6) leds[1] = 0;
	end
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

// for FT232H
assign i_tready = (state == RX);
assign o_tkeep  = (length>=4) ? 4'b1111 :
                  (length==3) ? 4'b0111 :
                  (length==2) ? 4'b0011 :
                  (length==1) ? 4'b0001 :
                 /*length==0*/  4'b0000;
assign o_tlast  = (length>=4) ? 1'b0 : 1'b1;

endmodule
