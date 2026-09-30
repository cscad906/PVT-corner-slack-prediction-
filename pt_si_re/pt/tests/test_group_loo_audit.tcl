# Run: tclsh pt_si_re/pt/tests/test_group_loo_audit.tcl
set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] .. run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

proc check {condition message} { if {!$condition} { error $message } }
set ::core_report {Group    Library   Temperature Voltage Process
Group 1
    CORE_LO      25.00       { VDD:0.540 VSS:0.0 } 1.0
    CORE_TARGET  25.00       { VDD:0.685 VSS:0.0 } 1.0
    CORE_HI      25.00       { VDD:0.800 VSS:0.0 } 1.0
1}
set ::mem_report {Group    Library   Temperature Voltage Process
Group 2
    MEM_LO       25.00       { V:0.475 VDDPE:0.475 } 1.0
    MEM_TARGET   25.00       { V:0.685 VDDPE:0.685 } 1.0
    MEM_HI       25.00       { V:0.800 VDDPE:0.800 } 1.0
1}
check [expr {[auto_scaling::group_rail_target_status $::core_report VDD 0.685 25] eq "TARGET"}] \
    "Core target not detected"
check [expr {[auto_scaling::group_rail_target_status $::mem_report VDDPE 0.685 25] eq "TARGET"}] \
    "u_mem VDDPE target not detected"
check [expr {[auto_scaling::group_rail_target_status $::mem_report V 0.54 25] eq "ABSENT"}] \
    "Wrong core voltage matched u_mem group"
check [expr {[auto_scaling::group_rail_target_status $::mem_report UNKNOWN 0.685 25] eq "RAIL_UNVERIFIED"}] \
    "Missing rail was silently accepted"
check [expr {[auto_scaling::group_rail_target_status \
    [string map {0.685 0.69} $::mem_report] VDDPE 0.685 25] eq "TARGET"}] \
    "Rounded target was missed"

proc sizeof_collection {items} { return [llength $items] }
proc get_object_name {items} { return $items }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
proc get_cells {args} { return [lindex $args end] }
proc get_lib_cells {args} {
    set result {}
    foreach cell [lindex $args end] {
        switch -- $cell {
            u_logic { lappend result CORE_LO/INV }
            u_mem { lappend result MEM_LO/CELL }
            default { error "Unknown cell $cell" }
        }
    }
    return $result
}
proc get_libs {args} {
    set result {}
    foreach cell [lindex $args end] {
        lappend result [lindex [split $cell /] 0]
    }
    return [lsort -unique $result]
}
proc get_attribute {args} {
    set object [lindex $args end-1]
    set attr [lindex $args end]
    switch -- $attr {
        lib_cell {
            set result {}
            foreach cell $object {
                if {$cell eq "u_logic"} { lappend result CORE_LO/INV }
                if {$cell eq "u_mem"} { lappend result MEM_LO/CELL }
            }
            return $result
        }
        full_name { return $object }
        lib_scaling_group {
            if {$object eq "CORE_LO"} { return {CORE_LO CORE_TARGET CORE_HI} }
            return {MEM_LO MEM_TARGET MEM_HI}
        }
        source_file_name { return /fixture/${object}.db }
    }
    error "Unknown attribute $attr"
}
proc add_to_collection {group lib} { return $group }
proc redirect {args} {
    set index [lsearch -exact $args -variable]
    upvar 1 [lindex $args [expr {$index+1}]] output
    set output [uplevel 1 [lindex $args end]]
}
proc report_lib_groups {args} {
    if {[lsearch -exact $args CORE_LO] >= 0} { return $::core_report }
    return $::mem_report
}
foreach command {set_voltage set_temperature define_scaling_lib_group update_timing} {
    proc $command {args} { error "Audit must be read-only" }
}
set supply [dict create path_cells {u_logic u_mem} \
    voltage_groups [list [dict create pin_name VDD cell_names {u_logic} rails VDD_SCALE]]]
set cfg [dict create target_t 25 target_v 0.685 target_vddpe 0.685 \
    vddpe_name_patterns *u_mem*]
set findings [auto_scaling::audit_fixed_path_group_targets $supply $cfg]
check [expr {[llength $findings] == 2}] "Expected both core and u_mem target groups"
set roles {}
foreach finding $findings { lappend roles [dict get $finding role] }
check [expr {[lsort $roles] eq {CORE U_MEM}}] "Wrong audit roles: $roles"
puts "ALL GROUP LOO AUDIT TESTS PASSED"
