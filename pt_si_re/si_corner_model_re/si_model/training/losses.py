"""Losses. Everything in ps."""
import torch
import torch.nn.functional as F


def total_loss(out: dict, batch: dict, lambda_si: float) -> "tuple[torch.Tensor, dict]":
    """MSE on the base residual + lambda * MSE aligning the SI branch to the
    smooth-fit SI residual (the SI deviation = label - per-path smooth fit).

    Two anti-collapse terms (both inherited from the boomcore_si_slack
    recipe): the UNgated prediction gets its own MSE so the head keeps
    receiving gradient in folds where the gate has closed, and (1-gate)^2 is
    lightly penalized so "close everywhere" is never the lazy optimum --
    the gate must earn each closure against the 0.02 open-bias.
    """
    l_resid = F.mse_loss(out["resid"], batch["resid_target"])
    l_raw = F.mse_loss(out["resid_raw"], batch["resid_target"])
    l_si = F.mse_loss(out["si_pred"], batch["si_target"])
    l_gate = (1.0 - out["gate"]).pow(2).mean()
    loss = l_resid + 0.3 * l_raw + lambda_si * l_si + 0.02 * l_gate
    parts = {"resid": l_resid.item(), "si": l_si.item(),
             "gate": out["gate"].mean().item()}
    return loss, parts
