// (C) 2001-2022 Intel Corporation. All rights reserved.
// Your use of Intel Corporation's design tools, logic functions and other 
// software and tools, and its AMPP partner logic functions, and any output 
// files from any of the foregoing (including device programming or simulation 
// files), and any associated documentation or information are expressly subject 
// to the terms and conditions of the Intel Program License Subscription 
// Agreement, Intel FPGA IP License Agreement, or other applicable 
// license agreement, including, without limitation, that your use is for the 
// sole purpose of programming logic devices manufactured by Intel and sold by 
// Intel or its authorized distributors.  Please refer to the applicable 
// agreement for further details.


`timescale 1 ps / 1 ps

module altera_lvds_core20
#(
    parameter NUM_CHANNELS = 1,
    parameter J_FACTOR = 10,
    parameter EXTERNAL_PLL = "false",
    parameter USE_BITSLIP = "false",
    parameter TX_OUTCLOCK_NON_STD_PHASE_SHIFT = "false", 
    parameter SILICON_REV = "20nm5",
    parameter USE_DIV_RECONFIG = "false",
       
    parameter pll_input_clock_frequency = "0 ps",
    parameter pll_vco_clock_frequency = "0 ps", 
    
    parameter pll_output_clock_frequency_0 = "0.0 MHz", 
    parameter pll_output_clock_frequency_1 = "0.0 MHz", 
    parameter pll_output_clock_frequency_2 = "0.0 MHz", 
    parameter pll_output_clock_frequency_3 = "0.0 MHz", 
    parameter pll_output_clock_frequency_4 = "0.0 MHz", 
    parameter pll_output_clock_frequency_5 = "0.0 MHz", 
    parameter pll_output_clock_frequency_6 = "0.0 MHz", 
    parameter pll_output_clock_frequency_7 = "0.0 MHz", 
    parameter pll_output_clock_frequency_8 = "0.0 MHz", 
    parameter pll_output_duty_cycle_0 = 50, 
    parameter pll_output_duty_cycle_1 = 50, 
    parameter pll_output_duty_cycle_2 = 50, 
    parameter pll_output_duty_cycle_3 = 50, 
    parameter pll_output_duty_cycle_4 = 50, 
    parameter pll_output_duty_cycle_5 = 50, 
    parameter pll_output_duty_cycle_6 = 50, 
    parameter pll_output_duty_cycle_7 = 50, 
    parameter pll_output_duty_cycle_8 = 50, 
    parameter pll_output_phase_shift_0 = "0 ps", 
    parameter pll_output_phase_shift_1 = "0 ps", 
    parameter pll_output_phase_shift_2 = "0 ps", 
    parameter pll_output_phase_shift_3 = "0 ps", 
    parameter pll_output_phase_shift_4 = "0 ps", 
    parameter pll_output_phase_shift_5 = "0 ps", 
    parameter pll_output_phase_shift_6 = "0 ps", 
    parameter pll_output_phase_shift_7 = "0 ps", 
    parameter pll_output_phase_shift_8 = "0 ps", 
    
    parameter SERDES_DPA_MODE = "OFF_MODE",
    parameter ALIGN_TO_RISING_EDGE_ONLY = "false",
    parameter LOSE_LOCK_ON_ONE_CHANGE = "false",
    parameter RESET_FIFO_AT_FIRST_LOCK = "false",
    parameter ENABLE_CLOCK_PIN_MODE = "false",
    parameter LOOPBACK_MODE = 0,
    parameter NET_PPM_VARIATION = "0",
    parameter IS_NEGATIVE_PPM_DRIFT = "false",
    parameter REGISTER_PARALLEL_DATA = "false",
    parameter USE_FALLING_CLOCK_EDGE = "false", 
    parameter TX_OUTCLOCK_ENABLED = "false",
    parameter TX_OUTCLOCK_BYPASS_SERIALIZER = "false",
    parameter TX_OUTCLOCK_USE_FALLING_CLOCK_EDGE = "false", 
    parameter TX_REGISTER_CLOCK = "tx_coreclock", 
    parameter TX_OUTCLOCK_DIV_WORD = 0, 
    parameter VCO_DIV_EXPONENT = 0,
    parameter VCO_FREQUENCY = 0,
    parameter RX_BITSLIP_ROLLOVER = J_FACTOR,

    parameter pll_clk_out_en_0 = "false",
    parameter pll_clk_out_en_1 = "false",
    parameter pll_clk_out_en_2 = "false",
    parameter pll_clk_out_en_3 = "false",
    parameter pll_clk_out_en_4 = "false",
    parameter pll_clk_out_en_5 = "false",
    parameter pll_clk_out_en_6 = "false",
    parameter pll_clk_out_en_7 = "false",
    parameter pll_clk_out_en_8 = "false",
    parameter m_cnt_hi_div = 3,
    parameter m_cnt_lo_div = 2,
    parameter n_cnt_hi_div = 256,
    parameter n_cnt_lo_div = 256,
    parameter m_cnt_bypass_en = "false",
    parameter n_cnt_bypass_en = "true",
    parameter m_cnt_odd_div_duty_en = "true",
    parameter n_cnt_odd_div_duty_en = "false",
    parameter c_cnt_hi_div0 = 256,
    parameter c_cnt_lo_div0 = 256,
    parameter c_cnt_prst0 = 1,
    parameter c_cnt_ph_mux_prst0 = 4,
    parameter c_cnt_bypass_en0 = "true",
    parameter c_cnt_odd_div_duty_en0 = "false",
    parameter c_cnt_hi_div1 = 5,
    parameter c_cnt_lo_div1 = 5,
    parameter c_cnt_prst1 = 1,
    parameter c_cnt_ph_mux_prst1 = 4,
    parameter c_cnt_bypass_en1 = "false",
    parameter c_cnt_odd_div_duty_en1 = "false",
    parameter c_cnt_hi_div2 = 1,
    parameter c_cnt_lo_div2 = 9,
    parameter c_cnt_prst2 = 9,
    parameter c_cnt_ph_mux_prst2 = 0,
    parameter c_cnt_bypass_en2 = "false",
    parameter c_cnt_odd_div_duty_en2 = "false",
    parameter c_cnt_hi_div3 = 256,
    parameter c_cnt_lo_div3 = 256,
    parameter c_cnt_prst3 = 1,
    parameter c_cnt_ph_mux_prst3 = 0,
    parameter c_cnt_bypass_en3 = "true",
    parameter c_cnt_odd_div_duty_en3 = "false",
    parameter c_cnt_hi_div4 = 256,
    parameter c_cnt_lo_div4 = 256,
    parameter c_cnt_prst4 = 1,
    parameter c_cnt_ph_mux_prst4 = 0,
    parameter c_cnt_bypass_en4 = "true",
    parameter c_cnt_odd_div_duty_en4 = "false",
    parameter c_cnt_hi_div5 = 256,
    parameter c_cnt_lo_div5 = 256,
    parameter c_cnt_prst5 = 1,
    parameter c_cnt_ph_mux_prst5 = 0,
    parameter c_cnt_bypass_en5 = "true",
    parameter c_cnt_odd_div_duty_en5 = "false",
    parameter c_cnt_hi_div6 = 256,
    parameter c_cnt_lo_div6 = 256,
    parameter c_cnt_prst6 = 1,
    parameter c_cnt_ph_mux_prst6 = 0,
    parameter c_cnt_bypass_en6 = "true",
    parameter c_cnt_odd_div_duty_en6 = "false",
    parameter c_cnt_hi_div7 = 256,
    parameter c_cnt_lo_div7 = 256,
    parameter c_cnt_prst7 = 1,
    parameter c_cnt_ph_mux_prst7 = 0,
    parameter c_cnt_bypass_en7 = "true",
    parameter c_cnt_odd_div_duty_en7 = "false",
    parameter c_cnt_hi_div8 = 256,
    parameter c_cnt_lo_div8 = 256,
    parameter c_cnt_prst8 = 1,
    parameter c_cnt_ph_mux_prst8 = 0,
    parameter c_cnt_bypass_en8 = "true",
    parameter c_cnt_odd_div_duty_en8 = "false",
    parameter pll_cp_current = 5,
    parameter pll_bwctrl = 18000,
    parameter pll_fbclk_mux_1 = "pll_fbclk_mux_1_lvds",
    parameter pll_fbclk_mux_2 = "pll_fbclk_mux_2_fb_1",
    parameter pll_m_cnt_in_src = "c_m_cnt_in_src_ph_mux_clk",
    parameter pll_bw_sel = "",
    parameter pll_bw_ctrl = "",
    parameter pll_cp_setting = "",
    parameter pll_ripplecap_setting = ""

) (
    input                                               ext_coreclock, 
    input                                               ext_fclk,
    input                                               ext_loaden,
    input                                               ext_tx_outclock_fclk,
    input                                               ext_tx_outclock_loaden,
    input       [7:0]                                   ext_vcoph,
    input                                               ext_pll_locked,
    input                                               inclock, 
    input       [NUM_CHANNELS-1:0]                      loopback_in,
    input                                               pll_areset,
    input       [NUM_CHANNELS-1:0]                      rx_bitslip_reset,
    input       [NUM_CHANNELS-1:0]                      rx_bitslip_ctrl,
    input       [NUM_CHANNELS-1:0]                      rx_dpa_reset,
    input       [NUM_CHANNELS-1:0]                      rx_dpa_hold,
    input       [NUM_CHANNELS-1:0]                      rx_fifo_reset,
    input       [NUM_CHANNELS-1:0]                      rx_in,
    input       [NUM_CHANNELS*J_FACTOR-1:0]             tx_in,
    input                                               user_mdio_dis,
    input                                               user_dprio_rst_n,
    input                                               user_dprio_read,
    input       [8:0]                                   user_dprio_reg_addr,
    input                                               user_dprio_write,
    input       [7:0]                                   user_dprio_writedata,

    output                                              user_dprio_clk,
    output                                              user_dprio_block_select,
    output      [7:0]                                   user_dprio_readdata,
    output                                              user_dprio_ready,
    output      [NUM_CHANNELS-1:0]                      rx_bitslip_max, 
    output      [NUM_CHANNELS-1:0]                      loopback_out,
    output      [NUM_CHANNELS-1:0]                      rx_dpa_locked,
    output      [NUM_CHANNELS-1:0]                      rx_divfwdclk, 
    output      [NUM_CHANNELS*J_FACTOR-1:0]             rx_out,
    output                                              rx_coreclock,
    output                                              tx_coreclock, 
    output      [NUM_CHANNELS-1:0]                      tx_out,
    output                                              tx_outclock,
    output                                              pll_locked,
    output                                              pll_extra_clock0,
    output                                              pll_extra_clock1,
    output                                              pll_extra_clock2,
    output                                              pll_extra_clock3
);

    wire                                                clock_tree_loaden;
    wire                                                clock_tree_fclk;
    wire                                                tx_outclock_fclk;
    wire                                                pll_tx_outclock_fclk;
    wire                                                pll_tx_outclock_loaden;
    wire                                                fclk;    
    wire                                                loaden;    
    wire        [7:0]                                   vcoph;   
    wire                                                coreclock; 
    wire                                                dprio_clk; 
    wire                                                dprio_rst_n; 
    wire        [NUM_CHANNELS-1:0]                      rx_dpa_reset_internal;

    wire                                                pll_areset_coreclock;
    wire                                                pll_dprio_clk;


    localparam PLL_COMPENSATION_MODE = (SERDES_DPA_MODE == "non_dpa_mode") ? "lvds" : "direct";
    localparam SYNC_STAGES = 3;
    
    assign rx_coreclock  = coreclock; 
    assign tx_coreclock  = coreclock; 
    
    generate
        if (EXTERNAL_PLL == "true")
        begin : breakout_clock_connections
            assign fclk                     = ext_fclk; 
            assign loaden                   = ext_loaden; 
            assign vcoph                    = ext_vcoph; 
            assign coreclock                = ext_coreclock;
            assign pll_tx_outclock_fclk     = ext_tx_outclock_fclk;
            assign pll_tx_outclock_loaden   = ext_tx_outclock_loaden;
            assign pll_locked               = ext_pll_locked;
        end
        else
        begin : internal_pll 
            wire [8:0] pll_outclock;
            wire [1:0] pll_lvds_clk;
            wire [1:0] pll_loaden;
            
            assign fclk                     = pll_lvds_clk[0]; 

            if (SERDES_DPA_MODE != "dpa_mode_cdr")
                assign loaden                   = pll_loaden[0];

                if (SERDES_DPA_MODE == "tx_mode" && TX_OUTCLOCK_ENABLED == "true" && TX_OUTCLOCK_NON_STD_PHASE_SHIFT == "true")
                begin
                    assign pll_tx_outclock_fclk     = pll_lvds_clk[1];
                    assign pll_tx_outclock_loaden   = pll_loaden[1];
                    assign coreclock                = pll_outclock[4];
                end
                else 
                begin
                    assign coreclock                = pll_outclock[2];
                end
        
                if (USE_DIV_RECONFIG == "true")
                    assign pll_dprio_clk = pll_outclock[3];
                
                assign pll_extra_clock0 = pll_outclock[5];
                assign pll_extra_clock1 = pll_outclock[6];
                assign pll_extra_clock2 = pll_outclock[7];
                assign pll_extra_clock3 = pll_outclock[8];
        
            altera_lvds_core20_pll #(
                .compensation_mode(PLL_COMPENSATION_MODE),
                .pll_fbclk_mux_1(pll_fbclk_mux_1),
                .pll_fbclk_mux_2(pll_fbclk_mux_2),
                .reference_clock_frequency(pll_input_clock_frequency),
                .vco_frequency (pll_vco_clock_frequency),
                .output_clock_frequency_0 (pll_output_clock_frequency_0),
                .output_clock_frequency_1 (pll_output_clock_frequency_1),
                .output_clock_frequency_2 (pll_output_clock_frequency_2),
                .output_clock_frequency_3 (pll_output_clock_frequency_3),
                .output_clock_frequency_4 (pll_output_clock_frequency_4),
                .output_clock_frequency_5 (pll_output_clock_frequency_5),
                .output_clock_frequency_6 (pll_output_clock_frequency_6),
                .output_clock_frequency_7 (pll_output_clock_frequency_7),
                .output_clock_frequency_8 (pll_output_clock_frequency_8),
                .duty_cycle_0 (pll_output_duty_cycle_0),
                .duty_cycle_1 (pll_output_duty_cycle_1),
                .duty_cycle_2 (pll_output_duty_cycle_2),
                .duty_cycle_3 (pll_output_duty_cycle_3),
                .duty_cycle_4 (pll_output_duty_cycle_4),
                .duty_cycle_5 (pll_output_duty_cycle_5),
                .duty_cycle_6 (pll_output_duty_cycle_6),
                .duty_cycle_7 (pll_output_duty_cycle_7),
                .duty_cycle_8 (pll_output_duty_cycle_8),
                .phase_shift_0 (pll_output_phase_shift_0),
                .phase_shift_1 (pll_output_phase_shift_1), 
                .phase_shift_2 (pll_output_phase_shift_2),
                .phase_shift_3 (pll_output_phase_shift_3),
                .phase_shift_4 (pll_output_phase_shift_4),
                .phase_shift_5 (pll_output_phase_shift_5), 
                .phase_shift_6 (pll_output_phase_shift_6),
                .phase_shift_7 (pll_output_phase_shift_7),
                .phase_shift_8 (pll_output_phase_shift_8),
                .pll_c0_out_en (pll_clk_out_en_0),    
                .pll_c1_out_en (pll_clk_out_en_1),    
                .pll_c2_out_en (pll_clk_out_en_2),
                .pll_c3_out_en (pll_clk_out_en_3),
                .pll_c4_out_en (pll_clk_out_en_4),
                .pll_c5_out_en (pll_clk_out_en_5),
                .pll_c6_out_en (pll_clk_out_en_6),
                .pll_c7_out_en (pll_clk_out_en_7),
                .pll_c8_out_en (pll_clk_out_en_8),
                .pll_c_counter_0_bypass_en (c_cnt_bypass_en0),
                .pll_c_counter_0_even_duty_en (c_cnt_odd_div_duty_en0),
                .pll_c_counter_0_high (c_cnt_hi_div0),
                .pll_c_counter_0_low (c_cnt_lo_div0),
                .pll_c_counter_0_ph_mux_prst (c_cnt_ph_mux_prst0),
                .pll_c_counter_0_prst (c_cnt_prst0),                
                .pll_c_counter_1_bypass_en (c_cnt_bypass_en1),
                .pll_c_counter_1_even_duty_en (c_cnt_odd_div_duty_en1),
                .pll_c_counter_1_high (c_cnt_hi_div1),
                .pll_c_counter_1_low (c_cnt_lo_div1),
                .pll_c_counter_1_ph_mux_prst (c_cnt_ph_mux_prst1),
                .pll_c_counter_1_prst (c_cnt_prst1),
                .pll_c_counter_2_bypass_en (c_cnt_bypass_en2),
                .pll_c_counter_2_even_duty_en (c_cnt_odd_div_duty_en2),
                .pll_c_counter_2_high (c_cnt_hi_div2),
                .pll_c_counter_2_low (c_cnt_lo_div2),
                .pll_c_counter_2_ph_mux_prst (c_cnt_ph_mux_prst2),
                .pll_c_counter_2_prst (c_cnt_prst2),
                .pll_c_counter_3_bypass_en (c_cnt_bypass_en3),
                .pll_c_counter_3_even_duty_en (c_cnt_odd_div_duty_en3),
                .pll_c_counter_3_high (c_cnt_hi_div3),
                .pll_c_counter_3_low (c_cnt_lo_div3),
                .pll_c_counter_3_ph_mux_prst (c_cnt_ph_mux_prst3),
                .pll_c_counter_3_prst (c_cnt_prst3),
                .pll_c_counter_4_bypass_en (c_cnt_bypass_en4),
                .pll_c_counter_4_even_duty_en (c_cnt_odd_div_duty_en4),
                .pll_c_counter_4_high (c_cnt_hi_div4),
                .pll_c_counter_4_low (c_cnt_lo_div4),
                .pll_c_counter_4_ph_mux_prst (c_cnt_ph_mux_prst4),
                .pll_c_counter_4_prst (c_cnt_prst4),
                .pll_c_counter_5_bypass_en (c_cnt_bypass_en5),
                .pll_c_counter_5_even_duty_en (c_cnt_odd_div_duty_en5),
                .pll_c_counter_5_high (c_cnt_hi_div5),
                .pll_c_counter_5_low (c_cnt_lo_div5),
                .pll_c_counter_5_ph_mux_prst (c_cnt_ph_mux_prst5),
                .pll_c_counter_5_prst (c_cnt_prst5),
                .pll_c_counter_6_bypass_en (c_cnt_bypass_en6),
                .pll_c_counter_6_even_duty_en (c_cnt_odd_div_duty_en6),
                .pll_c_counter_6_high (c_cnt_hi_div6),
                .pll_c_counter_6_low (c_cnt_lo_div6),
                .pll_c_counter_6_ph_mux_prst (c_cnt_ph_mux_prst6),
                .pll_c_counter_6_prst (c_cnt_prst6),
                .pll_c_counter_7_bypass_en (c_cnt_bypass_en7),
                .pll_c_counter_7_even_duty_en (c_cnt_odd_div_duty_en7),
                .pll_c_counter_7_high (c_cnt_hi_div7),
                .pll_c_counter_7_low (c_cnt_lo_div7),
                .pll_c_counter_7_ph_mux_prst (c_cnt_ph_mux_prst7),
                .pll_c_counter_7_prst (c_cnt_prst7),
                .pll_c_counter_8_bypass_en (c_cnt_bypass_en8),
                .pll_c_counter_8_even_duty_en (c_cnt_odd_div_duty_en8),
                .pll_c_counter_8_high (c_cnt_hi_div8),
                .pll_c_counter_8_low (c_cnt_lo_div8),
                .pll_c_counter_8_ph_mux_prst (c_cnt_ph_mux_prst8),
                .pll_c_counter_8_prst (c_cnt_prst8),
                .pll_m_counter_bypass_en (m_cnt_bypass_en),
                .pll_m_counter_even_duty_en (m_cnt_odd_div_duty_en),
                .pll_m_counter_high(m_cnt_hi_div),
                .pll_m_counter_low(m_cnt_lo_div),
                .pll_n_counter_bypass_en(n_cnt_bypass_en),
                .pll_n_counter_high(n_cnt_hi_div),
                .pll_n_counter_low(n_cnt_lo_div),
                .pll_n_counter_odd_div_duty_en (n_cnt_odd_div_duty_en),
                .pll_vco_ph0_en ("true"),
                .pll_vco_ph1_en ("true"),
                .pll_vco_ph2_en ("true"),
                .pll_vco_ph3_en ("true"),
                .pll_vco_ph4_en ("true"),
                .pll_vco_ph5_en ("true"),
                .pll_vco_ph6_en ("true"),
                .pll_vco_ph7_en ("true"),
                .bw_sel (pll_bw_sel),
                .pll_bwctrl (pll_bw_ctrl),
                .pll_cp_current_setting (pll_cp_setting)
            
            ) pll_inst (
            
                .rst_n(~pll_areset), 
                .refclk(inclock),
                .outclock(pll_outclock),
                .lvds_clk(pll_lvds_clk),
                .loaden(pll_loaden),
                .vcoph(vcoph),
                .lock(pll_locked));
        end
    endgenerate     

    
    

    generate 
        if  (ENABLE_CLOCK_PIN_MODE == "true" && (SERDES_DPA_MODE == "tx_mode" || SERDES_DPA_MODE == "non_dpa_mode")
            || SERDES_DPA_MODE == "dpa_mode_cdr") 
        begin : clock_pin_lvds_clock_tree
            cyclone10gx_lvds_clock_tree lvds_clock_tree_inst (
                .lvdsfclk_in(fclk),
                .lvdsfclk_out(clock_tree_fclk)
                );
        end
        else if (SERDES_DPA_MODE == "tx_mode" || SERDES_DPA_MODE == "non_dpa_mode" || SERDES_DPA_MODE == "dpa_mode_fifo")
        begin : default_lvds_clock_tree  
                cyclone10gx_lvds_clock_tree lvds_clock_tree_inst (
                .lvdsfclk_in(fclk),
                .loaden_in(loaden),
                .lvdsfclk_out(clock_tree_fclk),
                .loaden_out(clock_tree_loaden)
                );
        end
    endgenerate 

    generate 
       if (SERDES_DPA_MODE == "non_dpa_mode" || SERDES_DPA_MODE == "dpa_mode_fifo" || SERDES_DPA_MODE == "dpa_mode_cdr" || SERDES_DPA_MODE == "tx_mode" && TX_REGISTER_CLOCK == "tx_coreclock")
       begin : reset_coreclk_sync
           reset_synchronizer_active_high pll_areset_sync_coreclk (
               .async_reset(pll_areset),
               .clock(coreclock),
               .sync_reset(pll_areset_coreclock)
           );
       end
       else if (SERDES_DPA_MODE == "tx_mode")
       begin : reset_coreclk_sync
           reset_synchronizer_active_high pll_areset_sync_coreclk (
               .async_reset(pll_areset),
               .clock(inclock),
               .sync_reset(pll_areset_coreclock)
           );
       end
    endgenerate

    genvar CH_INDEX;
    generate
        for (CH_INDEX=0;CH_INDEX<NUM_CHANNELS;CH_INDEX=CH_INDEX+1)
        begin : channels
            if (SERDES_DPA_MODE == "tx_mode")
            begin : tx                
                reg [J_FACTOR-1:0] tx_reg /* synthesis syn_preserve=1*/ ;
                wire [9:0] inv_tx_in = tx_in[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX];
                wire tx_core_reg_clk = (TX_REGISTER_CLOCK == "tx_coreclock")? coreclock : inclock;
                
                genvar i; 
                for (i=0; i<J_FACTOR; i=i+1)
                begin : input_reg
                    always @(posedge tx_core_reg_clk or posedge pll_areset_coreclock)
                    begin
                        if (pll_areset_coreclock == 1'b1)
                            tx_reg[i] <= 1'b0; 
                        else
                            tx_reg[i] <= inv_tx_in[J_FACTOR-1-i];
                    end     
                end
                cyclone10gx_io_serdes_dpa #(
                    .mode(SERDES_DPA_MODE),
                    .data_width(J_FACTOR),
                    .enable_clock_pin_mode(ENABLE_CLOCK_PIN_MODE),
                    .loopback_mode(LOOPBACK_MODE),
                    .vco_frequency(VCO_FREQUENCY),
                    .silicon_rev(SILICON_REV)
                ) serdes_dpa_inst (
                    .fclk(clock_tree_fclk),
                    .loaden(clock_tree_loaden),
                    .txdata(tx_reg),
                    .loopbackin(loopback_in[CH_INDEX]), 
                    .lvdsout(tx_out[CH_INDEX]),
                    .loopbackout(loopback_out[CH_INDEX])
                );
            end 
            else if (SERDES_DPA_MODE == "non_dpa_mode")
            begin : rx_non_dpa
                wire [9:0] inv_rx_data;
                reg [J_FACTOR-1:0] rx_reg /* synthesis syn_preserve=1*/; 

                cyclone10gx_io_serdes_dpa #(
                    .mode(SERDES_DPA_MODE),
                    .bitslip_rollover(RX_BITSLIP_ROLLOVER-1),
                    .data_width(J_FACTOR),
                    .enable_clock_pin_mode(ENABLE_CLOCK_PIN_MODE),
                    .loopback_mode(LOOPBACK_MODE),
                    .vco_frequency(VCO_FREQUENCY),
                    .silicon_rev(SILICON_REV)
                ) serdes_dpa_inst (
                    .bitslipcntl(1'b0),
                    .bitslipreset(1'b1),
                    .fclk(clock_tree_fclk),
                    .loaden(clock_tree_loaden),
                    .lvdsin(rx_in[CH_INDEX]),
                    .loopbackin(loopback_in[CH_INDEX]),
                    .rxdata(inv_rx_data), 
                    .loopbackout(loopback_out[CH_INDEX])
                );

                genvar i; 
                for (i=0; i<J_FACTOR; i=i+1)
                begin : output_reg 
                    always @(posedge coreclock or posedge pll_areset_coreclock)
                    begin
                        if (pll_areset_coreclock)
                            rx_reg[J_FACTOR-1-i] <= 1'b0; 
                        else 
                            rx_reg[J_FACTOR-1-i] <= inv_rx_data[J_FACTOR-1-i];
                    end
                end
                
                if (USE_BITSLIP == "true")
                begin : soft_bitslip
                    parallel_bitslip #(
                        .DATA_SIZE(J_FACTOR),
                        .BITSLIP_ROLLOVER(RX_BITSLIP_ROLLOVER-1)
                    ) rx_bitslip (
                        .clock(coreclock),
                        .reset(pll_areset_coreclock),
                        .bitslip_reset(rx_bitslip_reset[CH_INDEX]),
                        .bitslip_ctrl(rx_bitslip_ctrl[CH_INDEX]),
                        .bitslip_max(rx_bitslip_max[CH_INDEX]),
                        .data_in(rx_reg),
                        .data_out(rx_out[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX])
                    );
                end
                else
                begin : no_bitslip
                    assign rx_out[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX] = rx_reg;
                end
           end
           else if (SERDES_DPA_MODE == "dpa_mode_fifo")
           begin : dpa_fifo
                wire [9:0] inv_rx_data;
                reg [J_FACTOR-1:0] rx_reg /* synthesis syn_preserve=1*/; 
                wire rx_dpa_locked_wire;
                (* altera_attribute = {"-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS; -name GLOBAL_SIGNAL OFF; -name AUTO_SHIFT_REGISTER_RECOGNITION OFF"}*) reg [SYNC_STAGES-1:0] dpa_locked_sync_reg /* synthesis dont_merge*/;
                
                if (USE_DIV_RECONFIG == "true" && CH_INDEX == 0)
                begin : ioserdesdpa
                    cyclone10gx_io_serdes_dpa #(
                        .mode(SERDES_DPA_MODE),
                        .align_to_rising_edge_only(ALIGN_TO_RISING_EDGE_ONLY),
                        .bitslip_rollover(RX_BITSLIP_ROLLOVER-1),
                        .data_width(J_FACTOR),
                        .lose_lock_on_one_change(LOSE_LOCK_ON_ONE_CHANGE),
                        .reset_fifo_at_first_lock(RESET_FIFO_AT_FIRST_LOCK),
                        .vco_div_exponent(VCO_DIV_EXPONENT),
                        .loopback_mode(LOOPBACK_MODE),
                        .vco_frequency(VCO_FREQUENCY),
                        .silicon_rev(SILICON_REV)
                    ) serdes_dpa_inst (
                        .bitslipcntl(1'b0),
                        .bitslipreset(1'b1),
                        .dpahold(rx_dpa_hold[CH_INDEX]),
                        .dpareset(pll_areset|rx_dpa_reset_internal[CH_INDEX]),
                        .fclk(clock_tree_fclk),
                        .dpafiforeset(pll_areset|rx_fifo_reset[CH_INDEX]),
                        .loaden(clock_tree_loaden),
                        .lvdsin(rx_in[CH_INDEX]),
                        .dpaclk(vcoph),
                        .loopbackin(loopback_in[CH_INDEX]),
                        .dpalock(rx_dpa_locked_wire),
                        .rxdata(inv_rx_data),
                        .mdio_dis(user_mdio_dis),
                        .dprio_clk(dprio_clk),
                        .dprio_rst_n(dprio_rst_n),
                        .dprio_read(user_dprio_read),
                        .dprio_reg_addr(user_dprio_reg_addr),
                        .dprio_write(user_dprio_write),
                        .dprio_writedata(user_dprio_writedata),
                        .dprio_block_select(user_dprio_block_select),
                        .dprio_readdata(user_dprio_readdata),
                        .loopbackout(loopback_out[CH_INDEX])
                    );
                end
                else
                begin : ioserdesdpa
                    cyclone10gx_io_serdes_dpa #(
                        .mode(SERDES_DPA_MODE),
                        .align_to_rising_edge_only(ALIGN_TO_RISING_EDGE_ONLY),
                        .bitslip_rollover(RX_BITSLIP_ROLLOVER-1),
                        .data_width(J_FACTOR),
                        .lose_lock_on_one_change(LOSE_LOCK_ON_ONE_CHANGE),
                        .reset_fifo_at_first_lock(RESET_FIFO_AT_FIRST_LOCK),
                        .vco_div_exponent(VCO_DIV_EXPONENT),
                        .loopback_mode(LOOPBACK_MODE),
                        .vco_frequency(VCO_FREQUENCY),
                        .silicon_rev(SILICON_REV)
                    ) serdes_dpa_inst (
                        .bitslipcntl(1'b0),
                        .bitslipreset(1'b1),
                        .dpahold(rx_dpa_hold[CH_INDEX]),
                        .dpareset(pll_areset|rx_dpa_reset_internal[CH_INDEX]),
                        .fclk(clock_tree_fclk),
                        .dpafiforeset(pll_areset|rx_fifo_reset[CH_INDEX]),
                        .loaden(clock_tree_loaden),
                        .lvdsin(rx_in[CH_INDEX]),
                        .dpaclk(vcoph),
                        .loopbackin(loopback_in[CH_INDEX]),
                        .dpalock(rx_dpa_locked_wire),
                        .rxdata(inv_rx_data), 
                        .dprio_clk(dprio_clk),
                        .dprio_rst_n(dprio_rst_n),
                        .loopbackout(loopback_out[CH_INDEX])
                    );
                end

                genvar i; 
                for (i=0; i<J_FACTOR; i=i+1)
                begin : output_reg 
                    always @(posedge coreclock or posedge pll_areset_coreclock)
                    begin
                        if (pll_areset_coreclock)
                            rx_reg[J_FACTOR-1-i] <= 1'b0; 
                        else 
                            rx_reg[J_FACTOR-1-i] <= inv_rx_data[J_FACTOR-1-i];
                    end
                end
                
                always @(posedge coreclock or posedge pll_areset_coreclock)
                begin
                    if (pll_areset_coreclock)
                    begin
                        dpa_locked_sync_reg <= {SYNC_STAGES{1'b0}};
                    end
                    else
                    begin
                        dpa_locked_sync_reg <= {dpa_locked_sync_reg[SYNC_STAGES-2:0], rx_dpa_locked_wire};
                    end
                end
                
                assign rx_dpa_locked[CH_INDEX] = dpa_locked_sync_reg[SYNC_STAGES-1];
                
                if (USE_BITSLIP == "true")
                begin : soft_bitslip
                    parallel_bitslip #(
                        .DATA_SIZE(J_FACTOR),
                        .BITSLIP_ROLLOVER(RX_BITSLIP_ROLLOVER-1)
                    ) rx_bitslip (
                        .clock(coreclock),
                        .reset(pll_areset_coreclock),
                        .bitslip_reset(rx_bitslip_reset[CH_INDEX]),
                        .bitslip_ctrl(rx_bitslip_ctrl[CH_INDEX]),
                        .bitslip_max(rx_bitslip_max[CH_INDEX]),
                        .data_in(rx_reg),
                        .data_out(rx_out[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX])
                    );
                end
                else
                begin : no_bitslip
                    assign rx_out[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX] = rx_reg;
                end
           end
           else if (SERDES_DPA_MODE == "dpa_mode_cdr")
           begin : soft_cdr
                wire [9:0] rx_data; 
                wire divfwdclk;
                reg [J_FACTOR-1:0] cdr_sync_reg /* synthesis syn_preserve=1*/;
                reg [J_FACTOR-1:0] rx_reg /* synthesis syn_preserve=1*/; 
                wire rx_dpa_locked_wire;
                wire pll_areset_divfwdclk;
                wire pll_areset_rxdivfwdclk;

                (* altera_attribute = {"-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS; -name GLOBAL_SIGNAL OFF; -name AUTO_SHIFT_REGISTER_RECOGNITION OFF"}*) reg [SYNC_STAGES-1:0] dpa_locked_sync_reg /* synthesis dont_merge*/;

                if (USE_DIV_RECONFIG == "true" && CH_INDEX == 0)
                begin : ioserdesdpa
                    cyclone10gx_io_serdes_dpa #(
                        .mode(SERDES_DPA_MODE),
                        .align_to_rising_edge_only(ALIGN_TO_RISING_EDGE_ONLY),
                        .bitslip_rollover(RX_BITSLIP_ROLLOVER-1),
                        .data_width(J_FACTOR),
                        .lose_lock_on_one_change(LOSE_LOCK_ON_ONE_CHANGE),
                        .reset_fifo_at_first_lock(RESET_FIFO_AT_FIRST_LOCK),
                        .enable_clock_pin_mode(ENABLE_CLOCK_PIN_MODE),
                        .loopback_mode(LOOPBACK_MODE),
                        .net_ppm_variation(NET_PPM_VARIATION),
                        .vco_div_exponent(VCO_DIV_EXPONENT),
                        .is_negative_ppm_drift(IS_NEGATIVE_PPM_DRIFT),
                        .vco_frequency(VCO_FREQUENCY),
                        .silicon_rev(SILICON_REV)
                    ) serdes_dpa_inst (
                        .bitslipcntl(1'b0),
                        .bitslipreset(1'b1),
                        .dpahold(rx_dpa_hold[CH_INDEX]),
                        .dpareset(pll_areset|rx_dpa_reset_internal[CH_INDEX]),
                        .fclk(clock_tree_fclk), 
                        .lvdsin(rx_in[CH_INDEX]),
                        .dpaclk(vcoph),
                        .loopbackin(loopback_in[CH_INDEX]),
                        .dpalock(rx_dpa_locked_wire),
                        .rxdata(rx_data),
                        .pclk(divfwdclk), 
                        .mdio_dis(user_mdio_dis),
                        .dprio_clk(dprio_clk),
                        .dprio_rst_n(dprio_rst_n),
                        .dprio_read(user_dprio_read),
                        .dprio_reg_addr(user_dprio_reg_addr),
                        .dprio_write(user_dprio_write),
                        .dprio_writedata(user_dprio_writedata),
                        .dprio_block_select(user_dprio_block_select),
                        .dprio_readdata(user_dprio_readdata),
                        .loopbackout(loopback_out[CH_INDEX])
                    );
                end
                else
                begin : ioserdesdpa
                    cyclone10gx_io_serdes_dpa #(
                        .mode(SERDES_DPA_MODE),
                        .align_to_rising_edge_only(ALIGN_TO_RISING_EDGE_ONLY),
                        .bitslip_rollover(RX_BITSLIP_ROLLOVER-1),
                        .data_width(J_FACTOR),
                        .lose_lock_on_one_change(LOSE_LOCK_ON_ONE_CHANGE),
                        .reset_fifo_at_first_lock(RESET_FIFO_AT_FIRST_LOCK),
                        .enable_clock_pin_mode(ENABLE_CLOCK_PIN_MODE),
                        .loopback_mode(LOOPBACK_MODE),
                        .net_ppm_variation(NET_PPM_VARIATION),
                        .vco_div_exponent(VCO_DIV_EXPONENT),
                        .is_negative_ppm_drift(IS_NEGATIVE_PPM_DRIFT),
                        .vco_frequency(VCO_FREQUENCY),
                        .silicon_rev(SILICON_REV)
                    ) serdes_dpa_inst (
                        .bitslipcntl(1'b0),
                        .bitslipreset(1'b1),
                        .dpahold(rx_dpa_hold[CH_INDEX]),
                        .dpareset(pll_areset|rx_dpa_reset_internal[CH_INDEX]),
                        .fclk(clock_tree_fclk), 
                        .lvdsin(rx_in[CH_INDEX]),
                        .dpaclk(vcoph),
                        .loopbackin(loopback_in[CH_INDEX]),
                        .dpalock(rx_dpa_locked_wire),
                        .rxdata(rx_data),
                        .pclk(divfwdclk), 
                        .dprio_clk(dprio_clk),
                        .dprio_rst_n(dprio_rst_n),
                        .loopbackout(loopback_out[CH_INDEX])
                    );
                end
                
                assign rx_divfwdclk[CH_INDEX] = ~divfwdclk;  

                reset_synchronizer_active_high pll_areset_sync_divfwdclk (
                    .async_reset(pll_areset),
                    .clock(divfwdclk),
                    .sync_reset(pll_areset_divfwdclk)
                );

                genvar i; 
                for (i=0; i<J_FACTOR; i=i+1)
                begin : cdr_sync
                    always @(posedge divfwdclk or posedge pll_areset_divfwdclk)
                    begin
                        if (pll_areset_divfwdclk)
                            cdr_sync_reg[i] <= 1'b0; 
                        else 
                            cdr_sync_reg[i] <= rx_data[i];
                    end
                end

                reset_synchronizer_active_high pll_areset_sync_rxdivfwdclk (
                    .async_reset(pll_areset),
                    .clock(rx_divfwdclk[CH_INDEX]),
                    .sync_reset(pll_areset_rxdivfwdclk)
                );

               
                always @(posedge rx_divfwdclk[CH_INDEX] or posedge pll_areset_rxdivfwdclk)
                begin 
                    if (pll_areset_rxdivfwdclk)
                        rx_reg <= {J_FACTOR{1'b0}}; 
                    else 
                        rx_reg <= cdr_sync_reg;
                end
                
                always @(posedge rx_divfwdclk[CH_INDEX] or posedge pll_areset_rxdivfwdclk)
                begin
                    if (pll_areset_rxdivfwdclk)
                    begin
                        dpa_locked_sync_reg <= {SYNC_STAGES{1'b0}};
                    end
                    else
                    begin
                        dpa_locked_sync_reg <= {dpa_locked_sync_reg[SYNC_STAGES-2:0], rx_dpa_locked_wire};
                    end
                end
                
                assign rx_dpa_locked[CH_INDEX] = dpa_locked_sync_reg[SYNC_STAGES-1];
                
                if (USE_BITSLIP == "true")
                begin : soft_bitslip
                    parallel_bitslip #(
                        .DATA_SIZE(J_FACTOR),
                        .BITSLIP_ROLLOVER(RX_BITSLIP_ROLLOVER-1)
                    ) rx_bitslip (
                        .clock(rx_divfwdclk[CH_INDEX]),
                        .reset(pll_areset_rxdivfwdclk),
                        .bitslip_reset(rx_bitslip_reset[CH_INDEX]),
                        .bitslip_ctrl(rx_bitslip_ctrl[CH_INDEX]),
                        .bitslip_max(rx_bitslip_max[CH_INDEX]),
                        .data_in(rx_reg),
                        .data_out(rx_out[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX])
                    );
                end
                else
                begin : no_bitslip
                    assign rx_out[(J_FACTOR*(CH_INDEX+1)-1):J_FACTOR*CH_INDEX] = rx_reg;
                end
            end    
        end
    endgenerate 

    
    generate 
        if (SERDES_DPA_MODE == "tx_mode" && TX_OUTCLOCK_ENABLED == "true" && TX_OUTCLOCK_NON_STD_PHASE_SHIFT == "false") 
        begin : std_tx_outclock_serdes
        
            wire [9:0] tx_outclock_div_word = TX_OUTCLOCK_DIV_WORD;
            cyclone10gx_io_serdes_dpa #(
                .mode("tx_mode"),
                .data_width(J_FACTOR),
                .enable_clock_pin_mode(ENABLE_CLOCK_PIN_MODE),
                .bypass_serializer(TX_OUTCLOCK_BYPASS_SERIALIZER),
                .use_falling_clock_edge(TX_OUTCLOCK_USE_FALLING_CLOCK_EDGE), 
                .loopback_mode(LOOPBACK_MODE),
                .vco_frequency(VCO_FREQUENCY),
                .silicon_rev(SILICON_REV)
            ) serdes_dpa_tx_outclock (
                .fclk(clock_tree_fclk),
                .loaden(clock_tree_loaden),
                .txdata(tx_outclock_div_word),
                .lvdsout(tx_outclock)
                );
        end
        else if (SERDES_DPA_MODE == "tx_mode" && TX_OUTCLOCK_ENABLED == "true" && TX_OUTCLOCK_NON_STD_PHASE_SHIFT == "true")
        begin : phase_shifted_tx_outclock_serdes 
            
            wire [9:0] tx_outclock_div_word = TX_OUTCLOCK_DIV_WORD;
            wire clock_tree_tx_outclock;
            wire clock_tree_tx_outclock_loaden;
            
            cyclone10gx_lvds_clock_tree outclock_tree (
                .lvdsfclk_in(pll_tx_outclock_fclk),
                .loaden_in(pll_tx_outclock_loaden),
                .lvdsfclk_out(clock_tree_tx_outclock),
                .loaden_out(clock_tree_tx_outclock_loaden)
                );

            cyclone10gx_io_serdes_dpa #(
                .mode("tx_mode"),
                .bypass_serializer(TX_OUTCLOCK_BYPASS_SERIALIZER),
                .loopback_mode(LOOPBACK_MODE),
                .vco_frequency(VCO_FREQUENCY),
                .is_tx_outclock("true"),
                .silicon_rev(SILICON_REV)
            ) serdes_dpa_tx_outclock (
                .fclk(clock_tree_tx_outclock),
                .loaden(clock_tree_tx_outclock_loaden),
                .txdata(tx_outclock_div_word),
                .lvdsout(tx_outclock)
                );
        end
    endgenerate 
    
    generate
        if  (SERDES_DPA_MODE == "dpa_mode_fifo" || SERDES_DPA_MODE == "dpa_mode_cdr")
        begin : dprio_clk_gen
            
            wire pll_areset_coreclock_dprio;
            lcell pll_areset_coreclock_wirelut (
                .in(pll_areset_coreclock),
                .out(pll_areset_coreclock_dprio)
            ) /* synthesis syn_keep = 1 */;
            
            reg dprio_done;
            reg dprio_start;
            
            
            wire dprio_clk_source = coreclock;
            (* noprune *) reg [1:0] dprio_div_counter;
            wire dprio_gen_reset = ~pll_locked | dprio_done | pll_areset_coreclock_dprio;
            
            always @(posedge dprio_clk_source or posedge dprio_gen_reset)
            begin
                if (dprio_gen_reset)
                    dprio_div_counter <= 2'd0; 
                else
                    dprio_div_counter <= dprio_div_counter + 2'd1;
            end
            
            reg [7:0] dprio_cycle_counter;
            
            if (USE_DIV_RECONFIG == "true")
            begin : div_reconfig
                assign dprio_clk = pll_dprio_clk;
                assign user_dprio_clk = dprio_clk;
                assign dprio_rst_n = dprio_done? user_dprio_rst_n : ~dprio_gen_reset & dprio_start;
                
                
                always @(posedge dprio_clk or posedge dprio_gen_reset)
                begin
                    if (dprio_gen_reset)
                        dprio_cycle_counter <= 7'd0; 
                    else
                        dprio_cycle_counter <= dprio_done? dprio_cycle_counter : dprio_cycle_counter + 7'd1;
                end
            end
            else
            begin : dprio
                assign dprio_clk = dprio_div_counter[1];
                assign dprio_rst_n = ~dprio_gen_reset & dprio_start;
                
                
                always @(posedge dprio_clk or posedge dprio_gen_reset)
                begin
                    if (dprio_gen_reset)
                        dprio_cycle_counter <= 7'd0; 
                    else
                        dprio_cycle_counter <= dprio_cycle_counter + 7'd1;
                end
            end
            
            assign user_dprio_ready = dprio_done;

            always @(posedge dprio_clk or posedge pll_areset_coreclock_dprio)
            begin
                if (pll_areset_coreclock_dprio)
                    dprio_start <= 1'b0;
                else if (&dprio_cycle_counter[1:0])
                    dprio_start <= 1'b1;
                    
                if (pll_areset_coreclock_dprio)
                    dprio_done <= 1'b0;
                else if (&dprio_cycle_counter)
                    dprio_done <= 1'b1;
            end
            
            assign rx_dpa_reset_internal = rx_dpa_reset | {NUM_CHANNELS{~dprio_done}};
        end
    endgenerate 

endmodule

module reset_synchronizer_active_high
#(
    parameter RESET_SYNC_LENGTH = 2
) (
    input async_reset,
    input clock,
    output sync_reset
);
    // Synchronize reset deassertion to core clock
    (* altera_attribute = {"-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS; -name GLOBAL_SIGNAL OFF; -name AUTO_SHIFT_REGISTER_RECOGNITION OFF"}*) reg [RESET_SYNC_LENGTH-1:0] sync_reg;
    always_ff @(posedge clock or posedge async_reset) 
    begin
        if (async_reset) 
        begin
            sync_reg <= {RESET_SYNC_LENGTH{1'b1}};
        end
        else 
        begin 
            sync_reg[0] <= 1'b0;
            sync_reg[RESET_SYNC_LENGTH-1:1] <= sync_reg[RESET_SYNC_LENGTH-2:0];
        end
    end
    assign sync_reset = sync_reg[RESET_SYNC_LENGTH-1];
endmodule

module data_synchronizer
#(
    parameter SYNC_LENGTH = 2
) (
    input data_in,
    input clock,
    input reset,
    output data_out
);
    (* altera_attribute = {"-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS; -name GLOBAL_SIGNAL OFF; -name AUTO_SHIFT_REGISTER_RECOGNITION OFF"}*) reg [SYNC_LENGTH-1:0] sync_reg /* synthesis dont_merge */;
    always_ff @(posedge clock or posedge reset) 
    begin
        if (reset) 
        begin
            sync_reg <= {SYNC_LENGTH{1'b0}};
        end
        else 
        begin 
            sync_reg[0] <= data_in;
            sync_reg[SYNC_LENGTH-1:1] <= sync_reg[SYNC_LENGTH-2:0];
        end
    end
    assign data_out = sync_reg[SYNC_LENGTH-1];
endmodule

module parallel_bitslip
(
    clock,
    reset,
    bitslip_reset,
    bitslip_ctrl,
    bitslip_max,
    data_in,
    data_out
);

    parameter DATA_SIZE = 10;
    parameter BITSLIP_ROLLOVER = DATA_SIZE - 1;

    input clock;
    input reset;
    input bitslip_reset;
    input bitslip_ctrl;
    input [DATA_SIZE-1:0] data_in;
    output [DATA_SIZE-1:0] data_out;
    output bitslip_max;

    localparam BITSLIP_COUNT_SIZE = 4;

    reg [DATA_SIZE-1:0] data_out_reg;
    reg [DATA_SIZE-1:0] data_in_delayed;
    reg [BITSLIP_COUNT_SIZE-1:0] bitslip_counter;
    reg prev_bitslip_ctrl;

    assign bitslip_max = (bitslip_counter == BITSLIP_ROLLOVER);

    wire bitslip_ctrl_sync;
    data_synchronizer bitslip_ctrl_synchronizer (
        .data_in(bitslip_ctrl),
        .clock(clock),
        .reset(reset),
        .data_out(bitslip_ctrl_sync)
    );
    
    wire bitslip_reset_sync;
    data_synchronizer bitslip_reset_synchronizer (
        .data_in(bitslip_reset),
        .clock(clock),
        .reset(reset),
        .data_out(bitslip_reset_sync)
    );

    always @(posedge clock or posedge reset) 
    begin
        if(reset) 
        begin
            prev_bitslip_ctrl <= 1'b0;
        end
        else 
        begin
            if (bitslip_reset_sync)
            begin
                prev_bitslip_ctrl <= 1'b0;
            end
            else
            begin
                prev_bitslip_ctrl <= bitslip_ctrl_sync;
            end
        end
    end

    always @(posedge clock or posedge reset) 
    begin
        if(reset) 
        begin
            bitslip_counter <= {BITSLIP_COUNT_SIZE{1'b0}};
        end
        else
        begin
            if (bitslip_reset_sync)
            begin
                bitslip_counter <= {BITSLIP_COUNT_SIZE{1'b0}};
            end
            else if(bitslip_ctrl_sync & ~prev_bitslip_ctrl) 
            begin
                if (bitslip_max) 
                begin
                    bitslip_counter <= {BITSLIP_COUNT_SIZE{1'b0}};
                end
                else 
                begin
                    bitslip_counter <= bitslip_counter + 1'b1;
                end
            end
        end
    end

    wire [2*DATA_SIZE-1:0] shifted_data = {data_in_delayed,data_in} >> bitslip_counter;
    
    always @(posedge clock or posedge reset) 
    begin
        if (reset)
        begin
            data_in_delayed <= {DATA_SIZE{1'b0}};;
            data_out_reg <= {DATA_SIZE{1'b0}};;
        end
        else
        begin
            data_in_delayed <= data_in;
            data_out_reg <= shifted_data[DATA_SIZE-1:0];
        end
    end
    
    assign data_out = data_out_reg;

endmodule

