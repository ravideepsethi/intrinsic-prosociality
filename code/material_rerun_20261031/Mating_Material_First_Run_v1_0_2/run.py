#!/usr/bin/env python3
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
if __name__ == "__main__":
    from mmrerun.run import main
    raise SystemExit(main())
