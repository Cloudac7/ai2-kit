# Amorphous Oxides Structure Analysis 

```bash 
ai2-kit algorithm aos_analysis
```

## Introduction
A set of Python functions to analyse the statistic properties of structure in amorphous oxides.

## Usage

### Effective Coordination Number (ECN)

```bash 
ai2-kit algorithm aos_analysis ECN
```

This commond is used to calculate the average bond length and effective coordination number in a given trajectory, and dump results as a new file.

#### Options
| Option | Description | Type | Default | Example |
| --- | --- | --- | --- | --- |
|input_traj|The trajectory you need to input for analysis.|str|(Required)|--input_traj ./in2o3-eq.xyz|
|result_dir|Dump the result of analysis `result (per frame)` and `average (average values)` in a new directory.|str|(Required)|--result ./result_data|
|ref|Reference atom (Central atom), the syntax is 'name X'.|str|(Required)|--ref 'name In'|
|conf|Configuration atom (Coordination atom), the syntax is 'name Y'.|str|(Required)|--conf 'name O'|
|cell|Setting the parameters of the cell.|list[float]|(Required)|--cell '[10.2, 10.2, 10.2, 90, 90, 90]'

#### Examples
We could run this method by the following commonds:
```bash
ai2-kit algorithm aos_analysis ECN \
--input_traj ./in2o3-eq.xyz \
--result_dir ./result \
--ref 'name In' \
--conf 'name O' \
--cell '[20.238452856, 20.23845286, 20.23845286, 90, 90, 90]' 
```

The output would be written in a new directory : `./result_data/result` and `./result_data/average`.

In the file `./result_data/result`:
```bash
# frame_index   l_av   ECN
    0        2.1778   5.3359
    1        2.1793   5.3555
    2        2.1789   5.3492
    3        2.1771   5.3276
    4        2.1771   5.3290
    ...      ...      ...
```

In the file`./result_data/average`:
```bash
l_av = 2.1752
ECN = 5.2832
```

### Counting Polyhedra

```bash 
ai2-kit algorithm aos_analysis count-shared-polyhedra
```

This commond is used to count the numbers and fractions of polyhedra linked in different forms, including "Corner-share", "Edge-share" and "Face-share".

#### Options
| Option | Description | Type | Default | Example |
| --- | --- | --- | --- | --- |
|input_traj|The trajectory you need to input for analysis.|str|(Required)|--input_traj ./in2o3-eq.xyz|
|result_dir|Dump the result of analysis `result (per frame)` and `average (average values)` in a new directory.|str|(Required)|--result ./result_data|
|ref|Reference atom (Central atom), the syntax is 'name X'.|str|(Required)|--ref 'name In'|
|conf|Configuration atom (Coordination atom), the syntax is 'name Y'.|str|(Required)|--conf 'name O'|
|cell|Setting the parameters of the cell.|list[float]|(Required)|--cell '[10.2, 10.2, 10.2, 90, 90, 90]'
|cutoff|Setting the cutoff distance to define a bond.|float|(Required)|--cutoff '2.36'|
|coord_num|Provide the coordination number of polyhedra that you want to count. For example, you could set `6` for $octahedra$. In particular, `-1` corresponds to counting $All\ categories\ of\ the\ polyhedra$.|int|(Required)|--coord_num -1|

#### Examples
We could run this method by the following commonds:
```bash
ai2-kit algorithm aos_analysis count-shared-polyhedra \
--input_traj ./in2o3-eq.xyz \
--result_dir ./result_data \
--ref 'name In' \
--conf 'name O' \
--cell '[20.23845286, 20.23845286, 20.23845286, 90, 90, 90]' \
--cutoff '2.36' \
--coord_num -1  
```

The output would be written in a new directory : `./result_data/result` and `./result_data/average`.

In the file `./result_data/result`:
```bash
# frame_index   corner   edge   face
    0        1106.0000   290.0000   0.0000
    1        1098.0000   300.0000   0.0000
    2        1134.0000   286.0000   2.0000
    3        1116.0000   288.0000   2.0000
    4        1114.0000   287.0000   2.0000
    ...      ...         ...        ...      
```
In the file `./result_data/average`:
```bash
Corner-share = 1096.4817
Edge-share = 285.7608
Face-share = 1.8439
```