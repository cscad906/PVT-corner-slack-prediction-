# Run: tclsh pt_si_re/pt/tests/test_net_scope.tcl
# Net-mode scaling (run_scaling_after_restore_net.tcl): config checks
# NET-010..NET-013, net-scope counting (one and two scaling nets, UPF
# segments, non-primary-only and mixed-rail cells, name fallback), NET-001,
# NET-002/NET-003 evidence parsing, and USER SETTINGS preservation.
set ::auto_scaling_restored_load_only 1
set test_dir [file dirname [file normalize [info script]]]
set pt_dir [file dirname $test_dir]
source [file join $pt_dir run_scaling_after_restore_net.tcl]

proc check {condition message} { if {!$condition} { error $message } }
proc expect_error {script pattern} {
    if {![catch {uplevel 1 $script} reason]} { error "Expected error $pattern" }
    if {![string match $pattern $reason]} { error "Wrong error: $reason (expected $pattern)" }
    return $reason
}
proc read_file {path} {
    set fp [open $path r]
    set text [read $fp]
    close $fp
    return $text
}
proc write_file {path text} {
    set fp [open $path w]
    puts -nonewline $fp $text
    close $fp
}

check [expr {$::auto_scaling_restored_load_only == 1}] "Sourcing the net file changed the load-only flag"
check [expr {[llength [info procs ::auto_scaling::run_after_restore]] == 1}] "Original procedures were not loaded"
check [expr {[llength [info procs ::auto_scaling_net::run_after_restore]] == 1}] "Net procedures were not defined"

set tmp [file join [expr {[info exists ::env(TMPDIR)] ? $::env(TMPDIR) : "/tmp"}] net_scope_test_[pid]]
file mkdir $tmp

# ---------------------------------------------------------------------------
# 1. USER SETTINGS of the net file survive sourcing the original.
# ---------------------------------------------------------------------------
set copy_dir [file join $tmp scripts]
file mkdir $copy_dir
file copy -force [file join $pt_dir run_scaling_after_restore.tcl] [file join $copy_dir run_scaling_after_restore.tcl]
set net_text [read_file [file join $pt_dir run_scaling_after_restore_net.tcl]]
foreach {pattern replacement} {
    {set TARGET_PROCESS      "SSPG"} {set TARGET_PROCESS      "NETPROC"}
    {set TARGET_VOLTAGE      0.75} {set TARGET_VOLTAGE      0.123}
    {set SCALING_POWER_NET ""} {set SCALING_POWER_NET "VDD_X, VDD_Y"}
    {set VDDPE_SCALING_NAME_PATTERNS "*u_mem*"} {set VDDPE_SCALING_NAME_PATTERNS ""}
} {
    check [expr {[string first $pattern $net_text] >= 0}] "Net USER SETTINGS line not found: $pattern"
    set net_text [string map [list $pattern $replacement] $net_text]
}
write_file [file join $copy_dir run_scaling_after_restore_net.tcl] $net_text
set original_text [read_file [file join $pt_dir run_scaling_after_restore.tcl]]
check [string match "*set TARGET_PROCESS      \"SSPG\"*" $original_text] "Original USER SETTINGS changed; update this test"
source [file join $copy_dir run_scaling_after_restore_net.tcl]
check [expr {$::TARGET_PROCESS eq "NETPROC"}] "TARGET_PROCESS was overwritten by the original: $::TARGET_PROCESS"
check [expr {$::TARGET_VOLTAGE eq "0.123"}] "TARGET_VOLTAGE was overwritten: $::TARGET_VOLTAGE"
check [expr {$::SCALING_POWER_NET eq "VDD_X, VDD_Y"}] "SCALING_POWER_NET was overwritten: $::SCALING_POWER_NET"
check [expr {$::VDDPE_SCALING_NAME_PATTERNS eq ""}] "VDDPE patterns were overwritten"
check [expr {$::auto_scaling_restored_load_only == 1}] "Load-only flag not restored to 1"
# The flag goes back to unset when it was unset before loading.
unset ::auto_scaling_restored_load_only
auto_scaling_net::load_original
check [expr {![info exists ::auto_scaling_restored_load_only]}] "Load-only flag left set after load_original"
check [expr {$::TARGET_PROCESS eq "NETPROC"}] "load_original did not restore settings"
set ::auto_scaling_restored_load_only 1
# build_config: two nets (comma), "_net" report name, original filename rules.
set cfg [auto_scaling_net::build_config]
check [expr {[dict get $cfg scaling_power_nets] eq {VDD_X VDD_Y}}] "Two nets not kept: [dict get $cfg scaling_power_nets]"
check [string match "*/scaled_NETPROC_0p123V_25C_RCMAX_V_setup_net.rpt" [dict get $cfg out_rpt]] \
    "Wrong net report name: [dict get $cfg out_rpt]"
check [string match "*/restored_scaled_NETPROC_0p123V_25C_RCMAX_V_setup_net.rpt" [auto_scaling_net::actual_report $cfg]] \
    "Wrong actual report name"
set ::SCALING_POWER_NET "VDD_X"
check [expr {[dict get [auto_scaling_net::build_config] scaling_power_nets] eq {VDD_X}}] "Single net changed"
set ::FIXED_LIBRARY_SET "macro_*"
expect_error {auto_scaling_net::build_config} {NET-010:*}
set ::FIXED_LIBRARY_SET ""
# Back to the repository copy for the remaining tests.
source [file join $pt_dir run_scaling_after_restore_net.tcl]
check [expr {$::TARGET_PROCESS eq "SSPG" && $::SCALING_POWER_NET eq ""}] "Repository settings not reloaded"
puts "PASS: net USER SETTINGS survive sourcing the original; load-only flag restored; two-net config and _net name"

# ---------------------------------------------------------------------------
# 2. Config checks NET-010..NET-013 and report names.
# ---------------------------------------------------------------------------
set base [dict create target_v 0.6 mode V fixed_library_set "" target_vddpe "" scaling_power_nets {VDD}]
auto_scaling_net::check_config $base
auto_scaling_net::check_config [dict replace $base target_vddpe 0.600]
auto_scaling_net::check_config [dict replace $base scaling_power_nets {VDD VDD_CPU}]
expect_error {auto_scaling_net::check_config [dict replace $base fixed_library_set "macro_*"]} {NET-010:*}
expect_error {auto_scaling_net::check_config [dict replace $base mode VT]} {NET-011:*}
expect_error {auto_scaling_net::check_config [dict replace $base mode T]} {NET-011:*}
expect_error {auto_scaling_net::check_config [dict replace $base target_vddpe 0.7]} {NET-012:*}
expect_error {auto_scaling_net::check_config [dict replace $base target_vddpe abc]} {NET-012:*}
expect_error {auto_scaling_net::check_config [dict replace $base scaling_power_nets [list "VDD VDD_CPU"]]} {NET-013:*}
check [expr {[auto_scaling_net::net_report_name /r/scaled_A_setup.rpt] eq "/r/scaled_A_setup_net.rpt"}] "net_report_name"
check [expr {[auto_scaling_net::net_report_name /r/scaled_A_setup_net.rpt] eq "/r/scaled_A_setup_net.rpt"}] "net_report_name not idempotent"
# Own sidecars are cleared on rerun; other files stay.
set out [file join $tmp result restored_scaled_A_setup_net.rpt]
foreach suffix {.net_scope.txt .net_power.txt .clock.dcalc .dcalc} {
    auto_scaling::write_text [auto_scaling::detail_path $out $suffix] old
}
check [expr {[auto_scaling_net::reset_net_sidecars $out] == 3}] "Wrong sidecar reset count"
check [file exists [auto_scaling::detail_path $out .dcalc]] "reset_net_sidecars removed a non-net file"
check [expr {![file exists [auto_scaling::detail_path $out .net_scope.txt]]}] "net_scope sidecar not removed"
puts "PASS: NET-010/011/012/013 config checks, report names, sidecar reset"

# ---------------------------------------------------------------------------
# 3. PrimeTime stubs. Collections are Tcl lists of object names.
# ---------------------------------------------------------------------------
proc sizeof_collection {items} { return [llength $items] }
proc get_object_name {items} { return $items }
proc foreach_in_collection {name objects body} {
    upvar 1 $name item
    foreach item $objects { uplevel 1 $body }
}
proc index_collection {items first {last ""}} {
    if {$last eq ""} { set last $first }
    return [lrange $items $first $last]
}
proc add_to_collection {args} {
    set args [lsearch -all -inline -not -exact $args -unique]
    set result [lindex $args 0]
    foreach item [lindex $args 1] { if {[lsearch -exact $result $item] < 0} { lappend result $item } }
    return $result
}
proc append_to_collection {var items} {
    upvar 1 $var value
    foreach item $items { lappend value $item }
}
proc remove_from_collection {args} {
    set intersect [expr {[lsearch -exact $args -intersect] >= 0}]
    set args [lsearch -all -inline -not -exact $args -intersect]
    lassign $args base other
    set result {}
    foreach item $base {
        set found [expr {[lsearch -exact $other $item] >= 0}]
        if {$found == $intersect} { lappend result $item }
    }
    return $result
}
proc option_value {args name} {
    set i [lsearch -exact $args $name]
    if {$i < 0} { return "" }
    return [lindex $args [expr {$i + 1}]]
}
foreach command {set_voltage set_temperature define_scaling_lib_group update_timing size_cell} {
    proc $command {args} { error "Scope and group checks must be read-only" }
}

# Fixture: cells -> {lib ref hier}; pins -> {type net conn}. "conn" is the
# supply_connection string; "net" is what get_supply_nets -of_objects returns.
proc load_fixture {} {
    set ::fx_cells [dict create \
        u_ck    {lib CORE_A ref BUF hier false} \
        u_ff1   {lib CORE_A ref FF hier false} \
        u_ff2   {lib CORE_A ref FF hier false} \
        u_inv   {lib CORE_B ref INV hier false} \
        u_ret   {lib RET ref RFF hier false} \
        u_ls    {lib LS ref LSH hier false} \
        u_mem0  {lib MEM ref SRAM hier false} \
        u_cpu1  {lib CORE_A ref FF hier false} \
        u_cpu2  {lib CORE_B ref INV hier false} \
        u_ao    {lib CORE_A ref INV hier false} \
        u_sub   {lib "" ref sub hier true} \
        u_sub/u_x {lib CORE_A ref INV hier false}]
    set ::fx_pins [dict create]
    foreach {pin type net} {
        u_ck/VDD primary_power VDD      u_ck/VSS primary_ground VSS
        u_ff1/VDD primary_power VDD     u_ff1/VDDR primary_power VDD    u_ff1/VSS primary_ground VSS
        u_ff2/VDD primary_power VDD     u_ff2/VDDR primary_power VDD    u_ff2/VSS primary_ground VSS
        u_inv/VDD primary_power VDD     u_inv/VSS primary_ground VSS
        u_ret/VDD primary_power VDD_AO  u_ret/VDDB backup_power VDD     u_ret/VSS primary_ground VSS
        u_ls/VDDL primary_power VDD     u_ls/VDDH primary_power VDD_AO  u_ls/VSS primary_ground VSS
        u_mem0/VDD primary_power VDD    u_mem0/VDDPE primary_power VDD  u_mem0/VSS primary_ground VSS
        u_cpu1/VDD primary_power VDD_CPU u_cpu1/VSS primary_ground VSS
        u_cpu2/VDD primary_power VDD_CPU u_cpu2/VSS primary_ground VSS
        u_ao/VDD primary_power VDD_AO   u_ao/VSS primary_ground VSS
        u_sub/u_x/VDD primary_power u_sub/VDDS u_sub/u_x/VSS primary_ground VSS
    } {
        dict set ::fx_pins $pin [dict create type $type net $net conn $net]
    }
    set ::fx_nets {VDD VDD_CPU VDD_AO VSS u_sub/VDDS}
    set ::fx_segments [dict create VDD {u_sub/VDDS VDD} u_sub/VDDS {u_sub/VDDS VDD}]
    set ::fx_libs [dict create \
        CORE_A {db /fixture/core_a.db group {CORE_A_LO CORE_A_HI}} \
        CORE_B {db /fixture/core_b.db group {CORE_B_LO}} \
        RET    {db /fixture/ret.db group {}} \
        LS     {db /fixture/ls.db group {}} \
        MEM    {db /fixture/mem.db group {MEM_LO}}]
    set ::pin_queries 0
}
load_fixture

proc cell_of_pin {pin} { return [string range $pin 0 [expr {[string last / $pin] - 1}]] }
proc attr_of {object attr} {
    if {[dict exists $::fx_pins $object]} {
        set record [dict get $::fx_pins $object]
        switch -- $attr {
            full_name { return $object }
            pin_name { return [lindex [split $object /] end] }
            type { return [dict get $record type] }
            supply_connection { return [dict get $record conn] }
            voltage_source { return CONNECTED_SUPPLY_NET }
        }
    } elseif {[dict exists $::fx_cells $object]} {
        set record [dict get $::fx_cells $object]
        switch -- $attr {
            full_name { return $object }
            is_hierarchical { return [dict get $record hier] }
            lib_cell { return "[dict get $record lib]/[dict get $record ref]" }
        }
    } elseif {[dict exists $::fx_libs $object]} {
        switch -- $attr {
            full_name { return $object }
            source_file_name { return [dict get $::fx_libs $object db] }
            lib_scaling_group { return [dict get $::fx_libs $object group] }
        }
    } elseif {[lsearch -exact $::fx_nets $object] >= 0} {
        if {$attr eq "full_name"} { return $object }
    }
    error "Unknown attribute $attr of $object"
}
proc get_attribute {args} {
    set objects [lindex $args end-1]
    set attr [lindex $args end]
    if {[llength $objects] == 1} { return [attr_of [lindex $objects 0] $attr] }
    set values {}
    foreach object $objects { lappend values [attr_of $object $attr] }
    return $values
}
# Evaluate PrimeTime filter expressions: comparisons joined by && || ( ) !.
proc filter_collection {objects expression} {
    set result {}
    foreach object $objects {
        set text $expression
        set rewritten ""
        while {[regexp -indices {([A-Za-z_]+)\s*(==|!=|<=|>=|<|>)\s*("[^"]*"|[^\s()&|]+)} $text all a o v]} {
            append rewritten [string range $text 0 [expr {[lindex $all 0] - 1}]]
            set attr [string range $text {*}$a]
            set op [string range $text {*}$o]
            set value [string trim [string range $text {*}$v] \"]
            set actual [attr_of $object $attr]
            switch -- $op {
                == { set r [expr {$actual eq $value}] }
                != { set r [expr {$actual ne $value}] }
                default { set r [expr "\$actual $op \$value"] }
            }
            append rewritten $r
            set text [string range $text [expr {[lindex $all 1] + 1}] end]
        }
        append rewritten $text
        if {[expr $rewritten]} { lappend result $object }
    }
    return $result
}
proc get_supply_nets {args} {
    set of [option_value $args -of_objects]
    if {$of ne ""} {
        incr ::pin_queries
        set result {}
        foreach pin $of { lappend result [dict get $::fx_pins $pin net] }
        return [lsort -unique $result]
    }
    if {[lsearch -exact $args -segments] >= 0} {
        set name [lindex $args end]
        if {[dict exists $::fx_segments $name]} { return [dict get $::fx_segments $name] }
        return [list $name]
    }
    return $::fx_nets
}
proc get_cells {args} {
    set of [option_value $args -of_objects]
    if {$of ne ""} {
        set result {}
        dict for {cell record} $::fx_cells {
            set hit 0
            foreach object $of {
                if {[lsearch -exact $::fx_nets $object] >= 0} {
                    if {$cell eq "u_sub" && $object eq "u_sub/VDDS"} { set hit 1 }
                    dict for {pin pin_record} $::fx_pins {
                        if {[cell_of_pin $pin] eq $cell && [dict get $pin_record net] eq $object} { set hit 1 }
                    }
                } elseif {"[dict get $record lib]/[dict get $record ref]" eq $object} {
                    set hit 1
                }
            }
            if {$hit} { lappend result $cell }
        }
        return $result
    }
    set result {}
    foreach name [lindex $args end] { if {[dict exists $::fx_cells $name]} { lappend result $name } }
    return $result
}
proc get_pg_pins {args} {
    set result {}
    foreach cell [option_value $args -of_objects] {
        dict for {pin record} $::fx_pins { if {[cell_of_pin $pin] eq $cell} { lappend result $pin } }
    }
    return $result
}
proc get_lib_cells {args} {
    set result {}
    foreach object [option_value $args -of_objects] {
        if {[dict exists $::fx_libs $object]} {
            dict for {cell record} $::fx_cells {
                if {[dict get $record lib] eq $object} { lappend result "$object/[dict get $record ref]" }
            }
        } else {
            lappend result [attr_of $object lib_cell]
        }
    }
    return [lsort -unique $result]
}
proc get_libs {args} {
    set of [option_value $args -of_objects]
    if {$of eq ""} { return [dict keys $::fx_libs] }
    set result {}
    foreach lib_cell $of { lappend result [lindex [split $lib_cell /] 0] }
    return [lsort -unique $result]
}

# ---------------------------------------------------------------------------
# 4. Net scope: two nets, segments, non-primary-only and mixed-rail cells.
# ---------------------------------------------------------------------------
set cfg2 [dict create scaling_power_nets {VDD VDD_CPU}]
set roles [auto_scaling::resolve_configured_supply_roles $cfg2]
check [expr {[dict get $roles u_sub/VDDS] eq "fixed"}] "Path-mode roles should call the segment fixed"
set nets [auto_scaling_net::resolve_scaling_nets $roles]
check [expr {[dict get $nets listed] eq {VDD VDD_CPU}}] "Wrong listed nets: [dict get $nets listed]"
check [expr {[dict get $nets segments VDD] eq {VDD u_sub/VDDS}}] "Wrong VDD segments: [dict get $nets segments VDD]"
check [expr {[dict get $nets fixed_nets] eq {VDD_AO VSS}}] "Wrong fixed nets: [dict get $nets fixed_nets]"
set roles [auto_scaling_net::apply_segment_roles $roles $nets]
check [expr {[dict get $roles u_sub/VDDS] eq "scaling"}] "Segment not reclassified as scaling"
check [expr {[dict get $roles VDD_AO] eq "fixed"}] "Fixed net changed role"

set supply [dict create path_cells {u_ff1 u_ff2 u_inv u_ao}]
set native [dict create cell_names {u_mem0}]
set out [file join $tmp result restored_scaled_TT_0p6V_25C_RCMAX_V_setup_net.rpt]
set scope [auto_scaling_net::net_scope_audit $nets $supply $native $out]
# VDD: u_ck u_ff1 u_ff2 u_inv u_ls u_mem0 (+ segment u_sub/u_x); u_ret touches
# VDD only through backup_power; u_sub is hierarchical and filtered.
check [expr {[dict get $scope count] == 9}] "Wrong total net cells: [dict get $scope count] [dict get $scope cells]"
check [expr {[dict get $scope per_net VDD] == 7}] "Wrong VDD count: [dict get $scope per_net VDD]"
check [expr {[dict get $scope per_net VDD_CPU] == 2}] "Wrong VDD_CPU count"
check [expr {[lsearch -exact [dict get $scope cells] u_ret] < 0}] "Non-primary-only cell entered the scope"
check [expr {[lsearch -exact [dict get $scope cells] u_sub] < 0}] "Hierarchical cell entered the scope"
check [expr {[lsearch -exact [dict get $scope cells] u_ao] < 0}] "Fixed-net cell entered the scope"
check [expr {[lsearch -exact [dict get $scope cells] u_sub/u_x] >= 0}] "Segment cell missing from the scope"
set counts [dict create]
foreach record [dict get $scope libraries] {
    dict set counts [dict get $record name] [list [dict get $record cells] [dict get $record group_before] [dict get $record db]]
}
check [expr {[dict get $counts CORE_A] eq {5 ACTIVE /fixture/core_a.db}}] "CORE_A count: [dict get $counts CORE_A]"
check [expr {[lindex [dict get $counts CORE_B] 0] == 2}] "CORE_B count"
check [expr {[dict get $counts LS] eq {1 NONE_YET /fixture/ls.db}}] "LS count: [dict get $counts LS]"
check [expr {[lindex [dict get $counts MEM] 0] == 1}] "MEM count"
check [expr {![dict exists $counts RET]}] "RET library counted"
check [expr {[lindex [dict get $scope libraries] 0 1] eq "CORE_A"}] "Libraries not sorted by cell count"
set text [read_file [auto_scaling::detail_path $out .net_scope.txt]]
foreach expected {
    "LISTED_NETS: VDD,VDD_CPU"
    "NET VDD cells=7 segments=VDD,u_sub/VDDS"
    "  SEGMENT u_sub/VDDS cells=1"
    "NET VDD_CPU cells=2 segments=VDD_CPU"
    "AUTO_FIXED_NETS: VDD_AO,VSS"
    "TOTAL net_cells=9 libraries=4"
    "nonprimary_only_cells=1 mixed_rail_pins=1"
    "FIXED_PATH_CELLS_ON_NET: 3 of 4"
    "LIBRARY lib=LS cells=1 group_before=NONE_YET DB=/fixture/ls.db"
    "NONPRIMARY_ONLY cell=u_ret segment=VDD pins=u_ret/VDDB:backup_power"
    "MIXED_RAIL_PIN u_ls/VDDH:VDD_AO"
    "U_MEM_VDDPE cell=u_mem0 net=VDD"
    "NET_SCOPE_STATUS: DONE"
} {
    check [expr {[string first $expected $text] >= 0}] "net_scope.txt lacks '$expected'"
}
puts "PASS: two-net scope (per net, total, per library+DB), UPF segment, non-primary-only, mixed-rail, hierarchical filter"

# Single net: VDD_CPU becomes auto-fixed.
set roles1 [auto_scaling::resolve_configured_supply_roles [dict create scaling_power_nets {VDD}]]
set nets1 [auto_scaling_net::resolve_scaling_nets $roles1]
check [expr {[dict get $nets1 fixed_nets] eq {VDD_AO VDD_CPU VSS}}] "Single-net fixed list: [dict get $nets1 fixed_nets]"
set scope1 [auto_scaling_net::net_scope_audit $nets1 $supply $native $out]
check [expr {[dict get $scope1 count] == 7 && [dict get $scope1 per_net VDD] == 7}] "Single-net count: [dict get $scope1 count]"
check [string match "*LISTED_NETS: VDD\n*" [read_file [auto_scaling::detail_path $out .net_scope.txt]]] "Single-net evidence"
puts "PASS: single-net scope"

# Name fallback: supply_connection gives a short name for the sub-scope net.
dict set ::fx_pins u_sub/u_x/VDD conn VDDS
set ::pin_queries 0
set scope_fb [auto_scaling_net::net_scope_audit $nets $supply $native $out]
check [expr {[dict get $scope_fb count] == 9}] "Fallback lost a cell: [dict get $scope_fb count]"
check [expr {$::pin_queries > 0}] "Fallback did not query PG pins one by one"
check [expr {[lsearch -exact [dict get $scope_fb primary_pins] u_sub/u_x/VDD] >= 0}] "Fallback pin not kept for NET-003"
set text [read_file [auto_scaling::detail_path $out .net_scope.txt]]
check [string match "*fallback_segments=1*" $text] "Fallback not recorded"
check [string match "*FALLBACK_SEGMENTS: u_sub/VDDS*" $text] "Fallback segment not named"
check [string match "*mixed_rail_pins=1 *" $text] "Fallback changed the mixed-rail count"
dict set ::fx_pins u_sub/u_x/VDD conn u_sub/VDDS
puts "PASS: supply_connection name fallback (per-pin query only for that segment)"

# NET-004: a ground net or a net feeding no primary_power pin.
set roles_gnd [auto_scaling::resolve_configured_supply_roles [dict create scaling_power_nets {VSS}]]
expect_error {auto_scaling_net::net_scope_audit [auto_scaling_net::resolve_scaling_nets $roles_gnd] $supply $native $out} {NET-004:*VSS*}
# NET-005: u_mem VDDPE on a fixed net.
dict set ::fx_pins u_mem0/VDDPE net VDD_AO
dict set ::fx_pins u_mem0/VDDPE conn VDD_AO
expect_error {auto_scaling_net::net_scope_audit $nets $supply $native $out} {NET-005:*u_mem0*VDD_AO*}
load_fixture
puts "PASS: NET-004 (ground net) and NET-005 (u_mem VDDPE off the scaling net)"

# ---------------------------------------------------------------------------
# 5. NET-001: every net library needs an active scaling group.
# ---------------------------------------------------------------------------
set scope [auto_scaling_net::net_scope_audit $nets $supply $native $out]
set plan [dict create scaling_library_rows [list \
    [dict create file /fixture/core_a.db lib_name CORE_A] \
    [dict create file /fixture/core_b.db lib_name CORE_B]] \
    native_umem [dict create library_names {MEM}]]
set reason [expect_error {auto_scaling_net::check_net_groups $scope $plan $out} {NET-001:*}]
check [string match "*LS (cells=1)*" $reason] "NET-001 did not name the library and cell count: $reason"
check [expr {[string first "CORE_A" $reason] < 0}] "NET-001 named a grouped library"
set text [read_file [auto_scaling::detail_path $out .net_scope.txt]]
check [string match "*NET-001 LIBRARY lib=LS cells=1 group=NONE planned_by_this_run=no*" $text] "NET-001 evidence lacks LS"
check [string match "*NET-001 LIBRARY lib=MEM cells=1 group=ACTIVE planned_by_this_run=yes*" $text] "Native u_mem group not accepted"
check [string match "*NET-001 STATUS: FAILED*" $text] "NET-001 evidence lacks FAILED"
dict set ::fx_libs LS group {LS_LO}
set scope [auto_scaling_net::net_scope_audit $nets $supply $native $out]
auto_scaling_net::check_net_groups $scope $plan $out
set text [read_file [auto_scaling::detail_path $out .net_scope.txt]]
check [string match "*NET-001 STATUS: PASSED libraries=4*" $text] "NET-001 pass evidence"
check [string match "*NET-001 LIBRARY lib=LS cells=1 group=ACTIVE planned_by_this_run=no*" $text] "Unplanned group not reported"
load_fixture
puts "PASS: NET-001 names ungrouped net libraries with cell counts; native u_mem group accepted"

# ---------------------------------------------------------------------------
# 6. NET-002 / NET-003 evidence parsing (pure).
# ---------------------------------------------------------------------------
proc supply_report {values} {
    set text "  Total of [expr {[llength $values] / 3}] supply nets defined.\n"
    foreach {net max min} $values {
        append text "-------------------------------------------------------------------------------\n"
        append text "    Supply Net :        $net\n    Scope :             <top level>\n"
        append text "    Max-delay Voltage : $max\n    Min-delay Voltage : $min\n"
    }
    return $text
}
proc pin_report {rows} {
    set text "Cell   Power Pin Name   Type   Voltage MaxD MinD   Power Net Connected\n---------------\n"
    foreach row $rows { append text "[join $row "   "]\n" }
    return "${text}1\n"
}
set before_nets [supply_report {VDD 0.650000 0.650000 VDD_CPU 0.650000 0.650000 u_sub/VDDS 0.650000 0.650000 VDD_AO 0.650000 0.650000 VSS 0.000000 0.000000}]
set good_nets [supply_report {VDD 0.600000 0.600000 VDD_CPU 0.600000 0.600000 u_sub/VDDS 0.600000 0.600000 VDD_AO 0.650000 0.650000 VSS 0.000000 0.000000}]
set before_pins [pin_report {
    {u_ff1 VDD primary_power 0.6500 0.6500 VDD} {u_ff1 VSS primary_ground 0.0000 0.0000 VSS}
    {u_ck VDD primary_power 0.6500 0.6500 VDD} {u_sub/u_x VDD primary_power 0.6500 0.6500 u_sub/VDDS}
    {u_cpu1 VDD primary_power 0.6500 0.6500 VDD_CPU} {u_ao VDD primary_power 0.6500 0.6500 VDD_AO}}]
set good_pins [pin_report {
    {u_ff1 VDD primary_power 0.6000 0.6000 VDD} {u_ff1 VSS primary_ground 0.0000 0.0000 VSS}
    {u_ck VDD primary_power 0.6000 0.6000 VDD} {u_sub/u_x VDD primary_power 0.6000 0.6000 u_sub/VDDS}
    {u_cpu1 VDD primary_power 0.6000 0.6000 VDD_CPU} {u_ao VDD primary_power 0.6500 0.6500 VDD_AO}}]
set sample {u_ff1 u_ck u_sub/u_x u_cpu1}
proc power_errors {nets_after pins_after {bulk {}} {sample_cells ""}} {
    if {$sample_cells eq ""} { set sample_cells $::sample }
    return [auto_scaling_net::net_power_errors $::nets 0.6 $::before_nets $nets_after \
        $::before_pins $pins_after $sample_cells {u_ao} $bulk]
}
set result [power_errors $good_nets $good_pins]
check [expr {![llength [dict get $result errors]]}] "Good evidence failed: [dict get $result errors]"
check [expr {[dict get $result sample_pins_checked] == 4 && [dict get $result control_pins] == 1}] "Wrong checked counts: $result"
# Listed net not at target.
set errors [dict get [power_errors [string map {"VDD_CPU\n    Scope :             <top level>\n    Max-delay Voltage : 0.600000" "VDD_CPU\n    Scope :             <top level>\n    Max-delay Voltage : 0.650000"} $good_nets] $good_pins] errors]
check [expr {[llength $errors] == 1 && [string match "NET-002: Scaling net VDD_CPU reports Max-delay Voltage=0.650000*" [lindex $errors 0]]}] "NET-002 max: $errors"
# Min voltage not at target on a segment.
set errors [dict get [power_errors [supply_report {VDD 0.6 0.6 VDD_CPU 0.6 0.6 u_sub/VDDS 0.6 0.65 VDD_AO 0.65 0.65 VSS 0 0}] $good_pins] errors]
check [string match "*NET-002: Scaling net u_sub/VDDS reports Min-delay Voltage=0.65*" $errors] "NET-002 segment min: $errors"
# A listed net missing from the report; an unreported extra segment is covered by pins.
set errors [dict get [power_errors [supply_report {VDD 0.6 0.6 u_sub/VDDS 0.6 0.6 VDD_AO 0.65 0.65 VSS 0 0}] $good_pins] errors]
check [string match "*NET-002: Scaling net VDD_CPU is missing*" $errors] "NET-002 missing listed net: $errors"
set errors [dict get [power_errors [supply_report {VDD 0.6 0.6 VDD_CPU 0.6 0.6 VDD_AO 0.65 0.65 VSS 0 0}] $good_pins] errors]
check [expr {![llength $errors]}] "Unreported extra segment should not fail NET-002: $errors"
# An auto-fixed net changed.
set errors [dict get [power_errors [supply_report {VDD 0.6 0.6 VDD_CPU 0.6 0.6 u_sub/VDDS 0.6 0.6 VDD_AO 0.6 0.6 VSS 0 0}] $good_pins] errors]
check [string match "*NET-002: Auto-fixed net VDD_AO changed Max-delay Voltage*" $errors] "NET-002 fixed net: $errors"
# Cell-level override keeps one pin at 0.66 (NET-003), also the min column.
set errors [dict get [power_errors $good_nets [string map {"u_ck   VDD   primary_power   0.6000   0.6000" "u_ck   VDD   primary_power   0.6600   0.6600"} $good_pins]] errors]
check [expr {[llength $errors] == 1 && [string match "NET-003: u_ck/VDD on VDD reports max=0.66*" [lindex $errors 0]]}] "NET-003 override: $errors"
set errors [dict get [power_errors $good_nets [string map {"u_cpu1   VDD   primary_power   0.6000   0.6000" "u_cpu1   VDD   primary_power   0.6000   0.6500"} $good_pins]] errors]
check [string match "*NET-003: u_cpu1/VDD on VDD_CPU reports max=0.6 min=0.65*" $errors] "NET-003 min column: $errors"
# Fixed-net control pin changed.
set errors [dict get [power_errors $good_nets [string map {"u_ao   VDD   primary_power   0.6500   0.6500" "u_ao   VDD   primary_power   0.6000   0.6000"} $good_pins]] errors]
check [string match "*NET-003: Fixed-net control pin u_ao/VDD changed*" $errors] "NET-003 control: $errors"
# Bulk attribute rows and an unparseable sample.
set errors [dict get [power_errors $good_nets $good_pins {{u_x/VDD 0.66 0.66 SET_VOLTAGE_ON_PG_PIN}}] errors]
check [string match "*NET-003: PG pin u_x/VDD reports max=0.66 min=0.66 source=SET_VOLTAGE_ON_PG_PIN*" $errors] "NET-003 bulk: $errors"
set errors [dict get [power_errors $good_nets $good_pins {} {u_nothing}] errors]
check [string match "*NET-003: No scaling-net primary_power pin of the 1 sample cell*" $errors] "NET-003 empty sample: $errors"
# A report without the MinD column still parses.
set rows [auto_scaling_net::power_pin_rows "I0   PWR   primary_power   1.0000   exp_VDD (*)\nI0   GND   primary_ground   0.0000   T_VSS\n"]
check [expr {[llength $rows] == 2 && [dict get [lindex $rows 0] min] eq "" && [dict get [lindex $rows 0] net] eq "exp_VDD"}] "Single-column report: $rows"
puts "PASS: NET-002 (listed/segment/fixed nets) and NET-003 (override, min column, control, bulk, sample) parsing"

file delete -force $tmp
puts "ALL NET SCOPE TESTS PASSED"
