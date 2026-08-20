# 최종 산출물 예시 — 모델에 넘기는 파일 2종

코너 하나를 끝까지 돌리면 그 폴더에 **이 두 파일**이 생긴다. `6_collect.py` 가
모으는 것도 이 둘뿐이다.

| 파일 | 만드는 단계 | 무엇 |
|---|---|---|
| `<코너>_fixed_annotated.txt` | `2c_merge.py` (묶음 1) | 타이밍 리포트 + Dist/Res/Cpin 3열 |
| `<코너>.path_context_si_compact.by_path.rpt` | `5c_report.py` (묶음 2) | crosstalk 14열 |

**BoomCore 실물 그대로다.** 자르지 않았다. 코너 하나(TT_0p8V_25C)를 끝까지
돌린 결과 두 파일을 그대로 넣었다.

| 파일 | 크기 | 내용 |
|---|---|---|
| `..._fixed_annotated.txt` | 4.3 MB | 경로 294개 |
| `...by_path.rpt` | 2.0 MB | 경로 294개, 쌍 16,577줄 |

경로 수가 많아지면 그만큼 커진다. BoomCoreV3 의 큰 코너(경로 3,000개)에서는
annotated 가 40 MB, crosstalk 이 36 MB 다.

---

## 1. annotated — 리포트 오른쪽에 3열이 붙는다

`report_timing` 출력 그대로에 **`Dist` `Res` `Cpin`** 세 열이 붙는다. 원본 열은
하나도 안 건드린다.

```
  Point                                          Fanout    Cap    Trans    Incr    Path      Dist        Res       Cpin
  ---------------------------------------------------------------------------------------------------------------------
  clock (net)                                         1 0.007069                           72.1570     0.0887     0.0015
  ZCTSNET_6904 (net)                                 12 0.023539                            5.7240   488.8332     0.0005
  ZCTSNET_6160 (net)                                  3 0.005031                           31.5900     0.3349     0.0010
```

값이 붙는 줄은 **`(net)` 줄뿐**이다. 핀 줄에는 안 붙는다.

| 열 | 뜻 | 어디서 |
|---|---|---|
| `Dist` | 드라이버 핀 ↔ 그 리시버 핀 거리 | 받은 표 (`resdist_map.txt`) |
| `Res`  | 그 두 핀 사이 저항 | 받은 표 |
| `Cpin` | 그 리시버 핀의 입력 cap | Liberty / `pin_attr.txt` / `cpin_map.txt` |

**드라이버와 리시버는 그 경로가 실제로 지나가는 쌍이다.** `(net)` 줄 바로 앞 핀이
드라이버, 바로 뒤 핀이 리시버다. 그래서 같은 넷이라도 경로마다 다른 값이 될 수 있다.

`N/A` 가 보이면 그 값을 못 채운 것이다. 어느 쪽이 빈 것인지는 `2c_merge.py` 가
화면에 `[Cpin]` / `[Dist/Res]` 로 갈라 준다.

맨 위 `### FIXED_PATH idx=N key=...` 는 `fixed_paths.tcl` 이 붙인 경로 표식이다.
코너가 달라도 같은 `idx` 는 같은 경로라서, 코너끼리 경로를 맞출 때 이걸 쓴다.

---

## 2. by_path.rpt — crosstalk 14열

경로마다 머리말이 붙고, 그 아래에 **victim–aggressor 쌍이 한 줄씩** 온다.

```
### FIXED_PATH idx=1 key=...
# Startpoint: FpPipeline_fregister_read_exe_reg_rs2_data_0_reg_25_
# Endpoint: iregister_read_exe_reg_rs2_data_1_reg_9_
# Path Group: myCLK
# Path Type: max
# Slack: VIOLATED -0.054488
path_segment	victim_net	aggressor_net	...
```

| # | 열 | 뜻 |
|---|---|---|
| 1 | `path_segment` | `launch_clock` / `data` / `capture_clock` — 경로의 어느 구간인지 |
| 2 | `victim_net` | 영향을 받는 넷 |
| 3 | `aggressor_net` | 영향을 주는 넷. **없으면 `0`** |
| 4 | `crosstalk_delta` | 그 victim 넷이 받은 지연 변화 |
| 5 | `aggressor_bump` | aggressor 가 밀어올린 전압 bump |
| 6 | `number_of_aggressors` | 그 넷에 결합된 aggressor 총 개수 |
| 7 | `victim_load_pin` | victim 쪽 수신 핀 |
| 8 | `victim_load_min_arrival` | 그 핀의 도착시각 min |
| 9 | `victim_load_max_arrival` | 그 핀의 도착시각 max |
| 10 | `aggressor_driver_pin` | aggressor 를 미는 핀 |
| 11 | `aggressor_driver_min_arrival` | 그 핀의 도착시각 min |
| 12 | `aggressor_driver_max_arrival` | 그 핀의 도착시각 max |
| 13 | `aggressor_driver_slew_max` | aggressor 드라이버 slew |
| 14 | `coupling_cap_ff` | 그 쌍의 결합 커패시턴스 (fF) |

**`0` 이 많은 이유** — aggressor 가 없거나 전부 걸러진 넷은 3열부터 `0` 이 된다.
결합은 있는데(6열이 392) 실제로 미는 것이 없으면 그렇게 나온다. crosstalk 은
victim 과 aggressor 가 **같은 시점에** 움직여야 영향이 있기 때문이다. 그 판단에
쓰이는 것이 8~12열의 도착시각이다.

한 victim 이 aggressor 를 여럿 가지면 **줄이 그만큼 늘어난다.** 예시의 `n43552`
처럼 같은 victim 이 세 줄에 걸쳐 나오는 것이 그 경우다.

`number_of_aggressors`(6열)와 실제 줄 수가 다른 것은 정상이다. 6열은 PT 가 센
**결합된 전체 개수**이고, 줄로 나오는 것은 그중 **실제로 영향을 준 것**뿐이다.

---

## 이 값들이 어디서 오나

```
annotated   리포트(담당자)  +  resdist_map.txt(받은 표)  +  Cpin
by_path     리포트(담당자)  +  xtalk/(담당자 PT 산출물)
```

두 파일은 서로 독립이다. 한쪽이 없어도 다른 쪽은 나온다.
