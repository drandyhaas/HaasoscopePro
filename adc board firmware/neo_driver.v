// Neopixel LED state control
// Adapted from https://vivonomicon.com/2018/12/24/learning-how-to-fpga-with-neopixel-leds/
`define neo_led_num_max 2
module neo_driver
(
   input clk_over_4,
   input [23:0] neo_color[`neo_led_num_max],
   input send_color,
   output reg led
);

reg [2:0] neostate;
reg [1:0] npxc;
reg [12:0] lpxc;
reg [7:0] neobits;
reg [1:0] neo_led_num;

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
       if (neo_led_num == `neo_led_num_max) begin
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
     if (neostate == 0 || neostate == 1 || neostate == 2) led = 1;
     else if (neostate == 3 || neostate == 6) led = 0;
   end
   else begin
     if (neostate == 0) led = 1;
     else if (neostate == 1 || neostate == 2 || neostate == 3 || neostate == 6) led = 0;
   end
end

endmodule
