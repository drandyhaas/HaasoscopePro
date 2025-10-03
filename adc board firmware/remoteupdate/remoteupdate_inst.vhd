	component remoteupdate is
		port (
			busy        : out std_logic;                                        -- busy
			data_out    : out std_logic_vector(28 downto 0);                    -- data_out
			param       : in  std_logic_vector(2 downto 0)  := (others => 'X'); -- param
			read_param  : in  std_logic                     := 'X';             -- read_param
			reconfig    : in  std_logic                     := 'X';             -- reconfig
			reset_timer : in  std_logic                     := 'X';             -- reset_timer
			read_source : in  std_logic_vector(1 downto 0)  := (others => 'X'); -- read_source
			clock       : in  std_logic                     := 'X';             -- clk
			reset       : in  std_logic                     := 'X'              -- reset
		);
	end component remoteupdate;

	u0 : component remoteupdate
		port map (
			busy        => CONNECTED_TO_busy,        --        busy.busy
			data_out    => CONNECTED_TO_data_out,    --    data_out.data_out
			param       => CONNECTED_TO_param,       --       param.param
			read_param  => CONNECTED_TO_read_param,  --  read_param.read_param
			reconfig    => CONNECTED_TO_reconfig,    --    reconfig.reconfig
			reset_timer => CONNECTED_TO_reset_timer, -- reset_timer.reset_timer
			read_source => CONNECTED_TO_read_source, -- read_source.read_source
			clock       => CONNECTED_TO_clock,       --       clock.clk
			reset       => CONNECTED_TO_reset        --       reset.reset
		);

