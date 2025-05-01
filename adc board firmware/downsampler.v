// handles the raw LVDS inputs and orders them into samples, also does downsampling
module downsampler
(
   input wire clklvds, // clk1, runs at LVDS bit rate (ADC clk input rate) / 2
   input wire [139:0] lvds1bits, lvds2bits, lvds3bits, lvds4bits,// rx_in[0] drives data to rx_out[(J-1)..0], rx_in[1] drives data to the next J number of bits on rx_out
   output reg [559:0] lvdsbitsout, //output bits to fifo
   
   input integer     downsamplecounter,
   output reg signed [11:0] samplevalue[40],
   
   // synced inputs from other clocks
   input reg [7:0]   channeltype, 
   input reg [7:0]   downsamplemerging,
   input reg         highres, 
   input reg [4:0]   downsample
);

// variables in clklvds domain, writing into the RAM buffer
reg signed [11:0] samplevalue2[40];
reg signed [11:0] samplevaluereg[40];
reg signed [5+11:0] highressamplevalue[20];
reg signed [47:0] highressamplevalueavg0 = 0, highressamplevalueavgtemp0 = 0;
reg signed [47:0] highressamplevalueavg1 = 0, highressamplevalueavgtemp1 = 0;
reg [1:0]   sampleclkstr[40];

// synced inputs from other clocks
reg [7:0]   channeltype_sync;
reg [7:0]   downsamplemerging_sync;
reg         highres_sync;
reg [4:0]   downsample_sync;

// this is all for downsample merging, since 40 samples come in each clklvds tick
integer i, j;
always @ (posedge clklvds) begin

   channeltype_sync       <= channeltype;
   downsamplemerging_sync <= downsamplemerging;
   highres_sync           <= highres;
   downsample_sync        <= downsample;

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

endmodule
