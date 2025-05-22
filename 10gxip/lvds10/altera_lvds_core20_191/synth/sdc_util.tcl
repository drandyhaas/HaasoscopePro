# (C) 2001-2022 Intel Corporation. All rights reserved.
# Your use of Intel Corporation's design tools, logic functions and other 
# software and tools, and its AMPP partner logic functions, and any output 
# files from any of the foregoing (including device programming or simulation 
# files), and any associated documentation or information are expressly subject 
# to the terms and conditions of the Intel Program License Subscription 
# Agreement, Intel FPGA IP License Agreement, or other applicable 
# license agreement, including, without limitation, that your use is for the 
# sole purpose of programming logic devices manufactured by Intel and sold by 
# Intel or its authorized distributors.  Please refer to the applicable 
# agreement for further details.


# Check whether a project has already been opened
if {[catch {get_current_project}]} {
	post_message -type error "Please open a project first"
	return
}

package require ::quartus::emif_timing_model
package require ::quartus::clock_uncertainty

# The protocol doesn't matter for how LVDS uses the package
initialize_emiftcl -protocol DDR3
initialize_clock_uncertainty_data

proc altera_iosubsystem_create_generated_clock {args} {
   array set opts {  -invert 0 \
      -add 0 \
      -remove_clock 1 \
      -name "" \
      -target "" \
      -source "" \
      -multiply_by 1 \
      -divide_by 1 \
      -phase 0 \
		-duty_cycle 50.00  }

   array set opts $args

   set multiply_by [expr int($opts(-multiply_by))]
   if {[expr $multiply_by - $opts(-multiply_by)] != 0.0} {
      post_message -type error "Specify an integer ranging from 0 to 99999999 for the option -multiply_by"
      return ""
   }
	
   if {$opts(-remove_clock)==1} {
      set clock_name_to_remove [altera_iosubsystem_get_clock_name_from_target $opts(-target)]
      if {$clock_name_to_remove != ""} {
         foreach i $clock_name_to_remove {
            remove_clock  [get_clock_info -name $i]
         }
      }
   }
	
   set extra_params [list]
   if {$opts(-invert)==1} {
      lappend extra_params "-invert"
   }
   if {$opts(-add)==1} {
      lappend extra_params "-add"
   }
   
   if {$extra_params == ""} {
      eval {create_generated_clock -name $opts(-name) -source $opts(-source) -multiply_by $multiply_by -divide_by $opts(-divide_by) -phase $opts(-phase) -duty_cycle $opts(-duty_cycle) $opts(-target)}
   } else {
      eval {create_generated_clock {*}$extra_params -name $opts(-name) -source $opts(-source) -multiply_by $multiply_by -divide_by $opts(-divide_by) -phase $opts(-phase) -duty_cycle $opts(-duty_cycle) $opts(-target)}
   }
   
}

proc altera_iosubsystem_get_clock_name_from_target { target } {
   set clock_name [list]
   foreach_in_collection i [get_clocks -nowarn] {  
      if {![is_clock_defined $i]} {
         continue
      }
      if { [catch { get_node_info -name  [get_clock_info -targets $i] } i_target ] } {
         continue
      }
      if {[string equal $target $i_target]} {
         lappend clock_name [get_clock_info -name $i]
      }
   }
   return $clock_name
}

proc altera_iosubsystem_get_ip_instance_names { libname corename } {
   set allkeepers [get_keepers * ]

   set_project_mode -always_show_entity_name on

   set inst_regexp {(^.*\m}
   append inst_regexp "$libname"
   append inst_regexp {\M.*)\|}
   append inst_regexp "$corename"
   append inst_regexp {:arch_inst|channels[0]}

   foreach_in_collection keeper $allkeepers {
      set name [ get_node_info -name $keeper ]

      if {[regexp -- $inst_regexp $name -> hier_name] == 1} {
         set tq_name [altera_iosubsystem_get_timequest_name $hier_name]
         set instance_array($tq_name) 1
      }
   }

   set instance_list [array names instance_array]

   set_project_mode -always_show_entity_name qsf

   if {[ llength $instance_list ] == 0} {
      post_message -type critical_warning "The auto-constraining script was not able to detect any instance for lib < $libname > core < $corename >"
      post_message -type critical_warning "Make sure the core < $corename > is instantiated within another component (wrapper)"
      post_message -type critical_warning "and it's not the top-level for your project"
   }

   return $instance_list
}

proc altera_iosubsystem_traverse_fanin_up_to_depth { node_id match_command edge_type results_array_name depth} {
   upvar 1 $results_array_name results

   altera_iosubsystem_traverse_fanin_up_to_depth_recurse $node_id $match_command $edge_type results $depth
}

proc altera_iosubsystem_traverse_fanin_up_to_depth_recurse { node_id match_command edge_type results_array_name depth} {
   upvar 1 $results_array_name results

   if {$depth < 0} {
      error "Internal error: Bad timing netlist search depth"
   }
   set fanin_edges [get_node_info -${edge_type}_edges $node_id]
   set number_of_fanin_edges [llength $fanin_edges]
   for {set i 0} {$i != $number_of_fanin_edges} {incr i} {
      set fanin_edge [lindex $fanin_edges $i]
      set fanin_id [get_edge_info -src $fanin_edge]
      if {$match_command == "" || [eval $match_command $fanin_id] != 0} {
         set results($fanin_id) 1
      } elseif {$depth == 0} {
      } else {
         altera_iosubsystem_traverse_fanin_up_to_depth_recurse $fanin_id $match_command $edge_type results [expr {$depth - 1}]
      }
   }
}

proc altera_iosubsystem_get_timequest_name { full_hier_name } {
   set tq_name ""
   set tq_name_list {}
   set lib_inst_pair_list [split $full_hier_name "|"]
   foreach i_lib_inst_pair_str $lib_inst_pair_list {
      set i_lib_inst_pair [split $i_lib_inst_pair_str ":"]
      if {[llength $i_lib_inst_pair] > 1} {
         lappend tq_name_list [join [lrange $i_lib_inst_pair 1 end] :]
      } else {
         lappend tq_name_list [lindex $i_lib_inst_pair end]
      }
   }
   set tq_name [join $tq_name_list "|"]
   return $tq_name
}

proc altera_iosubsystem_get_input_clk_id { pll_inclk_id } {

   array set results_array [list]

   altera_iosubsystem_traverse_fanin_up_to_depth $pll_inclk_id altera_iosubsystem_is_node_type_pin clock results_array 20
   if {[array size results_array] == 1} {
      set pin_id [lindex [array names results_array] 0]
      set result $pin_id
   } else {
      set result -1
   }

   return $result
}

proc altera_iosubsystem_get_src_pin_name { target_node_name {max_depth 5} } {
   if {[expr [get_global_assignment -name "HYPER_RETIMER"] == "ON"]} {
	   set max_depth [expr {$max_depth * 10}]
   }

   altera_iosubsystem_get_src_pin_name_recurse $target_node_name $max_depth
}

proc altera_iosubsystem_get_src_pin_name_recurse { target_node_name {max_depth 5} } {
   set prefix [join [lrepeat [expr 5-$max_depth+1] "\t"] ""]

   if {$max_depth == 0} {
      return $target_node_name
   }

   set catch_get_src [catch {get_node_info -name [get_edge_info -src [get_node_info -clock_edges $target_node_name]]} src_node_name] 
   
   if {$catch_get_src == 0} {
      if {[altera_iosubsystem_is_node_type_pin $src_node_name]} {
         return $src_node_name 
      } else {
         set recur_src_node_name [altera_iosubsystem_get_src_pin_name_recurse $src_node_name [expr $max_depth-1]]
         if {$recur_src_node_name == $src_node_name} {
            return $target_node_name
         } else {
            return $recur_src_node_name
         }
      }
   } else {
      return $target_node_name
   }
}

proc altera_iosubsystem_is_node_type_pin { node_id } {
   set node_type [get_node_info -type $node_id]
   if {$node_type == "port"} {
      set result 1
   } else {
      set result 0
   }
   return $result
}


proc altera_iosubsystem_is_node_pll_in_pin {node_id} {
	set node_type [get_node_info -type $node_id]
	set cell_wysiwyg_type [get_cell_info -wysiwyg_type [get_node_info -cell $node_id]]
	if {$node_type == "pin" && ($cell_wysiwyg_type == "twentynm_iopll" || $cell_wysiwyg_type == "cyclone10gx_iopll") && [get_pin_info -is_in_pin $node_id] == 1} {
		set result 1
	} else {
		set result 0
	}
	return $result
}

proc altera_iosubsystem_is_node_pll_out_pin {node_id} {
	set node_type [get_node_info -type $node_id]
	set cell_wysiwyg_type [get_cell_info -wysiwyg_type [get_node_info -cell $node_id]]
	if {$node_type == "pin" && ($cell_wysiwyg_type == "twentynm_iopll" || $cell_wysiwyg_type == "cyclone10gx_iopll") && [get_pin_info -is_out_pin $node_id] == 1} {
		set result 1
	} else {
		set result 0
	}
	return $result
}

proc altera_iosubsystem_get_src_pll_in_pin {node_id} { 
	array set result_array [list]
	
	altera_iosubsystem_traverse_fanin_up_to_depth $node_id altera_iosubsystem_is_node_pll_in_pin clock result_array 10
	return [array names result_array]

}

proc altera_iosubsystem_get_src_pll_out_pin {node_id} { 
	array set result_array [list]
	
	altera_iosubsystem_traverse_fanin_up_to_depth $node_id altera_iosubsystem_is_node_pll_out_pin clock result_array 10
	return [array names result_array]

}


proc altera_iosubsystem_get_pll_inclock_name_list { lvds_inst_name_list } {

	set pll_inclock_name_list {}
	
	foreach i_lvds_inst_name $lvds_inst_name_list {
		set i_pll_inclk_name [altera_iosubsystem_get_pll_inclock_name $i_lvds_inst_name]
		lappend pll_inclock_name_list $i_pll_inclk_name
	}
	
	return $pll_inclock_name_list
}

proc altera_iosubsystem_get_pll_inclock_name {lvds_instance_name} {
	
	set lvds_core_instance_name "${lvds_instance_name}|arch_inst"
	set pll_instance_name "$lvds_core_instance_name|internal_pll.pll_inst|altera_lvds_core20_iopll" 

	
	set catch_exception [catch {
		set pll_refclk_node [get_nodes "$pll_instance_name|refclk[0]"]
		set ref_ck_port_id [altera_iosubsystem_get_input_clk_id $pll_refclk_node]
		set ref_ck_port_name [get_port_info -name $ref_ck_port_id]
	} ]
	if {$catch_exception == 0} {
		set ref_ck_pin $ref_ck_port_name
	} else {
		set ref_ck_pin "${lvds_instance_name}_inclock_export"
	}

	return $ref_ck_pin
}

proc altera_iosubsystem_get_current_timequest_report_folder {} {

   set catch_exception [catch {get_current_timequest_report_folder} error_message]
   if {[regexp ERROR $error_message] == 1} {
      return "ReportDDR"
   } else {
      return [get_current_timequest_report_folder]
   }
}

proc altera_iosubsystem_report_rskm {} {

   set RX_NON_DPA_IP_TRAIL "|core|arch_inst|channels[0].rx_non_dpa.serdes_dpa_inst~rx_internal_reg"
   set RX_NON_DPA_REG_TRAIL {|core|arch_inst|channels[*].rx_non_dpa.serdes_dpa_inst~rx_internal_reg}
   set RX_NON_DPA_LVDSIN_TRAIL {|core|arch_inst|channels[*].rx_non_dpa.serdes_dpa_inst|lvdsin}

   set orig_op_cond [get_operating_conditions]

	set sw 300

   load_package report
   catch {load_report} load_report_out
   set report_not_loaded [regexp "ERROR" $load_report_out]
   if {$report_not_loaded == 1} {
      create_report_database -type cmp
      create_report_database -type taw
   }
	
	set current_tq_folder_name [altera_iosubsystem_get_current_timequest_report_folder]
   if {[string match "*GUI*" $current_tq_folder_name]} {
      set is_gui 1
   } else {
      set is_gui 0
   }
   if {[get_report_panel_id $current_tq_folder_name] == -1} {
      set panel_id [create_report_panel -folder $current_tq_folder_name]
   }

   set non_dpa_keepers_collection [get_keepers -nowarn "*${RX_NON_DPA_IP_TRAIL}"]
   if {[get_collection_size $non_dpa_keepers_collection] == 0} {
      post_message -type info "No Non-DPA RX instances detected to report RSKM"
   }

   foreach_in_collection i_non_dpa_keeper $non_dpa_keepers_collection {
      set keeper_name [altera_iosubsystem_get_timequest_name [get_node_info -name $i_non_dpa_keeper]]
      set lvds_instance_name [string range $keeper_name 0 [expr [string length $keeper_name] - [string length $RX_NON_DPA_IP_TRAIL] - 1]]
      set panel_name $lvds_instance_name
      foreach_in_collection lvds_node [get_nodes -nowarn "$lvds_instance_name|*|fclk"] {
         set fclk_name [get_node_info -name [get_edge_info -src [get_node_info -clock_edges [lindex $lvds_node 0]]]]
         break
      }
      set reg_name "${lvds_instance_name}${RX_NON_DPA_REG_TRAIL}"
      set lvdsin_name "${lvds_instance_name}${RX_NON_DPA_LVDSIN_TRAIL}"

      if { ! [string match "${current_tq_folder_name}*" $panel_name] } {
         set panel_name "${current_tq_folder_name}||$panel_name"
      }

      set panel_id [get_report_panel_id $panel_name]
      if {$panel_id != -1} {
         delete_report_panel -id $panel_id
      }

      set panel_id [create_report_panel -table $panel_name]

      if {$::RSKM_USE_MICRO == 1} {
         if {$is_gui == 1} {
            set setup_rpt [report_timing -setup -through $lvdsin_name -to [get_keepers $reg_name] ]
            set setup [lindex $setup_rpt 1]
            set hold_rpt [report_timing -hold -through $lvdsin_name -to [get_keepers $reg_name] ]
            set hold [lindex $hold_rpt 1]
            set rskm [expr min($setup, $hold)]
            post_message -type info "Micro RSKM of <$lvds_instance_name> = $rskm"

            if { ! [string match "${current_tq_folder_name}*" $panel_name] } {
               set panel_name "${current_tq_folder_name}||$panel_name"
            }

            add_row_to_table -id $panel_id [list "RSKM" "Worst-Case Setup Slack" "Worst-Case Hold Slack" "RCCS"]
            add_row_to_table -id $panel_id [list $rskm $setup $hold $::RCCS(${lvds_instance_name}|core)]
         } else {
            set rskm "_UNDEFINED"
            set header_row [list "LVDS Receiver Worst-case RSKM"]
            set data_row [list $rskm]

            foreach_in_collection i_op [get_available_operating_conditions] { 
               set i_op_name [get_operating_conditions_info -name $i_op] 
               set_operating_conditions $i_op
               update_timing_netlist
               set setup_rpt_at_op [report_timing -setup -through $lvdsin_name -to [get_keepers $reg_name] ]
               set setup_at_op [lindex $setup_rpt_at_op 1]
               set hold_rpt_at_op [report_timing -hold -through $lvdsin_name -to [get_keepers $reg_name] ]
               set hold_at_op [lindex $hold_rpt_at_op 1]
               if {$rskm == "_UNDEFINED"} {
                  set rskm [expr min($setup_at_op, $hold_at_op)]
               } else {
                  set rskm [expr min($rskm, $setup_at_op, $hold_at_op)]
               }

               lappend header_row "Setup:$i_op_name"
               lappend data_row $setup_at_op
               lappend header_row "Hold:$i_op_name"
               lappend data_row $hold_at_op
            }

            lset data_row 0 $rskm

            add_row_to_table -id $panel_id $header_row
            add_row_to_table -id $panel_id $data_row

         }
      } else {
         set fclk_target_name [get_node_info -name [get_edge_info -src [get_node_info -clock_edges $fclk_name]]]
         set fclk_setting_name [altera_iosubsystem_get_clock_name_from_target $fclk_target_name]
         set period [expr [get_clock_info -period [get_clocks [lindex $fclk_setting_name 0]]] * 1000]
         set rskm [expr 0.5 * ($period - $sw - $::RCCS(${lvds_instance_name}|core))]
         post_message -type info "RSKM of <$lvds_instance_name> = $rskm"

         add_row_to_table -id $panel_id [list "RSKM" "LVDS Period" "Sampling Window" "RCCS"]
         add_row_to_table -id $panel_id [list $rskm $period $sw $::RCCS(${lvds_instance_name}|core)]

      }
   }

   if {$is_gui == 0} {
      set_operating_conditions $orig_op_cond
      update_timing_netlist
   }
}

proc altera_iosubsystem_report_tccs {} {
   set TX_IP_TRAIL "|core|arch_inst|channels[0].tx.serdes_dpa_inst~tx_internal_reg"

   set orig_op_cond [get_operating_conditions]

   load_package report
   catch {load_report} load_report_out
   set report_not_loaded [regexp "ERROR" $load_report_out]
   if {$report_not_loaded == 1} {
      create_report_database -type cmp
      create_report_database -type taw
   }
	
	set current_tq_folder_name [altera_iosubsystem_get_current_timequest_report_folder]
   if {[string match "*GUI*" $current_tq_folder_name]} {
      set is_gui 1
   } else {
      set is_gui 0
   }

   if {[get_report_panel_id $current_tq_folder_name] == -1} {
      set panel_id [create_report_panel -folder $current_tq_folder_name]
   }

   set tx_keepers_collection [get_keepers -nowarn "*${TX_IP_TRAIL}"]
   if {[get_collection_size $tx_keepers_collection] == 0} {
      post_message -type info "No TX instances detected to report TCCS"
   }

   foreach_in_collection i_tx_keeper $tx_keepers_collection {
      set keeper_name [altera_iosubsystem_get_timequest_name [get_node_info -name $i_tx_keeper]]
		set lvds_instance_name [string range $keeper_name 0 [expr [string length $keeper_name] - [string length $TX_IP_TRAIL] - 1]]
      set panel_name [string range $keeper_name 0 [expr [string length $keeper_name] - [string length $TX_IP_TRAIL] - 1]]

      if { ! [string match "${current_tq_folder_name}*" $panel_name] } {
         set panel_name "${current_tq_folder_name}||$panel_name"
      }

      set panel_id [get_report_panel_id $panel_name]
      if {$panel_id != -1} {
         delete_report_panel -id $panel_id
      }
      
      set panel_id [create_report_panel -table $panel_name]
		set i_tccs 0


      if {$::TCCS_USE_MICRO == 0} {
         set header_row [list "LVDS Transmitter Constant TCCS"]
         set data_row [list 150]
      } else {
         if {$is_gui == 1} {
            set header_row [list "LVDS Transmitter TCCS"]
            set i_tccs [lindex [report_skew -from "${lvds_instance_name}|*~tx_internal_reg" -npaths 100] 1]
            set data_row [list $i_tccs]
         } else {
         
            set header_row [list "LVDS Transmitter Worst-case TCCS"]
            set data_row [list $i_tccs]
            

            foreach_in_collection i_op [get_available_operating_conditions] { 
               set i_op_name [get_operating_conditions_info -name $i_op] 
               set_operating_conditions $i_op
               update_timing_netlist
               set i_tccs_at_op [lindex [report_skew -from "${lvds_instance_name}|*~tx_internal_reg" -npaths 100] 1]
               lappend header_row $i_op_name
               lappend data_row $i_tccs_at_op
               if {$i_tccs < $i_tccs_at_op} {
                  set i_tccs $i_tccs_at_op
               }
            }

            lset data_row 0 $i_tccs
         }
      }
      add_row_to_table -id $panel_id $header_row
      add_row_to_table -id $panel_id $data_row

   }

   if {$is_gui == 0} {
      set_operating_conditions $orig_op_cond
      update_timing_netlist
   }

	
}

proc altera_iosubsystem_round_3dp { x } {
   return [expr { round($x * 1000) / 1000.0  } ]
}

proc altera_iosubsystem_get_periphery_clock_uncertainty { results_array_name } {
   upvar 1 $results_array_name results

   set speed_temp_grade [get_speedgrade_name]

   set c2p_setup  [altera_iosubsystem_round_3dp [expr [get_clock_uncertainty_data 900MV $speed_temp_grade LVDS SETUP C2P]*1e9 ]]
   set c2p_hold   [altera_iosubsystem_round_3dp [expr [get_clock_uncertainty_data 900MV $speed_temp_grade LVDS HOLD C2P]*1e9  ]]
   set p2c_setup  [altera_iosubsystem_round_3dp [expr [get_clock_uncertainty_data 900MV $speed_temp_grade LVDS SETUP P2C]*1e9 ]]
   set p2c_hold   [altera_iosubsystem_round_3dp [expr [get_clock_uncertainty_data 900MV $speed_temp_grade LVDS HOLD P2C]*1e9  ]]
   
   set results [list $c2p_setup $c2p_hold $p2c_setup $p2c_hold]
}

proc altera_iosubsystem_get_a10_iopll_workaround_present {} {
   set oscs [get_pins -nowarn -compatibility_mode *ALTERA_INSERTED_OSCILLATOR_FOR_IOPLL\|clkout]
   set num_oscs 0
   foreach_in_collection o $oscs {
      incr num_oscs
   }
   if {$num_oscs > 0} {
      return true
   } else {
      return false
   }
}


set ::RSKM_USE_MICRO 0
set ::TCCS_USE_MICRO 0
