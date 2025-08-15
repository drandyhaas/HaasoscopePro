module phase_detector (
   input clk_fast, // clk to count with
   input stop,     // echo signal
   input start,    // signal
   output reg [15:0] phase_diff // clk ticks between start and stop
);

reg [7:0] phase_diff1 = 0;
always @(posedge clk_fast) begin
   if (start && !stop) begin
      phase_diff1 <= 0;
   end
   else phase_diff1 <= phase_diff1 + 8'd1;
   if (stop) begin
      phase_diff[7:0] <= phase_diff1;
   end
end

reg [7:0] phase_diff2 = 0;
always @(negedge clk_fast) begin
   if (start && !stop) begin
      phase_diff2 <= 0;
   end
   else phase_diff2 <= phase_diff2 + 8'd1;
   if (stop) begin
      phase_diff[15:8] <= phase_diff2;
   end
end

endmodule
