"""Slack model assembly (setup / hold).

    slack(q) = base_OLS(q)                        # precomputed, per-path
             + gate(q) * [ CorrHead(tokens, sig, q)          # set-invariant correction
                         + si_dev_scale * SI_branch(q) ]     # jumpy SI deviation

base_OLS is a per-path polynomial fit (leave-one-out at seen corners, all-seen at
hidden) computed in training/loo.py. The SI branch predicts the SI DEVIATION
directly: its aux target is (PT SI label - per-path SI smooth fit), i.e. only the
gate-toggle/selection jumps the polynomial cannot represent -- the absolute SI
level is a per-path quantity the polynomial already nails and a shared-parameter
net cannot beat. All neural outputs are in ps.

There is deliberately NO per-stage cell/net delay head: the OLS base already
carries per-stage delays as well as it carries slack (the "OLS-base-is-enough"
finding), so the extra multi-task head was dropped in the unified engine.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from si_model.model.corr_head import CornerSetHead
from si_model.model.si_branch import SIBranch


class SlackModel(nn.Module):
    def __init__(self, n_token_feat: int, n_sig: int, d: int = 64,
                 heads: int = 4, dropout: float = 0.1, n_query: int = 6,
                 si_n_time: int = 16, si_w_ns: float = 0.05, si_tau_ps: float = 8.0,
                 si_elec_thresh: float = 0.01, si_w_elec: float = 0.004):
        super().__init__()
        self.head = CornerSetHead(n_token_feat, n_sig, d, heads, dropout, n_query)
        self.si = SIBranch(d, dropout, si_n_time, si_w_ns, si_tau_ps,
                           si_elec_thresh, si_w_elec)
        # zero-init scale: the model starts exactly at the OLS base (the head
        # output layer is zero-init too) and opens the SI-deviation path only
        # as the branch becomes accurate under the lambda aux loss.
        self.si_dev_scale = nn.Parameter(torch.zeros(1))
        # support gate over (dv, d<axis1>, one-sided neighbor gaps): learns to
        # shrink the neural correction where the query extrapolates (no seen
        # corner beyond it on some axis). Zero-init weights + bias 2.0 ->
        # starts at sigmoid(2)=0.88, i.e. near-transparent.
        self.gate_net = nn.Sequential(nn.Linear(n_query, 32), nn.GELU(), nn.Linear(32, 1))
        nn.init.zeros_(self.gate_net[-1].weight)
        nn.init.constant_(self.gate_net[-1].bias, 2.0)

    def forward(self, batch: dict) -> dict:
        corr = self.head(batch["tokens"], batch["token_mask"],
                         batch["query_vt"], batch["sig"])
        si_pred = self.si(batch["si_x"], batch["si_awin"], batch["si_vwin"],
                          batch["si_bump"], batch["si_present"],
                          batch["si_stage_mask"])
        gate = torch.sigmoid(self.gate_net(batch["query_vt"])).squeeze(-1)
        resid_raw = corr + self.si_dev_scale * si_pred
        resid = gate * resid_raw
        return {"resid": resid, "resid_raw": resid_raw, "corr": corr,
                "si_pred": si_pred, "gate": gate}
