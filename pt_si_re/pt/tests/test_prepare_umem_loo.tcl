# Run: tclsh pt_si_re/pt/tests/test_prepare_umem_loo.tcl
set ::umem_loo_prepare_load_only 1
source [file join [file dirname [info script]] .. prepare_umem_loo.tcl]
unset ::umem_loo_prepare_load_only

proc assert {condition message} { if {!$condition} { error $message } }
proc expect_error {script pattern} {
    set failed [catch {uplevel 1 $script} reason]
    assert [expr {$failed && [string match $pattern $reason]}] \
        "Expected $pattern; got $reason"
}

set members {{MEM_LO /fixture/lo.db} {MEM_TARGET /fixture/target.db} {MEM_HI /fixture/hi.db}}
set report {Group    Library       Temperature  Voltage                    Process
Group 1
    MEM_LO       25.00        { V:0.475 VDDPE:0.475 }     1.00
    MEM_TARGET   25.00        { V:0.685 VDDPE:0.685 }     1.00
    MEM_HI       25.00        { V:0.800 VDDPE:0.800 }     1.00
1}
set plan [umem_loo::select_members $members $report {MEM_LO} 25 0.685]
assert [expr {[dict get $plan excluded] eq {{MEM_TARGET /fixture/target.db}}}] \
    "Target DB was not excluded"
assert [expr {[dict get $plan bracket] eq {0.475 0.8}}] \
    "Wrong VDDPE bracket"
assert [expr {[llength [dict get $plan kept]] == 2}] \
    "Wrong group size after LOO"
expect_error {umem_loo::select_members $members $report {MEM_TARGET} 25 0.685} {UML-007:*}
set rounded [string map {0.685 0.69} $report]
set rounded_plan [umem_loo::select_members $members $rounded {MEM_LO} 25 0.685]
assert [expr {[dict get $rounded_plan excluded] eq {{MEM_TARGET /fixture/target.db}}}] \
    "Rounded target DB was not excluded"
expect_error {umem_loo::select_members [lrange $members 0 1] \
    [string map {MEM_HI OMIT_HI} $report] {MEM_LO} 25 0.685} {UML-008:*}
expect_error {umem_loo::select_members $members $report {MEM_LO} 25 0.76} {UML-006:*}
expect_error {umem_loo::select_members $members \
    [string map {VDDPE OTHER} $report] {MEM_LO} 25 0.685} {UML-002:*}

# The current full-group session can only generate a plan. Re-sourcing that
# plan there must fail before define_scaling_lib_group, while a group-free
# fixture must define exactly the retained two DBs.
rename auto_scaling::build_restore_config auto_scaling::original_build_restore_config
proc auto_scaling::build_restore_config {} {
    return [dict create target_vddpe 0.685 target_t 25 \
        fixed_tcl /fixture/fixed.tcl delay_type max \
        vddpe_name_patterns *u_mem*]
}
rename auto_scaling::read_fixed auto_scaling::original_read_fixed
proc auto_scaling::read_fixed {path dtype} { return [dict create paths {}] }
rename auto_scaling::fixed_path_cells auto_scaling::original_fixed_path_cells
proc auto_scaling::fixed_path_cells {fixed} { return {top/u_mem0} }
proc sizeof_collection {items} { return [llength $items] }
proc get_object_name {items} { return $items }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
proc get_cells {args} { return {top/u_mem0} }
proc get_lib_cells {args} { return {MEM_LO/CELL} }
proc get_libs {args} {
    if {$args eq {-quiet *}} { return {MEM_LO MEM_TARGET MEM_HI} }
    return {MEM_LO}
}
proc get_pg_pins {args} { return {top/u_mem0/VDDPE} }
proc add_to_collection {a b} { return $a }
proc current_design {} { return TOP }
set ::mock_active 1
set ::mock_defs {}
proc define_scaling_lib_group {dbs} { lappend ::mock_defs $dbs }
proc get_attribute {args} {
    set object [lindex $args end-1]
    set attr [lindex $args end]
    switch -- $attr {
        lib_cell { return {MEM_LO/CELL} }
        pin_name { return VDDPE }
        type { return primary_power }
        full_name { return $object }
        lib_scaling_group {
            if {[info exists ::mock_groups] && [dict exists $::mock_groups $object]} {
                return [dict get $::mock_groups $object]
            }
            if {$::mock_active} { return {MEM_LO MEM_TARGET MEM_HI} }
            return {}
        }
        source_file_name {
            set names [dict create MEM_LO /fixture/lo.db \
                MEM_TARGET /fixture/target.db MEM_HI /fixture/hi.db]
            return [dict get $names $object]
        }
    }
    error "Unexpected attribute $attr"
}
proc redirect {args} {
    set index [lsearch -exact $args -variable]
    upvar 1 [lindex $args [expr {$index+1}]] output
    set output [uplevel 1 [lindex $args end]]
}
proc report_lib_groups {args} { return $::report }
set test_dir [file join /tmp "umem_loo_test_[pid]"]
set ::RESULT_FOLDER $test_dir
set ::TARGET_VDDPE_VOLTAGE 0.685
set ::TARGET_TEMPERATURE 25
set ::FIXED_PATH_FILE /fixture/fixed.tcl
set ::VDDPE_SCALING_NAME_PATTERNS *u_mem*
set generated [umem_loo::prepare]
assert [file isfile $generated] "LOO group Tcl was not generated"
expect_error {source $generated} {UML-019:*}
assert [expr {$::mock_defs eq {}}] "Current session was mutated"
set ::mock_active 0
source $generated
assert [expr {[llength $::mock_defs] == 1 &&
    [lsort [lindex $::mock_defs 0]] eq {/fixture/hi.db /fixture/lo.db}}] \
    "Generated group includes target or misses source DB"

set scalar [list [dict create name CORE dbs {/fixture/lo.db /fixture/hi.db}]]
set ::mock_defs {}
auto_scaling::define_missing_scalar_groups $scalar
assert [expr {[llength $::mock_defs] == 1}] "Ungrouped scalar set was not defined"
set ::mock_defs {}
set ::mock_groups [dict create MEM_LO {MEM_LO MEM_HI} MEM_HI {MEM_LO MEM_HI}]
auto_scaling::define_missing_scalar_groups $scalar
assert [expr {$::mock_defs eq {}}] "Existing whole scalar group was redefined"
dict set ::mock_groups MEM_HI {MEM_HI}
expect_error {auto_scaling::define_missing_scalar_groups $scalar} {*different active groups*}
dict set ::mock_groups MEM_HI {}
expect_error {auto_scaling::define_missing_scalar_groups $scalar} {*only partly grouped*}
file delete -force $test_dir
puts "ALL U_MEM LOO PREPARATION TESTS PASSED"
