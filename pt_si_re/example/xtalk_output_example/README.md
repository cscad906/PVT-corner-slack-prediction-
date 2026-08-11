# xtalk_all.tcl 산출물 예시

`pt/xtalk_all.tcl` 을 코너 하나에서 돌리면 그 폴더 아래 `xtalk/` 이 생기고
**파일 4개**가 들어간다. 이 폴더는 실제 산출물(BoomCore, TT_0p6V_25C)에서
앞부분만 잘라 온 것이다. **줄 수만 줄였고 형식과 값은 실물 그대로다.**

실물 크기는 이 정도다.

| 파일 | 실물 크기 | 뭐가 들었나 |
|---|---|---|
| `unique_contexts.tsv` | 788줄 | 무엇을 측정할지 목록 |
| `context_raw.rpt` | 3.0 MB | **PT 원문. 실제 crosstalk 숫자가 여기 있다** |
| `victim_windows.tsv` | 788줄 | victim 쪽 도착시각/slew |
| `aggressor_windows.tsv` | 1,123줄 | aggressor 쪽 도착시각/slew |

이 예시는 **context_id 2 번과 3 번**만 담았다. 두 개를 고른 이유가 있다.

- **2번** — aggressor 가 전부 걸러진 조용한 경우 (delta delay = 0)
- **3번** — 실제로 밀린 경우 (delta delay 0.0046, arc delay 가 0.0045 → 0.0096 으로 **두 배**)

네 파일을 이 두 context 로 서로 이어서 볼 수 있게 맞춰 놓았다.

---

## 1. `unique_contexts.tsv` — 측정 대상 목록

`<코너>.rpt`(fixed path 리포트)를 tcl 이 직접 읽어서 만든다.

```
context_id  victim_net    victim_driver_pin        victim_load_pin
2           ZCTSNET_6904  ZCTSBUF_824211_22831/Y   ZCTSINV_497954_21676/A
3           ZCTSNET_6160  ZCTSINV_497954_21676/Y   ccd_setup_inst_30328/A
```

리포트에서 `(net)` 줄을 만날 때마다 **바로 앞 핀 = driver, 바로 뒤 핀 = load** 로
잡는다. 294개 경로 → 넷 줄 8,930개 → 중복 제거 → **788개**.

`first_path_id` / `first_arc_idx` / `occurrence_count` 열은 **비어 있다.** tcl 은
"어떤 넷인가"만 알고 "몇 번 경로의 넷인가"는 모른다. 경로별 귀속이 필요하면
annotated 리포트를 넣고 `5a_contexts.py` 를 돌려야 채워진다.

## 2. `context_raw.rpt` — PT 원문 (본체)

788개 각각에 이 명령을 돌린 출력을 **그대로** 담는다.

```tcl
report_delay_calculation -crosstalk -max -from <driver핀> -to <load핀>
```

`###` 로 시작하는 줄만 tcl 이 붙인 꼬리표이고, 나머지는 PT 가 뱉은 원문이다.

읽을 때 중요한 줄:

| 줄 | 뜻 |
|---|---|
| `Annotated max rise net delta delay` | **crosstalk 때문에 늘어난 지연.** 0 이면 영향 없음 |
| `arc delay` | 최종 지연 (delta 포함) |
| `Total capacitance` / `Total resistance` | 이 넷의 RC |
| `Number of aggressors` | 물리적으로 붙어 있는 놈 전부 (392개까지 나온다) |
| `Number of effective (non-filtered) aggressors` | **실제로 영향을 준 놈** |
| `Victim driver rail voltage(VDD)` | 이 코너의 전압. 코너가 맞는지 확인용 |

그 아래 `Victim is rising:` / `Victim is falling:` 표에 aggressor 가 하나씩 나온다.

```
   Aggressor                        Coupling    Driver                Attributes  Switching Bump
  io_lsu_fp_stdata_bits_data[28]
                                    0.000787    gt3_6t_nand2_x1_rvt       A        0.037141
  ZCTSNET_6395                      0.000090    gt3_6t_buf_x12_rvt        S           -
```

**이름이 길면 줄바꿈되어 이름만 홀로 놓인다.** (파서가 이걸 놓쳐서 aggressor 229개를
빠뜨린 적이 있다. 지금은 처리된다.)

`Attributes` 가 왜 걸러졌는지를 말해 준다.

| 글자 | 뜻 |
|---|---|
| `A` | **Active — 실제로 영향을 줬다** |
| `S` | bump 가 작아서 무시 (Small) |
| `N` | 타이밍이 안 겹쳐서 무시 (Not overlap) |
| `L` | 논리적으로 동시에 못 바뀜 (Logical correlation) |
| `E` / `X` | 사용자가 뺐음 |
| `P` | 이상적인 포트 aggressor |

`Switching Bump` 는 **VDD 대비 비율**이다. 0.037141 = VDD 의 3.7% 만큼 튀었다.

> **이 정보는 여기서만 나온다.** `report_attribute` 로는 넷 전체 합계만 나오고
> aggressor 하나하나의 coupling cap 과 bump 는 안 나온다.

## 3. `victim_windows.tsv` — victim 도착시각

```
victim_load_pin          min_arrival  max_arrival  min_rise  max_rise  min_fall  max_fall  slew_max  status
ZCTSINV_497954_21676/A   0.037638     0.038883     0.037638  0.037638  0.038338  0.038883  0.030642  OK
```

`unique_contexts.tsv` 의 `victim_load_pin` 마다 한 줄. 788줄.

## 4. `aggressor_windows.tsv` — aggressor 도착시각

```
aggressor_net                    driver_pin  min_arrival  max_arrival  ...  slew_max  status
io_lsu_fp_stdata_bits_data[28]   U27506/Y    0.293983     0.922942     ...  0.112544  OK
```

**이 파일이 왜 필요한가.** `context_raw.rpt` 에는 *누가* aggressor 인지는 있는데
*언제 스위칭하는지*는 없다. victim 과 aggressor 의 도착시각 구간이 겹쳐야 실제로
영향을 준다. 그 판정을 나중에 파이썬에서 하려면 양쪽 윈도우가 다 있어야 한다.

tcl 이 방금 받은 출력에서 aggressor 이름을 직접 긁어내므로 **중간에 파이썬이
끼지 않는다.** 원래는 PT 를 두 번 다녀와야 했던 부분이다.

`status` 가 `NO_DRIVER` 면 그 넷의 출력 핀을 못 찾은 것이다. **탑 레벨 입력 포트가
aggressor 인 경우**라 정상이다. 실측에서 1,123개 중 15개였다.

```
io_lsu_spec_ld_wakeup_0_bits[2]     ...  NO_DRIVER
reset                               ...  NO_DRIVER
```

절반이 넘으면 이름 규약 문제이므로 `W-NODRIVER` 경고가 뜬다.

> 이 파일에는 **걸러진(`S`/`N`) aggressor 도 들어온다.** 일부러 넉넉하게 긁기
> 때문이다. 최종 리포트는 이 표를 **이름으로 찾아 쓰는 사전**으로만 쓰므로,
> 안 쓰는 항목이 몇 개 더 있어도 결과는 달라지지 않는다.
> (그래서 788 context 인데 aggressor 는 1,123개로 더 많다.)

---

## 돌렸을 때 화면에 나오는 것

**전부 영어다.** pt_shell 에서 한글이 깨지는 사이트가 있어 일부러 영어로 뽑는다
(파일 안 주석은 한글 그대로).

```
  no net list found -- building it from the report : TT_0p6V_25C.rpt
  net list built : 788 rows  ->  xtalk/unique_contexts.tsv
--------------------------------------------------------------------
  directory : /data/round2/TT_0p6V_25C
  analysis  : setup (-max)
  SI        : ON
--------------------------------------------------------------------
  reading net list : xtalk/unique_contexts.tsv
    ... 200 done (ok 200 / fail 0)
    ... 400 done (ok 400 / fail 0)
    ... 600 done (ok 600 / fail 0)

  nets queried    : 788  (ok 788 / fail 0)
  aggressors seen : 1123

  collecting arrival / slew ...
  victim pins    : 788  (not found 0)
  aggressor nets : 1123  (no driver 15)

====================================================================
  RESULT
--------------------------------------------------------------------
  nets queried     788  (ok 788 / fail 0)
  aggressor nets   1123  (no driver 15)
  victim pins      788  (not found 0)
  raw PT output    xtalk/context_raw.rpt  (3056137 bytes)
--------------------------------------------------------------------
  finished normally   [ OK-XTALK ]
====================================================================

next, in the shell (PrimeTime is no longer needed):
    python3 5b_pairs.py    --dir /data/round2/TT_0p6V_25C
    python3 5c_report.py   --dir /data/round2/TT_0p6V_25C
```

**`[ OK-XTALK ]` 가 나오면 성공이다.** 대신 이런 게 나오면 멈추고 확인한다.

| 나온 것 | 뜻 | 할 일 |
|---|---|---|
| `SI : OFF` | SI 해석이 꺼짐 | crosstalk 이 전부 0 이 된다. `si_enable_analysis` 확인 |
| `E-NODESIGN` | 디자인이 안 올라옴 | 넷리스트/db/SDC/SPEF 를 먼저 읽는다 |
| `E-NORPTFILE` | 읽을 리포트를 못 정함 | 파일 위쪽 `RPT_FILE` 에 절대경로를 적는다 |
| `E-NOAGGR` | aggressor 를 하나도 못 찾음 | SPEF 에 coupling 이 없다. `-keep_capacitive_coupling` 확인 |
| `W-XCALCERR` | 일부 넷 계산 실패 | `context_raw.rpt` 에서 `status=ERROR` 를 찾아 본다 |

## 밖에서 값을 넘기고 싶을 때

파일을 안 고치고 넘길 수 있다. 코너를 도는 루프에서 쓴다.

```tcl
set XT_RPT   "/data/round2/TT_0p6V_25C/TT_0p6V_25C.rpt"
set XT_DELAY "max"        ;# setup=max, hold=min
source /pkg/pt/xtalk_all.tcl
```

`fixed_paths.tcl` 을 돌린 **그 세션 그대로** 이어서 `source` 하면 아무것도 안 줘도
된다. 방금 만든 리포트를 자동으로 물려받는다.

## 단위

`context_raw.rpt` 안에 PT 가 적어 준다.

```
Main Library Units:  1ns  1pF  1kOhm
```

시간 ns, 용량 pF, 저항 kΩ. **Liberty 가 정한 값이라 코드가 환산하지 않는다.**
라이브러리가 다르면 이 줄이 바뀌므로, 여러 사이트 데이터를 한 학습셋에 섞기 전에
반드시 확인해야 한다.

## 다음 단계 (PT 불필요, 셸에서)

```bash
python3 5b_pairs.py  --dir <코너폴더>    # context_raw.rpt 파싱 -> victim-aggressor pair
python3 5c_report.py --dir <코너폴더>    # 최종 14열 리포트
```

최종 산출물: `<코너>.path_context_si_compact.by_path.rpt`
