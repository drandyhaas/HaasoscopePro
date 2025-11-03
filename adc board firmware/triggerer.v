// handles triggering and storing of samples into RAM
module triggerer(
   input clklvds,
   input rstn,
   output reg        ram_wr=0,
   output reg [9:0]  ram_wr_address=0,
   input signed [11:0] samplevalue[40],
   input wire lvdsin_trig,
   output reg lvdsout_trig=0,
   input wire lvdsin_trig_b,
   output reg lvdsout_trig_b=0,
   input exttrigin,
   output auxout,
   output reg led, // controls LED2
   
   output reg [7:0]  acqstate,
   output integer    eventcounter,
   output reg [9:0]  ram_address_triggered,
   output reg [19:0] sample_triggered,
   output reg [7:0]  downsamplemergingcounter_triggered,
   output reg [8:0]  triggerphase,
   output integer    downsamplecounter,
   output integer    eventtime,
   
   output reg [19:0]  sample1_triggered=0,
   output reg [19:0]  sample2_triggered=0,
   output reg [19:0]  sample3_triggered=0,
   output reg [19:0]  sample4_triggered=0,

   // synced inputs from other clocks
   input reg signed [23:0]  lowerthresh,   // [11:0] = threshold, [23:12] = threshold2
   input reg signed [23:0]  upperthresh,   // [11:0] = threshold, [23:12] = threshold2
   input reg [15:0]  lengthtotake,
   input reg [15:0]  prelengthtotake,
   input reg         triggerlive,
   input reg         didreadout,
   input reg [7:0]   triggertype,
   input reg [7:0]   triggerToT,
   input reg         triggerchan,
   input reg         dorolling,
   input reg [3:0]   auxoutselector,
   input reg [7:0]   channeltype,
   input reg [7:0]   downsamplemerging,
   input reg [4:0]   downsample,
   input reg [1:0]   firstlast, // 1 for first, 2 for last, 0 for neither
   
   input reg [7:0]   trigger_options [2] // 0: trigger_delay: clock ticks to wait before firing trigger (going to acqstate 250)
                                         // 1: trigger_holdoff: clock ticks of quiet before firing trigger
   
);

//exttrigin is boardin[4], SMA in on back panel
assign led = exttrigin;

//auxout is debugout[10], SMA out on back panel
assign auxout = 
   (auxoutselector_sync==0) ? 1'b0: 
   (auxoutselector_sync==1) ? auxtrigout : 
   (auxoutselector_sync==2) ? eventtimecounter[15] : 
   (auxoutselector_sync==3) ? clklvds : 
   1'b0;

integer     rollingtriggercounter = 0;
reg [7:0]   tot_counter = 0;
reg [7:0]   trigger_delay_counter = 0, trigger_holdoff_counter = 0;
reg [7:0]   downsamplemergingcounter = 0;
reg [15:0]  triggercounter = 0;
reg         firingsecondstep = 0;
reg         runt_reject = 0;
reg [7:0]   current_active_trigger_type = 0;
reg         rising = 0;
reg         auxtrigout = 0;
integer     eventtimecounter = 0;
reg [1:0]   forwardsbackwardsexttrig = 0;
reg thebit, gotzerobit;
reg [3:0]   extra_trigger_delay = 0;

// synced inputs from other clocks
reg signed [11:0] lowerthresh_sync = 0;
reg signed [11:0] upperthresh_sync = 0;
reg signed [11:0] lowerthresh2_sync = 0;
reg signed [11:0] upperthresh2_sync = 0;
reg [15:0]  lengthtotake_sync = 0;
reg [15:0]  prelengthtotake_sync= 0;
reg [ 7:0]  triggertype_sync = 0;
reg [ 7:0]  triggerToT_sync = 0;
reg [ 7:0]  trigger_delay_sync = 0, trigger_holdoff_sync = 0;
reg         triggerchan_sync = 0;
reg         dorolling_sync = 0;
reg [3:0]   auxoutselector_sync = 0;
reg [ 7:0]  channeltype_sync = 0;
reg [7:0]   downsamplemerging_sync = 0;
reg [4:0]   downsample_sync = 0;
reg         triggerlive_sync = 0;
reg         didreadout_sync = 0;
reg         exttrigin_sync = 0, exttrigin_sync_last = 0, exttrig_rising = 0;
reg         lvdsin_trig_sync = 0, lvdsin_trig_b_sync = 0;
reg [1:0]   firstlast_sync = 0;

// Macro to reject trigger and reset to state 1
`define REJECT_RUNT \
   runt_reject=1'b1; \
   trigger_holdoff_counter <= 0; \
   tot_counter <= 0; \
   downsamplemergingcounter_triggered <= -8'd1; \
   sample1_triggered <= 0; \
   sample2_triggered <= 0; \
   sample3_triggered <= 0; \
   sample4_triggered <= 0; \
   acqstate <= 8'd1;

// this drives the trigger
integer i, j;
always @ (posedge clklvds) begin
   
   triggerlive_sync       <= triggerlive;
   lengthtotake_sync      <= lengthtotake;
   prelengthtotake_sync   <= prelengthtotake;
   triggertype_sync       <= triggertype;
   didreadout_sync        <= didreadout;
   lowerthresh_sync       <= lowerthresh[11:0];   // Lower 12 bits = threshold
   upperthresh_sync       <= upperthresh[11:0];   // Lower 12 bits = threshold
   lowerthresh2_sync      <= lowerthresh[23:12];  // Upper 12 bits = threshold2
   upperthresh2_sync      <= upperthresh[23:12];  // Upper 12 bits = threshold2
   triggerToT_sync        <= triggerToT;
   trigger_delay_sync     <= trigger_options[0];
   trigger_holdoff_sync   <= trigger_options[1];
   triggerchan_sync       <= triggerchan;
   dorolling_sync         <= dorolling;
   auxoutselector_sync    <= auxoutselector;
   channeltype_sync       <= channeltype;
   downsamplemerging_sync <= downsamplemerging;
   downsample_sync        <= downsample;
   exttrigin_sync         <= exttrigin;
   exttrigin_sync_last    <= exttrigin_sync; // remember for next cycle
   eventtimecounter       <= eventtimecounter + 1;
   lvdsin_trig_sync       <= lvdsin_trig;
   lvdsin_trig_b_sync     <= lvdsin_trig_b;
   firstlast_sync         <= firstlast;

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
         downsamplecounter <= downsamplecounter + 1;
         ram_wr <= 1'b0;
      end
   end
   
   if (lvdsin_trig_sync && firstlast_sync!=2'd1) begin // don't pay attention if we're the first board
      lvdsout_trig = 1'b1;
   end
   else lvdsout_trig = 1'b0;
   if (lvdsin_trig_b_sync && firstlast_sync!=2'd2) begin // don't pay attention if we're the last board
      lvdsout_trig_b = 1'b1;
   end
   else lvdsout_trig_b = 1'b0;
   
   // rolling trigger
   if (dorolling_sync && acqstate>0 && acqstate<200) begin
      if (rollingtriggercounter==8000000) begin // ~10 Hz
         sample_triggered = 0;
         downsamplemergingcounter_triggered <= downsamplemergingcounter;
         ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
         lvdsout_trig = 1'b1; // tell the others
         lvdsout_trig_b = 1'b1;
         acqstate <= 8'd250; // trigger
      end
      else rollingtriggercounter <= rollingtriggercounter + 1;
   end

   case (acqstate)
   0 : begin // ready
      auxtrigout <= 0;
      tot_counter <= 0;
      trigger_holdoff_counter <= 0;
      extra_trigger_delay <= 0;
      sample_triggered = 0;
      sample1_triggered <= 0;
      sample2_triggered <= 0;
      sample3_triggered <= 0;
      sample4_triggered <= 0;
      gotzerobit <= 0;
      triggerphase <= -9'd1;
      forwardsbackwardsexttrig <= 2'b11; // tell state 250 to fire forwards and backwards for one extra clock tick after trigger
      downsamplemergingcounter_triggered <= -8'd1;
      exttrig_rising <= 0;
      downsamplecounter <= 1;
      downsamplemergingcounter <= 1;
      triggercounter <= 0; // set to 0 as this register will be used to count in pre-aquisition
      trigger_delay_counter <= 8'd1; // set to 1 so it will go to 250 right away if trigger_delay is 1... we already had a 1 clock tick delay from going to 242
      current_active_trigger_type <= triggertype_sync;
      case(triggertype_sync)
         8'd0 : ; // disable conditional triggering
         default: begin
            if (triggerlive_sync) acqstate <= 8'd200; // go to pre-aquisition
         end
      endcase
   end

   200 : begin // pre-aquisition
      if (current_active_trigger_type != triggertype_sync) acqstate <= 8'd0; // go back to initial state
      else if (triggercounter<prelengthtotake_sync) begin
         if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) begin
            triggercounter <= triggercounter + 16'd1;
         end
      end
      else begin
         triggercounter <= 0; // will also use this to keep recording enough samples after the trigger, so reset
         
         if (current_active_trigger_type==1) rising<=1'b1;
         else rising<=1'b0;

         case(current_active_trigger_type)
            8'd1 : acqstate <= 8'd1; // threshold trigger rising edge
            8'd2 : acqstate <= 8'd1; // threshold trigger falling edge
            8'd3 : acqstate <= 8'd5; // external trigger from another board over LVDS
            8'd4 : acqstate <= 8'd6; // auto trigger (forces waveform capture unconditionally)
            8'd5 : begin
               acqstate <= 8'd7; // external trigger, like from back panel SMA
               extra_trigger_delay = 4'd3;
            end
            8'd30: acqstate <= 8'd5; // external trigger from another board over LVDS, with echo sent back
         endcase
      end
   end

   // edge trigger (1)
   1 : begin // ready for first part of trigger condition to be met: be below the threshold at some sample if rising edge, or above the threshold at some sample if falling edge
      if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
      else begin
         for (i=0;i<10;i=i+1) begin
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && // if in single channel mode OR triggering on channel 0
               ( (samplevalue[ 0+i]<lowerthresh_sync && rising) || (samplevalue[ 0+i]>upperthresh_sync && !rising) ) ) acqstate <= 8'd2;
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && // see if we actually also pass the second step in this step (there are 40 samples per clock tick!)
               ( (samplevalue[ 0+i]<lowerthresh_sync && !rising) || (samplevalue[ 0+i]>upperthresh_sync && rising) ) ) sample1_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
            else sample1_triggered[9-i] <= 1'b0;
            
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && // if in single channel mode OR triggering on channel 1
               ( (samplevalue[10+i]<lowerthresh_sync && rising) || (samplevalue[10+i]>upperthresh_sync && !rising) ) ) acqstate <= 8'd2;
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && // see if we actually also pass the second step in this step (there are 40 samples per clock tick!)
               ( (samplevalue[10+i]<lowerthresh_sync && !rising) || (samplevalue[10+i]>upperthresh_sync && rising) ) ) sample2_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
            else sample2_triggered[9-i] <= 1'b0;
            
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && // if in single channel mode OR triggering on channel 0
               ( (samplevalue[20+i]<lowerthresh_sync && rising) || (samplevalue[20+i]>upperthresh_sync && !rising) ) ) acqstate <= 8'd2;
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && // see if we actually also pass the second step in this step (there are 40 samples per clock tick!)
               ( (samplevalue[20+i]<lowerthresh_sync && !rising) || (samplevalue[20+i]>upperthresh_sync && rising) ) ) sample3_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
            else sample3_triggered[9-i] <= 1'b0;
            
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && // if in single channel mode OR triggering on channel 1
               ( (samplevalue[30+i]<lowerthresh_sync && rising) || (samplevalue[30+i]>upperthresh_sync && !rising) ) ) acqstate <= 8'd2;
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && // see if we actually also pass the second step in this step (there are 40 samples per clock tick!)
               ( (samplevalue[30+i]<lowerthresh_sync && !rising) || (samplevalue[30+i]>upperthresh_sync && rising) ) ) sample4_triggered[9-i] <= 1'b1; // remember the samples that caused the trigger
            else sample4_triggered[9-i] <= 1'b0;
         end
      end
   end
   2 : begin // ready for second part of trigger condition to be met: be above the threshold at some sample if rising edge, or below the threshold at some sample if falling edge
      if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
      else begin
         firingsecondstep=1'b0;
         runt_reject=1'b0; // Track if we reject due to runt pulse in this clock cycle
         for (i=0;i<10;i=i+1) begin
         
            // FIRST: Check if ANY sample exceeds the second threshold - if so, reject immediately (runt pulse rejection)
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) &&
               ( (samplevalue[ 0+i]<lowerthresh2_sync && !rising) || (samplevalue[ 0+i]>upperthresh2_sync && rising) ) ) begin
               // Exceeded second threshold - reject and go back to state 1
               `REJECT_RUNT
            end
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) &&
               ( (samplevalue[10+i]<lowerthresh2_sync && !rising) || (samplevalue[10+i]>upperthresh2_sync && rising) ) ) begin
               `REJECT_RUNT
            end
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) &&
               ( (samplevalue[20+i]<lowerthresh2_sync && !rising) || (samplevalue[20+i]>upperthresh2_sync && rising) ) ) begin
               `REJECT_RUNT
            end
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) &&
               ( (samplevalue[30+i]<lowerthresh2_sync && !rising) || (samplevalue[30+i]>upperthresh2_sync && rising) ) ) begin
               `REJECT_RUNT
            end

            // SECOND: Check if we passed the first threshold (runt rejection already handled above)
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && // if in single channel mode OR triggering on channel 0
               ( (samplevalue[ 0+i]<lowerthresh_sync && !rising) || (samplevalue[ 0+i]>upperthresh_sync && rising) ) ) begin // see if we pass
               firingsecondstep=1'b1;
               if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
                  sample1_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
                  downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
               end
            end
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && // if in single channel mode OR triggering on channel 1
               ( (samplevalue[10+i]<lowerthresh_sync && !rising) || (samplevalue[10+i]>upperthresh_sync && rising) ) ) begin // see if we pass
               firingsecondstep=1'b1;
               if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
                  sample2_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
                  downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
               end
            end
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b0) && // if in single channel mode OR triggering on channel 0
               ( (samplevalue[20+i]<lowerthresh_sync && !rising) || (samplevalue[20+i]>upperthresh_sync && rising) ) ) begin // see if we pass
               firingsecondstep=1'b1;
               if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
                  sample3_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
                  downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
               end
            end
            if ( (channeltype_sync[0]==1'b0 || triggerchan_sync==1'b1) && // if in single channel mode OR triggering on channel 1
               ( (samplevalue[30+i]<lowerthresh_sync && !rising) || (samplevalue[30+i]>upperthresh_sync && rising) ) ) begin // see if we pass
               firingsecondstep=1'b1;
               if (downsamplemergingcounter_triggered == -8'd1) begin // just the first time
                  sample4_triggered[10+9-i] <= 1'b1; // remember the samples that caused the trigger
                  downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
               end
            end
         end
         if (firingsecondstep && !runt_reject) begin // we decided we passed, and didn't reject due to runt pulse in same clock cycle
            if (trigger_holdoff_counter >= trigger_holdoff_sync) begin // require holdoff to be met
               if (downsamplecounter[downsample_sync] && downsamplemergingcounter==downsamplemerging_sync) tot_counter <= tot_counter + 8'd1; // count for ToT
               if (tot_counter>=triggerToT_sync && (triggerToT_sync==0 || downsamplemergingcounter==downsamplemergingcounter_triggered) ) begin // if triggerToT_sync is 0 then downsamplemergingcounter_triggered was set to downsamplemergingcounter in this clock tick... we just don't know it yet because of <=
                  if (trigger_delay_sync==8'd0) begin // if we're not doing trigger delay, fire immediately
                     ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
                     lvdsout_trig = 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
                     lvdsout_trig_b = 1'b1; // and backwards
                     acqstate <= 8'd250; // fire trigger
                  end
                  else acqstate <= 8'd242; // wait, then fire trigger
               end
            end
            else begin
               // not enough holdoff, reset and go back
               trigger_holdoff_counter <= 0;
               downsamplemergingcounter_triggered <= -8'd1;
               sample1_triggered <= 0;
               sample2_triggered <= 0;
               sample3_triggered <= 0;
               sample4_triggered <= 0;
               acqstate <= 8'd1;
            end
         end
         else begin
            tot_counter<=0; // if we didn't pass, reset the counter
            
            // count how long we fail to pass the threshold for (but don't roll over)
            if (downsamplecounter[downsample_sync] && (downsamplemergingcounter==downsamplemerging_sync) && (trigger_holdoff_counter!=8'hff) ) trigger_holdoff_counter <= trigger_holdoff_counter + 8'd1;
         end
      end
   end

   5 : begin // external trigger from another board (3, or 30 for extra echos)
      if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
      else begin
         if (lvdsin_trig_sync && firstlast_sync!=2'd1) begin // don't pay attention if we're the first board
            sample_triggered = 0; // not used, since we didn't measure the trigger edge - will take it from the board that caused the trigger
            downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that we were on when we got this trigger
            ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
            if (current_active_trigger_type==30) lvdsout_trig_b = 1; // echo back, if we're supposed to, for measuring time offset
            forwardsbackwardsexttrig <= 2'b01; // tell next state to only fire forwards still
            acqstate <= 8'd250;
         end
         if (lvdsin_trig_b_sync && firstlast_sync!=2'd2) begin // don't pay attention if we're the last board
            sample_triggered = 0; // not used, since we didn't measure the trigger edge - will take it from the board that caused the trigger
            downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that we were on when we got this trigger
            ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
            if (current_active_trigger_type==30) lvdsout_trig = 1; // echo back, if we're supposed to, for measuring time offset
            forwardsbackwardsexttrig <= 2'b10; // tell next state to only fire backwards still
            acqstate <= 8'd250;
         end
      end
   end

   6: begin // force waveform capture (4)         
      downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that caused this trigger
      sample_triggered = 0; // we didn't measure the trigger edge
      ram_address_triggered <= ram_wr_address - triggerToT_sync; // remember where the trigger happened
      lvdsout_trig = 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
      lvdsout_trig_b = 1'b1; // and backwards
      acqstate <= 8'd250;
   end
   
   7: begin // external trigger from the back panel SMA (5)
      if (current_active_trigger_type != triggertype_sync) acqstate <= 0;
      else begin
         if (exttrigin_sync && !exttrigin_sync_last) exttrig_rising=1'b1; // remember seeing rising edge of exttrigin_sync
         if (exttrig_rising && exttrigin_sync) tot_counter <= tot_counter + 8'd1; // keep counting while exttrigin is high
         else tot_counter<=0; // if exttrigin goes low, reset counter
         if (exttrig_rising && tot_counter>=triggerToT_sync) begin
            downsamplemergingcounter_triggered <= downsamplemergingcounter; // remember the downsample that we were on when we got this trigger
            sample_triggered = 0; // we didn't measure the trigger edge - going to be some jitter unfortunately
            if (trigger_delay_sync==8'd0) begin // if we're not doing trigger delay, fire immediately
               ram_address_triggered <= ram_wr_address - triggerToT_sync + extra_trigger_delay; // remember where the trigger happened, + trigger delay
               lvdsout_trig = 1'b1; // tell the others forwards
               lvdsout_trig_b = 1'b1; // tell the others backwards
               acqstate <= 8'd250; // fire trigger
            end
            else acqstate <= 8'd242; // wait, then fire trigger
         end
      end
   end

   242 : begin // wait before actually firing edge trigger, if trigger_delay>0
      if (downsamplecounter[downsample_sync]) begin // && downsamplemergingcounter==downsamplemerging_sync
         if (downsamplemergingcounter==downsamplemergingcounter_triggered) begin
            if (trigger_delay_counter>=trigger_delay_sync) begin
               ram_address_triggered <= ram_wr_address - triggerToT_sync + extra_trigger_delay; // remember where the trigger happened
               lvdsout_trig = 1'b1; // tell the others, important to do this on the right downsamplemergingcounter
               lvdsout_trig_b = 1'b1; // and backwards
               acqstate <= 8'd250; // trigger
            end
            else trigger_delay_counter <= trigger_delay_counter+8'd1;
         end
      end
   end

   250 : begin // triggered, now taking more data
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
         eventtime <= eventtimecounter; // remember the time the trigger occurred         
         if (forwardsbackwardsexttrig[0]) lvdsout_trig = 1'b1; // tell the others forwards still
         if (forwardsbackwardsexttrig[1]) lvdsout_trig_b = 1'b1; // tell the others backwards still
         
         for (int i=0; i<20; i++) begin
//            They go from top -> bottom and from left <- right
//            sample triggered 0 00001000 01111000 01111000
//            sample triggered 1 00001000 01111000 01111000
//            sample triggered 2 00001000 01111000 01111000
//            sample triggered 3 00001100 00111100 00111100
            
            for (int j=0; j<4; j++) begin
               if (channeltype_sync[0]==1'b0 || triggerchan_sync==j%2) begin
                  if (j==0) thebit = sample1_triggered[i];
                  if (j==1) thebit = sample2_triggered[i];
                  if (j==2) thebit = sample3_triggered[i];
                  if (j==3) thebit = sample4_triggered[i];
                  if (thebit==1'b0) gotzerobit = 1'b1;
                  if (gotzerobit && thebit) begin
                     gotzerobit = 1'b0;
                     triggerphase[1:0] = j[1:0];
                     sample_triggered = i[5:0];
                  end
               end
            end

         end
         
      end
      
   end

   251 : begin // ready to be read out, not writing into RAM
      auxtrigout<=0; // send to back panel, trigger out done
      triggercounter <= 0;
      if (didreadout_sync) acqstate <= 8'd0;
   end

   default : acqstate <= 8'd0;
   endcase
end

endmodule
