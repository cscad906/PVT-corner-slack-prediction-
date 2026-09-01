"""Slew model = adaptive-bandwidth OLS base + neural residual (no SI).

Same skeleton as the slack SlackModel minus the SI branch:

    slew(q) = base_adaptive(q)                 # per-corner adaptive WLS (precomputed)
            + gate(q) * CorrHead(tokens, q)    # set-invariant attention residual

The CorrHead cross-attends to the measured seen-corner tokens (a learned
interpolation over corner space); the support gate shrinks the residual where
the query extrapolates. All outputs are the base residual in ps.
"""
import torch
import torch.nn as nn

from si_model.model.corr_head import CornerSetHead


class SlewModel(nn.Module):
    def __init__(self, n_token_feat: int, n_sig: int, d: int = 64,
                 heads: int = 4, dropout: float = 0.1, n_query: int = 6):
        super().__init__()
        self.head = CornerSetHead(n_token_feat, n_sig, d, heads, dropout, n_query)
        self.gate_net = nn.Sequential(nn.Linear(n_query, 32), nn.GELU(), nn.Linear(32, 1))
        nn.init.zeros_(self.gate_net[-1].weight)
        nn.init.constant_(self.gate_net[-1].bias, 2.0)   # sigmoid(2)=0.88, near-open

    def forward(self, batch: dict) -> dict:
        corr = self.head(batch["tokens"], batch["token_mask"],
                         batch["query_vt"], batch["sig"])
        gate = torch.sigmoid(self.gate_net(batch["query_vt"])).squeeze(-1)
        resid = gate * corr
        return {"resid": resid, "resid_raw": corr, "gate": gate}
