"""SI branch: per-aggressor magnitude x PrimeTime worst-case window alignment,
with the F6 electrical filter applied on the interpolated bump ratio.

Per SI_model_vs_PrimeTimeSI_ch16_analysis.md fixes #1/#2/#4, refined by the
data check below.

Worst-case combine (UG p590 Table 42 / p594 Fig.163). PrimeTime SI takes every
aggressor whose window overlaps the victim window and combines them at the
worst common instant -- "the worst case of multiple aggressor transitions
occurring in the same direction at the same time". We reproduce it by sweeping
time inside the victim window and taking the worst instant:

    delta_i     = MLP(features)                        # signed magnitude (ps)
    S(t) = sum_{i : t in aggr_win_i, present} g6_i * delta_i
    z_s  = max_t S(t)   over  t in victim_win
    SI   = sum over launch+data stages z_s

This replaces the old softmax convex-combination (sum_i w_i delta_i, sum w=1),
which could never exceed max_i delta_i and so could not represent two
aggressors adding up.

F6 electrical filter (UG p584-585, Fig.159). PrimeTime filters an aggressor
when its induced-bump peak divided by VDD is below
si_filter_per_aggr_noise_peak_ratio (default 0.01). The dumped aggressor_bump
is ALREADY that VDD ratio (Fig.159 shows "0.009 VDD" etc.; data: raw min
~0.0107, across-corner CV of bump 0.071 vs bump/VDD 0.130 -> bump is the flat
ratio, dividing by VDD again was a bug). So the gate thresholds the
*interpolated ratio directly* at 0.01, with NO extra /VDD:

    g6_i = sigmoid((bump_ratio_i - thresh) / w_elec)   (hard: bump_ratio_i >= thresh)

At anchor corners every dumped aggressor already passed the filter (>=0.01) so
g6~1, but the polynomial interpolation dips below 0.01 at ~6% of hidden-corner
stages -- exactly the boundary aggressors PrimeTime would screen out. Gating on
the interpolated ratio recovers those screened (S) transitions / jumps that a
window-only model misses.

Soft (training) / hard (inference): window membership is a two-sigmoid soft
cover (softness w), the electrical filter is a sigmoid (softness w_elec), and
max_t is a soft-argmax at temperature tau; all anneal toward hard and inference
uses the exact hard max / hard threshold.
"""
import torch
import torch.nn as nn

N_AGGR_FEAT = 7  # [cc, bump, overlap, aslew, vw_width, dv, dt]


class SIBranch(nn.Module):
    def __init__(self, d: int = 64, dropout: float = 0.1, n_time: int = 16,
                 w_ns: float = 0.05, tau_ps: float = 8.0,
                 elec_thresh: float = 0.01, w_elec: float = 0.004):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(N_AGGR_FEAT, d), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(d, d // 2), nn.GELU(), nn.Linear(d // 2, 1))
        self.n_time = int(n_time)
        self.elec_thresh = float(elec_thresh)   # PT si_filter_per_aggr_noise_peak_ratio
        # annealed state (not parameters): window softness w (ns), electrical
        # filter softness w_elec (ratio), soft-argmax temperature tau (ps);
        # hard=True switches to exact PT worst-instant + hard 0.01 filter.
        self.w = float(w_ns)
        self.w_elec = float(w_elec)
        self.tau = float(tau_ps)
        self.hard = False

    def set_anneal(self, w: float, tau: float, hard: bool,
                   w_elec: "float | None" = None) -> None:
        self.w, self.tau, self.hard = float(w), float(tau), bool(hard)
        if w_elec is not None:
            self.w_elec = float(w_elec)

    def forward(self, x: torch.Tensor, awin: torch.Tensor, vwin: torch.Tensor,
                bump: torch.Tensor, present: torch.Tensor,
                stage_mask: torch.Tensor) -> torch.Tensor:
        """x [B,S,A,F] features; awin [B,S,A,2] aggressor (lo,hi) arrival window
        (ns); vwin [B,S,2] victim window (ns); bump [B,S,A] interpolated bump
        ratio (already /VDD); present [B,S,A] bool; stage_mask [B,S] bool.
        Returns SI pred [B] (ps)."""
        delta = self.net(x).squeeze(-1)                     # [B,S,A] signed, ps

        # F6 electrical filter on the interpolated ratio (no extra /VDD)
        if self.hard:
            g6 = (bump >= self.elec_thresh).to(delta.dtype)
        else:
            g6 = torch.sigmoid((bump - self.elec_thresh) / self.w_elec)
        delta = delta * g6                                  # screen weak aggressors

        K = self.n_time
        vlo = vwin[..., 0].unsqueeze(-1)                    # [B,S,1]
        vhi = vwin[..., 1].unsqueeze(-1)                    # [B,S,1]
        frac = torch.linspace(0.0, 1.0, K, device=x.device).view(1, 1, K)
        t = (vlo + frac * (vhi - vlo)).unsqueeze(-1)        # [B,S,K,1] samples in victim win

        alo = awin[..., 0].unsqueeze(2)                     # [B,S,1,A]
        ahi = awin[..., 1].unsqueeze(2)                     # [B,S,1,A]
        # soft membership: aggressor i covers instant t (its window contains t)
        cover = torch.sigmoid((t - alo) / self.w) * torch.sigmoid((ahi - t) / self.w)
        cover = cover * present.unsqueeze(2)                # [B,S,K,A] mask absent slots
        Sk = (cover * delta.unsqueeze(2)).sum(-1)          # [B,S,K] aligned sum at each t

        if self.hard:
            z = Sk.amax(dim=-1)                             # [B,S] worst instant (exact)
        else:
            wgt = torch.softmax(Sk / self.tau, dim=-1)      # soft-argmax over time
            z = (wgt * Sk).sum(-1)                          # [B,S] soft worst value
        return (z * stage_mask).sum(-1)                     # [B]
