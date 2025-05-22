	component clkctrl10 is
		port (
			inclk  : in  std_logic := 'X'; -- clk
			ena    : in  std_logic := 'X'; -- export
			outclk : out std_logic         -- clk
		);
	end component clkctrl10;

	u0 : component clkctrl10
		port map (
			inclk  => CONNECTED_TO_inclk,  --  inclk.clk
			ena    => CONNECTED_TO_ena,    --    ena.export
			outclk => CONNECTED_TO_outclk  -- outclk.clk
		);

