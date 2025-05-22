	component pll10_1 is
		port (
			refclk           : in  std_logic                    := 'X';             -- clk
			locked           : out std_logic;                                       -- export
			rst              : in  std_logic                    := 'X';             -- reset
			scanclk          : in  std_logic                    := 'X';             -- clk
			phase_en         : in  std_logic                    := 'X';             -- phase_en
			updn             : in  std_logic                    := 'X';             -- updn
			cntsel           : in  std_logic_vector(4 downto 0) := (others => 'X'); -- cntsel
			phase_done       : out std_logic;                                       -- phase_done
			num_phase_shifts : in  std_logic_vector(2 downto 0) := (others => 'X'); -- num_phase_shifts
			refclk1          : in  std_logic                    := 'X';             -- clk
			extswitch        : in  std_logic                    := 'X';             -- extswitch
			activeclk        : out std_logic;                                       -- activeclk
			clkbad           : out std_logic_vector(1 downto 0);                    -- clkbad
			outclk_0         : out std_logic;                                       -- clk
			outclk_1         : out std_logic;                                       -- clk
			outclk_2         : out std_logic;                                       -- clk
			outclk_3         : out std_logic                                        -- clk
		);
	end component pll10_1;

	u0 : component pll10_1
		port map (
			refclk           => CONNECTED_TO_refclk,           --           refclk.clk
			locked           => CONNECTED_TO_locked,           --           locked.export
			rst              => CONNECTED_TO_rst,              --            reset.reset
			scanclk          => CONNECTED_TO_scanclk,          --          scanclk.clk
			phase_en         => CONNECTED_TO_phase_en,         --         phase_en.phase_en
			updn             => CONNECTED_TO_updn,             --             updn.updn
			cntsel           => CONNECTED_TO_cntsel,           --           cntsel.cntsel
			phase_done       => CONNECTED_TO_phase_done,       --       phase_done.phase_done
			num_phase_shifts => CONNECTED_TO_num_phase_shifts, -- num_phase_shifts.num_phase_shifts
			refclk1          => CONNECTED_TO_refclk1,          --          refclk1.clk
			extswitch        => CONNECTED_TO_extswitch,        --        extswitch.extswitch
			activeclk        => CONNECTED_TO_activeclk,        --        activeclk.activeclk
			clkbad           => CONNECTED_TO_clkbad,           --           clkbad.clkbad
			outclk_0         => CONNECTED_TO_outclk_0,         --          outclk0.clk
			outclk_1         => CONNECTED_TO_outclk_1,         --          outclk1.clk
			outclk_2         => CONNECTED_TO_outclk_2,         --          outclk2.clk
			outclk_3         => CONNECTED_TO_outclk_3          --          outclk3.clk
		);

