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

module altera_lvds_core20_pll
(
    input refclk,
    input rst_n, 

    
    output lock,
    output [8:0] outclock,
    output [1:0] lvds_clk,
    output [1:0] loaden,
    output [7:0] vcoph
);


parameter number_of_counters = 9;
parameter number_of_extclks = 2;
parameter number_of_fine_delay_chains = 4;

parameter reference_clock_frequency = "100.0 MHz";
parameter vco_frequency = "300.0 MHz";
parameter output_clock_frequency_0 = "100.0 MHz";
parameter output_clock_frequency_1 = "0 ps";
parameter output_clock_frequency_2 = "0 ps";
parameter output_clock_frequency_3 = "0 ps";
parameter output_clock_frequency_4 = "0 ps";
parameter output_clock_frequency_5 = "0 ps";
parameter output_clock_frequency_6 = "0 ps";
parameter output_clock_frequency_7 = "0 ps";
parameter output_clock_frequency_8 = "0 ps";
parameter duty_cycle_0 = 50;
parameter duty_cycle_1 = 50;
parameter duty_cycle_2 = 50;
parameter duty_cycle_3 = 50;
parameter duty_cycle_4 = 50;
parameter duty_cycle_5 = 50;
parameter duty_cycle_6 = 50;
parameter duty_cycle_7 = 50;
parameter duty_cycle_8 = 50;
parameter phase_shift_0 = "0 ps";
parameter phase_shift_1 = "0 ps";
parameter phase_shift_2 = "0 ps";
parameter phase_shift_3 = "0 ps";
parameter phase_shift_4 = "0 ps";
parameter phase_shift_5 = "0 ps";
parameter phase_shift_6 = "0 ps";
parameter phase_shift_7 = "0 ps";
parameter phase_shift_8 = "0 ps";
parameter compensation_mode = "lvds";
parameter bw_sel = "auto";
parameter silicon_rev = "reva";
parameter speed_grade = "2";
parameter use_default_base_address = "true";
parameter user_base_address = 0;
parameter is_cascaded_pll = "false";

parameter pll_atb = "atb_selectdisable";
parameter pll_auto_clk_sw_en = "false";
parameter pll_bwctrl = "pll_bw_res_setting4";
parameter pll_c0_extclk_dllout_en = "false";
parameter pll_c0_out_en = "false";
parameter pll_c1_extclk_dllout_en = "false";
parameter pll_c1_out_en = "false";
parameter pll_c2_extclk_dllout_en = "false";
parameter pll_c2_out_en = "false";
parameter pll_c3_extclk_dllout_en = "false";
parameter pll_c3_out_en = "false";
parameter pll_c4_out_en = "false";
parameter pll_c5_out_en = "false";
parameter pll_c6_out_en = "false";
parameter pll_c7_out_en = "false";
parameter pll_c8_out_en = "false";
parameter pll_c_counter_0_bypass_en = "false";
parameter pll_c_counter_0_coarse_dly = "0 ps";
parameter pll_c_counter_0_even_duty_en = "false";
parameter pll_c_counter_0_fine_dly = "0 ps";
parameter pll_c_counter_0_high = 256;
parameter pll_c_counter_0_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_0_low = 256;
parameter pll_c_counter_0_ph_mux_prst = 0;
parameter pll_c_counter_0_prst = 1;
parameter pll_c_counter_1_bypass_en = "false";
parameter pll_c_counter_1_coarse_dly = "0 ps";
parameter pll_c_counter_1_even_duty_en = "false";
parameter pll_c_counter_1_fine_dly = "0 ps";
parameter pll_c_counter_1_high = 256;
parameter pll_c_counter_1_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_1_low = 256;
parameter pll_c_counter_1_ph_mux_prst = 0;
parameter pll_c_counter_1_prst = 1;
parameter pll_c_counter_2_bypass_en = "false";
parameter pll_c_counter_2_coarse_dly = "0 ps";
parameter pll_c_counter_2_even_duty_en = "false";
parameter pll_c_counter_2_fine_dly = "0 ps";
parameter pll_c_counter_2_high = 256;
parameter pll_c_counter_2_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_2_low = 256;
parameter pll_c_counter_2_ph_mux_prst = 0;
parameter pll_c_counter_2_prst = 1;
parameter pll_c_counter_3_bypass_en = "false";
parameter pll_c_counter_3_coarse_dly = "0 ps";
parameter pll_c_counter_3_even_duty_en = "false";
parameter pll_c_counter_3_fine_dly = "0 ps";
parameter pll_c_counter_3_high = 256;
parameter pll_c_counter_3_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_3_low = 256;
parameter pll_c_counter_3_ph_mux_prst = 0;
parameter pll_c_counter_3_prst = 1;
parameter pll_c_counter_4_bypass_en = "false";
parameter pll_c_counter_4_coarse_dly = "0 ps";
parameter pll_c_counter_4_even_duty_en = "false";
parameter pll_c_counter_4_fine_dly = "0 ps";
parameter pll_c_counter_4_high = 256;
parameter pll_c_counter_4_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_4_low = 256;
parameter pll_c_counter_4_ph_mux_prst = 0;
parameter pll_c_counter_4_prst = 1;
parameter pll_c_counter_5_bypass_en = "false";
parameter pll_c_counter_5_coarse_dly = "0 ps";
parameter pll_c_counter_5_even_duty_en = "false";
parameter pll_c_counter_5_fine_dly = "0 ps";
parameter pll_c_counter_5_high = 256;
parameter pll_c_counter_5_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_5_low = 256;
parameter pll_c_counter_5_ph_mux_prst = 0;
parameter pll_c_counter_5_prst = 1;
parameter pll_c_counter_6_bypass_en = "false";
parameter pll_c_counter_6_coarse_dly = "0 ps";
parameter pll_c_counter_6_even_duty_en = "false";
parameter pll_c_counter_6_fine_dly = "0 ps";
parameter pll_c_counter_6_high = 256;
parameter pll_c_counter_6_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_6_low = 256;
parameter pll_c_counter_6_ph_mux_prst = 0;
parameter pll_c_counter_6_prst = 1;
parameter pll_c_counter_7_bypass_en = "false";
parameter pll_c_counter_7_coarse_dly = "0 ps";
parameter pll_c_counter_7_even_duty_en = "false";
parameter pll_c_counter_7_fine_dly = "0 ps";
parameter pll_c_counter_7_high = 256;
parameter pll_c_counter_7_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_7_low = 256;
parameter pll_c_counter_7_ph_mux_prst = 0;
parameter pll_c_counter_7_prst = 1;
parameter pll_c_counter_8_bypass_en = "false";
parameter pll_c_counter_8_coarse_dly = "0 ps";
parameter pll_c_counter_8_even_duty_en = "false";
parameter pll_c_counter_8_fine_dly = "0 ps";
parameter pll_c_counter_8_high =256;
parameter pll_c_counter_8_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_c_counter_8_low = 256;
parameter pll_c_counter_8_ph_mux_prst = 0;
parameter pll_c_counter_8_prst = 1;
parameter pll_clk_loss_edge = "pll_clk_loss_both_edges";
parameter pll_clk_loss_sw_en = "false";
parameter pll_clk_sw_dly = 0;
parameter pll_clkin_0_src = "pll_clkin_0_src_ioclkin_0";
parameter pll_clkin_1_src = "pll_clkin_1_src_ioclkin_0";
parameter pll_cmp_buf_dly = "0 ps";
parameter pll_coarse_dly_0 = "0 ps";
parameter pll_coarse_dly_1 = "0 ps";
parameter pll_coarse_dly_2 = "0 ps";
parameter pll_coarse_dly_3 = "0 ps";
parameter pll_cp_compensation = "false";
parameter pll_cp_current_setting = "pll_cp_setting2";
parameter pll_ctrl_override_setting = "true";
parameter pll_dft_plniotri_override = "false";
parameter pll_dft_ppmclk = "c_cnt_out";
parameter pll_dll_src = "pll_dll_src_vss";
parameter pll_dly_0_enable = "true";
parameter pll_dly_1_enable = "true";
parameter pll_dly_2_enable = "true";
parameter pll_dly_3_enable = "true";
parameter pll_enable = "true";
parameter pll_extclk_0_cnt_src = "pll_extclk_cnt_src_vss";
parameter pll_extclk_0_enable = "false";
parameter pll_extclk_0_invert = "false";
parameter pll_extclk_1_cnt_src = "pll_extclk_cnt_src_vss";
parameter pll_extclk_1_enable = "false";
parameter pll_extclk_1_invert = "false";
parameter pll_fbclk_mux_1 = "pll_fbclk_mux_1_glb";
parameter pll_fbclk_mux_2 = "pll_fbclk_mux_2_fb_1";
parameter pll_fine_dly_0 = "0 ps";
parameter pll_fine_dly_1 = "0 ps";
parameter pll_fine_dly_2 = "0 ps";
parameter pll_fine_dly_3 = "0 ps";
parameter pll_lock_fltr_cfg = 25;
parameter pll_lock_fltr_test = "pll_lock_fltr_nrm";
parameter pll_m_counter_bypass_en = "true";
parameter pll_m_counter_coarse_dly = "0 ps";
parameter pll_m_counter_even_duty_en = "false";
parameter pll_m_counter_fine_dly = "0 ps";
parameter pll_m_counter_high = 256;
parameter pll_m_counter_in_src = "c_m_cnt_in_src_ph_mux_clk";
parameter pll_m_counter_low = 256;
parameter pll_m_counter_ph_mux_prst = 0;
parameter pll_m_counter_prst = 1;
parameter pll_manu_clk_sw_en = "false";
parameter pll_n_counter_bypass_en = "true";
parameter pll_n_counter_coarse_dly = "0 ps";
parameter pll_n_counter_fine_dly = "0 ps";
parameter pll_n_counter_high = 256;
parameter pll_n_counter_low = 256;
parameter pll_n_counter_odd_div_duty_en = "false";
parameter pll_nreset_invert = "false";
parameter pll_phyfb_mux = "m_cnt_phmux_out";
parameter pll_ref_buf_dly = "0 ps";
parameter pll_ripplecap_ctrl = "pll_ripplecap_setting0";
parameter pll_self_reset = "false";
parameter pll_sw_refclk_src = "pll_sw_refclk_src_clk_0";
parameter pll_tclk_mux_en = "false";
parameter pll_tclk_sel = "pll_tclk_m_src";
parameter pll_test_enable = "false";
parameter pll_testdn_enable = "false";
parameter pll_testup_enable = "false";
parameter pll_unlock_fltr_cfg = 2;
parameter pll_vccr_pd_en = "true";
parameter pll_vco_ph0_en = "true";
parameter pll_vco_ph1_en = "true";
parameter pll_vco_ph2_en = "true";
parameter pll_vco_ph3_en = "true";
parameter pll_vco_ph4_en = "true";
parameter pll_vco_ph5_en = "true";
parameter pll_vco_ph6_en = "true";
parameter pll_vco_ph7_en = "true";
parameter pll_dft_vco_ph0_en = "false";
parameter pll_dft_vco_ph1_en = "false";
parameter pll_dft_vco_ph2_en = "false";
parameter pll_dft_vco_ph3_en = "false";
parameter pll_dft_vco_ph4_en = "false";
parameter pll_dft_vco_ph5_en = "false";
parameter pll_dft_vco_ph6_en = "false";
parameter pll_dft_vco_ph7_en = "false";
parameter pll_powerdown_mode = "false";


wire            fbwire; 
wire             fbwire_core;

wire pll_dprio_clk;
wire pll_dprio_rst_n;
wire[8:0] pll_dprio_address;
wire pll_dprio_write;
wire pll_dprio_read;
wire[7:0] pll_dprio_writedata;
wire[7:0] pll_dprio_readdata;

wire pll_rst_n;

wire lock_wire;

iopll_bootstrap
#(
   `ifdef ALTERA_A10_IOPLL_BOOTSTRAP
      .PLL_CTR_RESYNC(1)
   `else
      .PLL_CTR_RESYNC(0)
   `endif
)
iopll_bootstrap_inst
(
   .u_dprio_clk(1'b0),
   .u_dprio_rst_n(rst_n),
   .u_dprio_address(9'b0),
   .u_dprio_read(1'b0),
   .u_dprio_write(1'b0),
   .u_dprio_writedata(8'b0),
   .u_rst_n(rst_n),
   .pll_locked(lock_wire),
   .pll_dprio_readdata(pll_dprio_readdata),

   .pll_dprio_clk(pll_dprio_clk),
   .pll_dprio_rst_n(pll_dprio_rst_n),
   .pll_dprio_address(pll_dprio_address),
   .pll_dprio_read(pll_dprio_read),
   .pll_dprio_write(pll_dprio_write),
   .pll_dprio_writedata(pll_dprio_writedata),
   .pll_rst_n(pll_rst_n),
   .u_dprio_readdata(),
   .u_locked(lock)
);

cyclone10gx_iopll altera_lvds_core20_iopll (
    .fblvds_in((compensation_mode == "lvds") ? fbwire: 1'b0),
    .fbclk_in((compensation_mode == "normal" || compensation_mode == "source_synchronous")? fbwire_core: 1'b0),
    .refclk({3'b0,refclk}),
    .rst_n(pll_rst_n),
    .fblvds_out(fbwire),
    .fbclk_out(fbwire_core),
    .lock(lock_wire),
    .outclk(outclock),
    .lvds_clk(lvds_clk),
    .loaden(loaden),    
    .vcoph(vcoph),
    .csr_clk(1'b0),
    .csr_en(1'b0),
    .csr_in(1'b0),
    .dprio_clk(pll_dprio_clk),
    .dprio_rst_n(pll_dprio_rst_n),
    .dprio_address(pll_dprio_address),
    .write(pll_dprio_write),
    .read(pll_dprio_read),
    .writedata(pll_dprio_writedata),
    .readdata(pll_dprio_readdata),
    .dps_rst_n(pll_rst_n),
    .mdio_dis(1'b0),
    .pfden(1'b1),
    .scan_mode_n(1'b1),
    .scan_shift_n(1'b1),
    .zdb_in(1'b0)
);
defparam altera_lvds_core20_iopll.reference_clock_frequency = reference_clock_frequency;
defparam altera_lvds_core20_iopll.vco_frequency = vco_frequency;
defparam altera_lvds_core20_iopll.output_clock_frequency_0 = output_clock_frequency_0;
defparam altera_lvds_core20_iopll.output_clock_frequency_1 = output_clock_frequency_1;
defparam altera_lvds_core20_iopll.output_clock_frequency_2 = output_clock_frequency_2;
defparam altera_lvds_core20_iopll.output_clock_frequency_3 = output_clock_frequency_3;
defparam altera_lvds_core20_iopll.output_clock_frequency_4 = output_clock_frequency_4;
defparam altera_lvds_core20_iopll.output_clock_frequency_5 = output_clock_frequency_5;
defparam altera_lvds_core20_iopll.output_clock_frequency_6 = output_clock_frequency_6;
defparam altera_lvds_core20_iopll.output_clock_frequency_7 = output_clock_frequency_7;
defparam altera_lvds_core20_iopll.output_clock_frequency_8 = output_clock_frequency_8;
defparam altera_lvds_core20_iopll.duty_cycle_0 = duty_cycle_0;
defparam altera_lvds_core20_iopll.duty_cycle_1 = duty_cycle_1;
defparam altera_lvds_core20_iopll.duty_cycle_2 = duty_cycle_2;
defparam altera_lvds_core20_iopll.duty_cycle_3 = duty_cycle_3;
defparam altera_lvds_core20_iopll.duty_cycle_4 = duty_cycle_4;
defparam altera_lvds_core20_iopll.duty_cycle_5 = duty_cycle_5;
defparam altera_lvds_core20_iopll.duty_cycle_6 = duty_cycle_6;
defparam altera_lvds_core20_iopll.duty_cycle_7 = duty_cycle_7;
defparam altera_lvds_core20_iopll.duty_cycle_8 = duty_cycle_8;
defparam altera_lvds_core20_iopll.phase_shift_0 = phase_shift_0;
defparam altera_lvds_core20_iopll.phase_shift_1 = phase_shift_1;
defparam altera_lvds_core20_iopll.phase_shift_2 = phase_shift_2;
defparam altera_lvds_core20_iopll.phase_shift_3 = phase_shift_3;
defparam altera_lvds_core20_iopll.phase_shift_4 = phase_shift_4;
defparam altera_lvds_core20_iopll.phase_shift_5 = phase_shift_5;
defparam altera_lvds_core20_iopll.phase_shift_6 = phase_shift_6;
defparam altera_lvds_core20_iopll.phase_shift_7 = phase_shift_7;
defparam altera_lvds_core20_iopll.phase_shift_8 = phase_shift_8;
defparam altera_lvds_core20_iopll.compensation_mode = compensation_mode;
defparam altera_lvds_core20_iopll.bw_sel = bw_sel;
defparam altera_lvds_core20_iopll.speed_grade = speed_grade;
defparam altera_lvds_core20_iopll.use_default_base_address = use_default_base_address;
defparam altera_lvds_core20_iopll.user_base_address = user_base_address;
defparam altera_lvds_core20_iopll.is_cascaded_pll = is_cascaded_pll;
defparam altera_lvds_core20_iopll.pll_atb = pll_atb;
defparam altera_lvds_core20_iopll.pll_auto_clk_sw_en = pll_auto_clk_sw_en;
defparam altera_lvds_core20_iopll.pll_bwctrl = pll_bwctrl;
defparam altera_lvds_core20_iopll.pll_c0_extclk_dllout_en = pll_c0_extclk_dllout_en;
defparam altera_lvds_core20_iopll.pll_c0_out_en = pll_c0_out_en;
defparam altera_lvds_core20_iopll.pll_c1_extclk_dllout_en = pll_c1_extclk_dllout_en;
defparam altera_lvds_core20_iopll.pll_c1_out_en = pll_c1_out_en;
defparam altera_lvds_core20_iopll.pll_c2_extclk_dllout_en = pll_c2_extclk_dllout_en;
defparam altera_lvds_core20_iopll.pll_c2_out_en = pll_c2_out_en;
defparam altera_lvds_core20_iopll.pll_c3_extclk_dllout_en = pll_c3_extclk_dllout_en;
defparam altera_lvds_core20_iopll.pll_c3_out_en = pll_c3_out_en;
defparam altera_lvds_core20_iopll.pll_c4_out_en = pll_c4_out_en;
defparam altera_lvds_core20_iopll.pll_c5_out_en = pll_c5_out_en;
defparam altera_lvds_core20_iopll.pll_c6_out_en = pll_c6_out_en;
defparam altera_lvds_core20_iopll.pll_c7_out_en = pll_c7_out_en;
defparam altera_lvds_core20_iopll.pll_c8_out_en = pll_c8_out_en;
defparam altera_lvds_core20_iopll.pll_c_counter_0_bypass_en = pll_c_counter_0_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_0_coarse_dly = pll_c_counter_0_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_0_even_duty_en = pll_c_counter_0_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_0_fine_dly = pll_c_counter_0_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_0_high = pll_c_counter_0_high;
defparam altera_lvds_core20_iopll.pll_c_counter_0_in_src = pll_c_counter_0_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_0_low = pll_c_counter_0_low;
defparam altera_lvds_core20_iopll.pll_c_counter_0_ph_mux_prst = pll_c_counter_0_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_0_prst = pll_c_counter_0_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_1_bypass_en = pll_c_counter_1_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_1_coarse_dly = pll_c_counter_1_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_1_even_duty_en = pll_c_counter_1_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_1_fine_dly = pll_c_counter_1_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_1_high = pll_c_counter_1_high;
defparam altera_lvds_core20_iopll.pll_c_counter_1_in_src = pll_c_counter_1_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_1_low = pll_c_counter_1_low;
defparam altera_lvds_core20_iopll.pll_c_counter_1_ph_mux_prst = pll_c_counter_1_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_1_prst = pll_c_counter_1_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_2_bypass_en = pll_c_counter_2_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_2_coarse_dly = pll_c_counter_2_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_2_even_duty_en = pll_c_counter_2_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_2_fine_dly = pll_c_counter_2_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_2_high = pll_c_counter_2_high;
defparam altera_lvds_core20_iopll.pll_c_counter_2_in_src = pll_c_counter_2_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_2_low = pll_c_counter_2_low;
defparam altera_lvds_core20_iopll.pll_c_counter_2_ph_mux_prst = pll_c_counter_2_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_2_prst = pll_c_counter_2_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_3_bypass_en = pll_c_counter_3_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_3_coarse_dly = pll_c_counter_3_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_3_even_duty_en = pll_c_counter_3_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_3_fine_dly = pll_c_counter_3_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_3_high = pll_c_counter_3_high;
defparam altera_lvds_core20_iopll.pll_c_counter_3_in_src = pll_c_counter_3_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_3_low = pll_c_counter_3_low;
defparam altera_lvds_core20_iopll.pll_c_counter_3_ph_mux_prst = pll_c_counter_3_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_3_prst = pll_c_counter_3_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_4_bypass_en = pll_c_counter_4_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_4_coarse_dly = pll_c_counter_4_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_4_even_duty_en = pll_c_counter_4_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_4_fine_dly = pll_c_counter_4_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_4_high = pll_c_counter_4_high;
defparam altera_lvds_core20_iopll.pll_c_counter_4_in_src = pll_c_counter_4_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_4_low = pll_c_counter_4_low;
defparam altera_lvds_core20_iopll.pll_c_counter_4_ph_mux_prst = pll_c_counter_4_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_4_prst = pll_c_counter_4_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_5_bypass_en = pll_c_counter_5_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_5_coarse_dly = pll_c_counter_5_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_5_even_duty_en = pll_c_counter_5_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_5_fine_dly = pll_c_counter_5_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_5_high = pll_c_counter_5_high;
defparam altera_lvds_core20_iopll.pll_c_counter_5_in_src = pll_c_counter_5_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_5_low = pll_c_counter_5_low;
defparam altera_lvds_core20_iopll.pll_c_counter_5_ph_mux_prst = pll_c_counter_5_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_5_prst = pll_c_counter_5_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_6_bypass_en = pll_c_counter_6_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_6_coarse_dly = pll_c_counter_6_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_6_even_duty_en = pll_c_counter_6_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_6_fine_dly = pll_c_counter_6_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_6_high = pll_c_counter_6_high;
defparam altera_lvds_core20_iopll.pll_c_counter_6_in_src = pll_c_counter_6_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_6_low = pll_c_counter_6_low;
defparam altera_lvds_core20_iopll.pll_c_counter_6_ph_mux_prst = pll_c_counter_6_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_6_prst = pll_c_counter_6_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_7_bypass_en = pll_c_counter_7_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_7_coarse_dly = pll_c_counter_7_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_7_even_duty_en = pll_c_counter_7_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_7_fine_dly = pll_c_counter_7_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_7_high = pll_c_counter_7_high;
defparam altera_lvds_core20_iopll.pll_c_counter_7_in_src = pll_c_counter_7_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_7_low = pll_c_counter_7_low;
defparam altera_lvds_core20_iopll.pll_c_counter_7_ph_mux_prst = pll_c_counter_7_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_7_prst = pll_c_counter_7_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_8_bypass_en = pll_c_counter_8_bypass_en;
defparam altera_lvds_core20_iopll.pll_c_counter_8_coarse_dly = pll_c_counter_8_coarse_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_8_even_duty_en = pll_c_counter_8_even_duty_en;
defparam altera_lvds_core20_iopll.pll_c_counter_8_fine_dly = pll_c_counter_8_fine_dly;
defparam altera_lvds_core20_iopll.pll_c_counter_8_high = pll_c_counter_8_high;
defparam altera_lvds_core20_iopll.pll_c_counter_8_in_src = pll_c_counter_8_in_src;
defparam altera_lvds_core20_iopll.pll_c_counter_8_low = pll_c_counter_8_low;
defparam altera_lvds_core20_iopll.pll_c_counter_8_ph_mux_prst = pll_c_counter_8_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_c_counter_8_prst = pll_c_counter_8_prst;
defparam altera_lvds_core20_iopll.pll_clk_loss_edge = pll_clk_loss_edge;
defparam altera_lvds_core20_iopll.pll_clk_loss_sw_en = pll_clk_loss_sw_en;
defparam altera_lvds_core20_iopll.pll_clk_sw_dly = pll_clk_sw_dly;
defparam altera_lvds_core20_iopll.pll_clkin_0_src = pll_clkin_0_src;
defparam altera_lvds_core20_iopll.pll_clkin_1_src = pll_clkin_1_src;
defparam altera_lvds_core20_iopll.pll_cmp_buf_dly = pll_cmp_buf_dly;
defparam altera_lvds_core20_iopll.pll_coarse_dly_0 = pll_coarse_dly_0;
defparam altera_lvds_core20_iopll.pll_coarse_dly_1 = pll_coarse_dly_1;
defparam altera_lvds_core20_iopll.pll_coarse_dly_2 = pll_coarse_dly_2;
defparam altera_lvds_core20_iopll.pll_coarse_dly_3 = pll_coarse_dly_3;
defparam altera_lvds_core20_iopll.pll_cp_compensation = pll_cp_compensation;
defparam altera_lvds_core20_iopll.pll_cp_current_setting = pll_cp_current_setting;
defparam altera_lvds_core20_iopll.pll_ctrl_override_setting = pll_ctrl_override_setting;
defparam altera_lvds_core20_iopll.pll_dft_plniotri_override = pll_dft_plniotri_override;
defparam altera_lvds_core20_iopll.pll_dft_ppmclk = pll_dft_ppmclk;
defparam altera_lvds_core20_iopll.pll_dll_src = pll_dll_src;
defparam altera_lvds_core20_iopll.pll_dly_0_enable = pll_dly_0_enable;
defparam altera_lvds_core20_iopll.pll_dly_1_enable = pll_dly_1_enable;
defparam altera_lvds_core20_iopll.pll_dly_2_enable = pll_dly_2_enable;
defparam altera_lvds_core20_iopll.pll_dly_3_enable = pll_dly_3_enable;
defparam altera_lvds_core20_iopll.pll_enable = pll_enable;
defparam altera_lvds_core20_iopll.pll_extclk_0_cnt_src = pll_extclk_0_cnt_src;
defparam altera_lvds_core20_iopll.pll_extclk_0_enable = pll_extclk_0_enable;
defparam altera_lvds_core20_iopll.pll_extclk_0_invert = pll_extclk_0_invert;
defparam altera_lvds_core20_iopll.pll_extclk_1_cnt_src = pll_extclk_1_cnt_src;
defparam altera_lvds_core20_iopll.pll_extclk_1_enable = pll_extclk_1_enable;
defparam altera_lvds_core20_iopll.pll_extclk_1_invert = pll_extclk_1_invert;
defparam altera_lvds_core20_iopll.pll_fbclk_mux_1 = pll_fbclk_mux_1;
defparam altera_lvds_core20_iopll.pll_fbclk_mux_2 = pll_fbclk_mux_2;
defparam altera_lvds_core20_iopll.pll_fine_dly_0 = pll_fine_dly_0;
defparam altera_lvds_core20_iopll.pll_fine_dly_1 = pll_fine_dly_1;
defparam altera_lvds_core20_iopll.pll_fine_dly_2 = pll_fine_dly_2;
defparam altera_lvds_core20_iopll.pll_fine_dly_3 = pll_fine_dly_3;
defparam altera_lvds_core20_iopll.pll_lock_fltr_cfg = pll_lock_fltr_cfg;
defparam altera_lvds_core20_iopll.pll_lock_fltr_test = pll_lock_fltr_test;
defparam altera_lvds_core20_iopll.pll_m_counter_bypass_en = pll_m_counter_bypass_en;
defparam altera_lvds_core20_iopll.pll_m_counter_coarse_dly = pll_m_counter_coarse_dly;
defparam altera_lvds_core20_iopll.pll_m_counter_even_duty_en = pll_m_counter_even_duty_en;
defparam altera_lvds_core20_iopll.pll_m_counter_fine_dly = pll_m_counter_fine_dly;
defparam altera_lvds_core20_iopll.pll_m_counter_high = pll_m_counter_high;
defparam altera_lvds_core20_iopll.pll_m_counter_in_src = pll_m_counter_in_src;
defparam altera_lvds_core20_iopll.pll_m_counter_low = pll_m_counter_low;
defparam altera_lvds_core20_iopll.pll_m_counter_ph_mux_prst = pll_m_counter_ph_mux_prst;
defparam altera_lvds_core20_iopll.pll_m_counter_prst = pll_m_counter_prst;
defparam altera_lvds_core20_iopll.pll_manu_clk_sw_en = pll_manu_clk_sw_en;
defparam altera_lvds_core20_iopll.pll_n_counter_bypass_en = pll_n_counter_bypass_en;
defparam altera_lvds_core20_iopll.pll_n_counter_coarse_dly = pll_n_counter_coarse_dly;
defparam altera_lvds_core20_iopll.pll_n_counter_fine_dly = pll_n_counter_fine_dly;
defparam altera_lvds_core20_iopll.pll_n_counter_high = pll_n_counter_high;
defparam altera_lvds_core20_iopll.pll_n_counter_low = pll_n_counter_low;
defparam altera_lvds_core20_iopll.pll_n_counter_odd_div_duty_en = pll_n_counter_odd_div_duty_en;
defparam altera_lvds_core20_iopll.pll_nreset_invert = pll_nreset_invert;
defparam altera_lvds_core20_iopll.pll_phyfb_mux = pll_phyfb_mux;
defparam altera_lvds_core20_iopll.pll_ref_buf_dly = pll_ref_buf_dly;
defparam altera_lvds_core20_iopll.pll_ripplecap_ctrl = pll_ripplecap_ctrl;
defparam altera_lvds_core20_iopll.pll_self_reset = pll_self_reset;
defparam altera_lvds_core20_iopll.pll_sw_refclk_src = pll_sw_refclk_src;
defparam altera_lvds_core20_iopll.pll_tclk_mux_en = pll_tclk_mux_en;
defparam altera_lvds_core20_iopll.pll_tclk_sel = pll_tclk_sel;
defparam altera_lvds_core20_iopll.pll_test_enable = pll_test_enable;
defparam altera_lvds_core20_iopll.pll_testdn_enable = pll_testdn_enable;
defparam altera_lvds_core20_iopll.pll_testup_enable = pll_testup_enable;
defparam altera_lvds_core20_iopll.pll_unlock_fltr_cfg = pll_unlock_fltr_cfg;
defparam altera_lvds_core20_iopll.pll_vccr_pd_en =pll_vccr_pd_en;
defparam altera_lvds_core20_iopll.pll_vco_ph0_en = pll_vco_ph0_en;
defparam altera_lvds_core20_iopll.pll_vco_ph1_en = pll_vco_ph1_en;
defparam altera_lvds_core20_iopll.pll_vco_ph2_en = pll_vco_ph2_en;
defparam altera_lvds_core20_iopll.pll_vco_ph3_en = pll_vco_ph3_en;
defparam altera_lvds_core20_iopll.pll_vco_ph4_en = pll_vco_ph4_en;
defparam altera_lvds_core20_iopll.pll_vco_ph5_en = pll_vco_ph5_en;
defparam altera_lvds_core20_iopll.pll_vco_ph6_en = pll_vco_ph6_en;
defparam altera_lvds_core20_iopll.pll_vco_ph7_en = pll_vco_ph7_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph0_en = pll_dft_vco_ph0_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph1_en = pll_dft_vco_ph1_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph2_en = pll_dft_vco_ph2_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph3_en = pll_dft_vco_ph3_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph4_en = pll_dft_vco_ph4_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph5_en = pll_dft_vco_ph5_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph6_en = pll_dft_vco_ph6_en;
defparam altera_lvds_core20_iopll.pll_dft_vco_ph7_en = pll_dft_vco_ph7_en;
defparam altera_lvds_core20_iopll.pll_powerdown_mode = pll_powerdown_mode;
defparam altera_lvds_core20_iopll.pll_dprio_broadcast_en = "false";
defparam altera_lvds_core20_iopll.pll_dprio_cvp_inter_sel = "false";
defparam altera_lvds_core20_iopll.pll_dprio_force_inter_sel = "false";
defparam altera_lvds_core20_iopll.pll_dprio_power_iso_en = "false";


endmodule 

