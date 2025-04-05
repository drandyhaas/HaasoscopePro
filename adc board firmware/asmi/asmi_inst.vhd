	component asmi is
		port (
			clkin         : in  std_logic                     := 'X';             -- clk
			read          : in  std_logic                     := 'X';             -- read
			rden          : in  std_logic                     := 'X';             -- rden
			addr          : in  std_logic_vector(23 downto 0) := (others => 'X'); -- addr
			reset         : in  std_logic                     := 'X';             -- reset
			dataout       : out std_logic_vector(7 downto 0);                     -- dataout
			busy          : out std_logic;                                        -- busy
			data_valid    : out std_logic;                                        -- data_valid
			bulk_erase    : in  std_logic                     := 'X';             -- bulk_erase
			illegal_erase : out std_logic;                                        -- illegal_erase
			write         : in  std_logic                     := 'X';             -- write
			datain        : in  std_logic_vector(7 downto 0)  := (others => 'X'); -- datain
			illegal_write : out std_logic                                         -- illegal_write
		);
	end component asmi;

	u0 : component asmi
		port map (
			clkin         => CONNECTED_TO_clkin,         --         clkin.clk
			read          => CONNECTED_TO_read,          --          read.read
			rden          => CONNECTED_TO_rden,          --          rden.rden
			addr          => CONNECTED_TO_addr,          --          addr.addr
			reset         => CONNECTED_TO_reset,         --         reset.reset
			dataout       => CONNECTED_TO_dataout,       --       dataout.dataout
			busy          => CONNECTED_TO_busy,          --          busy.busy
			data_valid    => CONNECTED_TO_data_valid,    --    data_valid.data_valid
			bulk_erase    => CONNECTED_TO_bulk_erase,    --    bulk_erase.bulk_erase
			illegal_erase => CONNECTED_TO_illegal_erase, -- illegal_erase.illegal_erase
			write         => CONNECTED_TO_write,         --         write.write
			datain        => CONNECTED_TO_datain,        --        datain.datain
			illegal_write => CONNECTED_TO_illegal_write  -- illegal_write.illegal_write
		);

