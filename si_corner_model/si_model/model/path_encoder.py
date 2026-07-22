"""Stage-sequence path encoder: interleaved chain message passing + BiGRU.

Same architecture family as the inherited v18 PathEncoderV2 (kept because it
worked): nodes are the cell-pin rows of the ref-corner annotated report in
path order, edges are the net rows between them. Each block does one chain-MP
step (left/right neighbor messages with edge features) followed by a BiGRU
sweep, with residual + LayerNorm. Readout = mean pool + attention pool, where
PT's '<-' critical markers bias the attention logits.
"""
from __future__ import annotations

import torch
import torch.nn as nn


def _shift_left(h: torch.Tensor) -> torch.Tensor:
    out = torch.zeros_like(h)
    out[:, :-1] = h[:, 1:]
    return out


def _shift_right(h: torch.Tensor) -> torch.Tensor:
    out = torch.zeros_like(h)
    out[:, 1:] = h[:, :-1]
    return out


class ChainMPLayer(nn.Module):
    def __init__(self, d: int, edge_dim: int, dropout: float = 0.1):
        super().__init__()
        self.lin_self = nn.Linear(d, d)
        self.lin_left = nn.Linear(d + edge_dim, d)
        self.lin_right = nn.Linear(d + edge_dim, d)
        self.act = nn.GELU()
        self.drop = nn.Dropout(dropout)

    def forward(self, h: torch.Tensor, edge: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        B, L, _ = h.shape
        E = edge.shape[-1]
        e_r = torch.zeros(B, L, E, dtype=h.dtype, device=h.device)
        e_l = torch.zeros(B, L, E, dtype=h.dtype, device=h.device)
        if L > 1:
            e_r[:, :L - 1] = edge
            e_l[:, 1:] = edge
        m_l = self.lin_left(torch.cat([_shift_right(h), e_l], -1))
        m_r = self.lin_right(torch.cat([_shift_left(h), e_r], -1))
        out = self.lin_self(h) + m_l + m_r
        return self.drop(self.act(out)) * mask.unsqueeze(-1)


class InterleavedBlock(nn.Module):
    def __init__(self, d: int, edge_dim: int, gru_hidden: int, dropout: float = 0.1):
        super().__init__()
        self.mp = ChainMPLayer(d, edge_dim, dropout)
        self.gru = nn.GRU(d, gru_hidden, batch_first=True, bidirectional=True)
        self.gru_proj = nn.Linear(2 * gru_hidden, d)
        self.norm = nn.LayerNorm(d)
        self.drop = nn.Dropout(dropout)

    def forward(self, h: torch.Tensor, edge: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        res = h
        h = self.mp(h, edge, mask)
        lengths = mask.sum(1).long().cpu().clamp(min=1)
        packed = nn.utils.rnn.pack_padded_sequence(
            h, lengths, batch_first=True, enforce_sorted=False)
        out, _ = self.gru(packed)
        out, _ = nn.utils.rnn.pad_packed_sequence(
            out, batch_first=True, total_length=h.shape[1])
        h = self.gru_proj(out) * mask.unsqueeze(-1)
        h = self.drop(self.norm(h + res))
        return h * mask.unsqueeze(-1)


class PathEncoder(nn.Module):
    """Returns path_emb [B, 2*d] (and per-node states [B, L, d] on request)."""

    def __init__(self, n_families: int, node_dim: int, edge_dim: int,
                 family_emb: int = 16, d: int = 128, gru_hidden: int = 64,
                 num_blocks: int = 3, dropout: float = 0.1, emb_dropout: float = 0.3):
        super().__init__()
        self.family_emb = nn.Embedding(n_families, family_emb, padding_idx=0)
        self.emb_drop = nn.Dropout(emb_dropout)
        self.node_in = nn.Sequential(nn.Linear(family_emb + node_dim, d), nn.GELU())
        self.blocks = nn.ModuleList(
            [InterleavedBlock(d, edge_dim, gru_hidden, dropout) for _ in range(num_blocks)])
        self.att_readout = nn.Sequential(nn.Linear(d, d), nn.Tanh(), nn.Linear(d, 1))
        self.critical_bias = nn.Parameter(torch.tensor(1.0))
        self.out_dim = 2 * d

    def forward(self, fam: torch.Tensor, node: torch.Tensor, edge: torch.Tensor,
                mask: torch.Tensor, critical: torch.Tensor,
                return_nodes: bool = False):
        x = torch.cat([self.emb_drop(self.family_emb(fam)), node], -1)
        h = self.node_in(x) * mask.unsqueeze(-1)
        for blk in self.blocks:
            h = blk(h, edge, mask)
        denom = mask.sum(1, keepdim=True).clamp(min=1.0)
        mean_pool = (h * mask.unsqueeze(-1)).sum(1) / denom
        logits = self.att_readout(h).squeeze(-1) + self.critical_bias * critical
        logits = logits.masked_fill(mask == 0, float("-inf"))
        att = torch.softmax(logits, 1)
        att_pool = (h * att.unsqueeze(-1)).sum(1)
        pooled = torch.cat([mean_pool, att_pool], -1)
        if return_nodes:
            return pooled, h
        return pooled
