# Read-only audit of the active groups reached by fixed-path target-rail cells
# and selected u_mem/VDDPE cells. Works in the existing full-group session.
#
# 1. Edit USER SETTINGS in run_scaling_after_restore.tcl.
# 2. restore_session /path/to/current_session
# 3. source /path/to/pt/check_loo_groups_after_restore.tcl
#
# This does not define/remove groups, change voltage/temperature, or update timing.

set ::auto_scaling_restored_load_only 1
source [file join [file dirname [info script]] run_scaling_after_restore.tcl]
unset ::auto_scaling_restored_load_only

set loo_check_config [auto_scaling::build_restore_config]
set loo_check_log [auto_scaling::detail_path \
    [dict get $loo_check_config out_rpt] .loo_groups.log]
file mkdir [file dirname $loo_check_log]
redirect -tee -file $loo_check_log {
    puts "LOO GROUP AUDIT MODE: read-only; no timing update or group change"
    dict set loo_check_config configured_supply_roles \
        [auto_scaling::resolve_configured_supply_roles $loo_check_config]
    set loo_check_fixed [auto_scaling::read_fixed \
        [dict get $loo_check_config fixed_tcl] \
        [dict get $loo_check_config delay_type]]
    set loo_check_supply [auto_scaling::classify_fixed_path_supply \
        $loo_check_fixed $loo_check_config]
    set loo_check_findings [auto_scaling::audit_fixed_path_group_targets \
        $loo_check_supply $loo_check_config]
    puts "LOO GROUP AUDIT FILE: $loo_check_log"
    puts "LOO GROUP AUDIT RESULT: target_or_unverified=[llength $loo_check_findings]"
}
