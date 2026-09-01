"""Set-invariant correction head.

The query corner cross-attends to the measured seen-corner tokens (a learned
interpolation kernel over corner space) -- permutation/count-invariant, so the
same module serves LOO training folds (19 tokens) and hidden-corner inference
(20 tokens). The target corner's own token is always masked out (anti-leakage).
"""
import torch
import torch.nn as nn


class CornerSetHead(nn.Module):
    def __init__(self, n_token_feat: int, n_sig: int, d: int = 64,
                 heads: int = 4, dropout: float = 0.1, n_query: int = 2):
        super().__init__()
        self.token_net = nn.Sequential(
            nn.Linear(n_token_feat, d), nn.GELU(), nn.Linear(d, d))
        self.sig_net = nn.Sequential(
            nn.Linear(n_sig, d), nn.GELU(), nn.Dropout(dropout), nn.Linear(d, d))
        self.query_net = nn.Sequential(nn.Linear(n_query + d, d), nn.GELU(), nn.Linear(d, d))
        self.attn = nn.MultiheadAttention(d, heads, dropout=dropout, batch_first=True)
        self.out = nn.Sequential(
            nn.Linear(3 * d, d), nn.GELU(), nn.Dropout(dropout), nn.Linear(d, 1))
        nn.init.zeros_(self.out[-1].weight)
        nn.init.zeros_(self.out[-1].bias)

    def forward(self, tokens: torch.Tensor, token_mask: torch.Tensor,
                query_vt: torch.Tensor, sig: torch.Tensor) -> torch.Tensor:
        """tokens [B,C,F]; token_mask [B,C] True=usable; query_vt [B,n_query]
        (dv, dt, one-sided neighbor gaps); sig [B,n_sig]. Returns [B] (ps)."""
        se = self.sig_net(sig)
        q = self.query_net(torch.cat([query_vt, se], dim=-1)).unsqueeze(1)
        t = self.token_net(tokens)
        att, _ = self.attn(q, t, t, key_padding_mask=~token_mask)
        return self.out(torch.cat([att.squeeze(1), q.squeeze(1), se], dim=-1)).squeeze(-1)
