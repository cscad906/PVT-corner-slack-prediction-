# Run with: tclsh pt_si_re/pt/tests/test_umem_native_group.tcl
# Native multirail preflight and cell-only power verification, without company DBs.
set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] .. run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

proc check {condition message} { if {!$condition} { error $message } }
proc expect_error {script pattern} {
    set failed [catch {uplevel 1 $script} reason]
    check [expr {$failed && [string match $pattern $reason]}] "Expected $pattern; got $reason"
}
proc sizeof_collection {objects} { return [llength $objects] }
proc get_object_name {objects} { return $objects }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
proc get_cells {args} {
    if {[lsearch -exact $args -of_objects] >= 0} {
        return {top/u_mem0 top/u_mem_control}
    }
    return [lindex $args end]
}
proc get_pg_pins {args} { return {top/u_mem0/VDDPE} }
proc get_lib_cells {args} { return {MEM_LO/CELL} }
proc get_libs {args} { return {MEM_LO} }
proc get_attribute {args} {
    set object [lindex $args end-1]
    set attribute [lindex $args end]
    switch -- $attribute {
        full_name { return $object }
        lib_cell {
            set result {}
            foreach cell $object {
                if {$cell eq "top/u_logic"} {
                    lappend result CORE/LOGIC
                } else {
                    lappend result MEM_LO/CELL
                }
            }
            return $result
        }
        pin_name { return VDDPE }
        type { return primary_power }
        lib_scaling_group { return {MEM_LO MEM_HI} }
    }
    error "Unexpected attribute $attribute"
}
proc redirect {args} {
    set index [lsearch -exact $args -variable]
    if {$index < 0} { error "Unexpected redirect args" }
    upvar 1 [lindex $args [expr {$index+1}]] output
    set output [uplevel 1 [lindex $args end]]
}
set ::native_report {Group    Library     Temperature Voltage          Process
Group 1
    MEM_LO       25.00       { V:0.475 VDDPE:0.475 } 1.00
    MEM_HI       25.00       { V:0.685 VDDPE:0.685 } 1.00
1}
proc report_lib_groups {args} { return $::native_report }

set supply [dict create path_cells {top/u_mem0 top/u_logic}]
set cfg [dict create target_vddpe 0.54 target_t 25 target_v 0.54 \
    vddpe_name_patterns {*u_mem*}]
set native [auto_scaling::native_umem_scope $supply $cfg]
check [expr {[dict get [auto_scaling::native_umem_scope [dict create path_cells {top/u_logic}] [dict replace $cfg target_vddpe ""]] cell_names] eq ""}] "Empty u_mem scope requires no setting"
check [expr {[dict get $native cell_names] eq {top/u_mem0}}] "Wrong fixed-path macro scope"
check [expr {[dict get [auto_scaling::native_umem_scope $supply [dict replace $cfg vddpe_name_patterns {*nomatch*, MEM_*}]] cell_names] eq {top/u_mem0}}] "Linked-library wildcard did not select the macro"
check [expr {[dict get [auto_scaling::native_umem_scope $supply [dict replace $cfg vddpe_name_patterns ""]] cell_names] eq ""}] "Blank pattern did not disable macro selection"
expect_error {auto_scaling::native_umem_scope $supply [dict replace $cfg vddpe_name_patterns {*u_mem*,,MEM_*}]} {UM-020:*}
check [expr {[dict get [dict get [dict get $native groups] MEM_LO] bracket] eq {0.475 0.685}}] "Native VDDPE bracket lost"
check [expr {[auto_scaling::umem_control_cells $native] eq {top/u_mem_control}}] "Control instance not identified"
expect_error {auto_scaling::native_umem_scope $supply [dict replace $cfg target_vddpe ""]} {UM-001:*}
expect_error {auto_scaling::native_umem_scope $supply [dict replace $cfg target_vddpe 0.685]} {UM-015:*}
expect_error {auto_scaling::native_umem_scope $supply [dict replace $cfg target_vddpe 0.76]} {UM-009:*}
set original_report $::native_report
append ::native_report "\n    MEM_TARGET    25.00       { V:0.540 VDDPE:0.540 } 1.00"
expect_error {auto_scaling::native_umem_scope $supply $cfg} {UM-015:*}
set ::native_report $original_report
set ::native_report [string map {VDDPE OTHER} $::native_report]
expect_error {auto_scaling::native_umem_scope $supply $cfg} {UM-006:*}

set before_pins {Cell Power Pin Name Type Voltage Power Net Connected
top/u_mem0 VDDPE primary_power 0.475 MEM_NET
top/u_mem_control VDDPE primary_power 0.475 MEM_NET}
set after_pins {Cell Power Pin Name Type Voltage Power Net Connected
top/u_mem0 VDDPE primary_power 0.540 MEM_NET
top/u_mem_control VDDPE primary_power 0.475 MEM_NET}
set supply_report {Supply Net : MEM_NET
Max-delay Voltage : 0.475
Min-delay Voltage : 0.475}
set before [dict create pins_report $before_pins nets_report $supply_report \
    pins [auto_scaling::umem_pin_voltages $before_pins {top/u_mem0 top/u_mem_control}] \
    nets [auto_scaling::umem_supply_voltages $supply_report]]
set after [dict create pins_report $after_pins nets_report $supply_report \
    pins [auto_scaling::umem_pin_voltages $after_pins {top/u_mem0 top/u_mem_control}] \
    nets [auto_scaling::umem_supply_voltages $supply_report]]
set test_dir [file join /tmp "umem_native_test_[pid]"]
set out [file join $test_dir report.rpt]
auto_scaling::verify_umem_power $out $native {top/u_mem_control} $before $after
dict set after pins [list top/u_mem_control VDDPE] 0.54
expect_error {auto_scaling::verify_umem_power $out $native {top/u_mem_control} $before $after} {U_MEM power verification failed:*}
dict set after pins [list top/u_mem_control VDDPE] 0.475
dict set after nets [list MEM_NET {Max-delay Voltage}] 0.54
expect_error {auto_scaling::verify_umem_power $out $native {top/u_mem_control} $before $after} {U_MEM power verification failed:*}
file delete -force $test_dir
puts "ALL U_MEM NATIVE GROUP TESTS PASSED"
