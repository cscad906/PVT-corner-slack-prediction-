# Run: tclsh pt_si_re/pt/tests/test_multi_scaling_nets.tcl
# SCALING_POWER_NET may list one or more nets; every listed net is a scaling
# rail at the same TARGET_VOLTAGE, and unlisted nets stay fixed.
set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] .. run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

proc check {condition message} { if {!$condition} { error $message } }
proc expect_error {script pattern} {
    if {![catch {uplevel 1 $script} reason]} { error "Expected error $pattern" }
    if {![string match $pattern $reason]} { error "Wrong error: $reason (expected $pattern)" }
}

# Parsing: spaces, commas, both; single net unchanged.
check [expr {[auto_scaling::scaling_net_list "VDD"] eq {VDD}}] "Single net changed"
check [expr {[auto_scaling::scaling_net_list " VDD  VDD_CPU "] eq {VDD VDD_CPU}}] "Space list failed"
check [expr {[auto_scaling::scaling_net_list "VDD,VDD_CPU"] eq {VDD VDD_CPU}}] "Comma list failed"
check [expr {[auto_scaling::scaling_net_list "VDD, VDD_CPU u_top/VDD_GPU"] eq {VDD VDD_CPU u_top/VDD_GPU}}] \
    "Mixed list failed"
expect_error {auto_scaling::scaling_net_list ""} {Set SCALING_POWER_NET*}
expect_error {auto_scaling::scaling_net_list "VDD,,VDD_CPU"} {*empty comma-separated item*}
expect_error {auto_scaling::scaling_net_list "VDD,"} {*empty comma-separated item*}
expect_error {auto_scaling::scaling_net_list "VDD VDD_CPU VDD"} {*lists 'VDD' twice*}

# build_restore_config stores a proper list (it used to wrap the whole string).
set ::SCALING_POWER_NET "VDD_A VDD_B"
check [expr {[dict get [auto_scaling::build_restore_config] scaling_power_nets] eq {VDD_A VDD_B}}] \
    "Config did not keep two nets"
set ::SCALING_POWER_NET "VDD_A"
check [expr {[dict get [auto_scaling::build_restore_config] scaling_power_nets] eq {VDD_A}}] \
    "Config changed a single net"
puts "PASS: SCALING_POWER_NET parsing (space/comma, empty item, duplicate, single net unchanged)"

# Supply classification with two scaling nets and one fixed net.
proc sizeof_collection {objects} { return [llength $objects] }
proc get_object_name {objects} { return $objects }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
set ::pin_rail [dict create cpu/VDD VDD_A gpu/VDD VDD_B io/VDD VDD_FIXED]
proc get_cells {args} { return [lindex $args end] }
proc get_pg_pins {args} {
    set result {}
    foreach cell [lindex $args end] {
        foreach pin [dict keys $::pin_rail "$cell/*"] { lappend result $pin }
    }
    return $result
}
proc filter_collection {objects expression} { return $objects }
proc get_supply_nets {args} {
    if {[lsearch -exact $args -of_objects] >= 0} { return [dict get $::pin_rail [lindex $args end]] }
    return {VDD_A VDD_B VDD_FIXED}
}
proc get_attribute {args} {
    set objects [lindex $args end-1]
    switch -- [lindex $args end] {
        full_name { return $objects }
        pin_name { return [lindex [split $objects /] end] }
        supply_connection { return [dict get $::pin_rail $objects] }
    }
    error "Unexpected attribute [lindex $args end]"
}
foreach command {set_voltage set_temperature define_scaling_lib_group update_timing} {
    proc $command {args} { error "Classification must not mutate the session" }
}
set fixed [dict create paths {{p#1 cpu/Q io/A {gpu/A gpu/Z}}}]

set cfg [dict create scaling_power_nets {VDD_A VDD_B}]
set roles [auto_scaling::resolve_configured_supply_roles $cfg]
check [expr {[dict get $roles VDD_A] eq "scaling" && [dict get $roles VDD_B] eq "scaling" &&
    [dict get $roles VDD_FIXED] eq "fixed"}] "Wrong roles for two scaling nets: $roles"
dict set cfg configured_supply_roles $roles
set supply [auto_scaling::classify_fixed_path_supply $fixed $cfg]
check [expr {[lsort [dict get $supply target_cells]] eq {cpu gpu}}] \
    "Both scaling nets' cells must be targets: [dict get $supply target_cells]"
check [expr {[dict get $supply fixed_cell_names] eq {io}}] "Fixed-net cell misclassified"
set group [lindex [dict get $supply voltage_groups] 0]
check [expr {[lsort [dict get $group rails]] eq {VDD_A VDD_B}}] "Voltage group lost a rail"

# Listing only one of the two nets leaves the other net's cells fixed (the
# silent case the user must check in AUTO-FIXED POWER NETS).
set cfg [dict create scaling_power_nets {VDD_A}]
dict set cfg configured_supply_roles [auto_scaling::resolve_configured_supply_roles $cfg]
set supply [auto_scaling::classify_fixed_path_supply $fixed $cfg]
check [expr {[dict get $supply target_cells] eq {cpu}}] "Single-net config scaled the other net"
check [expr {[lsort [dict get $supply fixed_cell_names]] eq {gpu io}}] "Unlisted net not fixed"

# A net named twice through two spellings still stops.
expect_error {auto_scaling::resolve_configured_supply_roles [dict create scaling_power_nets {VDD_A VDD_A}]} \
    {*configured twice*}
expect_error {auto_scaling::resolve_configured_supply_roles [dict create scaling_power_nets {VDD_A VDD_X}]} \
    {*'VDD_X' was not found*}
puts "PASS: two scaling nets classify both rails as targets; unlisted nets stay fixed"
puts "ALL MULTI SCALING NET TESTS PASSED"
