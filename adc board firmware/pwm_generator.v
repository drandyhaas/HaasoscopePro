//
// Module: pwm_generator
// Description: An 8-bit PWM generator.
//
// Parameters:
//   - clk: System clock input.
//   - rst_n: Active-low asynchronous reset.
//   - duty_cycle: 8-bit value (0-255) to control the pulse width.
//   - pwm_out: The single-bit PWM output signal.
//
module pwm_generator (
    // Inputs
    input wire         clk,
    input wire         rst_n,      // Active-low reset
    input wire [7:0]   duty_cycle, // 8-bit duty cycle (0-255)

    // Output
    output wire        pwm_out
);

    // Internal 8-bit counter to track the PWM period
    reg [7:0] counter;

    // Counter logic: increments every clock cycle
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Reset the counter to zero
            counter <= 8'd0;
        end else begin
            // Increment the counter, it will automatically wrap from 255 to 0
            counter <= counter + 8'd1;
        end
    end

    // Combinational logic for PWM output
    // The output is high as long as the counter is less than the duty_cycle value.
    assign pwm_out = (counter < duty_cycle);

endmodule
