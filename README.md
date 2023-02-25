# ZJU-NSR
This repository is a preprocessing method of camera matrix for applying ZJU-MoCap dataset to neural surface reconstruction methods (IDR, NeuS, VolSDF, and etc).

#### Data Convention
The data is organized as follows:

```
<case_name>
|-- intri.yml    # camera intrinsic parameters from ZJU-MoCap dataset
|-- extri.yml    # camera extrinsic parameters from ZJU-MoCap dataset
|-- mask
    |-- 000.png        # target mask each view (Unmasked region as 1 and masked region as 0)
    |-- 001.png
    ...
```

The code is extracted from zju3dv/EasyMocap (https://github.com/zju3dv/EasyMocap) and lioryariv/idr (https://github.com/lioryariv/idr)
