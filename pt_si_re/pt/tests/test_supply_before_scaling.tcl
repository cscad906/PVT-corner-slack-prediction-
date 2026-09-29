# Run with: tclsh pt_si_re/pt/tests/test_supply_before_scaling.tcl
# Regression: supply connections determine which families need interpolation.
set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] .. run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

proc assert {value message} { if {!$value} { error $message } }
proc expect_error {script pattern} {
    set failed [catch {uplevel 1 $script} reason]
    assert [expr {$failed && [string match $pattern $reason]}] "Expected '$pattern', got '$reason'"
}
proc sizeof_collection {objects} { return [llength $objects] }
proc get_object_name {objects} { return $objects }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
set ::cell_lib [dict create launch CORE/FF logic CORE/INV memory LIMITED/INV]
set ::pin_rail [dict create launch/VDD VDD_SCALE logic/VDD VDD_SCALE memory/VDD VDD_FIXED]
set ::pg_queries 0
set ::group_queries 0
set ::catalog_queries 0
set ::groups_ready 0
proc get_cells {args} {
    if {[lsearch -exact $args -hierarchical] >= 0} { return [dict keys $::cell_lib] }
    return [lindex $args end]
}
proc get_lib_cells {args} {
    set result {}
    foreach cell [lindex $args end] { lappend result [dict get $::cell_lib $cell] }
    return [lsort -unique $result]
}
proc get_libs {args} {
    set result {}
    foreach cell [lindex $args end] { lappend result [lindex [split $cell /] 0] }
    return [lsort -unique $result]
}
proc get_pg_pins {args} {
    incr ::pg_queries
    set result {}
    foreach cell [lindex $args end] {
        foreach pin [dict keys $::pin_rail "$cell/*"] { lappend result $pin }
    }
    return $result
}
proc filter_collection {objects expression} { return $objects }
proc get_supply_nets {args} {
    if {[lsearch -exact $args -of_objects] >= 0} {
        return [dict get $::pin_rail [lindex $args end]]
    }
    return {VDD_SCALE VDD_FIXED}
}
proc get_attribute {args} {
    set objects [lindex $args end-1]
    set attribute [lindex $args end]
    switch -- $attribute {
        full_name { return $objects }
        pin_name { return [lindex [split $objects /] end] }
        supply_connection { return [dict get $::pin_rail $objects] }
        lib_cell {
            set result {}
            foreach cell $objects { lappend result [dict get $::cell_lib $cell] }
            return $result
        }
        lib_scaling_group {
            incr ::group_queries
            assert $::groups_ready "Supply classification must not depend on scaling groups"
            return {active_group}
        }
    }
    error "Unexpected attribute $attribute"
}
foreach command {set_voltage set_temperature define_scaling_lib_group update_timing read_db link_design} {
    proc $command {args} { error "Planning must not mutate the session" }
}
rename auto_scaling::catalog auto_scaling::native_catalog
proc auto_scaling::catalog {cfg} {
    incr ::catalog_queries
    set rows {}
    foreach {family voltages} {CORE {0.50 0.80} LIMITED {0.475 0.685} UNUSED {0.4 0.5}} {
        foreach v $voltages {
            lappend rows [dict create process SSPG v $v t 25 family $family \
                lib_name $family file /fixture/${family}_${v}.db]
        }
    }
    return [dict create rows $rows shadows {} ignored {}]
}
set fixed [dict create file /fixture/fixed_paths.tcl count 1 dtype max \
    paths {{path#42 launch/Q memory/Z {logic/A logic/Z memory/A}}}]
set cfg [dict create target_process SSPG target_v 0.76 target_t 25 target_beol rcmax \
    mode V resolved_fixed $fixed scaling_power_nets VDD_SCALE]

# A two-voltage library outside the requested range on a fixed rail must pass.
set plan [auto_scaling::plan $cfg]
assert [expr {[dict get $plan family] eq "CORE"}] "Fixed-rail family entered interpolation"
assert [expr {[dict get $plan fixed_rail_sets] eq "LIMITED"}] "Fixed-rail family not recorded"
assert [expr {$::group_queries == 0}] "Group queried before supply classification"
assert [expr {[llength [dict get $plan selected]] == 2}] "Wrong core inputs"
assert [expr {[string first "FIXED_RAIL_UNSCALED family=LIMITED" \
    [auto_scaling::scaling_inputs_text $plan]] >= 0}] "Missing fixed-rail evidence"
puts "PASS: target 0.76 ignores fixed-rail 0.475/0.685 set before groups exist"

# On the target rail the SAME library must retain its interpolation checks.
dict set ::pin_rail memory/VDD VDD_SCALE
expect_error {auto_scaling::plan $cfg} {*library set 'LIMITED'*Cannot bracket*}
dict set cfg target_v 0.54
set plan [auto_scaling::plan $cfg]
assert [expr {[llength [dict get $plan groups]] == 2}] "Both rail families must interpolate"
dict set cfg target_v 0.685
expect_error {auto_scaling::plan $cfg} {*library set 'LIMITED'*Cannot bracket*}
puts "PASS: same set on target rail interpolates at 0.54 and rejects 0.76/LOO endpoint"

# The declared exception is independent of target voltage and rail filtering.
dict set cfg fixed_library_set LIMITED
dict set cfg fixed_library_voltage 0.685
set plan [auto_scaling::plan $cfg]
assert [expr {[llength [dict get $plan groups]] == 1}] "Declared fixed set was interpolated"
dict set ::pin_rail memory/VDD VDD_FIXED
set plan [auto_scaling::plan $cfg]
assert [expr {[llength [dict get $plan fixed_library_rows]] == 2}] "Fixed DB validation policy lost"
dict set cfg fixed_library_set missing
expect_error {auto_scaling::plan $cfg} {*not a selected fixed-path library set*}
dict unset cfg fixed_library_set
dict unset cfg fixed_library_voltage
puts "PASS: explicit fixed exception preserved on both fixed and target rails"

# One common pattern selects numbered variants without merging families.
set families {macro_1 macro_2 CORE {literal[1]} literal1 {space name} space name {star*}}
assert [expr {[auto_scaling::resolve_fixed_families "macro_*" $families] eq {macro_1 macro_2}}] "Numbered variants not selected"
assert [expr {[auto_scaling::resolve_fixed_families "macro_1 macro_2" $families] eq {macro_1 macro_2}}] "Multiple exact names not selected"
assert [expr {[auto_scaling::resolve_fixed_families "" $families] eq {}}] "Blank option changed"
assert [expr {[auto_scaling::resolve_fixed_families {literal[1]} $families] eq {{literal[1]}}}] "Literal brackets changed"
assert [expr {[auto_scaling::resolve_fixed_families {literal[1]*} $families] eq {{literal[1]}}}] "Pattern matched brackets as a character class"
assert [expr {[auto_scaling::resolve_fixed_families "space name" $families] eq {{space name}}}] "Exact name with spaces lost precedence"
assert [expr {[auto_scaling::resolve_fixed_families {star*} $families] eq [list {star*}]}] "Exact star name lost precedence"
expect_error {auto_scaling::resolve_fixed_families "absent_*" $families} {*not a selected fixed-path library set*}
assert [expr {[auto_scaling::resolve_fixed_families "absent_*" $families 0] eq {}}] "Read-only non-strict query failed"

# Two fixed-path sets on the selected rail must both be declared fixed while
# CORE keeps its interpolation and target-exclusion rules.
rename auto_scaling::catalog auto_scaling::base_test_catalog
proc auto_scaling::catalog {cfg} {
    set data [base_test_catalog $cfg]
    foreach family {LIMITED_1 LIMITED_2} {
        foreach v {0.475 0.685} {
            dict lappend data rows [dict create process SSPG v $v t 25 family $family \
                lib_name $family file [format /fixture/%s_%s.db $family $v]]
        }
    }
    return $data
}
dict set ::cell_lib memory LIMITED_1/INV
dict set ::cell_lib memory2 LIMITED_2/INV
dict set ::pin_rail memory/VDD VDD_SCALE
dict set ::pin_rail memory2/VDD VDD_SCALE
set more_fixed $fixed
dict set more_fixed paths {{path#42 launch/Q memory/Z {logic/A logic/Z memory2/A memory2/Z memory/A}}}
dict set cfg resolved_fixed $more_fixed
dict set cfg target_v 0.76
dict set cfg fixed_library_set "LIMITED_*"
dict set cfg fixed_library_voltage 0.685
set plan [auto_scaling::plan $cfg]
assert [expr {[dict get $plan explicit_fixed_sets] eq {LIMITED_1 LIMITED_2}}] "Pattern expansion incorrect"
assert [expr {[llength [dict get $plan fixed_library_rows]] == 4}] "One fixed set lost"
assert [expr {[llength [dict get $plan groups]] == 1 && [dict get [lindex [dict get $plan groups] 0] family] eq "CORE"}] "Pattern leaked into core"
rename auto_scaling::catalog {}
rename auto_scaling::base_test_catalog auto_scaling::catalog
dict set ::cell_lib memory LIMITED/INV
dict unset ::cell_lib memory2
dict set ::pin_rail memory/VDD VDD_FIXED
dict unset ::pin_rail memory2/VDD
dict set cfg resolved_fixed $fixed
dict unset cfg fixed_library_set
dict unset cfg fixed_library_voltage
puts "PASS: numbered patterns, multiple/exact/blank selectors, literal brackets/spaces/stars, unmatched rejection, two fixed sets with core still scaled"

# A cell using two primary rails still needs interpolation for its target rail.
dict set ::pin_rail memory/VDDAUX VDD_SCALE
dict set cfg target_v 0.76
expect_error {auto_scaling::plan $cfg} {*library set 'LIMITED'*Cannot bracket*}
dict unset ::pin_rail memory/VDDAUX

# Reusing the early map avoids a second PG lookup. Existing groups of a fixed
# or unplanned set do not make its cells eligible for V/T overrides.
set supply [auto_scaling::classify_fixed_path_supply $fixed $cfg]
dict set cfg fixed_path_supply $supply
set before $::pg_queries
set plan [auto_scaling::plan $cfg]
dict set cfg scaling_library_names CORE
set ::groups_ready 1
set power [auto_scaling::plan_fixed_path_power $fixed $cfg]
assert [expr {[dict get $power scaled_cells] eq {launch logic}}] "Fixed rail entered V/T scope"
assert [expr {$::pg_queries == $before}] "PG connections queried twice"
dict set cfg fixed_path_supply [dict replace $supply voltage_groups \
    [list [dict create pin_name VDD cell_names {launch logic memory} rails VDD_SCALE]]]
set power [auto_scaling::plan_fixed_path_power $fixed $cfg]
assert [expr {[dict get $power scaled_cells] eq {launch logic}}] "Unplanned active library entered V/T scope"
puts "PASS: shared/multiple rails respected, cached PG map reused, unplanned groups excluded"

# An unknown connection or missing PG pin must not silently become fixed.
dict unset cfg fixed_path_supply
dict set ::pin_rail memory/VDD UNKNOWN_RAIL
set before $::catalog_queries
expect_error {auto_scaling::plan $cfg} {FP-007:*}
assert [expr {$::catalog_queries == $before}] "Libraries checked before unknown supply error"
dict unset ::pin_rail memory/VDD
expect_error {auto_scaling::plan $cfg} {FP-006:*}
dict set ::pin_rail memory/VDD VDD_FIXED
dict set ::pin_rail launch/VDD VDD_FIXED
dict set ::pin_rail logic/VDD VDD_FIXED
expect_error {auto_scaling::plan $cfg} {FP-008:*}
puts "PASS: unknown/missing supplies and no target-rail cells stop before interpolation"

# Library conditions must not turn 0.685 V into 0.69 V. Preserve the user's
# report precision on success/error, including an originally higher setting.
proc get_app_var {name} { return $::report_digits }
proc set_app_var {name value} { set ::report_digits $value; lappend ::precision_changes $value }
proc redirect {option variable body} {
    upvar 1 $variable captured
    set captured [uplevel 1 $body]
}
proc report_lib {args} {
    if {$::fail_report} { error "Fixture report failure" }
    return "Operating Conditions:\nName Process Temp Voltage\nNOM 1.0 25 [format %.*f $::report_digits 0.685]\n\n"
}
foreach saved {2 6 11} {
    set ::report_digits $saved
    set ::precision_changes {}
    set ::fail_report 0
    set condition [auto_scaling::report_operating_condition LIB /fixture/lib.db]
    assert [expr {abs([dict get $condition v] - 0.685) < 1e-8}] "Nominal voltage was rounded"
    assert [expr {$::report_digits == $saved}] "Report precision not restored on success"
    if {$saved == 6} { assert [expr {$::precision_changes eq {}}] "Matching precision changed unnecessarily" }
    set ::fail_report 1
    expect_error {auto_scaling::report_operating_condition LIB /fixture/lib.db} {*Fixture report failure*}
    assert [expr {$::report_digits == $saved}] "Report precision not restored on error"
}
puts "PASS: exact nominal voltage read without rounding, report precision preserved on success/failure"
puts "ALL SUPPLY-BEFORE-SCALING TESTS PASSED"
