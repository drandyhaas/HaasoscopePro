module phase_detector (
   input clk_fast, // clk to count with
   input stop,     // echo signal
   input start,    // signal
   output reg [6:0] phase_diff // clk ticks between start and stop
);

reg counting = 0;
always @(posedge clk_fast) begin
   if (start && !stop) begin
      counting = 1;
      phase_diff = 0;
   end
   if (stop) begin
      counting = 0;
   end
   
   if (counting) phase_diff = phase_diff + 6'd1;
end

endmodule
