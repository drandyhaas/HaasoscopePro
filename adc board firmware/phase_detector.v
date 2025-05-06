module phase_detector (
   input clk_fast, // clk to count with
   input stop,     // echo signal
   input start,    // signal
   output reg [15:0] phase_diff // clk ticks between start and stop
);

reg counting = 0;
always @(posedge clk_fast) begin
   if (start && !stop) begin
      counting = 1;
      phase_diff[7:0] = 0;
   end
   if (stop) begin
      counting = 0;
   end
   
   if (counting) phase_diff[7:0] = phase_diff[7:0] + 8'd1;
end

reg counting2 = 0;
always @(posedge clk_fast) begin
   if (start && !stop) begin
      counting2 = 1;
      phase_diff[15:8] = 0;
   end
   if (stop) begin
      counting2 = 0;
   end
   
   if (counting2) phase_diff[15:8] = phase_diff[15:8] + 8'd1;
end

endmodule
