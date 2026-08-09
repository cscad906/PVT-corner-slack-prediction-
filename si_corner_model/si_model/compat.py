"""Version shims for the interpreters this actually has to run on.

The deployment target is whatever python the site already has -- often the
distro's 3.6 with an old torch, since PrimeTime output is brought TO that
machine rather than produced on it. Keep such differences here, not scattered
through the model code.
"""


def load_checkpoint(path, map_location=None):
    """``torch.load`` that works on old and new torch alike.

    ``weights_only`` arrived in torch 1.13 and its DEFAULT flipped to True in
    2.6. Our checkpoints store the config dict alongside the tensors, so the
    load must be a full unpickle: pass ``weights_only=False`` where the argument
    exists, and simply omit it where it does not (torch 1.10 raises TypeError).
    """
    import torch
    try:
        return torch.load(path, map_location=map_location, weights_only=False)
    except TypeError:
        return torch.load(path, map_location=map_location)
