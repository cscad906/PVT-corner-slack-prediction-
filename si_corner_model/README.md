# si_corner_model — SI-aware per-path timing prediction at unmeasured corners

Predict per-path timing (slack, or slew) at **unmeasured corners** of a design
that was characterized on a coarse corner grid — **including SI/crosstalk** —
from PrimeTime fixed-path annotated + crosstalk reports.

One design is measured on a dense grid over a few **continuous corner axes**
(voltage, and a BEOL/RC parasitic corner); the model fills in the corners you did
*not* measure. Everything that is not a smooth interpolation axis — **temperature,
process, setup vs hold** — is trained as a **separate model**, not an axis.

```
prediction  = OLS_base(V, RC)                          # per-path weighted OLS, leave-one-out
            + gate · [ CorrHead(seen corners, path)    # set-invariant attention residual
                     + SI_branch ]                     # jumpy crosstalk deviation (slack only)
```

## The organizing idea: axes vs splits

| | how it enters the model |
|---|---|
| **voltage** | continuous OLS axis (always axis 0) |
| **BEOL / RC** | continuous OLS axis (14nm) |
| **temperature** | a **split** → one model per temp (14nm), *or* a continuous axis if you have enough levels (3nm) — your choice, in the config |
| **process** | a **split** → one model per process |
| **setup / hold** | a **split** → separate models (different library check + SI sign) |
| **slew** | a **separate task** (no SI branch) — `si_model/tasks/slew/` |

Only the axes go in the polynomial. Splits are just different configs pointing at
different data. This is what lets the same engine run on a new company's data:
declare its axes, list its splits, point at its reports.

## Layout

```
si_model/                 # the single engine (import si_model)
  config.py               # config loader + polynomial-basis generator (order/rank guard)
  parsing/                # PrimeTime reference parser: annotated, crosstalk, keys, build_dataset
  features/si_features.py # SI feature interpolation
  model/                  # base_ols (plain/local/adaptive), corr_head, path_encoder, si_branch
  training/               # loo (split + base artifacts), losses
  tasks/
    slack/                # SlackModel + train.py    (base + attention + SI branch)
    slew/                 # SlewModel  + build + train (base + attention, NO SI branch)
configs/
  _defaults.yaml          # shared model dims + train schedule + base defaults
  beol14/                 # 14nm V×RC reference: {setup,hold,slew}×{m40,125}
  gt3/                    # 3nm  V×T  reference: setup, hold
  TEMPLATE.yaml           # start here for a new dataset
scripts/  build.sh train.sh predict.sh sweep.sh
docs/     WALKTHROUGH.md (새 데이터 step-by-step) · USAGE.md (run + config reference)
          · PARSING.md (data formats + contract)
tests/    test_parsing.py · test_base_ols.py
```

## The OLS base (the "best version", now config-driven)

The per-path base is a polynomial in the corner axes with closed-form
leave-one-out. Three fit modes (`base.weighting`):

- `plain` — one global OLS fit.
- `local` — fixed-bandwidth **locally-weighted** OLS (the "가중 OLS").
- `adaptive` — **per-corner** bandwidth selection (default, best). Merges the
  isotropic-kNN neighbour metric, the extrapolation-variance guard, and the
  measured-range clip. Label-free: it never consults hidden corners.

**Polynomial order is a config option** — the 3rd- vs 4th-order question. Each
axis declares an `order`; the basis is generated in `config.expand_terms` and
rank-deficient terms are dropped automatically (e.g. `dv4` when only 4 voltage
levels are seen, `drc3` when RC has 3 levels). The generator reproduces both
reference bases exactly:

```yaml
base:
  axes:
    - {name: v,  ref: 0.8, order: 3}   # cubic in V
    - {name: rc, ref: 0.0, order: 2}   # RC 3 levels → quadratic cap
  weighting: adaptive
```

## Run

```bash
PY=/root/.conda/envs/torch310/bin/python     # any env with numpy + torch

# 1) build the cache for one model instance
PY=$PY bash scripts/build.sh configs/beol14/setup_m40.yaml

# 2) train it (slack); slew configs auto-route to the slew trainer
PY=$PY bash scripts/train.sh configs/beol14/setup_m40.yaml
PY=$PY bash scripts/train.sh configs/beol14/slew_m40.yaml

# SI aux-loss sweep, and parser/base unit tests (numpy-only)
PY=$PY bash scripts/sweep.sh configs/beol14/setup_m40.yaml
$PY -m pytest tests/ -q
```

Four 14nm slack models = `{setup,hold} × {m40,125}`; two 14nm slew models; the
3nm pair demonstrates a temperature **axis** instead of a split. No data is
shipped (`.gitignore`d) — configs point at absolute report paths.

## Running on new data

**Start with [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)** — the full
step-by-step (data layout → reconnaissance → configs → build → train →
predictions) for a brand-new dataset. Reference docs: data formats + array
contract in [docs/PARSING.md](docs/PARSING.md), commands + every config knob in
[docs/USAGE.md](docs/USAGE.md).
