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
	input wire clk50, // needed while doing pllreset
	input wire lvdsin_trig,
	output reg lvdsout_trig=0,
	input wire lvdsin_trig_b,
	output reg lvdsout_trig_b=0,
	output reg clkswitch=0,
	input wire lvdsin_spare,
	output reg lvdsout_spare=0,
	input wire [69:0] lvdsEbits, lvdsLbits,
	output reg [1:0] leds, // controls LED3..2 (LED1..0 are controlled directly by ftdi245fifo module)

	output reg [23:0] flash_addr,
	output reg flash_bulk_erase,
	output reg clk_over_4,
	output reg [7:0] flash_datain,
	output reg flash_rden,
	output reg flash_read,
	output reg flash_write,
	output reg flash_reset,
	
	output reg clkout_ena=1,

	input flash_busy,
	input flash_data_valid,
	input [7:0] flash_dataout
);

integer version = 24; // firmware version

// these 10 debugout's go to LEDs on the board
assign debugout[0] = clkswitch;
assign debugout[1] = lvdsin_trig;
assign debugout[2] = lvdsin_trig_b;
assign debugout[3] = lvdsin_spare;
assign debugout[4] = lockinfo[0]; //locked
assign debugout[5] = lockinfo[1]; //activeclock
assign debugout[6] = lockinfo[2]; //clkbad0
assign debugout[7] = lockinfo[3]; //clkbad1
assign debugout[8] = boardin[0]; // extra inputs on PCB, mirrored to LEDs for now
assign debugout[9] = boardin[1];
// boardin[2] is 12Vconnected
// boardin[3] is PG12V
wire exttrigin; assign exttrigin = boardin[4]; // SMA in on back panel
// boardin[5] is Lockdetect (from ADF4350)
// boardin[6] is Muxout (from ADF4350)
// boardin[7] is Calstat (from ADC)

// boardout[3] is the 1kHz square wave going to the front panel
// other 7 boardout's are for controlling relays

wire auxtrigout; 
assign debugout[10] = (auxoutselector_sync==0) ? clklvds: auxtrigout; // SMA out on back panel

wire fanon; assign debugout[11] = fanon; // the cooling fan (could be PWM'ed for finer control)

assign flash_reset = ~rstn; // active high flash controller reset signal
assign leds[0] = exttrigin; // LED2 (LED3 is used for controlling both the RGB LEDs on the front panel)

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
reg 			firingsecondstep = 0;

// variables synced between domains
reg [ 7:0]	acqstate = 0, acqstate_sync = 0;
reg signed [11:0]  lowerthresh = 0, lowerthresh_sync = 0;
reg signed [11:0]  upperthresh = 0, upperthresh_sync = 0;
integer		eventcounter = 0, eventcounter_sync = 0;
reg [15:0]	lengthtotake = 0, lengthtotake_sync = 0;
reg [15:0]	prelengthtotake=1000, prelengthtotake_sync=1000;
reg 			triggerlive = 0, triggerlive_sync = 0;
reg			didreadout = 0, didreadout_sync = 0;
reg [ 7:0]	triggertype = 0, triggertype_sync = 0, current_active_trigger_type = 0;
reg 			rising = 0;
reg [ 7:0]	channeltype = 0, channeltype_sync = 0;
reg [ 9:0]	ram_address_triggered = 0, ram_address_triggered_sync = 0;
reg [ 7:0] 	triggerToT = 0, triggerToT_sync = 0;
reg [4:0] 	downsample = 0, downsample_sync = 0;
reg			highres = 0, highres_sync = 0;
reg [7:0]	downsamplemerging = 1, downsamplemerging_sync = 1;
reg [19:0] 	sample_triggered = 0, sample_triggered_sync = 0;
reg [19:0] 	sample_triggered2 = 0;
reg [19:0] 	sample_triggered3 = 0;
reg [19:0] 	sample_triggered4 = 0;
reg [9:0]   sample_triggered_max_val1=0, sample_triggered_max_val2=0;
reg [7:0]	downsamplemergingcounter_triggered = 0, downsamplemergingcounter_triggered_sync = 0;
reg [8:0]	triggerphase = 0, triggerphase_sync = 0;
reg 			triggerchan = 0, triggerchan_sync = 0;
reg			dorolling = 0, dorolling_sync = 0; // TODO: to be removed
reg 			auxoutselector = 0, auxoutselector_sync = 0;
reg 			st1zero, st2zero, st3zero, st4zero; // for sample_triggered

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
		dorolling_sync         <= dorolling; // TODO: to be removed
		auxoutselector_sync	  <= auxoutselector;

		if (acqstate==251 || acqstate==0) begin
			// not writing, while waiting to be read out or in initial state where trigger might be disabled
			ram_wr <= 1'b0;
			downsamplecounter <= 1;
			downsamplemergingcounter <= 1;
		end
		else begin
			// Acqure data if some trigger has been armed (acqstate > 0) and it has not arrived yet to its
			// final state (acqstate == 251) where we will be waiting for data to be read out.
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

		// rolling trigger; TODO: this whole if block is to be deleted
		if (dorolling_sync && acqstate>0 && acqstate<249) begin
			if (rollingtriggercounter==8000000) begin // ~10 Hz
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
			auxtrigout <= 0;
			tot_counter <= 0;
			sample_triggered <= 0;
			sample_triggered2 <= 0;
			sample_triggered3 <= 0;
			sample_triggered4 <= 0;
			sample_triggered_max_val1 <= 0;
			sample_triggered_max_val2 <= 0;
			triggerphase <= -9'd1;
			downsamplemergingcounter_triggered <= -8'd1;
			lvdsout_trig <= 0;
			lvdsout_trig_b <= 0;
			downsamplecounter <= 1;
			downsamplemergingcounter <= 1;
			triggercounter <= 0; // set to 0 as this register will be used to count in pre-aquisition
			current_active_trigger_type <= triggertype_sync;
			case(triggertype_sync)
				8'd0 : ; // disable conditional triggering
				default: acqstate <= 8'd249; // go to pre-aquisition
			endcase
		end

		249 : begin // pre-aquisition
			if (current_active_trigger_type != triggertype_sync) acqstate <= 8'd0; // go back to initial state
			else if (triggercounter<prelengthtotake_sync) begin
				if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) begin
					triggercounter <= triggercounter + 16'd1;
				end
			end
			else if (triggerlive_sync) begin
				triggercounter <= 0; // will also use this to keep recording enough samples after the trigger, so reset
				
				if (current_active_trigger_type==1) rising<=1'b1;
				else rising<=1'b0;

				case(current_active_trigger_type)
					8'd1 : acqstate <= 8'd1; // threshold trigger rising edge
					8'd2 : acqstate <= 8'd1; // threshold trigger falling edge
					8'd3 : acqstate <= 8'd5; // external trigger from another board over LVDS
					8'd4 : acqstate <= 8'd6; // auto trigger (forces waveform capture unconditionally)
					8'd5 : acqstate <= 8'd7; // external trigger, like from back panel SMA
				endcase
			end
		end

		// edge trigger (1)
		1 : begin // ready for first part of trigger condition to be met
			if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
			else begin
				if (channeltype_sync[0]==1'b0) begin // single channel mode
				for (i=0;i<10;i=i+1) begin
					if ( (samplevalue[ 0+i]<lowerthresh_sync && rising) || (samplevalue[ 0+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
					if ( (samplevalue[ 0+i]<lowerthresh_sync && !rising) || (samplevalue[ 0+i]>upperthresh_sync && rising) ) begin
						sample_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
					end
					else sample_triggered[9-i] <= 1'b0;
					
					if ( (samplevalue[10+i]<lowerthresh_sync && rising) || (samplevalue[10+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
					if ( (samplevalue[10+i]<lowerthresh_sync && !rising) || (samplevalue[10+i]>upperthresh_sync && rising) ) begin
						sample_triggered2[9-i] <= 1'b1; // remember the samples that caused the trigger
					end
					else sample_triggered2[9-i] <= 1'b0;
					
					if ( (samplevalue[20+i]<lowerthresh_sync && rising) || (samplevalue[20+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
					if ( (samplevalue[20+i]<lowerthresh_sync && !rising) || (samplevalue[20+i]>upperthresh_sync && rising) ) begin
						sample_triggered3[9-i] <= 1'b1; // remember the samples that caused the trigger
					end
					else sample_triggered3[9-i] <= 1'b0;
					
					if ( (samplevalue[30+i]<lowerthresh_sync && rising) || (samplevalue[30+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
					if ( (samplevalue[30+i]<lowerthresh_sync && !rising) || (samplevalue[30+i]>upperthresh_sync && rising) ) begin
						sample_triggered4[9-i] <= 1'b1; // remember the samples that caused the trigger
					end
					else sample_triggered4[9-i] <= 1'b0;
				end
				end				
				else begin // two channel
					if (triggerchan_sync==1'b0) begin // channel 0 triggering
						for (i=0;i<10;i=i+1) begin
							if ( (samplevalue[ 0+i]<lowerthresh_sync && rising) || (samplevalue[ 0+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
							if ( (samplevalue[ 0+i]<lowerthresh_sync && !rising) || (samplevalue[ 0+i]>upperthresh_sync && rising) ) begin
								sample_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
							end
							else sample_triggered[9-i] <= 1'b0;
							
							if ( (samplevalue[20+i]<lowerthresh_sync && rising) || (samplevalue[20+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
							if ( (samplevalue[20+i]<lowerthresh_sync && !rising) || (samplevalue[20+i]>upperthresh_sync && rising) ) begin
								sample_triggered3[9-i] <= 1'b1; // remember the samples that caused the trigger
							end
							else sample_triggered3[9-i] <= 1'b0;
							
							sample_triggered2[9-i] <= 1'b0;
							sample_triggered4[9-i] <= 1'b0;
						end
					end
					else begin // channel 1 triggering
						for (i=0;i<10;i=i+1) begin
							if ( (samplevalue[10+i]<lowerthresh_sync && rising) || (samplevalue[10+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
							if ( (samplevalue[10+i]<lowerthresh_sync && !rising) || (samplevalue[10+i]>upperthresh_sync && rising) ) begin
								sample_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
							end
							else sample_triggered2[9-i] <= 1'b0;
							
							if ( (samplevalue[30+i]<lowerthresh_sync && rising) || (samplevalue[30+i]>upperthresh_sync && !rising) ) acqstate <= 8'd2;
							if ( (samplevalue[30+i]<lowerthresh_sync && !rising) || (samplevalue[30+i]>upperthresh_sync && rising) ) begin
								sample_triggered4[9-i] <= 1'b1; // remember the samples that caused the trigger
							end
							else sample_triggered4[9-i] <= 1'b0;
							
							sample_triggered[9-i] <= 1'b0;
							sample_triggered3[9-i] <= 1'b0;
						end
					end
				end
			end
		end

		2 : begin // ready for second part of trigger condition to be met
			if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
			else begin
			  firingsecondstep=1'b0;
			  
			  for (i=0;i<10;i=i+1) begin
					if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && 
						( (samplevalue[ 0+i]<lowerthresh_sync && !rising) || (samplevalue[ 0+i]>upperthresh_sync && rising) ) ) begin
						firingsecondstep=1'b1;
						if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
							 sample_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
							 downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
						end
					end
					if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && 
						( (samplevalue[10+i]<lowerthresh_sync && !rising) || (samplevalue[10+i]>upperthresh_sync && rising) ) ) begin
						firingsecondstep=1'b1;
						if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
							 sample_triggered2[10+9-i] <= 1'b1; // remember the samples that caused the trigger
							 downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
						end
					end
					if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && 
						( (samplevalue[20+i]<lowerthresh_sync && !rising) || (samplevalue[20+i]>upperthresh_sync && rising) ) ) begin
						firingsecondstep=1'b1;
						if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
							 sample_triggered3[10+9-i] <= 1'b1; // remember the samples that caused the trigger
							 downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
						end
					end
					if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && 
						( (samplevalue[30+i]<lowerthresh_sync && !rising) || (samplevalue[30+i]>upperthresh_sync && rising) ) ) begin
						firingsecondstep=1'b1;
						if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
							 sample_triggered4[10+9-i] <= 1'b1; // remember the samples that caused the trigger
							 downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
						end
					end
			  end
			  
    			if (firingsecondstep) begin
					if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) tot_counter <= tot_counter + 8'd1;
					if (tot_counter>=triggerToT_sync && (triggerToT_sync==0 || downsamplemergingcounter==downsamplemergingcounter_triggered) ) begin
						 ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
						 lvdsout_trig <= 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
						 lvdsout_trig_b <= 1'b1; // and backwards
						 acqstate <= 8'd250;
					end
			   end
				
			end
		end

		5 : begin // external trigger, like from another board (3)
            if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
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
			// triggertype == 4, force waveform capture
			ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
			lvdsout_trig <= 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
			lvdsout_trig_b <= 1'b1; // and backwards
			downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
			acqstate <= 8'd250;
		end
		
		7: begin // external trigger, like from the back panel SMA
           if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
			  else begin
					if (exttrigin) begin
                    ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
                    lvdsout_trig <= 1'b1; // tell the others forwards
                    lvdsout_trig_b <= 1'b1; // tell the others backwards
                    sample_triggered <= 0; // we didn't measure the trigger edge - going to be some jitter unfortunately
                    downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that we were on when we got this trigger
                    acqstate <= 8'd250;
                end
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
			
			auxtrigout<=1; // send to back panel, trigger out
			
			if (triggerphase == -9'd1) begin // just once
				triggerphase = 0;
				
				// see whether the sample_triggered's have a 0 in the first 10 bits
				st1zero=0;
				st2zero=0;
				st3zero=0;
				st4zero=0;
				for (int i=0; i<10; i++) begin
					if (sample_triggered [i]==0) st1zero=1;
					if (sample_triggered2[i]==0) st2zero=1;
					if (sample_triggered3[i]==0) st3zero=1;
					if (sample_triggered4[i]==0) st4zero=1;
				end
				
				// find the best sample_triggered that has a zero, and use it for the output sample_triggered
				// usually that will determine the triggerphase as well
				if (st1zero) sample_triggered_max_val1 = sample_triggered [9:0];
				if (st2zero && sample_triggered2[9:0] > sample_triggered_max_val1) begin
					sample_triggered_max_val1 = sample_triggered2[9:0];
					triggerphase[1:0] = 2'd1;
				end
				if (st3zero && sample_triggered3[9:0] > sample_triggered_max_val1) begin
					sample_triggered_max_val1 = sample_triggered3[9:0];
					triggerphase[1:0] = 2'd2;
				end
				if (st4zero && sample_triggered4[9:0] > sample_triggered_max_val1) begin
					sample_triggered_max_val1 = sample_triggered4[9:0];
					triggerphase[1:0] = 2'd3;
				end
				if (triggerphase[1:0]==2'd1) sample_triggered[9:0] <= sample_triggered2[9:0];
				else if (triggerphase[1:0]==2'd2) sample_triggered[9:0] <= sample_triggered3[9:0];
				else if (triggerphase[1:0]==2'd3) sample_triggered[9:0] <= sample_triggered4[9:0];
				
				// correct triggerphase in the rare case that the best one would have been all zeros in the first 10 bits
				sample_triggered_max_val1 = sample_triggered [9:0];
				if (sample_triggered2[9:0] > sample_triggered_max_val1) begin
					sample_triggered_max_val1 = sample_triggered2[9:0];
					triggerphase[3:2] = 2'd1;
				end
				if (sample_triggered3[9:0] > sample_triggered_max_val1) begin
					sample_triggered_max_val1 = sample_triggered3[9:0];
					triggerphase[3:2] = 2'd2;
				end
				if (sample_triggered4[9:0] > sample_triggered_max_val1) begin
					sample_triggered_max_val1 = sample_triggered4[9:0];
					triggerphase[3:2] = 2'd3;
				end

				// find the best sample_triggered to use for when the rising edge is in the last 10 bits
				sample_triggered_max_val2 = sample_triggered[19:10];
				if (sample_triggered2[19:10] > sample_triggered_max_val2) begin
					sample_triggered_max_val2 = sample_triggered2[19:10];
					triggerphase[5:4] = 2'd1;
				end
				if (sample_triggered3[19:10] > sample_triggered_max_val2) begin
					sample_triggered_max_val2 = sample_triggered3[19:10];
					triggerphase[5:4] = 2'd2;
				end
				if (sample_triggered4[19:10] > sample_triggered_max_val2) begin
					sample_triggered_max_val2 = sample_triggered4[19:10];
					triggerphase[5:4] = 2'd3;
				end
				if (triggerphase[5:4]==2'd1) sample_triggered[19:10] <= sample_triggered2[19:10];
				else if (triggerphase[5:4]==2'd2) sample_triggered[19:10] <= sample_triggered3[19:10];
				else if (triggerphase[5:4]==2'd3) sample_triggered[19:10] <= sample_triggered4[19:10];
			end
			
		end

		251 : begin // ready to be read out, not writing into RAM
			auxtrigout<=0; // send to back panel, trigger out done
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
reg [5:0]	channel2 = 0; // the "channel" we are sending out for two-channel mode, to reorder samples
reg [5:0]	spicscounter = 0;
reg [7:0] pllclock_counter = 0; // for clock phase
reg [7:0] scanclk_cycles = 0;
reg [9:0] ram_preoffset = 0;
integer overrange_counter[4];
reg [15:0]	probecompcounter = 0;
reg send_color = 1;
reg [3:0] flashstate=0, flashbusycounter=0;
reg [31:0] o_tdatatemp = 0;
reg clkstrprob = 0;
reg [7:0] boardin_sync = 0;

always @ (posedge clk) begin
	acqstate_sync <= acqstate;
	eventcounter_sync <= eventcounter;
	ram_address_triggered_sync <= ram_address_triggered;
	sample_triggered_sync <= sample_triggered;
	downsamplemergingcounter_triggered_sync <= downsamplemergingcounter_triggered;
	triggerphase_sync <= triggerphase;
	boardin_sync <= boardin;

	for (i=0;i<4;i=i+1)
	    if (overrange[i]) overrange_counter[i] <= overrange_counter[i] + 1;
end

// Sequence of register writes that triggers sending 4 bytes usb response.
`define SEND_STD_USB_RESPONSE \
    length <= 4; \
    o_tvalid <= 1'b1; \
    state <= TX_DATA_CONST;

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
					 if (acqstate_sync == 0 || acqstate_sync == 249) triggerlive <= 1'b1; // gets reset in INIT state
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

                // Assuming that trigger type is changed, trigger will always be re-armed;
                // For debuging current acqstate in the first byte
                o_tdata <= {8'd0, 8'd0, 8'd0, acqstate_sync};
                `SEND_STD_USB_RESPONSE
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
                else if (channel==46) begin
						 for (i=0; i<10; i++) begin
							o_tdatatemp[i] = lvdsbitsin[14*(20+i)+13]; //samplestr 20-29
							o_tdatatemp[i+16] = lvdsbitsin[14*(30+i)+13]; //samplestr 30-39
						 end
						 for (i=0; i<6; i++) begin
							o_tdatatemp[i+10] = 0; //padding
							o_tdatatemp[i+26] = 0; //padding
						 end
						 if (o_tdatatemp[9:0]!=0 && o_tdatatemp[9:0]!=1 && o_tdatatemp[9:0]!=2 && o_tdatatemp[9:0]!=4 && o_tdatatemp[9:0]!=8 && o_tdatatemp[9:0]!=16 &&
							  o_tdatatemp[9:0]!=32 && o_tdatatemp[9:0]!=64 && o_tdatatemp[9:0]!=128 && o_tdatatemp[9:0]!=256 && o_tdatatemp[9:0]!=512) begin
							  clkstrprob<=1'b1; // issue with str
						 end
						 if (o_tdatatemp[25:16]!=0 && o_tdatatemp[25:16]!=1 && o_tdatatemp[25:16]!=2 && o_tdatatemp[25:16]!=4 && o_tdatatemp[25:16]!=8 && o_tdatatemp[25:16]!=16 &&
							  o_tdatatemp[25:16]!=32 && o_tdatatemp[25:16]!=64 && o_tdatatemp[25:16]!=128 && o_tdatatemp[25:16]!=256 && o_tdatatemp[25:16]!=512) begin
							  clkstrprob<=1'b1; // issue with str
						 end
						 o_tdata <= o_tdatatemp;
					 end
                else if (channel==44) begin
						 for (i=0; i<10; i++) begin
							o_tdatatemp[i] = lvdsbitsin[14*(0+i)+13]; //samplestr 0-9
							o_tdatatemp[i+16] = lvdsbitsin[14*(10+i)+13]; //samplestr 10-19
						 end
						 for (i=0; i<6; i++) begin
							o_tdatatemp[i+10] = 0; //padding
							o_tdatatemp[i+26] = 0; //padding
						 end
						 if (o_tdatatemp[9:0]!=0 && o_tdatatemp[9:0]!=1 && o_tdatatemp[9:0]!=2 && o_tdatatemp[9:0]!=4 && o_tdatatemp[9:0]!=8 && o_tdatatemp[9:0]!=16 &&
							  o_tdatatemp[9:0]!=32 && o_tdatatemp[9:0]!=64 && o_tdatatemp[9:0]!=128 && o_tdatatemp[9:0]!=256 && o_tdatatemp[9:0]!=512) begin
							  clkstrprob<=1'b1; // issue with str
						 end
						 if (o_tdatatemp[25:16]!=0 && o_tdatatemp[25:16]!=1 && o_tdatatemp[25:16]!=2 && o_tdatatemp[25:16]!=4 && o_tdatatemp[25:16]!=8 && o_tdatatemp[25:16]!=16 &&
							  o_tdatatemp[25:16]!=32 && o_tdatatemp[25:16]!=64 && o_tdatatemp[25:16]!=128 && o_tdatatemp[25:16]!=256 && o_tdatatemp[25:16]!=512) begin
							  clkstrprob<=1'b1; // issue with str
						 end
						 o_tdata <= o_tdatatemp;
					 end
                else if (channel==42) begin
						 for (i=0; i<10; i++) begin
							o_tdatatemp[i] = lvdsbitsin[14*(20+i)+12]; //sampleclk 20-29
							o_tdatatemp[i+16] = lvdsbitsin[14*(30+i)+12]; //sampleclk 30-39
						 end
						 for (i=0; i<6; i++) begin
							o_tdatatemp[i+10] = 0; //padding
							o_tdatatemp[i+26] = 0; //padding
						 end
						 if (o_tdatatemp[9:0]!=10'd341 && o_tdatatemp[9:0]!=10'd682) begin
							clkstrprob<=1'b1; // issue with clk
						 end
						 if (o_tdatatemp[25:16]!=10'd341 && o_tdatatemp[9:0]!=10'd682) begin
							clkstrprob<=1'b1; // issue with clk
						 end
						 o_tdata <= o_tdatatemp;
					 end
                else if (channel==40) begin
                   for (i=0; i<10; i++) begin
							o_tdatatemp[i] = lvdsbitsin[14*(20+i)+12]; //sampleclk 0-9
							o_tdatatemp[i+16] = lvdsbitsin[14*(30+i)+12]; //sampleclk 10-19
						 end
						 for (i=0; i<6; i++) begin
							o_tdatatemp[i+10] = 0; //padding
							o_tdatatemp[i+26] = 0; //padding
						 end
						 if (o_tdatatemp[9:0]!=10'd341 && o_tdatatemp[9:0]!=10'd682) begin
							clkstrprob<=1'b1; // issue with clk
						 end
						 if (o_tdatatemp[25:16]!=10'd341 && o_tdatatemp[9:0]!=10'd682) begin
							clkstrprob<=1'b1; // issue with clk
						 end
						 o_tdata <= o_tdatatemp;
						 clkstrprob <= 1'b0; // assume no clkstr problems, will check in next steps
					 end
                else begin // data
						 if (channeltype[0]==1'b0) begin // single channel mode
							o_tdata  <= {lvdsbitsin[14*(38-channel) +: 12], 4'd0, lvdsbitsin[14*(39-channel) +: 12], 4'd0};
						 end
						 else begin // two channel mode
							o_tdata  <= {lvdsbitsin[14*(38-channel2) +: 12], 4'd0, lvdsbitsin[14*(39-channel2) +: 12], 4'd0};
						 end
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
