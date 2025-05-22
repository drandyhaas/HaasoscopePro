	component pll10_3 is
		port (
			refclk   : in  std_logic := 'X'; -- clk
			locked   : out std_logic;        -- export
			rst      : in  std_logic := 'X'; -- reset
			outclk_0 : out std_logic         -- clk
		);
	end component pll10_3;

	u0 : component pll10_3
		port map (
			refclk   => CONNECTED_TO_refclk,   --  refclk.clk
			locked   => CONNECTED_TO_locked,   --  locked.export
			rst      => CONNECTED_TO_rst,      --   reset.reset
			outclk_0 => CONNECTED_TO_outclk_0  -- outclk0.clk
		);

